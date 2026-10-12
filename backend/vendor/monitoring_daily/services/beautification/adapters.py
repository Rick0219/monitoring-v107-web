"""Monitor-specific adapters for non-destructive beautification data."""

from __future__ import annotations

from copy import deepcopy
from math import hypot
from typing import Any, Callable

from monitoring_daily.services.axial_force import (
    INITIAL_FREQUENCY_COLUMN,
    NUMBER_COLUMN,
    POINT_COLUMN,
    SENSOR_REBAR,
    SENSOR_TYPE_COLUMN,
    calculate_axial_force,
    calculate_rebar_point_force,
)
from monitoring_daily.services.beautification.base import (
    BeautificationContext,
    adapter_registry,
)
from monitoring_daily.services.measurement_calculations import (
    calculate_difference,
    calculate_horizontal_displacement_mm,
    calculate_water_elevation,
)
from monitoring_daily.services.report_data import normalize_horizontal_displacement_mode
from monitoring_daily.services.tilt import (
    POINT_1_COLUMN,
    POINT_2_COLUMN,
    TILT_COLUMN,
)
from monitoring_daily.services.water_level import (
    PIPE_ELEVATION_COLUMN,
    WATER_POINT_COLUMN,
    WATER_READING_COLUMN,
)


def _number(value: Any) -> float | None:
    if value in (None, "", "/"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_date(record: dict) -> str:
    return str(record.get("时间", "") or "")


def _normalized_depth(value: Any) -> str:
    numeric = _number(value)
    if numeric is None:
        return str(value or "").strip()
    # The workbook stores depth labels exactly as entered (for example 1.0),
    # so preserve that representation in the series key.
    return str(value).strip()


def _records_for_series(
    context: BeautificationContext,
    series_id: str,
    identify: Callable[[dict], str],
) -> list[dict]:
    rows = context.project.get("measurements", {}).get(context.monitor_key, [])
    return sorted(
        (row for row in rows if identify(row) == series_id),
        key=_record_date,
    )


def _baseline_record(
    context: BeautificationContext,
    series_id: str,
    identify: Callable[[dict], str],
    fallback: list[dict],
) -> dict:
    records = _records_for_series(context, series_id, identify)
    if records:
        return records[0]
    ordered_fallback = sorted(fallback, key=_record_date)
    if ordered_fallback:
        return ordered_fallback[0]
    raise ValueError(f"测点“{series_id}”没有可用于计算的首期数据。")


def solve_frequency_for_target_axial(
    *,
    target_axial: float,
    forward: Callable[[float], float | None],
    lower_frequency: float,
    upper_frequency: float,
    tolerance: float = 1e-6,
    max_iterations: int = 60,
) -> float:
    """Use the existing axial-force forward formula to recover a frequency.

    This deliberately has no fabricated-frequency fallback.  A caller must
    provide a range that brackets the desired axial force.
    """

    def evaluate(frequency: float) -> float:
        value = forward(frequency)
        if value is None:
            raise ValueError("目标轴力无法在有效频率范围内反算")
        return float(value)

    lo = float(lower_frequency)
    hi = float(upper_frequency)
    flo = evaluate(lo) - float(target_axial)
    fhi = evaluate(hi) - float(target_axial)
    if flo == 0.0:
        return lo
    if fhi == 0.0:
        return hi
    if flo * fhi > 0:
        raise ValueError("目标轴力无法在有效频率范围内反算")

    for _ in range(max_iterations):
        mid = (lo + hi) / 2.0
        fmid = evaluate(mid) - float(target_axial)
        if abs(fmid) <= tolerance:
            return mid
        if flo * fmid <= 0:
            hi = mid
            fhi = fmid
        else:
            lo = mid
            flo = fmid

    mid = (lo + hi) / 2.0
    if abs(evaluate(mid) - float(target_axial)) > tolerance:
        raise ValueError("目标轴力反算未在迭代上限内收敛")
    return mid


def _axial_parameters(context: BeautificationContext) -> list[dict]:
    raw_parameters = context.project.get("axial_parameters", {})
    if isinstance(raw_parameters, dict):
        rows = raw_parameters.get(context.monitor_key, raw_parameters.get("axial", []))
    else:
        rows = raw_parameters
    return [dict(row) for row in rows if isinstance(row, dict)]


def _horizontal_displacement_mode(context: BeautificationContext) -> str:
    report_settings = context.project.get("report_settings", {})
    if not isinstance(report_settings, dict):
        return "xy"
    alerts = report_settings.get("alerts", {})
    if not isinstance(alerts, dict):
        alerts = {}
    settings = alerts.get(context.monitor_key)
    if not isinstance(settings, dict):
        defaults = report_settings.get("alert_defaults", {})
        settings = defaults.get("horizontal") if isinstance(defaults, dict) else None
    if not isinstance(settings, dict):
        for key, candidate in reversed(list(alerts.items())):
            if str(key).partition(":")[0] == "horizontal" and isinstance(candidate, dict):
                settings = candidate
                break
    return normalize_horizontal_displacement_mode(
        settings.get("displacement_mode") if isinstance(settings, dict) else None
    )


class LevelBeautificationAdapter:
    monitor_type = "level"

    def series_id(self, record: dict) -> str:
        return str(record.get("点号", "") or "").strip()

    def metric_unit(self, context: BeautificationContext) -> str:
        return "mm"

    def has_actual_measurement(
        self, record: dict, *, context: BeautificationContext
    ) -> bool:
        return _number(record.get("测量值")) is not None

    def raw_to_metric(
        self,
        record: dict,
        *,
        context: BeautificationContext,
        history: list[dict],
    ) -> float:
        series_id = self.series_id(record)
        initial = _baseline_record(context, series_id, self.series_id, [*history, record])
        result = calculate_difference(
            _number(record.get("测量值")),
            _number(initial.get("测量值")),
            multiplier=1000.0,
        )
        if result is None:
            raise ValueError(f"测点“{series_id}”缺少有效水准测量值。")
        return result

    def metric_to_record(
        self,
        target_metric: float,
        *,
        context: BeautificationContext,
        source_record: dict | None,
        previous_record: dict | None,
    ) -> dict:
        result = deepcopy(source_record or previous_record or {})
        series_id = self.series_id(result)
        initial = _baseline_record(context, series_id, self.series_id, [row for row in (previous_record,) if row])
        initial_value = _number(initial.get("测量值"))
        if initial_value is None:
            raise ValueError(f"测点“{series_id}”缺少有效水准首期测量值。")
        result["测量值"] = initial_value + float(target_metric) / 1000.0
        return result


class WaterBeautificationAdapter:
    monitor_type = "water"

    def series_id(self, record: dict) -> str:
        return str(record.get(WATER_POINT_COLUMN, record.get("点号", "")) or "").strip()

    def metric_unit(self, context: BeautificationContext) -> str:
        return "mm"

    def has_actual_measurement(
        self, record: dict, *, context: BeautificationContext
    ) -> bool:
        return _number(record.get(WATER_READING_COLUMN)) is not None

    def _pipe_elevation(self, context: BeautificationContext, series_id: str, record: dict) -> float:
        for parameter in context.project.get("water_parameters", []):
            parameter_point = str(
                parameter.get(WATER_POINT_COLUMN, parameter.get("点号", "")) or ""
            ).strip()
            if parameter_point == series_id:
                value = _number(parameter.get(PIPE_ELEVATION_COLUMN))
                if value is not None:
                    return value
        value = _number(record.get(PIPE_ELEVATION_COLUMN))
        if value is None:
            raise ValueError(f"点位“{series_id}”缺少管口高程（m）。")
        return value

    def _elevation(self, context: BeautificationContext, record: dict) -> float | None:
        series_id = self.series_id(record)
        return calculate_water_elevation(
            self._pipe_elevation(context, series_id, record),
            _number(record.get(WATER_READING_COLUMN)),
        )

    def raw_to_metric(
        self,
        record: dict,
        *,
        context: BeautificationContext,
        history: list[dict],
    ) -> float:
        series_id = self.series_id(record)
        initial = _baseline_record(context, series_id, self.series_id, [*history, record])
        result = calculate_difference(
            self._elevation(context, record),
            self._elevation(context, initial),
            multiplier=1000.0,
        )
        if result is None:
            raise ValueError(f"点位“{series_id}”缺少有效水位读数。")
        return result

    def metric_to_record(
        self,
        target_metric: float,
        *,
        context: BeautificationContext,
        source_record: dict | None,
        previous_record: dict | None,
    ) -> dict:
        result = deepcopy(source_record or previous_record or {})
        series_id = self.series_id(result)
        initial = _baseline_record(context, series_id, self.series_id, [row for row in (previous_record,) if row])
        pipe_elevation = self._pipe_elevation(context, series_id, result)
        initial_elevation = self._elevation(context, initial)
        if initial_elevation is None:
            raise ValueError(f"点位“{series_id}”缺少有效水位首期读数。")
        target_elevation = initial_elevation + float(target_metric) / 1000.0
        result[WATER_POINT_COLUMN] = series_id
        result[PIPE_ELEVATION_COLUMN] = pipe_elevation
        result[WATER_READING_COLUMN] = pipe_elevation - target_elevation
        return result


class TiltBeautificationAdapter:
    monitor_type = "tilt"

    def series_id(self, record: dict) -> str:
        point_1 = str(record.get(POINT_1_COLUMN, "") or "").strip()
        point_2 = str(record.get(POINT_2_COLUMN, "") or "").strip()
        return f"{point_1}|{point_2}"

    def metric_unit(self, context: BeautificationContext) -> str:
        return "‰"

    def has_actual_measurement(
        self, record: dict, *, context: BeautificationContext
    ) -> bool:
        return _number(record.get(TILT_COLUMN)) is not None

    def raw_to_metric(
        self,
        record: dict,
        *,
        context: BeautificationContext,
        history: list[dict],
    ) -> float:
        value = _number(record.get(TILT_COLUMN))
        if value is None:
            raise ValueError(f"倾斜测点组“{self.series_id(record)}”缺少有效倾斜度。")
        return value

    def metric_to_record(
        self,
        target_metric: float,
        *,
        context: BeautificationContext,
        source_record: dict | None,
        previous_record: dict | None,
    ) -> dict:
        result = deepcopy(source_record or previous_record or {})
        result[TILT_COLUMN] = float(target_metric)
        return result


class InclinometerBeautificationAdapter:
    """Keep each inclinometer depth as an independent cumulative-displacement series."""

    monitor_type = "inclinometer"

    def series_id(self, record: dict) -> str:
        return f"depth:{_normalized_depth(record.get('深度'))}"

    def metric_unit(self, context: BeautificationContext) -> str:
        return "mm"

    def has_actual_measurement(
        self, record: dict, *, context: BeautificationContext
    ) -> bool:
        return _number(record.get("测值")) is not None

    def raw_to_metric(
        self,
        record: dict,
        *,
        context: BeautificationContext,
        history: list[dict],
    ) -> float:
        series_id = self.series_id(record)
        initial = _baseline_record(context, series_id, self.series_id, [*history, record])
        result = calculate_difference(
            _number(record.get("测值")),
            _number(initial.get("测值")),
            multiplier=1000.0,
        )
        if result is None:
            raise ValueError(f"深度“{_normalized_depth(record.get('深度'))}m”缺少有效测值。")
        return result

    def metric_to_record(
        self,
        target_metric: float,
        *,
        context: BeautificationContext,
        source_record: dict | None,
        previous_record: dict | None,
    ) -> dict:
        result = deepcopy(source_record or previous_record or {})
        series_id = self.series_id(result)
        initial = _baseline_record(
            context,
            series_id,
            self.series_id,
            [row for row in (previous_record,) if row],
        )
        initial_value = _number(initial.get("测值"))
        if initial_value is None:
            raise ValueError(
                f"深度“{_normalized_depth(result.get('深度'))}m”缺少有效首期测值。"
            )
        result["测值"] = initial_value + float(target_metric) / 1000.0
        return result


class AxialBeautificationAdapter:
    """Generate axial-force records by inverting the existing force formula."""

    monitor_type = "axial"

    def series_id(self, record: dict) -> str:
        point = str(record.get(POINT_COLUMN, "") or "").strip()
        number = str(record.get(NUMBER_COLUMN, "") or "").strip()
        return f"{point}|{number}"

    def metric_unit(self, context: BeautificationContext) -> str:
        return "kN"

    def has_actual_measurement(
        self, record: dict, *, context: BeautificationContext
    ) -> bool:
        return _number(record.get("频率")) is not None

    def _parameter_for_record(
        self,
        context: BeautificationContext,
        record: dict,
    ) -> dict:
        point = str(record.get(POINT_COLUMN, "") or "").strip()
        number = str(record.get(NUMBER_COLUMN, "") or "").strip()
        for parameter in _axial_parameters(context):
            if (
                str(parameter.get(POINT_COLUMN, "") or "").strip() == point
                and str(parameter.get(NUMBER_COLUMN, "") or "").strip() == number
            ):
                return parameter
        raise ValueError(f"轴力测点“{point}”编号“{number}”缺少参数设置。")

    def _point_parameters(
        self,
        context: BeautificationContext,
        point: str,
    ) -> list[dict]:
        return [
            parameter
            for parameter in _axial_parameters(context)
            if str(parameter.get(POINT_COLUMN, "") or "").strip() == point
            and str(parameter.get(SENSOR_TYPE_COLUMN, "") or "").strip() == SENSOR_REBAR
        ]

    def _date_frequencies(
        self,
        context: BeautificationContext,
        record: dict,
    ) -> dict[str, float]:
        point = str(record.get(POINT_COLUMN, "") or "").strip()
        record_date = _record_date(record)
        rows = context.project.get("measurements", {}).get(context.monitor_key, [])
        frequencies: dict[str, float] = {}
        for row in rows:
            if (
                str(row.get(POINT_COLUMN, "") or "").strip() != point
                or _record_date(row) != record_date
            ):
                continue
            frequency = _number(row.get("频率"))
            if frequency is not None:
                frequencies[str(row.get(NUMBER_COLUMN, "") or "").strip()] = frequency
        frequency = _number(record.get("频率"))
        if frequency is not None:
            frequencies[str(record.get(NUMBER_COLUMN, "") or "").strip()] = frequency
        return frequencies

    @staticmethod
    def _solve_frequency(
        *,
        target_axial: float,
        forward: Callable[[float], float | None],
        initial_frequency: float | None,
        current_frequency: float | None,
    ) -> float:
        upper = max(
            10.0,
            abs(initial_frequency or 0.0) * 2.0,
            abs(current_frequency or 0.0) * 2.0,
        )
        for _ in range(10):
            try:
                return solve_frequency_for_target_axial(
                    target_axial=target_axial,
                    forward=forward,
                    lower_frequency=0.0,
                    upper_frequency=upper,
                )
            except ValueError as exc:
                if str(exc) != "目标轴力无法在有效频率范围内反算":
                    raise
                upper *= 2.0
        raise ValueError("目标轴力无法在有效频率范围内反算")

    def raw_to_metric(
        self,
        record: dict,
        *,
        context: BeautificationContext,
        history: list[dict],
    ) -> float:
        parameter = self._parameter_for_record(context, record)
        sensor_type = str(parameter.get(SENSOR_TYPE_COLUMN, "") or "").strip()
        if sensor_type == SENSOR_REBAR:
            point = str(record.get(POINT_COLUMN, "") or "").strip()
            value = calculate_rebar_point_force(
                self._date_frequencies(context, record),
                self._point_parameters(context, point),
            )
        else:
            value = calculate_axial_force(record.get("频率"), parameter)
        if value is None:
            raise ValueError(f"轴力测点“{self.series_id(record)}”无法根据频率计算轴力。")
        return float(value)

    def metric_to_record(
        self,
        target_metric: float,
        *,
        context: BeautificationContext,
        source_record: dict | None,
        previous_record: dict | None,
    ) -> dict:
        result = deepcopy(source_record or previous_record or {})
        if not result:
            raise ValueError("轴力美化记录缺少点号、编号和频率。")
        parameter = self._parameter_for_record(context, result)
        sensor_type = str(parameter.get(SENSOR_TYPE_COLUMN, "") or "").strip()
        initial_frequency = _number(parameter.get(INITIAL_FREQUENCY_COLUMN))
        current_frequency = _number(result.get("频率"))
        target = round(float(target_metric), 1)

        if sensor_type == SENSOR_REBAR:
            point = str(result.get(POINT_COLUMN, "") or "").strip()
            parameters = self._point_parameters(context, point)
            frequencies = self._date_frequencies(context, result)
            number = str(result.get(NUMBER_COLUMN, "") or "").strip()
            if number not in frequencies:
                raise ValueError(f"钢筋计“{point}”编号“{number}”缺少待反算频率。")

            def forward(frequency: float) -> float | None:
                candidate = dict(frequencies)
                candidate[number] = frequency
                return calculate_rebar_point_force(candidate, parameters)

        else:
            def forward(frequency: float) -> float | None:
                return calculate_axial_force(frequency, parameter)

        frequency = self._solve_frequency(
            target_axial=target,
            forward=forward,
            initial_frequency=initial_frequency,
            current_frequency=current_frequency,
        )
        verified_force = forward(frequency)
        if verified_force is None or abs(float(verified_force) - target) > 1e-6:
            raise ValueError("生成频率未通过轴力正算验证。")
        result["频率"] = frequency
        result["轴力（kN）"] = float(verified_force)
        return result


class HorizontalDisplacementBeautificationAdapter:
    """Rebuild horizontal coordinates through the existing X/Y/XY rule."""

    monitor_type = "horizontal"

    def series_id(self, record: dict) -> str:
        return str(record.get("点号", "") or "").strip()

    def metric_unit(self, context: BeautificationContext) -> str:
        return "mm"

    def has_actual_measurement(
        self, record: dict, *, context: BeautificationContext
    ) -> bool:
        mode = _horizontal_displacement_mode(context)
        has_x = _number(record.get("X 坐标")) is not None
        has_y = _number(record.get("Y 坐标")) is not None
        if mode == "x":
            return has_x
        if mode == "y":
            return has_y
        return has_x and has_y

    def raw_to_metric(
        self,
        record: dict,
        *,
        context: BeautificationContext,
        history: list[dict],
    ) -> float:
        series_id = self.series_id(record)
        initial = _baseline_record(context, series_id, self.series_id, [*history, record])
        mode = _horizontal_displacement_mode(context)
        result = calculate_horizontal_displacement_mm(
            {"x": _number(initial.get("X 坐标")), "y": _number(initial.get("Y 坐标"))},
            {"x": _number(record.get("X 坐标")), "y": _number(record.get("Y 坐标"))},
            mode,
        )
        if result is None:
            raise ValueError(f"测点“{series_id}”缺少有效水平位移坐标。")
        return result

    def metric_to_record(
        self,
        target_metric: float,
        *,
        context: BeautificationContext,
        source_record: dict | None,
        previous_record: dict | None,
    ) -> dict:
        result = deepcopy(source_record or previous_record or {})
        series_id = self.series_id(result)
        if not series_id:
            raise ValueError("水平位移美化记录缺少点号。")
        initial = _baseline_record(
            context,
            series_id,
            self.series_id,
            [row for row in (previous_record,) if row],
        )
        initial_x = _number(initial.get("X 坐标"))
        initial_y = _number(initial.get("Y 坐标"))
        mode = _horizontal_displacement_mode(context)
        offset_m = float(target_metric) / 1000.0

        if mode == "x":
            if initial_x is None:
                raise ValueError(f"测点“{series_id}”缺少初始 X 坐标。")
            result["X 坐标"] = initial_x + offset_m
            return result
        if mode == "y":
            if initial_y is None:
                raise ValueError(f"测点“{series_id}”缺少初始 Y 坐标。")
            result["Y 坐标"] = initial_y + offset_m
            return result

        if initial_x is None or initial_y is None:
            raise ValueError(f"测点“{series_id}”缺少初始 XY 坐标。")
        direction_source = source_record or previous_record
        source_x = _number(direction_source.get("X 坐标")) if direction_source else None
        source_y = _number(direction_source.get("Y 坐标")) if direction_source else None
        if source_x is None or source_y is None:
            raise ValueError("缺少水平位移方向")
        dx = source_x - initial_x
        dy = source_y - initial_y
        length = hypot(dx, dy)
        if length == 0.0:
            raise ValueError("缺少水平位移方向")
        result["X 坐标"] = initial_x + offset_m * dx / length
        result["Y 坐标"] = initial_y + offset_m * dy / length
        return result


adapter_registry.register(LevelBeautificationAdapter())
adapter_registry.register(WaterBeautificationAdapter())
adapter_registry.register(TiltBeautificationAdapter())
adapter_registry.register(InclinometerBeautificationAdapter())
adapter_registry.register(AxialBeautificationAdapter())
adapter_registry.register(HorizontalDisplacementBeautificationAdapter())
