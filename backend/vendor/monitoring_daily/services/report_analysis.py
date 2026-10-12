from __future__ import annotations

from typing import Any, Iterable

from openpyxl.utils import get_column_letter, range_boundaries

from monitoring_daily.domain.monitoring import get_monitoring_type
from monitoring_daily.services.alert_thresholds import alert_status
from monitoring_daily.services.project_service import ProjectService
from monitoring_daily.services.report_data import build_report_rows


ANALYSIS_EXPORT_COLUMNS = [
    "监测项目",
    "本次变化最大点号",
    "本次变化最大值",
    "最大速率点号",
    "最大速率",
    "累计变化最大点号",
    "累计变化最大值",
    "速率控制值",
    "累计控制值",
    "监测结论",
    "备注",
]

_POINT_COLUMNS = ("点号", "点位", "监测孔号", "点号1")
_CURRENT_CHANGE_COLUMNS = (
    "变化量（mm）",
    "本次变化量(mm)",
    "本次变化量（mm）",
    "本次变化量（kN）",
    "本次倾斜变化量（‰）",
    "相邻变化量（mm）",
)
_RATE_COLUMNS = (
    "变化速率（mm/d）",
    "变化速率(mm/d)",
    "变化速率（kN/d）",
)
_CUMULATIVE_COLUMNS = (
    "本次累计变化量（mm）",
    "本次累计变化量(mm)",
    "累计变化量（kN）",
    "累计倾斜变化量（‰）",
    "本次累计值（mm）",
)
_RATE_CONTROL_COLUMNS = (
    "速率控制值（mm/d）",
    "变化速率控制值（mm/d）",
    "速率控制值(mm/d)",
    "速率控制值（kN/d）",
)
_CUMULATIVE_CONTROL_COLUMNS = (
    "累计控制值（mm）",
    "累计控制值(mm)",
    "累计控制值（kN）",
    "累计控制值（‰）",
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "")
    if not text or text == "/":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _first_value(row: dict[str, Any], columns: Iterable[str]) -> Any:
    for column in columns:
        value = row.get(column)
        if value not in (None, "", "/"):
            return value
    return "/"


def _point_name(row: dict[str, Any]) -> str:
    point = str(_first_value(row, _POINT_COLUMNS)).strip()
    if point == "/":
        return point
    point_2 = str(row.get("点号2") or "").strip()
    if point_2:
        return f"{point}/{point_2}"
    depth = _number(row.get("深度（m）"))
    if depth is None:
        return point
    depth_text = str(int(depth)) if depth.is_integer() else f"{depth:.3f}".rstrip("0").rstrip(".")
    return f"{point}（{depth_text}m）"


def _maximum_row(
    rows: list[dict[str, Any]],
    columns: tuple[str, ...],
) -> tuple[str, float | None]:
    candidates: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        value = _number(_first_value(row, columns))
        if value is not None:
            candidates.append((row, value))
    if not candidates:
        return "/", None
    row, value = max(candidates, key=lambda candidate: abs(candidate[1]))
    return _point_name(row), value


def _measurement_units(monitor_key: str) -> tuple[str, str]:
    if monitor_key == "axial":
        return "kN", "kN/d"
    if monitor_key == "tilt":
        return "‰", "‰/d"
    return "mm", "mm/d"


def _format_number(value: float | None, unit: str) -> str:
    if value is None:
        return "/"
    rounded = round(value, 3)
    number = str(int(rounded)) if rounded.is_integer() else f"{rounded:.3f}".rstrip("0").rstrip(".")
    return f"{number} {unit}"


def _highest_conclusion(rows: list[dict[str, Any]], alert: dict[str, Any]) -> str:
    rank = {"/": 0, "正常": 1, "黄色预警": 2, "预警": 2, "红色预警": 3}
    conclusions: list[str] = []
    for row in rows:
        conclusion = str(row.get("监测结论") or "").strip()
        if not conclusion:
            cumulative = _number(_first_value(row, _CUMULATIVE_COLUMNS))
            rate = _number(_first_value(row, _RATE_COLUMNS))
            if cumulative is not None or rate is not None:
                conclusion = alert_status(
                    cumulative if cumulative is not None else "/",
                    rate if rate is not None else "/",
                    alert,
                )
        conclusions.append(conclusion or "/")
    return max(conclusions or ["/"], key=lambda value: rank.get(value, 1))


def _normalize_start_cell(start_cell: str) -> tuple[str, int, int]:
    text = str(start_cell or "").strip().upper().replace("$", "")
    try:
        min_column, min_row, max_column, max_row = range_boundaries(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("统计区域起始单元格无效。") from exc
    if min_column != max_column or min_row != max_row or min_row < 1 or min_column < 1:
        raise ValueError("统计区域起始单元格必须是一个有效单元格，例如 A1。")
    return f"{get_column_letter(min_column)}{min_row}", min_row, min_column


def calculated_statistics_range(
    start_cell: str,
    data_row_count: int,
    column_count: int,
) -> str:
    """根据表头、数据行数及导出列数计算统计区域的最小范围。"""

    normalized, start_row, start_column = _normalize_start_cell(start_cell)
    rows = max(int(data_row_count), 0) + 1
    columns = int(column_count)
    if columns < 1:
        raise ValueError("请至少勾选一个统计导出列。")
    end_row = start_row + rows - 1
    end_column = start_column + columns - 1
    return f"{normalized}:{get_column_letter(end_column)}{end_row}"


def validate_statistics_range(
    start_cell: str,
    cell_range: str,
    data_row_count: int,
    column_count: int,
) -> str:
    """校验用户范围：起点必须一致，范围只能大于或等于自动计算值。"""

    normalized_start, start_row, start_column = _normalize_start_cell(start_cell)
    text = str(cell_range or "").strip().upper().replace("$", "")
    try:
        min_column, min_row, max_column, max_row = range_boundaries(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("统计区域无效，请输入例如 A1:F10 的连续区域。") from exc
    if min_row != start_row or min_column != start_column:
        raise ValueError(f"统计区域必须从起始单元格 {normalized_start} 开始。")
    required_rows = max(int(data_row_count), 0) + 1
    required_columns = int(column_count)
    if max_row - min_row + 1 < required_rows or max_column - min_column + 1 < required_columns:
        minimum = calculated_statistics_range(
            normalized_start,
            data_row_count,
            column_count,
        )
        raise ValueError(f"统计区域不能小于自动计算范围 {minimum}。")
    return (
        f"{get_column_letter(min_column)}{min_row}:"
        f"{get_column_letter(max_column)}{max_row}"
    )


def _analysis_measurement_name(
    monitor_key: str,
    data_name: str,
    original_label: str,
    *,
    merged: bool,
) -> str:
    monitor_name = (
        "深层水平位移"
        if monitor_key == "inclinometer"
        else get_monitoring_type(monitor_key).name
    )
    if merged:
        return monitor_name
    if monitor_key == "inclinometer":
        return f"{monitor_name} - {data_name}" if data_name else monitor_name
    return original_label


def _unique_text(values: Iterable[Any]) -> str:
    unique = list(
        dict.fromkeys(
            text
            for value in values
            if (text := str(value or "").strip()) and text != "/"
        )
    )
    return "；".join(unique) if unique else "/"


_CONCLUSION_RANK = {"/": 0, "正常": 1, "黄色预警": 2, "预警": 2, "红色预警": 3}


def _measurement_statistics_record(
    measurement: dict[str, str],
    monitor_key: str,
    data_name: str,
    rows: list[dict[str, Any]],
    alert: dict[str, Any],
) -> dict[str, Any]:
    value_unit, rate_unit = _measurement_units(monitor_key)
    change_point, change_value = _maximum_row(rows, _CURRENT_CHANGE_COLUMNS)
    rate_point, rate_value = _maximum_row(rows, _RATE_COLUMNS)
    cumulative_point, cumulative_value = _maximum_row(rows, _CUMULATIVE_COLUMNS)
    remarks = _unique_text(row.get("备注") for row in rows)
    conclusion = _highest_conclusion(rows, alert)
    public = {
        "监测项目": _analysis_measurement_name(
            monitor_key,
            data_name,
            measurement["label"],
            merged=False,
        ),
        "本次变化最大点号": change_point,
        "本次变化最大值": _format_number(change_value, value_unit),
        "最大速率点号": rate_point,
        "最大速率": _format_number(rate_value, rate_unit),
        "累计变化最大点号": cumulative_point,
        "累计变化最大值": _format_number(cumulative_value, value_unit),
        "速率控制值": str(_first_value(rows[0], _RATE_CONTROL_COLUMNS)),
        "累计控制值": str(_first_value(rows[0], _CUMULATIVE_CONTROL_COLUMNS)),
        "监测结论": conclusion,
        "备注": "" if remarks == "/" else remarks,
    }
    return {
        "monitor_key": monitor_key,
        "data_name": data_name,
        "public": public,
        "change_point": change_point,
        "change_value": change_value,
        "rate_point": rate_point,
        "rate_value": rate_value,
        "cumulative_point": cumulative_point,
        "cumulative_value": cumulative_value,
        "rate_control": public["速率控制值"],
        "cumulative_control": public["累计控制值"],
        "conclusion": conclusion,
        "remarks": public["备注"],
    }


def _maximum_record(
    records: list[dict[str, Any]],
    value_key: str,
) -> dict[str, Any] | None:
    candidates = [record for record in records if record.get(value_key) is not None]
    return max(candidates, key=lambda record: abs(float(record[value_key]))) if candidates else None


def _merge_monitor_statistics(records: list[dict[str, Any]]) -> dict[str, str]:
    monitor_key = str(records[0]["monitor_key"])
    value_unit, rate_unit = _measurement_units(monitor_key)
    change = _maximum_record(records, "change_value")
    rate = _maximum_record(records, "rate_value")
    cumulative = _maximum_record(records, "cumulative_value")
    conclusion = max(
        (str(record.get("conclusion") or "/") for record in records),
        key=lambda value: _CONCLUSION_RANK.get(value, 1),
    )
    remarks = _unique_text(record.get("remarks") for record in records)
    return {
        "监测项目": _analysis_measurement_name(
            monitor_key,
            "",
            "",
            merged=True,
        ),
        "本次变化最大点号": str(change["change_point"]) if change else "/",
        "本次变化最大值": _format_number(
            change.get("change_value") if change else None,
            value_unit,
        ),
        "最大速率点号": str(rate["rate_point"]) if rate else "/",
        "最大速率": _format_number(
            rate.get("rate_value") if rate else None,
            rate_unit,
        ),
        "累计变化最大点号": str(cumulative["cumulative_point"]) if cumulative else "/",
        "累计变化最大值": _format_number(
            cumulative.get("cumulative_value") if cumulative else None,
            value_unit,
        ),
        "速率控制值": _unique_text(record.get("rate_control") for record in records),
        "累计控制值": _unique_text(record.get("cumulative_control") for record in records),
        "监测结论": conclusion,
        "备注": "" if remarks == "/" else remarks,
    }


def _analysis_statistics_records(
    project_service: ProjectService,
    current_date: str,
    previous_date: str,
    measurement_keys: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    allowed_keys = (
        None
        if measurement_keys is None
        else {str(value) for value in measurement_keys}
    )
    records: list[dict[str, Any]] = []
    for measurement in project_service.list_measurement_sets():
        measurement_key = measurement["key"]
        if allowed_keys is not None and measurement_key not in allowed_keys:
            continue
        monitor_key, _separator, data_name = measurement_key.partition(":")
        alert = project_service.report_alert_for(measurement_key)
        try:
            rows = build_report_rows(
                project_service.load_measurement_set(measurement_key),
                current_date,
                previous_date,
                alert,
                fallback_to_latest=False,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if not rows:
            continue
        if monitor_key == "inclinometer":
            rows = [
                {
                    **row,
                    "监测孔号": data_name,
                }
                for row in rows
            ]
        records.append(
            _measurement_statistics_record(
                measurement,
                monitor_key,
                data_name,
                rows,
                alert,
            )
        )
    return records


def analysis_statistics_monitor_options(
    project_service: ProjectService,
    current_date: str,
    previous_date: str,
    measurement_keys: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """返回可配置合并的监测类型及其有效子页面数量。"""

    records = _analysis_statistics_records(
        project_service,
        current_date,
        previous_date,
        measurement_keys,
    )
    options: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        monitor_key = str(record["monitor_key"])
        option = by_key.get(monitor_key)
        if option is None:
            option = {
                "key": monitor_key,
                "label": _analysis_measurement_name(monitor_key, "", "", merged=True),
                "page_count": 0,
            }
            by_key[monitor_key] = option
            options.append(option)
        option["page_count"] += 1
    return options


def build_analysis_statistics(
    project_service: ProjectService,
    current_date: str,
    previous_date: str,
    statistics_mode: str = "separate",
    merge_monitor_types: Iterable[str] | None = None,
    measurement_keys: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    """按子测项统计，并可只合并用户指定的监测类型。"""

    if statistics_mode not in {"separate", "merged"}:
        raise ValueError("统计方式必须是单个测项统计或合并所有页面统计。")
    records = _analysis_statistics_records(
        project_service,
        current_date,
        previous_date,
        measurement_keys,
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record["monitor_key"]), []).append(record)
    if merge_monitor_types is None:
        selected = set(grouped) if statistics_mode == "merged" else set()
    else:
        selected = {str(value) for value in merge_monitor_types}

    result: list[dict[str, str]] = []
    merged: set[str] = set()
    for record in records:
        monitor_key = str(record["monitor_key"])
        group = grouped[monitor_key]
        if monitor_key in selected and len(group) > 1:
            if monitor_key not in merged:
                result.append(_merge_monitor_statistics(group))
                merged.add(monitor_key)
            continue
        result.append(record["public"])
    return result
def calculated_photo_range(statistics_range: str, row_count: int = 10) -> str:
    """返回统计表下方空一行、同列宽的默认图片区域。"""
    text = str(statistics_range or "").strip().upper().replace("$", "")
    try:
        min_column, _min_row, max_column, max_row = range_boundaries(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("请先设置有效的统计区域。") from exc
    if min_column < 1 or max_column < min_column or max_row < 1:
        raise ValueError("统计区域无效。")
    rows = max(int(row_count), 1)
    start_row = max_row + 2
    end_row = start_row + rows - 1
    return (
        f"{get_column_letter(min_column)}{start_row}:"
        f"{get_column_letter(max_column)}{end_row}"
    )

