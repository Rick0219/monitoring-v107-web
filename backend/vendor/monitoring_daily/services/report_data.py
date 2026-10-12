from __future__ import annotations

from typing import Any

from monitoring_daily.services.alert_thresholds import (
    alert_status,
    threshold_range_from_settings,
)
from monitoring_daily.services.water_level import (
    PIPE_ELEVATION_COLUMN,
    WATER_POINT_COLUMN,
    WATER_READING_COLUMN,
)
from monitoring_daily.services.observation_date import (
    observation_interval_days,
    observation_sort_key,
    split_observation_date,
)
from monitoring_daily.services.measurement_calculations import (
    calculate_difference,
    calculate_horizontal_displacement_mm,
    calculate_water_elevation,
)


DISPLACEMENT_EXPORT_COLUMNS = [
    "点号",
    "初始值（m）",
    "本次测量值（m）",
    "上次测量值（m）",
    "变化量（mm）",
    "变化速率（mm/d）",
    "本次累计变化量（mm）",
    "上次累计变化量（mm）",
    "速率控制值（mm/d）",
    "累计控制值（mm）",
    "监测结论",
    "备注",
]

WATER_EXPORT_COLUMNS = [
    "点位",
    "管口高程(m)",
    "初始水位高程(m)",
    "本次水位读数(m)",
    "本次水位高程(m)",
    "本次变化量(mm)",
    "变化速率(mm/d)",
    "本次累计变化量(mm)",
    "速率控制值(mm/d)",
    "累计控制值(mm)",
    "监测结论",
    "备注",
]

HORIZONTAL_EXPORT_COLUMNS = [
    "点号",
    "初始值X（m）",
    "初始值Y（m）",
    "本次测量值X（m）",
    "本次测量值Y（m）",
    "上次测量值X（m）",
    "上次测量值Y（m）",
    "本次变化量（mm）",
    "变化速率（mm/d）",
    "本次累计变化量（mm）",
    "上次累计变化量（mm）",
    "变化速率控制值（mm/d）",
    "累计控制值（mm）",
    "备注",
]

HORIZONTAL_DISPLACEMENT_MODES = {"x", "y", "xy"}

AXIAL_EXPORT_COLUMNS = [
    "点号",
    "编号",
    "初始频率（Hz）",
    "本次频率（Hz）",
    "上次频率（Hz）",
    "初始轴力（kN）",
    "本次轴力（kN）",
    "上次轴力（kN）",
    "本次变化量（kN）",
    "变化速率（kN/d）",
    "累计变化量（kN）",
    "上次累计变化量（kN）",
    "速率控制值（kN/d）",
    "累计控制值（kN）",
    "监测结论",
    "备注",
]

INCLINOMETER_EXPORT_COLUMNS = [
    "监测孔号",
    "深度（m）",
    "初始值（mm）",
    "本次测值（mm）",
    "上次测值（mm）",
    "相邻变化量（mm）",
    "变化速率（mm/d）",
    "上次累计值（mm）",
    "本次累计值（mm）",
    "累计控制值（mm）",
]
TILT_EXPORT_COLUMNS = [
    "点号1",
    "点号2",
    "两点距离(m)",
    "本次倾斜变化量（‰）",
    "变化速率（‰/d）",
    "累计倾斜变化量（‰）",
    "累计控制值（‰）",
    "监测结论",
    "备注",
]
LEGACY_INCLINOMETER_EXPORT_COLUMNS = ["累计变形（mm）"]
LEGACY_EXPORT_COLUMN_ALIASES = {
    "初始值": "初始值（mm）",
    "上次测值": "上次测值（mm）",
    "本次测值": "本次测值（mm）",
    "累计控制值": "累计控制值(mm)",
    "速率控制值": "速率控制值(mm/d)",
    "累计控制值 （‰）": "累计控制值（‰）",
}

# 保留原名称，兼容既有模板和调用方。
EXPORT_COLUMNS = DISPLACEMENT_EXPORT_COLUMNS
ALL_EXPORT_COLUMNS = list(
    dict.fromkeys(
        [
            *DISPLACEMENT_EXPORT_COLUMNS,
            *WATER_EXPORT_COLUMNS,
            *HORIZONTAL_EXPORT_COLUMNS,
            *AXIAL_EXPORT_COLUMNS,
            *INCLINOMETER_EXPORT_COLUMNS,
            *TILT_EXPORT_COLUMNS,
            *LEGACY_INCLINOMETER_EXPORT_COLUMNS,
        ]
    )
)


def normalize_export_column_name(value: Any) -> str:
    name = str(value or "").strip()
    return LEGACY_EXPORT_COLUMN_ALIASES.get(name, name)


def export_columns_for_measurement(measurement_key: str) -> list[str]:
    monitor_key = measurement_key.partition(":")[0]
    if monitor_key == "axial":
        return list(AXIAL_EXPORT_COLUMNS)
    if monitor_key == "inclinometer":
        return list(INCLINOMETER_EXPORT_COLUMNS)
    if monitor_key == "horizontal":
        return list(HORIZONTAL_EXPORT_COLUMNS)
    if monitor_key == "tilt":
        return list(TILT_EXPORT_COLUMNS)
    if monitor_key == "water":
        return list(WATER_EXPORT_COLUMNS)
    return list(EXPORT_COLUMNS)


def normalize_horizontal_displacement_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in HORIZONTAL_DISPLACEMENT_MODES else "xy"


def primary_value_header(headers: list[str]) -> str | None:
    for header in ("测量值", "水位读数（m）", "水深", "频率", "X 坐标", "Y 坐标", "管口高程（m）", "洞口高程", "测值"):
        if header in headers:
            return header
    for header in headers:
        if header not in {"序号", "时间", "点号", "编号", "备注"}:
            return header
    return None


def build_report_rows(
    rows: list[dict[str, Any]],
    current_date: str,
    previous_date: str,
    alert: dict[str, Any] | None = None,
    fallback_to_latest: bool = False,
    include_empty: bool = False,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    day_count = observation_interval_days(current_date, previous_date)
    if day_count <= 0:
        raise ValueError("本次数据日期必须晚于上次数据日期。")
    if "深度" in rows[0] and "时间" not in rows[0]:
        return _build_inclinometer_report_rows(
            rows,
            current_date,
            previous_date,
            alert or {},
            fallback_to_latest,
            include_empty,
        )
    if "倾斜度（‰）" in rows[0] and "点号1" in rows[0] and "点号2" in rows[0]:
        return _build_tilt_report_rows(
            rows,
            current_date,
            previous_date,
            alert or {},
            fallback_to_latest,
            include_empty,
        )
    if (
        WATER_POINT_COLUMN in rows[0]
        or WATER_READING_COLUMN in rows[0]
        or "水深" in rows[0]
    ):
        return _build_water_report_rows(
            rows,
            current_date,
            previous_date,
            alert or {},
            fallback_to_latest,
            include_empty,
        )
    if "轴力（kN）" in rows[0] or rows[0].get("编号") is not None and "频率" in rows[0]:
        return _build_axial_report_rows(
            rows,
            current_date,
            previous_date,
            alert or {},
            fallback_to_latest,
            include_empty,
        )
    if "点号" in rows[0] and {"X 坐标", "Y 坐标"} & set(rows[0]):
        return _build_horizontal_report_rows(
            rows,
            current_date,
            previous_date,
            alert or {},
            fallback_to_latest,
            include_empty,
        )
    value_header = primary_value_header(list(rows[0].keys()))
    if not value_header or "点号" not in rows[0]:
        return []

    settings = alert or {}
    rate_control_display = threshold_range_from_settings(settings, "rate_limit")
    cumulative_control_display = threshold_range_from_settings(
        settings, "cumulative_warning"
    )
    by_point: dict[str, dict[str, dict[str, Any]]] = {}
    numeric_dates: set[str] = set()
    point_order: list[str] = []
    for row in rows:
        point = str(row.get("点号", "")).strip()
        observed = str(row.get("时间", "")).strip()
        value = _optional_number(row.get(value_header))
        if not point or not observed:
            continue
        if point not in by_point:
            by_point[point] = {}
            point_order.append(point)
        by_point[point].setdefault(observed, {"value": value, "remark": str(row.get("备注", ""))})
        if value is not None:
            numeric_dates.add(observed)

    effective_current = current_date
    if effective_current not in numeric_dates and fallback_to_latest:
        candidates = sorted(observed for observed in numeric_dates if observed <= current_date)
        effective_current = candidates[-1] if candidates else ""
    effective_previous = previous_date
    if fallback_to_latest:
        candidates = sorted(
            observed
            for observed in numeric_dates
            if observed <= previous_date and observed < effective_current
        )
        effective_previous = candidates[-1] if candidates else ""
    effective_day_count = day_count
    if effective_previous:
        effective_day_count = observation_interval_days(
            effective_current, effective_previous
        )

    result: list[dict[str, Any]] = []
    for point in point_order:
        values = by_point[point]
        available_dates = sorted(
            (
                observed
                for observed, record in values.items()
                if record.get("value") is not None
            ),
            key=observation_sort_key,
        )
        point_previous_date = effective_previous
        second_measurement = (
            len(available_dates) >= 2 and effective_current == available_dates[1]
        )
        if second_measurement:
            point_previous_date = available_dates[0]
        point_day_count = (
            observation_interval_days(effective_current, point_previous_date)
            if point_previous_date
            else effective_day_count
        )
        current_record = values.get(effective_current)
        current = current_record.get("value") if current_record else None
        previous_record = values.get(point_previous_date)
        previous = previous_record.get("value") if previous_record else None
        remark = _selected_remark(current_record, previous_record)
        if second_measurement and _observation_dates_differ(
            effective_current, point_previous_date
        ):
            rate_note = f"{max(point_day_count, 1)}天变化速率"
            remark = f"{remark}；{rate_note}" if remark else rate_note
        if fallback_to_latest and current is None:
            continue
        if not include_empty and current is None and previous is None and not remark:
            continue
        initial = values[available_dates[0]]["value"] if available_dates else None
        current_cumulative_value = calculate_difference(
            current,
            initial,
            multiplier=1000.0,
        )
        previous_cumulative_value = calculate_difference(
            previous,
            initial,
            multiplier=1000.0,
        )
        change_value = calculate_difference(
            current,
            previous,
            multiplier=1000.0,
        )
        current_cumulative = (
            _rounded(current_cumulative_value)
            if current_cumulative_value is not None
            else "/"
        )
        previous_cumulative = (
            _rounded(previous_cumulative_value)
            if previous_cumulative_value is not None
            else "/"
        )
        rate = (
            _rounded(change_value / point_day_count)
            if change_value is not None and point_day_count > 0
            else "/"
        )
        change = _rounded(change_value) if change_value is not None else "/"
        conclusion = (
            alert_status(current_cumulative, rate, settings)
            if current_cumulative != "/" or rate != "/"
            else "/"
        )
        result.append(
            {
                "点号": point,
                "初始值（m）": initial if initial is not None else "/",
                "本次累计变化量（mm）": current_cumulative,
                "上次累计变化量（mm）": previous_cumulative,
                "本次测量值（m）": current if current is not None else "/",
                "上次测量值（m）": previous if previous is not None else "/",
                "变化量（mm）": change,
                "速率控制值（mm/d）": rate_control_display,
                "累计控制值（mm）": cumulative_control_display,
                "监测结论": conclusion,
                "备注": remark,
                "变化速率（mm/d）": rate,
            }
        )
    return result


def _build_water_report_rows(
    rows: list[dict[str, Any]],
    current_date: str,
    previous_date: str,
    settings: dict[str, Any],
    fallback_to_latest: bool,
    include_empty: bool,
) -> list[dict[str, Any]]:
    requested_day_count = observation_interval_days(current_date, previous_date)
    by_point: dict[str, dict[str, dict[str, Any]]] = {}
    point_order: list[str] = []
    valid_dates: set[str] = set()
    for row in rows:
        point = str(row.get(WATER_POINT_COLUMN, row.get("点号", "")) or "").strip()
        observed = str(row.get("时间", "")).strip()
        if not point or not observed:
            continue
        pipe_elevation = _optional_number(
            row.get(PIPE_ELEVATION_COLUMN, row.get("洞口高程"))
        )
        reading = _optional_number(row.get(WATER_READING_COLUMN, row.get("水深")))
        record = {
            "pipe_elevation": pipe_elevation,
            "reading": reading,
            "water_elevation": calculate_water_elevation(pipe_elevation, reading),
            "remark": str(row.get("备注", "")),
        }
        if point not in by_point:
            by_point[point] = {}
            point_order.append(point)
        by_point[point].setdefault(observed, record)
        if record["water_elevation"] is not None:
            valid_dates.add(observed)

    effective_current = current_date
    if effective_current not in valid_dates and fallback_to_latest:
        candidates = sorted(date for date in valid_dates if date <= current_date)
        effective_current = candidates[-1] if candidates else ""
    effective_previous = previous_date
    if fallback_to_latest:
        candidates = sorted(
            date
            for date in valid_dates
            if date <= previous_date and date < effective_current
        )
        effective_previous = candidates[-1] if candidates else ""
    effective_day_count = requested_day_count
    if effective_current and effective_previous:
        effective_day_count = observation_interval_days(
            effective_current, effective_previous
        )

    rate_control_display = threshold_range_from_settings(settings, "rate_limit")
    cumulative_control_display = threshold_range_from_settings(
        settings, "cumulative_warning"
    )
    result: list[dict[str, Any]] = []
    for point in point_order:
        values = by_point[point]
        available_dates = sorted(
            date
            for date, record in values.items()
            if record.get("water_elevation") is not None
        )
        current_record = values.get(effective_current)
        previous_record = values.get(effective_previous)
        remark = _selected_remark(current_record, previous_record)
        current_elevation = current_record.get("water_elevation") if current_record else None
        previous_elevation = previous_record.get("water_elevation") if previous_record else None
        if not include_empty and current_elevation is None and previous_elevation is None and not remark:
            continue
        initial_record = (
            values[available_dates[0]]
            if available_dates
            else current_record or previous_record or next(iter(values.values()))
        )
        initial_elevation = initial_record.get("water_elevation")
        current_cumulative_value = calculate_difference(
            current_elevation,
            initial_elevation,
            multiplier=1000.0,
        )
        current_change_value = calculate_difference(
            current_elevation,
            previous_elevation,
            multiplier=1000.0,
        )
        current_cumulative = (
            _rounded(current_cumulative_value)
            if current_cumulative_value is not None
            else "/"
        )
        current_change = (
            _rounded(current_change_value)
            if current_change_value is not None
            else "/"
        )
        rate = (
            _rounded(float(current_change) / effective_day_count)
            if current_change != "/" and effective_day_count > 0
            else "/"
        )
        conclusion = (
            alert_status(current_cumulative, rate, settings)
            if current_cumulative != "/" or rate != "/"
            else "/"
        )
        result.append(
            {
                "点位": point,
                "管口高程(m)": (
                    current_record.get("pipe_elevation")
                    if current_record and current_record.get("pipe_elevation") is not None
                    else initial_record.get("pipe_elevation", "/")
                ),
                "初始水位高程(m)": (
                    _rounded(float(initial_elevation))
                    if initial_elevation is not None
                    else "/"
                ),
                "本次水位读数(m)": (
                    current_record.get("reading")
                    if current_record and current_record.get("reading") is not None
                    else "/"
                ),
                "本次水位高程(m)": (
                    _rounded(float(current_elevation))
                    if current_elevation is not None
                    else "/"
                ),
                "本次累计变化量(mm)": current_cumulative,
                "本次变化量(mm)": current_change,
                "变化速率(mm/d)": rate,
                "监测结论": conclusion,
                "累计控制值(mm)": cumulative_control_display,
                "速率控制值(mm/d)": rate_control_display,
                "备注": remark,
            }
        )
    return result


def _build_tilt_report_rows(
    rows: list[dict[str, Any]],
    current_date: str,
    previous_date: str,
    settings: dict[str, Any],
    fallback_to_latest: bool,
    include_empty: bool,
) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    pair_order: list[tuple[str, str]] = []
    valid_dates: set[str] = set()
    for row in rows:
        point_1 = str(row.get("点号1", "")).strip()
        point_2 = str(row.get("点号2", "")).strip()
        observed = str(row.get("时间", "")).strip()
        if not point_1 or not point_2 or not observed:
            continue
        pair = (point_1, point_2)
        if pair not in by_pair:
            by_pair[pair] = {}
            pair_order.append(pair)
        value = _optional_number(row.get("倾斜度（‰）"))
        by_pair[pair].setdefault(
            observed,
            {
                "value": value,
                "distance": _optional_number(
                    row.get("两点距离L（m）", row.get("两点距离L（mm）"))
                ),
                "remark": str(row.get("备注", "")),
            },
        )
        if value is not None:
            valid_dates.add(observed)

    effective_current = current_date
    if effective_current not in valid_dates and fallback_to_latest:
        candidates = sorted(date for date in valid_dates if date <= current_date)
        effective_current = candidates[-1] if candidates else ""
    effective_previous = previous_date
    if fallback_to_latest:
        candidates = sorted(
            date
            for date in valid_dates
            if date <= previous_date and date < effective_current
        )
        effective_previous = candidates[-1] if candidates else ""
    effective_day_count = (
        observation_interval_days(effective_current, effective_previous)
        if effective_current and effective_previous
        else 0
    )

    cumulative_control_display = threshold_range_from_settings(
        settings, "cumulative_warning"
    )
    result: list[dict[str, Any]] = []
    for point_1, point_2 in pair_order:
        values = by_pair[(point_1, point_2)]
        current_record = values.get(effective_current)
        previous_record = values.get(effective_previous)
        current = current_record.get("value") if current_record else None
        previous = previous_record.get("value") if previous_record else None
        remark = _selected_remark(current_record, previous_record)
        if not include_empty and current is None and previous is None and not remark:
            continue
        cumulative = round(current, 2) if current is not None else "/"
        change = cumulative
        rate = (
            _rounded(float(change) / effective_day_count)
            if change != "/" and effective_day_count > 0
            else "/"
        )
        distance = next(
            (
                record.get("distance")
                for record in (current_record, previous_record, *values.values())
                if record and record.get("distance") is not None
            ),
            None,
        )
        conclusion = (
            alert_status(cumulative, None, settings)
            if cumulative != "/"
            else "/"
        )
        result.append(
            {
                "点号1": point_1,
                "点号2": point_2,
                "两点距离(m)": distance if distance is not None else "/",
                "本次倾斜变化量（‰）": change,
                "变化速率（‰/d）": rate,
                "累计倾斜变化量（‰）": cumulative,
                "累计控制值（‰）": cumulative_control_display,
                "监测结论": conclusion,
                "备注": remark,
            }
        )
    return result


def _build_horizontal_report_rows(
    rows: list[dict[str, Any]],
    current_date: str,
    previous_date: str,
    settings: dict[str, Any],
    fallback_to_latest: bool,
    include_empty: bool,
) -> list[dict[str, Any]]:
    mode = normalize_horizontal_displacement_mode(settings.get("displacement_mode"))
    rate_control_display = threshold_range_from_settings(settings, "rate_limit")
    cumulative_control_display = threshold_range_from_settings(
        settings, "cumulative_warning"
    )
    by_point: dict[str, dict[str, dict[str, Any]]] = {}
    point_order: list[str] = []
    valid_dates: set[str] = set()

    for row in rows:
        point = str(row.get("点号", "")).strip()
        observed = str(row.get("时间", "")).strip()
        if not point or not observed:
            continue
        record = {
            "x": _optional_number(row.get("X 坐标")),
            "y": _optional_number(row.get("Y 坐标")),
            "remark": str(row.get("备注", "")),
        }
        if point not in by_point:
            by_point[point] = {}
            point_order.append(point)
        by_point[point].setdefault(observed, record)
        if _horizontal_record_is_valid(record, mode):
            valid_dates.add(observed)

    effective_current = current_date
    if effective_current not in valid_dates and fallback_to_latest:
        candidates = sorted(observed for observed in valid_dates if observed <= current_date)
        effective_current = candidates[-1] if candidates else ""
    effective_previous = previous_date
    if fallback_to_latest:
        candidates = sorted(
            observed
            for observed in valid_dates
            if observed <= previous_date and observed < effective_current
        )
        effective_previous = candidates[-1] if candidates else ""
    effective_day_count = (
        observation_interval_days(effective_current, effective_previous)
        if effective_current and effective_previous
        else 0
    )

    result: list[dict[str, Any]] = []
    for point in point_order:
        values = by_point[point]
        available_dates = sorted(
            observed
            for observed, record in values.items()
            if _horizontal_record_is_valid(record, mode)
        )
        current_record = values.get(effective_current)
        previous_record = values.get(effective_previous)
        remark = _selected_remark(current_record, previous_record)
        current_valid = _horizontal_record_is_valid(current_record, mode)
        previous_valid = _horizontal_record_is_valid(previous_record, mode)
        if not include_empty and not current_valid and not previous_valid and not remark:
            continue
        initial_record = values[available_dates[0]] if available_dates else None
        current_cumulative = _horizontal_displacement_mm(
            initial_record,
            current_record,
            mode,
        )
        previous_cumulative = _horizontal_displacement_mm(
            initial_record,
            previous_record,
            mode,
        )
        change_value = calculate_difference(current_cumulative, previous_cumulative)
        change = _rounded(change_value) if change_value is not None else None
        rate = (
            _rounded(change / effective_day_count)
            if change is not None and effective_day_count > 0
            else None
        )
        conclusion = (
            alert_status(current_cumulative, rate, settings)
            if current_cumulative is not None or rate is not None
            else "/"
        )
        result.append(
            {
                "点号": point,
                "初始值X（m）": _horizontal_coordinate(initial_record, "x"),
                "初始值Y（m）": _horizontal_coordinate(initial_record, "y"),
                "本次测量值X（m）": _horizontal_coordinate(current_record, "x"),
                "本次测量值Y（m）": _horizontal_coordinate(current_record, "y"),
                "上次测量值X（m）": _horizontal_coordinate(previous_record, "x"),
                "上次测量值Y（m）": _horizontal_coordinate(previous_record, "y"),
                "本次累计变化量（mm）": (
                    current_cumulative if current_cumulative is not None else "/"
                ),
                "上次累计变化量（mm）": (
                    previous_cumulative if previous_cumulative is not None else "/"
                ),
                "本次变化量（mm）": change if change is not None else "/",
                "变化速率（mm/d）": rate if rate is not None else "/",
                "累计控制值（mm）": cumulative_control_display,
                "变化速率控制值（mm/d）": rate_control_display,
                "备注": remark,
                "监测结论": conclusion,
            }
        )
    return result


def _horizontal_record_is_valid(record: dict[str, Any] | None, mode: str) -> bool:
    if not record:
        return False
    if mode == "x":
        return record.get("x") is not None
    if mode == "y":
        return record.get("y") is not None
    return record.get("x") is not None and record.get("y") is not None


def _horizontal_coordinate(record: dict[str, Any] | None, axis: str) -> float | str:
    if not record or record.get(axis) is None:
        return "/"
    return float(record[axis])


def _horizontal_displacement_mm(
    initial: dict[str, Any] | None,
    measured: dict[str, Any] | None,
    mode: str,
) -> float | None:
    value = calculate_horizontal_displacement_mm(initial, measured, mode)
    return _rounded(value) if value is not None else None


def _build_inclinometer_report_rows(
    rows: list[dict[str, Any]],
    current_date: str,
    previous_date: str,
    settings: dict[str, Any],
    fallback_to_latest: bool,
    include_empty: bool,
) -> list[dict[str, Any]]:
    available_dates = sorted(
        {
            str(column)
            for row in rows
            for column, value in row.items()
            if column != "深度" and _is_date(str(column)) and _optional_number(value) is not None
        }
    )
    effective_current = current_date
    effective_previous = previous_date
    if fallback_to_latest and effective_current not in available_dates:
        candidates = [date for date in available_dates if date <= current_date]
        effective_current = candidates[-1] if candidates else ""
    if fallback_to_latest:
        candidates = [
            date
            for date in available_dates
            if date <= previous_date and date < effective_current
        ]
        effective_previous = candidates[-1] if candidates else ""
    day_count = (
        observation_interval_days(effective_current, effective_previous)
        if effective_current and effective_previous
        else 0
    )
    cumulative_control_display = threshold_range_from_settings(
        settings, "cumulative_warning"
    )

    result: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: _number(item.get("深度"), 0.0)):
        depth = _optional_number(row.get("深度"))
        if depth is None:
            continue
        row_dates = sorted(
            date
            for date in available_dates
            if _optional_number(row.get(date)) is not None
        )
        initial = _optional_number(row.get(row_dates[0])) if row_dates else None
        previous = _optional_number(row.get(effective_previous))
        current = _optional_number(row.get(effective_current))
        if not include_empty and current is None and previous is None:
            continue
        change_value = calculate_difference(current, previous)
        change = _rounded(change_value) if change_value is not None else "/"
        rate = (
            _rounded(float(change) / day_count)
            if change != "/" and day_count > 0
            else "/"
        )
        previous_cumulative_value = calculate_difference(previous, initial)
        current_cumulative_value = calculate_difference(current, initial)
        previous_cumulative = (
            _rounded(previous_cumulative_value)
            if previous_cumulative_value is not None
            else "/"
        )
        current_cumulative = (
            _rounded(current_cumulative_value)
            if current_cumulative_value is not None
            else "/"
        )
        result.append(
            {
                "监测孔号": "",
                "深度（m）": depth,
                "初始值（mm）": initial if initial is not None else "/",
                "上次测值（mm）": previous if previous is not None else "/",
                "本次测值（mm）": current if current is not None else "/",
                "相邻变化量（mm）": change,
                "变化速率（mm/d）": rate,
                "上次累计值（mm）": previous_cumulative,
                "本次累计值（mm）": current_cumulative,
                "累计控制值（mm）": cumulative_control_display,
                "累计变形（mm）": current_cumulative,
            }
        )
    return result


def _build_axial_report_rows(
    rows: list[dict[str, Any]],
    current_date: str,
    previous_date: str,
    settings: dict[str, Any],
    fallback_to_latest: bool,
    include_empty: bool,
) -> list[dict[str, Any]]:
    rate_control_display = threshold_range_from_settings(settings, "rate_limit")
    cumulative_control_display = threshold_range_from_settings(
        settings, "cumulative_warning"
    )
    by_number: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    sensor_types: dict[tuple[str, str], str] = {}
    number_order: list[tuple[str, str]] = []
    point_remarks: dict[tuple[str, str], str] = {}
    point_numeric_dates: dict[str, set[str]] = {}
    numeric_dates: set[str] = set()
    for row in rows:
        point = str(row.get("点号", "")).strip()
        number = str(row.get("编号", "")).strip()
        observed = str(row.get("时间", "")).strip()
        if not number or not observed:
            continue
        identity = (point, number)
        if identity not in by_number:
            by_number[identity] = {}
            sensor_types[identity] = str(row.get("传感器类型", "")).strip()
            number_order.append(identity)
        force = _optional_number(row.get("轴力（kN）"))
        frequency = _optional_number(row.get("频率"))
        remark = str(row.get("备注", ""))
        if remark.strip():
            point_remarks.setdefault((point, observed), remark)
        by_number[identity].setdefault(
            observed,
            {"force": force, "frequency": frequency, "remark": remark},
        )
        if force is not None:
            numeric_dates.add(observed)
            point_numeric_dates.setdefault(point, set()).add(observed)

    effective_current = current_date
    if effective_current not in numeric_dates and fallback_to_latest:
        candidates = sorted(date for date in numeric_dates if date <= current_date)
        effective_current = candidates[-1] if candidates else ""
    effective_previous = previous_date
    if fallback_to_latest:
        candidates = sorted(
            date for date in numeric_dates if date <= previous_date and date < effective_current
        )
        effective_previous = candidates[-1] if candidates else ""
    day_count = (
        observation_interval_days(effective_current, effective_previous)
        if effective_current and effective_previous
        else 0
    )

    result: list[dict[str, Any]] = []
    for identity in number_order:
        point, number = identity
        records = by_number[identity]
        available_dates = sorted(
            (
                date
                for date, record in records.items()
                if record.get("force") is not None
            ),
            key=observation_sort_key,
        )
        point_dates = sorted(
            point_numeric_dates.get(point, set()),
            key=observation_sort_key,
        )
        point_previous_date = effective_previous
        second_measurement = (
            len(point_dates) >= 2 and effective_current == point_dates[1]
        )
        if second_measurement:
            point_previous_date = point_dates[0]
        point_day_count = (
            observation_interval_days(effective_current, point_previous_date)
            if effective_current and point_previous_date
            else day_count
        )
        current_record = records.get(effective_current)
        previous_record = records.get(point_previous_date)
        remark = point_remarks.get(
            (point, effective_current),
            _selected_remark(current_record, previous_record),
        )
        if second_measurement and _observation_dates_differ(
            effective_current, point_previous_date
        ):
            rate_note = f"{max(point_day_count, 1)}天变化速率"
            remark = f"{remark}；{rate_note}" if remark else rate_note
        current_force = current_record.get("force") if current_record else None
        previous_force = previous_record.get("force") if previous_record else None
        if not include_empty and current_force is None and previous_force is None and not remark:
            continue
        initial_record = (
            records[available_dates[0]]
            if available_dates
            else current_record or previous_record or next(iter(records.values()))
        )
        initial_force = initial_record.get("force")
        current_cumulative = (
            _rounded(current_force - initial_force)
            if current_force is not None and initial_force is not None
            else "/"
        )
        previous_cumulative = (
            _rounded(previous_force - initial_force)
            if previous_force is not None and initial_force is not None
            else "/"
        )
        change = (
            _rounded(current_force - previous_force)
            if current_force is not None and previous_force is not None
            else "/"
        )
        rate = (
            _rounded(float(change) / point_day_count)
            if change != "/" and point_day_count > 0
            else "/"
        )
        conclusion = (
            alert_status(current_cumulative, rate, settings)
            if current_cumulative != "/" or rate != "/"
            else "/"
        )
        sensor_type = sensor_types.get(identity, "")
        result.append(
            {
                "点号": point,
                "编号": number,
                "传感器类型": sensor_type,
                "初始频率（Hz）": initial_record.get("frequency") if initial_record.get("frequency") is not None else "/",
                "上次频率（Hz）": previous_record.get("frequency") if previous_record and previous_record.get("frequency") is not None else "/",
                "本次频率（Hz）": current_record.get("frequency") if current_record and current_record.get("frequency") is not None else "/",
                "初始轴力（kN）": initial_force if initial_force is not None else "/",
                "上次轴力（kN）": previous_force if previous_force is not None else "/",
                "本次轴力（kN）": current_force if current_force is not None else "/",
                "上次累计变化量（kN）": previous_cumulative,
                "累计变化量（kN）": current_cumulative,
                "本次变化量（kN）": change,
                "变化速率（kN/d）": rate,
                "速率控制值（kN/d）": rate_control_display,
                "累计控制值（kN）": cumulative_control_display,
                "监测结论": conclusion,
                "备注": remark,
                "_merge_group": point if sensor_type == "钢筋计" else "",
            }
        )
    return result


def build_cumulative_series(
    rows: list[dict[str, Any]],
    displacement_mode: str = "xy",
) -> tuple[list[str], dict[str, list[float | None]]]:
    if not rows:
        return [], {}
    if "倾斜度（‰）" in rows[0] and "点号1" in rows[0] and "点号2" in rows[0]:
        dates = sorted(
            {
                str(row.get("时间", "")).strip()
                for row in rows
                if _optional_number(row.get("倾斜度（‰）")) is not None
                and _is_date(str(row.get("时间", "")).strip())
            }
        )
        by_pair: dict[str, dict[str, float]] = {}
        for row in rows:
            point_1 = str(row.get("点号1", "")).strip()
            point_2 = str(row.get("点号2", "")).strip()
            observed = str(row.get("时间", "")).strip()
            value = _optional_number(row.get("倾斜度（‰）"))
            if point_1 and point_2 and observed and value is not None:
                by_pair.setdefault(f"{point_1}-{point_2}", {}).setdefault(observed, value)
        return dates, {
            pair: [values.get(observed) for observed in dates]
            for pair, values in by_pair.items()
        }
    if "深度" in rows[0] and "时间" not in rows[0]:
        dates = sorted(
            {
                str(column)
                for row in rows
                for column, value in row.items()
                if column != "深度" and _is_date(str(column)) and _optional_number(value) is not None
            }
        )
        series: dict[str, list[float | None]] = {}
        for row in rows:
            depth = str(row.get("深度", "")).strip()
            values = [_optional_number(row.get(date)) for date in dates]
            initial = next((value for value in values if value is not None), None)
            if not depth or initial is None:
                continue
            series[depth] = [
                _rounded(value - initial) if value is not None else None
                for value in values
            ]
        return dates, series
    if "点号" in rows[0] and {"X 坐标", "Y 坐标"} & set(rows[0]):
        mode = normalize_horizontal_displacement_mode(displacement_mode)
        by_point: dict[str, dict[str, dict[str, Any]]] = {}
        dates: set[str] = set()
        for row in rows:
            point = str(row.get("点号", "")).strip()
            observed = str(row.get("时间", "")).strip()
            record = {
                "x": _optional_number(row.get("X 坐标")),
                "y": _optional_number(row.get("Y 坐标")),
            }
            if not point or not observed:
                continue
            by_point.setdefault(point, {}).setdefault(observed, record)
            if _horizontal_record_is_valid(record, mode):
                dates.add(observed)
        ordered_dates = sorted(dates)
        series: dict[str, list[float | None]] = {}
        for point, values in by_point.items():
            available = sorted(
                observed
                for observed, record in values.items()
                if _horizontal_record_is_valid(record, mode)
            )
            if not available:
                continue
            initial = values[available[0]]
            series[point] = [
                _horizontal_displacement_mm(initial, values.get(observed), mode)
                for observed in ordered_dates
            ]
        return ordered_dates, series
    axial = "轴力（kN）" in rows[0]
    if axial:
        rows = _collapse_rebar_rows(rows)
    value_header = "轴力（kN）" if axial else primary_value_header(list(rows[0].keys()))
    identity_header = "点号"
    if not value_header or identity_header not in rows[0]:
        return [], {}
    by_point: dict[str, dict[str, float]] = {}
    dates: set[str] = set()
    for row in rows:
        point = str(row.get(identity_header, "")).strip()
        observed = str(row.get("时间", "")).strip()
        value = _optional_number(row.get(value_header))
        if not point or not observed or value is None:
            continue
        by_point.setdefault(point, {}).setdefault(observed, value)
        dates.add(observed)
    ordered_dates = sorted(dates)
    series: dict[str, list[float | None]] = {}
    for point, values in by_point.items():
        available = sorted(values)
        if not available:
            continue
        initial = values[available[0]]
        scale = 1 if axial else 1000
        series[point] = [
            _rounded((values[observed] - initial) * scale) if observed in values else None
            for observed in ordered_dates
        ]
    return ordered_dates, series


def _collapse_rebar_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collapsed: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if str(row.get("传感器类型", "")).strip() != "钢筋计":
            collapsed.append(dict(row))
            continue
        key = (
            str(row.get("点号", "")).strip(),
            str(row.get("时间", "")).strip(),
        )
        if key not in grouped:
            positions[key] = len(collapsed)
            collapsed.append({})
            grouped[key] = []
        grouped[key].append(dict(row))
    for key, group_rows in grouped.items():
        ordered = sorted(group_rows, key=lambda item: str(item.get("编号", "")))
        frequencies = [
            str(item.get("频率", "")).strip() or "/"
            for item in ordered
        ]
        forces = [
            value
            for item in ordered
            if (value := _optional_number(item.get("轴力（kN）"))) is not None
        ]
        collapsed[positions[key]] = {
            "时间": key[1],
            "点号": key[0],
            "编号": "\n".join(str(item.get("编号", "")).strip() for item in ordered),
            "传感器类型": "钢筋计",
            "频率显示": "\n".join(frequencies),
            "轴力（kN）": forces[0] if forces else "/",
            "备注": next(
                (
                    str(item.get("备注", ""))
                    for item in ordered
                    if str(item.get("备注", "")).strip()
                ),
                "",
            ),
        }
    return collapsed


def _optional_number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _observation_dates_differ(current: Any, previous: Any) -> bool:
    current_parts = split_observation_date(current)
    previous_parts = split_observation_date(previous)
    if current_parts is None or previous_parts is None:
        return str(current or "") != str(previous or "")
    return current_parts[0] != previous_parts[0]


def _number(value: Any, default: float) -> float:
    parsed = _optional_number(value)
    return default if parsed is None else parsed


def _selected_remark(*records: dict[str, Any] | None) -> str:
    for record in records:
        if not record:
            continue
        remark = str(record.get("remark", "") or "").strip()
        if remark:
            return remark
    return ""


def _rounded(value: float) -> float:
    return round(value, 3)


def _is_date(value: str) -> bool:
    return split_observation_date(value) is not None
