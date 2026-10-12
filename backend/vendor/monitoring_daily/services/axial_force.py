from __future__ import annotations

from math import sqrt
from typing import Any


SENSOR_REBAR = "钢筋计"
SENSOR_OTHER = "其他传感器"
AXIAL_SENSOR_TYPES = (SENSOR_REBAR, SENSOR_OTHER)

# 兼容既有调用方和旧工程值。
FORMULA_REBAR = SENSOR_REBAR
FORMULA_GENERAL = SENSOR_OTHER
FORMULA_CONCRETE = SENSOR_OTHER
AXIAL_FORMULA_TYPES = AXIAL_SENSOR_TYPES

POINT_COLUMN = "点号"
NUMBER_COLUMN = "编号"
SENSOR_TYPE_COLUMN = "传感器类型"
CALIBRATION_COLUMN = "标定系数 K（kN/Hz²）"
INITIAL_FREQUENCY_COLUMN = "初始频率 f0（Hz）"
CONVERSION_COLUMN = "轴力转换系数 C（无量纲）"
BAR_DIAMETER_COLUMN = "钢筋直径 d（mm）"
REBAR_COUNT_COLUMN = "钢筋根数 n（根）"
SUPPORT_LENGTH_COLUMN = "支撑长度 L（mm）"
SUPPORT_WIDTH_COLUMN = "支撑宽度 B（mm）"

PI_APPROXIMATION = 3.14
CONCRETE_STEEL_MODULUS_RATIO = 3.0 / 20.0

AXIAL_PARAMETER_COLUMNS = [
    POINT_COLUMN,
    NUMBER_COLUMN,
    SENSOR_TYPE_COLUMN,
    CALIBRATION_COLUMN,
    INITIAL_FREQUENCY_COLUMN,
    CONVERSION_COLUMN,
    BAR_DIAMETER_COLUMN,
    REBAR_COUNT_COLUMN,
    SUPPORT_LENGTH_COLUMN,
    SUPPORT_WIDTH_COLUMN,
]

REBAR_GROUP_COLUMNS = (
    BAR_DIAMETER_COLUMN,
    REBAR_COUNT_COLUMN,
    SUPPORT_LENGTH_COLUMN,
    SUPPORT_WIDTH_COLUMN,
)
REBAR_EDITABLE_COLUMNS = {
    CALIBRATION_COLUMN,
    INITIAL_FREQUENCY_COLUMN,
    *REBAR_GROUP_COLUMNS,
}
OTHER_EDITABLE_COLUMNS = {
    CALIBRATION_COLUMN,
    INITIAL_FREQUENCY_COLUMN,
    CONVERSION_COLUMN,
}

_ALIASES = {
    CALIBRATION_COLUMN: ("标定系数K", "K"),
    INITIAL_FREQUENCY_COLUMN: ("初始频率f0", "出厂频率"),
    CONVERSION_COLUMN: ("轴力转换系数C",),
    BAR_DIAMETER_COLUMN: (
        "钢筋直径",
        "钢筋直径(mm)",
        "钢筋直径（mm）",
    ),
    REBAR_COUNT_COLUMN: ("钢筋根数",),
    SUPPORT_LENGTH_COLUMN: (
        "混凝土支撑长（mm)",
        "混凝土支撑长(mm)",
        "混凝土支撑长度",
    ),
    SUPPORT_WIDTH_COLUMN: (
        "混凝土支撑宽(mm)",
        "混凝土支撑宽（mm)",
        "混凝土支撑宽度",
    ),
}

_LEGACY_GAUGE_AREA_COLUMNS = (
    "钢筋计截面积 Ajs（mm²）",
    "钢筋计截面积Ajs",
    "钢筋横截面积S",
    "钢筋计截面积Ag",
)
_LEGACY_CONCRETE_AREA_COLUMNS = (
    "混凝土截面面积 Ac（mm²）",
    "混凝土截面面积Ac",
    "混凝土截面积Ac",
)
_LEGACY_STEEL_AREA_COLUMNS = (
    "钢筋总截面面积 As（mm²）",
    "钢筋总截面面积As",
    "钢筋截面积As",
)


def parameter_header_label(column: str) -> str:
    """Return a compact two-line UI label while keeping stable storage keys."""
    if "（" not in column or not column.endswith("）"):
        return column
    title, unit = column.rsplit("（", 1)
    return f"{title.rstrip()}\n（{unit}"


def normalize_axial_parameter(
    row: dict[str, Any],
    *,
    strict: bool = True,
) -> dict[str, Any]:
    raw_type = str(
        row.get(SENSOR_TYPE_COLUMN)
        or row.get("计算类型")
        or SENSOR_OTHER
    ).strip()
    sensor_type = SENSOR_REBAR if raw_type == SENSOR_REBAR else SENSOR_OTHER
    normalized: dict[str, Any] = {
        POINT_COLUMN: str(row.get(POINT_COLUMN, "")).strip(),
        NUMBER_COLUMN: str(row.get(NUMBER_COLUMN, "")).strip(),
        SENSOR_TYPE_COLUMN: sensor_type,
    }
    if strict and not normalized[POINT_COLUMN]:
        raise ValueError("轴力参数的点号不能为空。")
    if strict and not normalized[NUMBER_COLUMN]:
        raise ValueError("轴力参数的编号不能为空。")

    for column in AXIAL_PARAMETER_COLUMNS[3:]:
        normalized[column] = _parameter_number(row, column)
    _migrate_legacy_rebar_geometry(row, normalized)

    # 旧“混凝土支撑”参数先按原公式生成 C，再迁移为其他传感器。
    if raw_type == "混凝土支撑" and normalized[CONVERSION_COLUMN] is None:
        ac = _first_number(row, _LEGACY_CONCRETE_AREA_COLUMNS)
        ec = _first_number(row, ("混凝土弹性模量Ec",))
        ag = _first_number(row, _LEGACY_GAUGE_AREA_COLUMNS)
        eg = _first_number(
            row,
            ("钢筋弹性模量Es", "钢筋弹性模量E", "钢筋弹性模量Eg"),
        )
        reinforcement = _first_number(row, _LEGACY_STEEL_AREA_COLUMNS) or 0.0
        if None not in (ac, ec, ag, eg) and ag and eg:
            normalized[CONVERSION_COLUMN] = round(
                float(ac) * float(ec) / (float(ag) * float(eg))
                + float(reinforcement) / float(ag),
                12,
            )

    if sensor_type == SENSOR_REBAR:
        normalized[CONVERSION_COLUMN] = "/"
    else:
        for column in REBAR_GROUP_COLUMNS:
            normalized[column] = "/"

    if strict:
        for column in (CALIBRATION_COLUMN, INITIAL_FREQUENCY_COLUMN):
            if normalized[column] is None:
                raise ValueError(f"{column}不能为空。")
        if sensor_type == SENSOR_REBAR:
            for column in REBAR_GROUP_COLUMNS:
                if normalized[column] is None:
                    raise ValueError(f"钢筋计参数 {column} 不能为空。")
                if float(normalized[column]) <= 0:
                    raise ValueError(f"钢筋计参数 {column} 必须大于 0。")
            if _net_concrete_area(normalized) <= 0:
                raise ValueError("支撑截面积必须大于钢筋总截面积。")
        elif normalized[CONVERSION_COLUMN] is None:
            raise ValueError("其他传感器的轴力转换系数 C 不能为空。")
    return normalized


def synchronize_rebar_group_parameters(
    rows: list[dict[str, Any]],
    *,
    strict: bool,
) -> list[dict[str, Any]]:
    normalized = [normalize_axial_parameter(row, strict=False) for row in rows]
    values_by_point: dict[str, dict[str, float | None]] = {}
    for row in normalized:
        if row[SENSOR_TYPE_COLUMN] != SENSOR_REBAR:
            continue
        point = str(row[POINT_COLUMN])
        point_values = values_by_point.setdefault(
            point,
            {column: None for column in REBAR_GROUP_COLUMNS},
        )
        for column in REBAR_GROUP_COLUMNS:
            value = _optional_number(row.get(column))
            if point_values[column] is None and value is not None:
                point_values[column] = value
    for row in normalized:
        if row[SENSOR_TYPE_COLUMN] != SENSOR_REBAR:
            continue
        for column, value in values_by_point.get(str(row[POINT_COLUMN]), {}).items():
            row[column] = value
    return [normalize_axial_parameter(row, strict=strict) for row in normalized]


def calculate_axial_force(
    frequency: Any,
    parameter: dict[str, Any] | None,
) -> float | None:
    if not parameter:
        return None
    normalized = normalize_axial_parameter(parameter, strict=False)
    if normalized[SENSOR_TYPE_COLUMN] == SENSOR_REBAR:
        return None
    measured = _optional_number(frequency)
    coefficient = _optional_number(normalized.get(CONVERSION_COLUMN))
    calibration = _optional_number(normalized.get(CALIBRATION_COLUMN))
    initial = _optional_number(normalized.get(INITIAL_FREQUENCY_COLUMN))
    if measured is None or coefficient is None or calibration is None or initial is None:
        return None
    value = coefficient * calibration * (measured**2 - initial**2)
    return round(value, 1)


def calculate_rebar_point_force(
    frequencies_by_number: dict[str, Any],
    parameters: list[dict[str, Any]],
) -> float | None:
    if not parameters:
        return None
    normalized = synchronize_rebar_group_parameters(parameters, strict=False)
    if any(row[SENSOR_TYPE_COLUMN] != SENSOR_REBAR for row in normalized):
        return None
    first = normalized[0]
    diameter = _optional_number(first.get(BAR_DIAMETER_COLUMN))
    rebar_count = _optional_number(first.get(REBAR_COUNT_COLUMN))
    support_length = _optional_number(first.get(SUPPORT_LENGTH_COLUMN))
    support_width = _optional_number(first.get(SUPPORT_WIDTH_COLUMN))
    if (
        diameter is None
        or rebar_count is None
        or support_length is None
        or support_width is None
        or min(diameter, rebar_count, support_length, support_width) <= 0
    ):
        return None

    single_rebar_area = PI_APPROXIMATION * (diameter / 2.0) ** 2
    stresses: list[float] = []
    for parameter in normalized:
        number = str(parameter[NUMBER_COLUMN])
        frequency = _optional_number(frequencies_by_number.get(number))
        calibration = _optional_number(parameter.get(CALIBRATION_COLUMN))
        initial = _optional_number(parameter.get(INITIAL_FREQUENCY_COLUMN))
        if frequency is None:
            continue
        if calibration is None or initial is None:
            continue
        gauge_value = calibration * (initial**2 - frequency**2)
        stresses.append(gauge_value / single_rebar_area)
    if not stresses:
        return None

    steel_area = single_rebar_area * rebar_count
    gross_area = support_length * support_width
    net_concrete_area = gross_area - steel_area
    if net_concrete_area <= 0:
        return None
    average_stress = sum(stresses) / len(stresses)
    equivalent_area = (
        CONCRETE_STEEL_MODULUS_RATIO * net_concrete_area
        + steel_area
    )
    return round(average_stress * equivalent_area, 1)


def _migrate_legacy_rebar_geometry(
    row: dict[str, Any],
    normalized: dict[str, Any],
) -> None:
    if normalized[SENSOR_TYPE_COLUMN] != SENSOR_REBAR:
        return
    legacy_gauge_area = _first_number(row, _LEGACY_GAUGE_AREA_COLUMNS)
    if normalized[BAR_DIAMETER_COLUMN] is None and legacy_gauge_area:
        normalized[BAR_DIAMETER_COLUMN] = 2.0 * sqrt(
            legacy_gauge_area / PI_APPROXIMATION
        )
    legacy_steel_area = _first_number(row, _LEGACY_STEEL_AREA_COLUMNS)
    diameter = _optional_number(normalized.get(BAR_DIAMETER_COLUMN))
    if normalized[REBAR_COUNT_COLUMN] is None and legacy_steel_area and diameter:
        single_area = PI_APPROXIMATION * (diameter / 2.0) ** 2
        if single_area:
            normalized[REBAR_COUNT_COLUMN] = legacy_steel_area / single_area
    legacy_concrete_area = _first_number(row, _LEGACY_CONCRETE_AREA_COLUMNS)
    if (
        legacy_concrete_area is not None
        and legacy_steel_area is not None
        and (
            normalized[SUPPORT_LENGTH_COLUMN] is None
            or normalized[SUPPORT_WIDTH_COLUMN] is None
        )
    ):
        side = sqrt(max(legacy_concrete_area + legacy_steel_area, 0.0))
        normalized[SUPPORT_LENGTH_COLUMN] = (
            normalized[SUPPORT_LENGTH_COLUMN] or side
        )
        normalized[SUPPORT_WIDTH_COLUMN] = (
            normalized[SUPPORT_WIDTH_COLUMN] or side
        )


def _net_concrete_area(parameter: dict[str, Any]) -> float:
    diameter = float(parameter[BAR_DIAMETER_COLUMN])
    rebar_count = float(parameter[REBAR_COUNT_COLUMN])
    gross_area = (
        float(parameter[SUPPORT_LENGTH_COLUMN])
        * float(parameter[SUPPORT_WIDTH_COLUMN])
    )
    steel_area = PI_APPROXIMATION * (diameter / 2.0) ** 2 * rebar_count
    return gross_area - steel_area


def _parameter_number(row: dict[str, Any], column: str) -> float | None:
    if column in row:
        return _optional_number(row.get(column))
    return _first_number(row, _ALIASES.get(column, ()))


def _first_number(
    row: dict[str, Any],
    columns: tuple[str, ...],
) -> float | None:
    for column in columns:
        if column in row:
            return _optional_number(row.get(column))
    return None


def _optional_number(value: Any) -> float | None:
    text = str(value if value is not None else "").strip()
    if not text or text == "/":
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None
