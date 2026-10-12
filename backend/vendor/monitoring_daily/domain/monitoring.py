from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonitoringType:
    key: str
    name: str
    description: str
    icon: str
    accent: str


SINGLE_PERIOD_TYPES: tuple[MonitoringType, ...] = (
    MonitoringType("level", "水准", "竖向位移、沉降等水准观测数据", "level.svg", "#D99A17"),
    MonitoringType("tilt", "倾斜", "由两个水准点累计沉降差计算倾斜度", "tilt.svg", "#5B7FA3"),
    MonitoringType("water", "水位", "地下水位、管口高程和水位读数数据", "water.svg", "#2477B8"),
    MonitoringType("inclinometer", "深层水平位移", "深层水平位移孔深度与测值数据", "inclinometer.svg", "#C28C16"),
    MonitoringType("axial", "支撑轴力", "支撑轴力频率和编号数据", "axial.svg", "#1F6FA8"),
    MonitoringType("horizontal", "水平位移", "平面坐标和水平位移观测数据", "horizontal.svg", "#B98314"),
)

TABLE_HEADERS: dict[str, list[str]] = {
    "level": ["序号", "时间", "点号", "测量值", "备注"],
    "tilt": ["点号1", "点号2", "两点距离L（m）", "倾斜度（‰）"],
    "water": ["序号", "时间", "点位", "管口高程（m）", "水位读数（m）", "备注"],
    "horizontal": ["序号", "时间", "点号", "X 坐标", "Y 坐标", "备注"],
    "inclinometer": ["深度", "测值"],
    "axial": ["时间", "点号", "编号", "频率", "轴力（kN）", "备注"],
}

EXCEL_SHEETS: dict[str, str] = {
    "level": "单期水准数据",
    "water": "单期水位数据",
    "horizontal": "单期水平位移数据",
    "axial": "单期轴力数据",
    "inclinometer": "ZQT-1",
}

EXCEL_HEADER_ALIASES: dict[str, dict[str, str]] = {
    "water": {
        "点号": "点位",
        "洞口高程": "管口高程（m）",
        "水深": "水位读数（m）",
        "测量值": "水位读数（m）",
    },
    "horizontal": {"X坐标": "X 坐标", "Y坐标": "Y 坐标"},
}

LEVEL_DATA_NAMES: tuple[str, ...] = (
    "建筑物位移",
    "地表位移",
    "管线位移",
    "桩顶竖向位移",
)

DEFAULT_AXIAL_DATA_NAME = "第一道支撑"


def get_monitoring_type(key: str) -> MonitoringType:
    for item in SINGLE_PERIOD_TYPES:
        if item.key == key:
            return item
    raise KeyError(f"未知监测类型：{key}")


def get_table_headers(key: str) -> list[str]:
    try:
        return list(TABLE_HEADERS[key])
    except KeyError as exc:
        raise KeyError(f"未知表格类型：{key}") from exc


def get_excel_sheet_name(key: str) -> str:
    try:
        return EXCEL_SHEETS[key]
    except KeyError as exc:
        raise KeyError(f"未知 Excel 映射类型：{key}") from exc


def normalize_excel_header(key: str, header: str) -> str:
    return EXCEL_HEADER_ALIASES.get(key, {}).get(header, header)
