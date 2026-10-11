import tempfile
import io
from zipfile import BadZipFile, ZipFile
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import Field
from app import entry as e
from app.api.deps import SessionDep
from app.api.routes.projects import save_project, public
from app.api.routes.workspace import EntryProject, bounded_upload, data_error
from app.project_models import StrictInput, DataWrite
from monitoring_daily.services.excel_importer import ExcelImporter

router = APIRouter(prefix='/projects/{project_id}/entry', tags=['entry'])


class EntryPreview(StrictInput):
    measurement_key: str = Field(min_length=1, max_length=150)
    date: str = Field(min_length=1, max_length=40)
    rows: list[dict] = Field(max_length=20000)


class EntryWrite(EntryPreview):
    revision: int = Field(ge=1)


@router.get('')
def read(project: EntryProject, measurement_key: str, date: str):
    try:
        return e.read_entry(project, measurement_key, date)
    except (ValueError, KeyError, TypeError) as exc:
        data_error(exc)


@router.post('/preview')
def preview(body: EntryPreview, project: EntryProject):
    try:
        return {'rows': e.prepare_rows(e.service_for(project), body.measurement_key, body.date, body.rows)}
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        data_error(exc)


@router.put('')
def write(body: EntryWrite, project: EntryProject, session: SessionDep):
    try:
        payload = e.save_entry(project, body.measurement_key, body.date, body.rows)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        data_error(exc)
    save_project(session, project, body.revision, payload=payload)
    return public(project, session)


@router.put('/parameters')
def parameters(body: DataWrite, project: EntryProject, session: SessionDep):
    try:
        payload = e.save_parameters(project, body.measurement_key, body.rows)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        data_error(exc)
    save_project(session, project, body.revision, payload=payload)
    return public(project, session)


@router.post('/import')
def import_excel(project: EntryProject, measurement_key: str, date: str, file: UploadFile = File(...)):
    if Path(file.filename or '').suffix.lower() not in {'.xlsx', '.xlsm'}:
        raise HTTPException(422, '请选择 Excel 文件（.xlsx 或 .xlsm）')
    content = bounded_upload(file)
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError('Excel 解压后超过 100 MB，请拆分文件')
        monitor, _, _ = e.context(measurement_key, date)
        if monitor == 'tilt':
            raise ValueError('倾斜由关联水准数据计算，请导入对应水准测项')
        with tempfile.TemporaryDirectory(prefix='monitoring-entry-') as directory:
            path = Path(directory) / 'upload.xlsx'
            path.write_bytes(content)
            rows = ExcelImporter(path).import_sheet(monitor)
        if len(rows) > 20000:
            raise ValueError('单期最多 20000 行')
        normalized = e.prepare_rows(e.service_for(project), measurement_key, date, rows)
        return {'rows': normalized, 'count': len(normalized), 'message': '导入预览，请核对后保存'}
    except (BadZipFile, InvalidFileException):
        raise HTTPException(422, '无法读取 Excel，请使用未损坏的 .xlsx 或 .xlsm 文件') from None
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        data_error(exc)


@router.get('/template')
def template(project: EntryProject, measurement_key: str):
    try:
        monitor, _, _ = e.context(measurement_key, '2000-01-01')
        name = e.EXCEL_SHEETS[monitor]
    except (ValueError, KeyError, TypeError) as exc:
        data_error(exc)
    workbook = Workbook()
    workbook.active.title = name
    workbook.active.append(e.m.TABLE_HEADERS[monitor])
    output = io.BytesIO()
    workbook.save(output)
    return Response(output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename="entry-template.xlsx"'})
