"""Adapter to the unchanged V1.07 calculation snapshot (no shared mutable service)."""
import copy
import math
import sys
from pathlib import Path
from datetime import datetime
from fastapi import HTTPException
from app.core.config import settings
from app.project_models import ProjectRecord

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from monitoring_daily.services.project_service import ProjectService, Project
from monitoring_daily.domain.monitoring import TABLE_HEADERS, SINGLE_PERIOD_TYPES
from monitoring_daily.analysis.monitoring import MonitoringReader as DesktopMonitoringReader
from monitoring_daily.analysis.knowledge import KnowledgeStore
from monitoring_daily.analysis.assistant import AnalysisAssistant, format_analysis_summary
from monitoring_daily.analysis.models import ModelClient, ModelConfig
from monitoring_daily.services.observation_date import normalize_observation_date
from monitoring_daily.services.water_level import normalize_water_measurement

class MemoryProjectService(ProjectService):
    def _write(self):
        pass

    def _rows_with_water_parameters(self, rows):
        # Web rows are the editable source of truth. Use imported calibration
        # only for older rows that do not contain an elevation at all.
        parameters = {str(p.get("点位", "")): p for p in self.list_water_parameters()}
        return [normalize_water_measurement(row, None if "管口高程（m）" in row
                else parameters.get(str(row.get("点位", row.get("点号", "")))))
                for row in rows]


class MonitoringReader(DesktopMonitoringReader):
    def __init__(self, service):
        super().__init__(service)
        snapshot = MemoryProjectService()
        snapshot.current_project = self._service.current_project
        snapshot._payload = self._service._payload
        self._service = snapshot
        self._project.pop("path", None)


def save_web_rows(project, key, rows):
    """Recalculate configured measurements; preserve unconfigured legacy imports."""
    from app.entry import service_for as entry_service
    monitor, _, name = key.partition(':')
    configured = (monitor == 'axial' and key in project.payload.get('axial_parameters', {})) or (
        monitor == 'water' and bool(project.payload.get('water_parameters'))) or (
        monitor == 'level' and 'tilt:' + name in project.payload.get('tilt_parameters', {}))
    if monitor == 'tilt' and key in project.payload.get('tilt_parameters', {}):
        raise ValueError('倾斜度由关联水准数据计算，请修改水准测量值或测点参数')
    if configured:
        service = entry_service(project)
        service.save_measurement_set(key, rows)
        return service._payload
    payload = copy.deepcopy(project.payload)
    measurements = payload.setdefault("measurements", {})
    if rows:
        measurements[key] = copy.deepcopy(rows)
    else:
        measurements.pop(key, None)
    return payload

def service_for(project: ProjectRecord):
    service = MemoryProjectService()
    # UUID is validated by FastAPI; no client supplied path can reach this adapter.
    path = settings.STORAGE_DIR / str(project.id) / "project.proj"
    service.current_project = Project(path=path, name=project.name, created_at=str(project.created_at), updated_at=str(project.updated_at))
    service._payload = copy.deepcopy(project.payload)
    service._payload["project"] = {"name":project.name}
    return service

def knowledge_for(project):
    return KnowledgeStore(settings.STORAGE_DIR / str(project.id) / "project.proj")

def normalize_rows(key, rows):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("监测数据必须是表格行列表")
    if key.partition(":")[0] == "water":
        return [normalize_water_measurement(row) for row in rows]
    return copy.deepcopy(rows)

def validate_rows(key, rows):
    monitor, _, name = key.partition(":")
    if monitor not in TABLE_HEADERS or len(key)>150 or not isinstance(rows,list) or len(rows)>20000:
        raise ValueError("测项或数据行数无效（单测项最多 20000 行）")
    if monitor in ("level","inclinometer") and not name.strip():
        raise ValueError("请填写测项名称或测斜孔号")
    errors, seen = [], set()
    for index,row in enumerate(rows,1):
        if not isinstance(row,dict) or len(row)>250:
            raise ValueError(f"第 {index} 行格式无效")
        for column,value in row.items():
            if not isinstance(column,str) or len(column)>120 or isinstance(value,(dict,list,bool)) or (isinstance(value,str) and len(value)>2000) or (isinstance(value,float) and not math.isfinite(value)):
                raise ValueError(f"第 {index} 行 {column} 内容无效")
        if monitor=="inclinometer":
            point = str(row.get("深度","")).strip()
            dates = [c for c in row if normalize_observation_date(c)]
            numeric = ["深度", *dates]
            if not dates:
                errors.append(f"第 {index} 行：需要日期列（YYYY-MM-DD）")
            identity=(point,)
        else:
            point = (str(row.get("点号1",""))+"-"+str(row.get("点号2",""))) if monitor=="tilt" else str(row.get("点位" if monitor=="water" else "点号","")).strip()
            date = normalize_observation_date(row.get("时间",""))
            if not date:
                errors.append(f"第 {index} 行：时间应为有效日期")
            identity=(point,date,str(row.get("编号","")) if monitor=="axial" else "")
            numeric = {"level":["测量值"],"water":["管口高程（m）","水位读数（m）"],"horizontal":["X 坐标","Y 坐标"],"axial":["频率","轴力（kN）"],"tilt":["两点距离L（m）","倾斜度（‰）"]}[monitor]
        if not point or point=="-":
            errors.append(f"第 {index} 行：点位不能为空")
        if identity in seen:
            errors.append(f"第 {index} 行：点位、日期或编号重复")
        seen.add(identity)
        for column in numeric:
            value=row.get(column)
            if value in (None,"","/","—"):
                continue
            try:
                if not math.isfinite(float(value)):
                    raise ValueError()
            except (ValueError,TypeError):
                errors.append(f"第 {index} 行 {column}：请输入数值，缺测留空")
        if len(errors)>15:
            break
    if errors:
        raise ValueError("；".join(errors))

def analysis_for(project, scope):
    reader=MonitoringReader(service_for(project))
    result=reader.analyze(scope.measurement_key,scope.start_date,scope.end_date,scope.point,limit=1000)
    result["project"]={"id":str(project.id),"name":project.name}
    return result

def model_client():
    if not settings.AI_BASE_URL or not settings.AI_MODEL:
        raise HTTPException(503,"管理员尚未配置 AI 模型，请在服务器 .env 中设置 AI_BASE_URL、AI_MODEL 和 AI_API_KEY；本地模型可以不填 Key")
    return ModelClient(ModelConfig(base_url=settings.AI_BASE_URL,model=settings.AI_MODEL,api_key=settings.AI_API_KEY,key_env="",timeout=settings.AI_TIMEOUT))
