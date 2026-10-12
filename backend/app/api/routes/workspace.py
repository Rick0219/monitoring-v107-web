import copy
import io
import json
import tempfile
from typing import Annotated
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, UploadFile, File, Request, Depends
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.projects import ProjectDep, EditProject, require_features, save_project, public
from app.project_models import ProjectRecord, DataWrite, DatabaseWrite, DatabaseDate, Scope, Ask, ChartPreference, ChartSettings
from app.database_view import replace_date_rows
from app.charts import chart_data
from app.chart_links import make_chart_link
from app import monitoring as m
from app.core.config import settings

router=APIRouter(prefix="/projects/{project_id}",tags=["workspace"])
MAX_UPLOAD=20*1024*1024
DatabaseProject = Annotated[ProjectRecord, Depends(require_features('database_data'))]
ChartProject = Annotated[ProjectRecord, Depends(require_features('database_charts'))]
EntryProject = Annotated[ProjectRecord, Depends(require_features('data_entry'))]
AnalysisProject = Annotated[ProjectRecord, Depends(require_features('analysis'))]
ReportProject = Annotated[ProjectRecord, Depends(require_features('reports'))]
CatalogProject = Annotated[ProjectRecord, Depends(require_features('data_entry', 'database_data', 'database_charts', 'analysis', 'reports'))]

@router.get("/chart-link")
def chart_link(measurement_key: str, request: Request, project: ChartProject):
    reader = m.MonitoringReader(m.service_for(project))
    if measurement_key not in {item["key"] for item in reader.list_measurements()}:
        raise HTTPException(422, "当前工程中不存在此测项")
    return make_chart_link(request, project.id, measurement_key)

@router.get("/charts")
def charts(measurement_key: str, project: ChartProject, current_user: CurrentUser, session: SessionDep):
    result = measurement_view(measurement_key, project, current_user, session)
    # Chart-only accounts must not receive raw readings or report table fields.
    return {key: value for key, value in result.items()
            if key not in {'rows', 'columns', 'raw_rows', 'raw_columns'}}

@router.get('/database')
def database(measurement_key: str, project: DatabaseProject, current_user: CurrentUser, session: SessionDep):
    result = measurement_view(measurement_key, project, current_user, session)
    fields = {'measurement_key', 'label', 'monitor', 'unit', 'dates', 'effective_date',
              'columns', 'rows', 'raw_rows', 'raw_columns', 'warnings'}
    return {key: value for key, value in result.items() if key in fields} | {
        'end_date': result['settings']['end_date'],
    }

def measurement_view(measurement_key, project, current_user, session):
    saved = session.get(ChartPreference, (project.id, current_user.id, measurement_key))
    preference = ChartSettings(measurement_key=measurement_key, **(saved.settings if saved else {}))
    try:
        return chart_data(project, preference)
    except (ValueError, KeyError, TypeError) as exc:
        data_error(exc)

@router.put('/database-date')
def database_date(body: DatabaseDate, project: DatabaseProject, current_user: CurrentUser, session: SessionDep):
    reader = m.MonitoringReader(m.service_for(project))
    try:
        dates = reader.list_dates(body.measurement_key)
        if body.end_date and body.end_date not in dates:
            raise ValueError("请选择当前测项中存在的监测日期")
    except (ValueError, KeyError, TypeError) as exc:
        data_error(exc)
    preference = session.get(ChartPreference, (project.id, current_user.id, body.measurement_key))
    if preference is None:
        preference = ChartPreference(project_id=project.id, user_id=current_user.id, measurement_key=body.measurement_key)
    preference.settings = {**preference.settings, 'end_date': body.end_date}
    session.add(preference)
    session.commit()
    return {'message': '数据库日期已保存'}

@router.put("/chart-settings")
def chart_settings(body: ChartSettings, project: ChartProject, current_user: CurrentUser, session: SessionDep):
    reader = m.MonitoringReader(m.service_for(project))
    try:
        available = set(reader.list_points(body.measurement_key))
        if any(point not in available for point in body.points):
            raise ValueError("所选点位不属于当前测项，请刷新后重新选择")
        if body.end_date and body.end_date not in reader.list_dates(body.measurement_key):
            raise ValueError("请选择当前测项中存在的监测日期")
    except (ValueError, KeyError, TypeError) as exc:
        data_error(exc)
    preference = session.get(ChartPreference, (project.id, current_user.id, body.measurement_key))
    if preference is None:
        preference = ChartPreference(project_id=project.id, user_id=current_user.id, measurement_key=body.measurement_key)
    preference.settings = body.model_dump(exclude={"measurement_key"})
    session.add(preference)
    session.commit()
    return {"message": "图表设置已保存"}

def data_error(exc):
    raise HTTPException(422,str(exc)) from None

def document_public(document):
    return {k:v for k,v in document.items() if k not in {"source_path","file_hash"}}

def bounded_upload(file):
    content=file.file.read(MAX_UPLOAD+1)
    if len(content)>MAX_UPLOAD:
        raise HTTPException(413,"文件超过 20 MB，请拆分后导入")
    if not content:
        raise HTTPException(422,"文件为空")
    return content

def dataset(project, include_rows):
    service=m.service_for(project)
    reader=m.MonitoringReader(service)
    catalog=reader.list_measurements()
    entry_sets = list(dict.fromkeys([*[item['key'] for item in catalog],
        *project.payload.get('axial_parameters', {}), *project.payload.get('tilt_parameters', {}),
        *(['water'] if project.payload.get('water_parameters') else []),
        *['inclinometer:' + str(p['点号']) for p in project.payload.get('measurements', {}).get('inclinometer_points', []) if p.get('点号')]]))
    return {"revision":project.revision,"entry_sets":entry_sets,"measurements":project.payload.get("measurements",{}) if include_rows else {},
        "catalog":[{**item,"dates":reader.list_dates(item["key"]),"points":reader.list_points(item["key"])} for item in catalog],
        "types":[{"key":t.key,"name":t.name,"description":t.description,"columns":m.TABLE_HEADERS[t.key]} for t in m.SINGLE_PERIOD_TYPES]}

@router.get('/catalog')
def catalog(project: CatalogProject):
    return dataset(project, False)

@router.get('/data')
def data(project: EntryProject):
    return dataset(project, True)

@router.put("/data")
def save_data(body:DataWrite,project:EntryProject,session:SessionDep):
    try:
        rows=m.normalize_rows(body.measurement_key,body.rows)
        m.validate_rows(body.measurement_key,rows)
        payload=m.save_web_rows(project,body.measurement_key,rows)
    except (ValueError,KeyError,TypeError) as exc:
        data_error(exc)
    save_project(session,project,body.revision,payload=payload)
    return public(project,session)

@router.put('/database')
def save_database(body: DatabaseWrite, project: EntryProject, session: SessionDep):
    try:
        rows = replace_date_rows(project, body.measurement_key, body.date, body.rows)
        m.validate_rows(body.measurement_key, rows)
        payload = m.save_web_rows(project, body.measurement_key, rows)
    except (ValueError, KeyError, TypeError) as exc:
        data_error(exc)
    save_project(session, project, body.revision, payload=payload)
    return public(project, session)

@router.get("/export")
def export_project(project:EntryProject):
    payload=copy.deepcopy(project.payload)
    payload["project"]={"name":project.name,"created_at":str(project.created_at),"updated_at":str(project.updated_at)}
    return Response(json.dumps(payload,ensure_ascii=False,allow_nan=False).encode("utf-8"),media_type="application/json",headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(project.name+".proj")})

@router.post("/import")
def import_project(project:EditProject,session:SessionDep,revision:int,file:UploadFile=File(...)):
    content=bounded_upload(file)
    try:
        payload=json.loads(content.decode("utf-8-sig"),parse_constant=lambda v: (_ for _ in ()).throw(ValueError("非有限数值")))
        if not isinstance(payload,dict) or not isinstance(payload.get("measurements"),dict):
            raise ValueError("不是有效的桌面 .proj 工程文件")
        if len(payload["measurements"])>200:
            raise ValueError("单工程最多 200 个测项")
        for key,rows in payload["measurements"].items():
            if key=="inclinometer_points":
                if not isinstance(rows,list) or len(rows)>20000 or any(not isinstance(row,dict) for row in rows):
                    raise ValueError("测斜点位配置必须是表格行列表")
                continue
            rows=m.normalize_rows(key,rows)
            m.validate_rows(key,rows)
            payload["measurements"][key]=rows
        allowed={"version","measurements","axial_parameters","tilt_parameters","water_parameters","monitor_type_order"}
        clean={k:v for k,v in payload.items() if k in allowed}
        expected_types={"axial_parameters":dict,"tilt_parameters":dict,"water_parameters":list,"monitor_type_order":list}
        for name, expected in expected_types.items():
            if name in clean and not isinstance(clean[name],expected):
                raise ValueError(f"{name} 配置格式无效")
        for name in ("axial_parameters","tilt_parameters"):
            if any(not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows)
                   for rows in clean.get(name,{}).values()):
                raise ValueError(f"{name} 的测项参数必须是表格行列表")
        if any(not isinstance(row,dict) for row in clean.get("water_parameters",[])):
            raise ValueError("水位参数必须是表格行列表")
        settings_in=payload.get("report_settings",{})
        if not isinstance(settings_in,dict) or not isinstance(settings_in.get("alerts",{}),dict):
            raise ValueError("报警配置格式无效")
        clean["report_settings"]={"alerts":settings_in.get("alerts",{})}
        clean["project"]={"name":project.name}
        # Imported payload must be consumable before replacing the previous data.
        candidate=project.model_copy(update={"payload":clean})
        reader=m.MonitoringReader(m.service_for(candidate))
        for item in reader.list_measurements():
            reader.list_dates(item["key"])
            reader.list_points(item["key"])
    except (ValueError,KeyError,TypeError,AttributeError,UnicodeError) as exc:
        data_error(exc)
    save_project(session,project,revision,payload=clean)
    return {**public(project,session),"message":"原始数据和计算参数已导入；桌面排版及美化数据不参与网页分析"}

@router.get("/documents")
def documents(project:AnalysisProject):
    return {"documents":[document_public(d) for d in m.knowledge_for(project).list_documents()],
            "model_configured":bool(settings.AI_BASE_URL and settings.AI_MODEL),"model":settings.AI_MODEL}

@router.post("/documents")
def add_document(project:EditProject,file:UploadFile=File(...)):
    content=bounded_upload(file)
    filename=Path((file.filename or "document").replace("\\","/")).name
    if Path(filename).suffix.lower() not in {".txt",".md",".pdf",".docx",".xlsx"}:
        raise HTTPException(422,"支持 TXT、MD、PDF、DOCX、XLSX")
    try:
        with tempfile.TemporaryDirectory(dir=settings.STORAGE_DIR) as temporary:
            path=Path(temporary)/filename
            path.write_bytes(content)
            document=m.knowledge_for(project).add_document(path)
        return document_public(document)
    except (ValueError,RuntimeError,KeyError) as exc:
        data_error(exc)

@router.delete("/documents/{document_id}")
def delete_document(document_id:str,project:EditProject):
    try:
        m.knowledge_for(project).delete_document(document_id)
    except KeyError:
        raise HTTPException(404,"资料不存在")
    return {"message":"资料已删除"}

@router.post("/analysis")
def analysis(body:Scope,project:AnalysisProject):
    try:
        return m.analysis_for(project,body)
    except (ValueError,KeyError,TypeError) as exc:
        data_error(exc)

@router.post("/ask")
def ask(body:Ask,project:AnalysisProject):
    store=m.knowledge_for(project)
    if body.mode=="documents" and not any(d["chunk_count"] for d in store.list_documents()):
        raise HTTPException(422,"请先上传并成功解析项目资料")
    client=m.model_client()
    try:
        assistant=m.AnalysisAssistant(store,m.MonitoringReader(m.service_for(project)),client)
        result=assistant.answer(body.question,body.model_dump(exclude={"question"}))
        if result.get("analysis"):
            result["analysis"]["project"]={"id":str(project.id),"name":project.name}
        return result
    except (ValueError,KeyError,TypeError) as exc:
        data_error(exc)
    except (RuntimeError,TimeoutError) as exc:
        raise HTTPException(502,str(exc)) from None

def report_for(project,scope):
    analysis=m.analysis_for(project,scope)
    return {"project_name":project.name,"scope":scope.model_dump(),"analysis":analysis,"summary_text":m.format_analysis_summary(analysis),
            "notice":"本报告采用原始监测数据与工程配置；请复核缺失数据、阈值和分析结论后签发。"}

@router.post("/reports/preview")
def preview(body:Scope,project:ReportProject):
    try:
        return report_for(project,body)
    except (ValueError,KeyError,TypeError) as exc:
        data_error(exc)

def text_cell(value):
    # Workbook contents are data, never executable Excel formulas.
    if isinstance(value,str) and value.lstrip().startswith(("=","+","-","@")):
        return "'"+value
    return value if value is not None else ""

@router.post("/reports/download")
def download(body:Scope,project:ReportProject):
    try:
        report=report_for(project,body)
    except (ValueError,KeyError,TypeError) as exc:
        data_error(exc)
    workbook=Workbook()
    sheet=workbook.active
    sheet.title="监测日报"
    sheet.append(["监测日报",text_cell(project.name)])
    sheet.append(["日期范围",body.start_date+" 至 "+body.end_date])
    sheet.append(["测项",text_cell(body.measurement_key)])
    sheet.append(["数据来源","原始监测数据"])
    sheet.append(["复核提示",report["notice"]])
    for line in report["summary_text"].splitlines():
        sheet.append([text_cell(line)])
    detail=workbook.create_sheet("分析明细")
    analysis=report["analysis"]
    detail.append(analysis["columns"])
    for row in analysis["rows"]:
        detail.append([text_cell(row.get(c)) for c in analysis["columns"]])
    warnings=workbook.create_sheet("待复核")
    warnings.append(["待复核事项"])
    for warning in analysis["warnings"]:
        warnings.append([text_cell(warning)])
    for tab in workbook:
        tab.freeze_panes="A2"
        tab.auto_filter.ref=tab.dimensions
        for cell in tab[1]:
            cell.font=Font(bold=True,color="FFFFFF")
            cell.fill=PatternFill("solid",fgColor="165D8D")
        for column in tab.columns:
            tab.column_dimensions[column[0].column_letter].width=30
        for row in tab:
            for cell in row:
                cell.alignment=Alignment(vertical="top",wrap_text=True)
    output=io.BytesIO()
    workbook.save(output)
    return Response(output.getvalue(),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(project.name+"-监测日报.xlsx")})
