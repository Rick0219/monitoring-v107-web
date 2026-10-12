from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from openpyxl import load_workbook

from monitoring_daily.domain.monitoring import SINGLE_PERIOD_TYPES


EXPORT_PARAMETER_KEYS = tuple(item.key for item in SINGLE_PERIOD_TYPES)


def default_export_column_parameters() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for monitor_key in EXPORT_PARAMETER_KEYS:
        result[monitor_key] = {
            "row_height": None,
            "column_width": None,
            "row_height_points": 26.0,
            "column_width_points": 120.0,
            "full_border": None,
            "measurement_decimals": 5,
            "change_decimals": 2,
        }
    return result


def normalize_export_column_parameters(
    values: Mapping[str, Any] | None,
    *,
    legacy_row_height: int | None = None,
    legacy_full_border: bool | None = None,
) -> dict[str, dict[str, Any]]:
    normalized = default_export_column_parameters()
    if legacy_row_height is not None or isinstance(legacy_full_border, bool):
        for settings in normalized.values():
            settings["row_height"] = legacy_row_height
            if legacy_row_height is not None:
                settings["row_height_points"] = None
            settings["full_border"] = legacy_full_border
    if not isinstance(values, Mapping):
        return normalized
    for monitor_key in EXPORT_PARAMETER_KEYS:
        source = values.get(monitor_key)
        if not isinstance(source, Mapping):
            continue
        target = normalized[monitor_key]
        row_height = _optional_int(source.get("row_height"), minimum=1, maximum=1000)
        column_width = _optional_int(
            source.get("column_width"), minimum=1, maximum=2000
        )
        target["row_height"] = row_height
        target["column_width"] = column_width
        row_height_points = _optional_float(
            source.get("row_height_points"), minimum=1.0, maximum=1000.0
        )
        column_width_points = _optional_float(
            source.get("column_width_points"), minimum=1.0, maximum=2000.0
        )
        if row_height_points is not None:
            target["row_height_points"] = row_height_points
        elif row_height is not None:
            target["row_height_points"] = None
        if column_width_points is not None:
            target["column_width_points"] = column_width_points
        elif column_width is not None:
            target["column_width_points"] = None
        full_border = source.get("full_border")
        target["full_border"] = full_border if isinstance(full_border, bool) else None
        measurement_decimals = _optional_int(
            source.get("measurement_decimals"), minimum=0, maximum=10
        )
        change_decimals = _optional_int(
            source.get("change_decimals"), minimum=0, maximum=10
        )
        if measurement_decimals is not None:
            target["measurement_decimals"] = measurement_decimals
        if change_decimals is not None:
            target["change_decimals"] = change_decimals
    return normalized


def parameters_for_measurement(
    parameters: Mapping[str, Any] | None,
    measurement_key: str,
) -> dict[str, Any]:
    monitor_key = str(measurement_key or "").partition(":")[0]
    normalized = normalize_export_column_parameters(parameters)
    return deepcopy(normalized.get(monitor_key, normalized["level"]))


def export_column_number_kind(column_name: str) -> str | None:
    name = str(column_name or "").replace(" ", "")
    if not name or any(token in name for token in ("点号", "点位", "编号", "监测孔号", "结论", "备注")):
        return None
    if "控制值" in name:
        return None
    if any(token in name for token in ("变化", "速率", "累计", "倾斜度")):
        return "change"
    if any(
        token in name
        for token in (
            "初始值",
            "测量值",
            "测值",
            "频率",
            "轴力",
            "水位读数",
            "水位高程",
            "管口高程",
        )
    ):
        return "measurement"
    return None


def number_format_for_export_column(
    parameters: Mapping[str, Any] | None,
    measurement_key: str,
    column_name: str,
) -> str | None:
    kind = export_column_number_kind(column_name)
    if kind is None:
        return None
    settings = parameters_for_measurement(parameters, measurement_key)
    decimals = settings.get(f"{kind}_decimals")
    if decimals is None:
        return None
    decimals = max(int(decimals), 0)
    return "0" if decimals == 0 else f"0.{''.join('0' for _ in range(decimals))}"


def format_export_value(value: Any, number_format: str | None) -> str:
    if value is None:
        return ""
    if value in ("", "/") or not number_format:
        return str(value)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    decimals = len(number_format.partition(".")[2])
    return f"{numeric:.{decimals}f}"


def _optional_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(parsed, maximum))


def _optional_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(parsed, maximum))


def points_to_screen_pixels(value: Any) -> int | None:
    """Convert a physical point dimension to the 96-DPI preview base size."""
    points = _optional_float(value, minimum=1.0, maximum=2000.0)
    if points is None:
        return None
    return max(round(points * 96.0 / 72.0), 1)


def screen_pixels_to_points(value: Any) -> float | None:
    pixels = _optional_float(value, minimum=1.0, maximum=4000.0)
    if pixels is None:
        return None
    return round(pixels * 72.0 / 96.0, 2)


def read_export_column_parameters_from_workbook(
    path: str | Path | None,
) -> dict[str, dict[str, Any]] | None:
    if not path or not Path(path).is_file():
        return None
    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
    except Exception:
        return None
    try:
        if "_数据页面设置" not in workbook.sheetnames:
            return None
        for row in workbook["_数据页面设置"].iter_rows(values_only=True):
            if row and row[0] == "export_parameters" and len(row) >= 2 and row[1]:
                loaded = json.loads(str(row[1]))
                if isinstance(loaded, dict):
                    return normalize_export_column_parameters(loaded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    finally:
        workbook.close()
    return None
