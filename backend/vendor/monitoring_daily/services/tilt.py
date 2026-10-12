from __future__ import annotations

from typing import Any, Iterable

from monitoring_daily.services.observation_date import normalize_observation_date


POINT_1_COLUMN = "点号1"
POINT_2_COLUMN = "点号2"
DISTANCE_COLUMN = "两点距离L（m）"
LEGACY_DISTANCE_COLUMN = "两点距离L（mm）"
TILT_COLUMN = "倾斜度（‰）"

TILT_PARAMETER_COLUMNS = [POINT_1_COLUMN, POINT_2_COLUMN, DISTANCE_COLUMN]
TILT_TABLE_COLUMNS = [*TILT_PARAMETER_COLUMNS, TILT_COLUMN]


def normalize_tilt_parameter(
    row: dict[str, Any],
    *,
    allowed_points: Iterable[str] | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    point_1 = str(row.get(POINT_1_COLUMN, "")).strip()
    point_2 = str(row.get(POINT_2_COLUMN, "")).strip()
    distance_value = row.get(DISTANCE_COLUMN)
    if distance_value in (None, "") and row.get(LEGACY_DISTANCE_COLUMN) not in (None, ""):
        legacy_distance = _numeric(row.get(LEGACY_DISTANCE_COLUMN))
        distance_value = legacy_distance / 1000.0 if legacy_distance is not None else None
    distance = _positive_number(distance_value, strict=strict)

    if strict and (not point_1 or not point_2):
        raise ValueError("点号1和点号2不能为空。")
    if point_1 and point_2 and point_1 == point_2:
        raise ValueError("点号1和点号2不能相同。")

    if allowed_points is not None:
        available = {str(point).strip() for point in allowed_points if str(point).strip()}
        missing = [point for point in (point_1, point_2) if point and point not in available]
        if missing:
            raise ValueError(
                f"点号“{'、'.join(missing)}”不在所选水准数据库中。"
            )

    return {
        POINT_1_COLUMN: point_1,
        POINT_2_COLUMN: point_2,
        DISTANCE_COLUMN: distance if distance is not None else "",
    }


def calculate_tilt_rows(
    parameters: list[dict[str, Any]],
    level_rows: list[dict[str, Any]],
    observed_date: str,
) -> list[dict[str, Any]]:
    target_date = _normalize_date(observed_date)
    values_by_point: dict[str, dict[str, float]] = {}
    for row in level_rows:
        point = str(row.get("点号", "")).strip()
        date_value = _normalize_date(row.get("时间"))
        value = _numeric(row.get("测量值"))
        if point and date_value and value is not None:
            values_by_point.setdefault(point, {})[date_value] = value

    cumulative_by_point: dict[str, float | None] = {}
    for point, dated_values in values_by_point.items():
        ordered_dates = sorted(dated_values)
        initial = dated_values[ordered_dates[0]] if ordered_dates else None
        current = dated_values.get(target_date) if target_date else None
        cumulative_by_point[point] = (
            (current - initial) * 1000.0
            if current is not None and initial is not None
            else None
        )

    result: list[dict[str, Any]] = []
    for parameter in parameters:
        normalized = normalize_tilt_parameter(parameter, strict=False)
        point_1 = normalized[POINT_1_COLUMN]
        point_2 = normalized[POINT_2_COLUMN]
        distance_m = _numeric(normalized[DISTANCE_COLUMN])
        cumulative_1 = cumulative_by_point.get(point_1)
        cumulative_2 = cumulative_by_point.get(point_2)
        if (
            cumulative_1 is None
            or cumulative_2 is None
            or distance_m is None
            or distance_m <= 0
        ):
            tilt: float | int | str = "/"
        else:
            distance_mm = distance_m * 1000.0
            tilt = round(abs(cumulative_1 - cumulative_2) / distance_mm * 1000.0, 2)
        result.append({**normalized, TILT_COLUMN: tilt})
    return result


def _positive_number(value: Any, *, strict: bool) -> float | int | None:
    number = _numeric(value)
    if number is None:
        if strict:
            raise ValueError("两点距离L（m）必须是数字。")
        return None
    if number <= 0:
        if strict:
            raise ValueError("两点距离L（m）必须大于0。")
        return None
    return _rounded(number)


def _numeric(value: Any) -> float | None:
    if value in (None, "", "/"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_date(value: Any) -> str | None:
    return normalize_observation_date(value)


def _rounded(value: float) -> float | int:
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded
