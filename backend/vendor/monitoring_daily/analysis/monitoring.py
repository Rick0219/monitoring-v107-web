"""Bounded, JSON-only analysis over a snapshot of ORIGINAL project measurements.

The existing report functions remain the authority for report columns.  Each
identity is calculated separately so gaps in other points cannot choose its
previous observation. No service method is invoked on the live service.
"""
from __future__ import annotations

import copy
import math
from datetime import timedelta
from typing import Any

from .models import check_cancel

from monitoring_daily.services.alert_thresholds import alert_status, threshold_bounds_from_settings
from monitoring_daily.services.measurement_calculations import calculate_water_elevation
from monitoring_daily.services.observation_date import (
    normalize_observation_date,
    observation_datetime,
    observation_interval_days,
    observation_sort_key,
)
from monitoring_daily.services.project_service import ProjectService
from monitoring_daily.services.report_data import (
    build_cumulative_series,
    build_report_rows,
    export_columns_for_measurement,
    normalize_horizontal_displacement_mode,
)


_METRICS = {
    "level": ("mm", "本次累计变化量（mm）", "变化速率（mm/d）"),
    "water": ("mm", "本次累计变化量(mm)", "变化速率(mm/d)"),
    "horizontal": ("mm", "本次累计变化量（mm）", "变化速率（mm/d）"),
    "inclinometer": ("mm", "本次累计值（mm）", "变化速率（mm/d）"),
    "axial": ("kN", "累计变化量（kN）", "变化速率（kN/d）"),
    "tilt": ("‰", "累计倾斜变化量（‰）", "变化速率（‰/d）"),
}
_VALUE_COLUMNS = {
    "level": ("测量值",), "water": ("管口高程（m）", "水位读数（m）"),
    "horizontal": ("X 坐标", "Y 坐标"), "axial": ("轴力（kN）", "频率"),
    "tilt": ("倾斜度（‰）",),
}
MAX_ROWS = 1000
MAX_SERIES = 30
ALL_MEASUREMENTS = '__all__'
MAX_MODEL_MEASUREMENTS = 120


def _checked(items, cancel=None):
    for item in items:
        check_cancel(cancel)
        yield item


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class MonitoringReader:
    """Snapshot once, query many times without modifying the service or .proj.

    Points are exact identifiers: ordinary point names, a tilt pair ``P1-P2``,
    or inclinometer depth text (e.g. ``1``, ``10``). Axial point selection
    includes all of that point's sensors, each with a separate row and series.
    ``limit`` caps both returned report rows and total trend values; at most
    30 trend series and 1000 rows are returned per measurement. Single-item
    statistics cover returned rows; comprehensive statistics stream every row
    in the selected range independently of the detail and trend limits.
    """

    def __init__(self, project_service: ProjectService):
        if not project_service.has_project:
            raise ValueError("请先打开工程。")
        self._service = ProjectService()
        self._service.current_project = copy.deepcopy(project_service.current_project)
        self._service._payload = copy.deepcopy(project_service._payload)
        # This snapshot is never persisted and beautification cannot be read by
        # accident, including through a future helper introduced in this class.
        for name in ("beautified_measurements", "beautification_config", "beautification_meta"):
            self._service._payload.pop(name, None)
        project = self._service.current_project
        self._project = {"name": project.name, "path": str(project.path)}
        self._measurements = []
        for item in self._service.list_measurement_sets():
            key = item["key"]
            monitor, _, data_name = key.partition(":")
            self._measurements.append({**item, "measurement_key": key,
                                       "monitor_key": monitor, "data_name": data_name or item["label"]})

    def list_measurements(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._measurements)

    def _measurement(self, key: str) -> dict[str, Any]:
        for item in self._measurements:
            if item["key"] == key:
                return item
        raise ValueError("所选测项不存在于当前工程快照中。")

    def _load(self, key: str, cancel=None) -> tuple[list[dict[str, Any]], int]:
        check_cancel(cancel)
        item = self._measurement(key)
        monitor = item["monitor_key"]
        result, invalid = [], 0
        for raw in _checked(self._service.load_measurement_set(key), cancel):
            if not isinstance(raw, dict):
                invalid += 1
                continue
            row = copy.deepcopy(raw)
            if monitor == "inclinometer":
                normalized = {"深度": row.get("深度", "")}
                for column, value in _checked(row.items(), cancel):
                    date = normalize_observation_date(column)
                    if date:
                        normalized.setdefault(date, _number(value) if _number(value) is not None else "/")
                if _number(normalized["深度"]) is None or len(normalized) == 1:
                    invalid += 1
                    continue
                row = normalized
            else:
                date = normalize_observation_date(row.get("时间"))
                if date is None:
                    invalid += 1
                    continue
                row["时间"] = date
                for column in _VALUE_COLUMNS.get(monitor, ()):
                    value = _number(row.get(column))
                    row[column] = value if value is not None else "/"
            result.append(row)
        return result, invalid

    @staticmethod
    def _dates(rows: list[dict[str, Any]], monitor: str, cancel=None) -> list[str]:
        if monitor == "inclinometer":
            dates = {column for row in _checked(rows, cancel) for column in _checked(row, cancel) if column != "深度"}
        else:
            dates = {_text(row.get("时间")) for row in _checked(rows, cancel)}
        return sorted(dates, key=observation_sort_key)

    def list_dates(self, measurement_key: str = "") -> list[str]:
        keys = [measurement_key] if measurement_key and measurement_key != ALL_MEASUREMENTS else [item["key"] for item in self._measurements]
        dates = set()
        for key in keys:
            try:
                rows, _ = self._load(key)
                dates.update(self._dates(rows, key.partition(":")[0]))
            except InterruptedError:
                raise
            except Exception:
                if measurement_key != ALL_MEASUREMENTS:
                    raise
                # Keep the comprehensive date picker usable. analyze_all
                # reports each unreadable measurement explicitly to the user.
                continue
        return sorted(dates, key=observation_sort_key)

    @staticmethod
    def _identity(row: dict[str, Any], monitor: str) -> tuple[str, ...]:
        if monitor == "inclinometer":
            return (_text(row.get("深度")),)
        if monitor == "tilt":
            return (_text(row.get("点号1")), _text(row.get("点号2")))
        point = _text(row.get("点位" if monitor == "water" else "点号"))
        return (point, _text(row.get("编号"))) if monitor == "axial" else (point,)

    @staticmethod
    def _selector(identity: tuple[str, ...], monitor: str) -> str:
        return "-".join(identity) if monitor == "tilt" else identity[0]

    def list_points(self, measurement_key: str) -> list[str]:
        item = self._measurement(measurement_key)
        rows, _ = self._load(measurement_key)
        points = []
        for row in rows:
            identity = self._identity(row, item["monitor_key"])
            if all(identity):
                point = self._selector(identity, item["monitor_key"])
                if point not in points:
                    points.append(point)
        return points

    @staticmethod
    def _value(row: dict[str, Any], monitor: str, mode: str) -> float | None:
        if monitor == "water":
            return calculate_water_elevation(_number(row.get("管口高程（m）")),
                                             _number(row.get("水位读数（m）")))
        if monitor == "horizontal":
            x, y = _number(row.get("X 坐标")), _number(row.get("Y 坐标"))
            if mode == "x":
                return x
            if mode == "y":
                return y
            return math.hypot(x, y) if x is not None and y is not None else None
        column = {"level": "测量值", "axial": "轴力（kN）", "tilt": "倾斜度（‰）"}.get(monitor)
        return _number(row.get(column))

    @staticmethod
    def _history(rows: list[dict[str, Any]], monitor: str, end: str, cancel=None) -> list[dict[str, Any]]:
        end_key = observation_sort_key(end)
        if monitor == "inclinometer":
            return [{key: value for key, value in _checked(row.items(), cancel)
                     if key == "深度" or observation_sort_key(key) <= end_key} for row in _checked(rows, cancel)]
        return [row for row in _checked(rows, cancel) if observation_sort_key(row["时间"]) <= end_key]

    def _series_values(self, rows, monitor, mode, cancel=None) -> dict[str, float | None]:
        check_cancel(cancel)
        if monitor == "water":
            # build_cumulative_series has no native water branch. Adapt the
            # ORIGINAL computed water elevation to its level input in metres.
            rows = [{"点号": row["点位"], "时间": row["时间"], "测量值": self._value(row, monitor, mode)}
                    for row in _checked(rows, cancel)]
        dates, series = build_cumulative_series(rows, displacement_mode=mode)
        check_cancel(cancel)
        values = next(iter(series.values()), [])
        return dict(zip(dates, values))

    @staticmethod
    def _conclusion(cumulative, rate, settings) -> str:
        if cumulative is None:
            return "未知（缺少数据）"
        cumulative_set = any(all(bound is not None for bound in threshold_bounds_from_settings(settings, name))
                             for name in ("cumulative_warning", "cumulative_alarm"))
        rate_set = any(all(bound is not None for bound in threshold_bounds_from_settings(settings, name))
                       for name in ("rate_limit", "rate_alarm"))
        if not cumulative_set and not rate_set:
            return "未知（未配置阈值）"
        result = alert_status(cumulative, rate, settings)
        if result != "正常":
            return result
        if rate is None:
            return "未知（缺少数据）"
        if not cumulative_set or not rate_set:
            return "未超已配置阈值（配置不完整）"
        return "未超已配置阈值"

    def analyze(self, measurement_key: str, start_date: str, end_date: str,
                point: str = "", *, limit: int = 300, cancel=None) -> dict[str, Any]:
        check_cancel(cancel)
        if measurement_key == ALL_MEASUREMENTS:
            if point:
                raise ValueError('综合分析仅支持全部点位，请清除点位筛选。')
            return self.analyze_all(start_date, end_date, limit=limit, cancel=cancel)
        return self._analyze_measurement(measurement_key, start_date, end_date, point,
                                         limit=limit, cancel=cancel)

    def _analyze_measurement(self, measurement_key: str, start_date: str, end_date: str,
                             point: str = '', *, limit: int = 300, cancel=None,
                             full_statistics: bool = False) -> dict[str, Any]:
        check_cancel(cancel)
        item = self._measurement(measurement_key)
        start, end = normalize_observation_date(start_date), normalize_observation_date(end_date)
        if not start or not end:
            raise ValueError("请选择有效的开始和结束日期。")
        if observation_sort_key(start) > observation_sort_key(end):
            raise ValueError("开始日期不能晚于结束日期。")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("最大条数必须是正整数。")
        requested_limit, limit = limit, min(limit, MAX_ROWS)
        monitor = item["monitor_key"]
        warnings = ["分析仅使用原始监测数据；阈值来源为工程报表配置，未与文档依据核验。"]
        if monitor not in _METRICS:
            raise ValueError("暂不支持该监测类型的计算。")
        unit, cumulative_column, rate_column = _METRICS[monitor]
        period_column = f"期内变化量（{unit}）"
        adjacent_rate_column = f"相邻有效期变化速率（{unit}/d）"
        raw_rows, invalid = self._load(measurement_key, cancel)
        settings = self._service.report_alert_for(measurement_key)
        mode = normalize_horizontal_displacement_mode(settings.get("displacement_mode"))
        selected_dates = [date for date in _checked(self._dates(raw_rows, monitor, cancel), cancel)
                          if observation_sort_key(start) <= observation_sort_key(date) <= observation_sort_key(end)]
        groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        seen_dates: dict[tuple[str, ...], set[str]] = {}
        duplicates = 0
        for row in _checked(self._history(raw_rows, monitor, end, cancel), cancel):
            identity = self._identity(row, monitor)
            if not all(identity):
                invalid += 1
                continue
            if point and self._selector(identity, monitor) != point:
                continue
            group = groups.setdefault(identity, [])
            seen = seen_dates.setdefault(identity, set())
            observed_date = row.get('时间', '')
            if (monitor == "inclinometer" and group) or observed_date in seen:
                duplicates += 1
                continue
            group.append(row)
            seen.add(observed_date)
        if invalid:
            warnings.append(f"已排除 {invalid} 条日期、点位或深度无效的记录；不能视为完整监测数据。")
        if duplicates:
            warnings.append(f"存在 {duplicates} 条重复点位/日期记录，按既有报表口径采用第一条。")
        if not selected_dates:
            warnings.append("所选日期区间没有观测日期，未外推或使用区间外观测代替。")
        if point and not groups:
            warnings.append("所选点位在截止日期前没有可分析记录，请核对完整点位标识。")
        if not any(threshold_bounds_from_settings(settings, name) != (None, None)
                   for name in ("cumulative_warning", "cumulative_alarm", "rate_limit", "rate_alarm")):
            warnings.append("未配置有效阈值，无法判断是否正常或安全。")
        if monitor == "tilt":
            warnings.append("倾斜原始值已由水准累计沉降差计算；既有报表的本次倾斜变化量仍为累计值，"
                            "报表速率为累计值/相邻天数；相邻有效期变化速率与期内变化量另列，统计速率使用前者。")
            warnings.append("倾斜记录未携带原始水准基准日期，初始基准日期留空，请回查对应水准记录。")
        if monitor == "horizontal":
            warnings.append(f"水平位移采用工程报表的 {mode.upper()} 模式；XY 变化量为累计位移模长之差，并非相邻坐标向量长度。")
        if monitor == "axial":
            warnings.append("轴力按点号/编号分别展示原始轴力；未将频率当轴力，未将多个传感器轴力相加。")

        prepared = {}
        for identity, history in _checked(groups.items(), cancel):
            values = self._series_values(history, monitor, mode, cancel)
            if monitor == "inclinometer":
                valid_dates = [date for date in _checked(self._dates(history, monitor, cancel), cancel) if _number(history[0].get(date)) is not None]
            else:
                valid_dates = sorted([row["时间"] for row in _checked(history, cancel) if self._value(row, monitor, mode) is not None],
                                     key=observation_sort_key)
            candidates = [date for date in _checked(valid_dates, cancel) if observation_sort_key(date) <= observation_sort_key(start)]
            period_baseline = candidates[-1] if candidates else (valid_dates[0] if valid_dates else "")
            label = "-".join(identity) if monitor == "tilt" else " / ".join(identity)
            if monitor == "inclinometer":
                label = f"{item['data_name']} / {identity[0]}m"
            prepared[identity] = (values, valid_dates, period_baseline, label)
        report_rows = []
        total_rows = len(selected_dates) * len(groups)
        statistics_rows, missing = 0, 0
        conclusions = {}
        metrics = {name: self._extrema([], column, metric_unit)
                   for name, column, metric_unit in (
                       ('cumulative', cumulative_column, unit),
                       ('rate', adjacent_rate_column, unit + '/d'),
                       ('period_change', period_column, unit))}
        for observed in _checked(selected_dates, cancel):
            for identity, history in _checked(groups.items(), cancel):
                if not full_statistics and len(report_rows) >= limit:
                    break
                values, valid_dates, period_baseline, label = prepared[identity]
                before = [date for date in _checked(valid_dates, cancel) if observation_sort_key(date) < observation_sort_key(observed)]
                previous = before[-1] if before else ""
                through_current = self._history(history, monitor, observed, cancel)
                # A prior request date is required by the report API even when
                # there is no prior observation. This date is not fabricated
                # data: no row is created, and previous date/rate remain empty.
                calculation_previous = previous or (observation_datetime(observed) - timedelta(days=1)).date().isoformat()
                calculated = build_report_rows(through_current, observed, calculation_previous,
                                               settings, include_empty=True)
                check_cancel(cancel)
                row = calculated[0] if calculated else {column: "/" for column in export_columns_for_measurement(measurement_key)}
                if monitor == "inclinometer":
                    row["监测孔号"], row["深度（m）"] = item["data_name"], _number(identity[0])
                elif monitor == "tilt":
                    row["点号1"], row["点号2"] = identity
                else:
                    row["点位" if monitor == "water" else "点号"] = identity[0]
                    if monitor == "axial":
                        row["编号"] = identity[1]
                cumulative = _number(row.get(cumulative_column))
                valid_to_current = [date for date in _checked(valid_dates, cancel) if observation_sort_key(date) <= observation_sort_key(observed)]
                period_value, baseline_value = _number(values.get(observed)), _number(values.get(period_baseline))
                period_change = (round(period_value - baseline_value, 3)
                                 if period_value is not None and baseline_value is not None
                                 and observation_sort_key(period_baseline) <= observation_sort_key(observed) else None)
                rate = _number(row.get(rate_column))
                if not previous:
                    row[rate_column], rate = "/", None
                if monitor == "tilt":
                    old = _number(values.get(previous))
                    rate = (round((period_value - old) / observation_interval_days(observed, previous), 3)
                            if period_value is not None and old is not None and previous else None)
                row.update({"日期": observed, "分析点位": label,
                            "初始基准日期": valid_to_current[0] if valid_to_current and monitor != "tilt" else "",
                            "上一有效日期": previous,
                            "间隔天数": observation_interval_days(observed, previous) if previous else None,
                            "期内基准日期": period_baseline,
                            period_column: period_change if period_change is not None else "/",
                            adjacent_rate_column: rate if rate is not None else "/",
                            "监测结论": self._conclusion(cumulative, rate, settings)})
                # Retain only the detail preview. Extrema and alert counts use
                # constant space even when all dates and points are visited.
                statistics_rows += 1
                missing += cumulative is None
                status = row['监测结论']
                conclusions[status] = conclusions.get(status, 0) + 1
                for metric in metrics.values():
                    self._include_extreme(metric, row)
                if len(report_rows) < limit:
                    report_rows.append(row)
            if not full_statistics and len(report_rows) >= limit:
                break
        trend = []
        trend_count = 0
        # Interleave dates to keep the bounded trend consistent with the row
        # ordering, rather than spending the entire allowance on the first point.
        for identity in list(groups)[:MAX_SERIES]:
            trend.append({"point": prepared[identity][3], "unit": unit, "values": []})
        for observed in _checked(selected_dates, cancel):
            for identity, series in zip(list(groups)[:MAX_SERIES], trend):
                if trend_count >= limit:
                    break
                series["values"].append({"date": observed, "value": _number(prepared[identity][0].get(observed))})
                trend_count += 1
            if trend_count >= limit:
                break
        trend = [series for series in trend if series["values"]]
        if missing:
            scope_label = '所选全区间' if full_statistics else '返回行中'
            warnings.append(f"{scope_label}有 {missing} 条缺少有效当前值/初始值；缺测保持空值，不补零、不作正常判断。")
        if any(prepared[identity][2] and observation_sort_key(prepared[identity][2]) > observation_sort_key(start)
               for identity in groups):
            warnings.append("部分点位在开始日期及之前无有效观测，期内基准采用区间首个有效观测；不能覆盖完整区间变化。")
        truncated_rows = total_rows - len(report_rows)
        truncated_values = total_rows - trend_count
        if truncated_rows or truncated_values:
            statistics_note = ('统计已覆盖所选全区间全部点位，明细与趋势截断不影响极值和预警计数。'
                               if full_statistics else '统计仅覆盖返回报表行，请缩小范围后复核。')
            warnings.append(f"结果已截断：报表返回 {len(report_rows)}/{total_rows} 行；趋势返回 {trend_count}/{total_rows} 个值、"
                            f"{len(trend)}/{len(groups)} 条序列。{statistics_note}")
        if requested_limit > MAX_ROWS:
            warnings.append(f"请求上限已限制为 {MAX_ROWS} 条。")
        columns = list(dict.fromkeys(["日期", "分析点位", *export_columns_for_measurement(measurement_key),
                                     "初始基准日期", "上一有效日期", "间隔天数", "期内基准日期", period_column,
                                     adjacent_rate_column, "监测结论", *[column for row in report_rows for column in row]]))
        summary = {
            "total_rows": total_rows, "returned_rows": len(report_rows), "truncated_rows": truncated_rows,
            "point_count": len({self._selector(identity, monitor) for identity in groups}),
            "identity_count": len(groups), "date_count": len(selected_dates), "missing_rows": missing,
            "total_series": len(groups), "returned_series": len(trend), "total_series_values": total_rows,
            "returned_series_values": trend_count, "truncated_series_values": truncated_values,
            "invalid_records": invalid, "duplicate_records": duplicates,
            "statistics_rows": statistics_rows, "statistics_truncated_rows": total_rows - statistics_rows,
            "statistics_complete": statistics_rows == total_rows,
            "statistics_scope": ("所选全区间全部点位；明细与趋势显示上限不限制统计。" if full_statistics
                                 else "返回报表行；截断时不代表全区间"),
            "threshold_source": "工程报表配置（未与文档核验）", "threshold_settings": settings,
            "baseline_rule": ("倾斜累计沿用保存的水准累计沉降差计算值；原始水准基准日期未记录。" if monitor == "tilt" else "累计以点位最早有效原始观测为基准。") + "期内以开始日及之前最后有效观测为基准，缺少时采用区间首个有效观测。",
            "previous_rule": "各点位/编号/深度在当前日期之前最后一次有效原始观测；同日加密依既有报表按1天计算。",
            **metrics,
            "conclusions": dict(sorted(conclusions.items())),
        }
        check_cancel(cancel)
        return _json_value({"project": self._project, "measurement_key": measurement_key,
                            "data_name": item["data_name"], "start_date": start, "end_date": end,
                            "source": "原始监测数据", "columns": columns, "rows": report_rows,
                            "summary": summary, "warnings": warnings, "series": trend})

    def analyze_all(self, start_date: str, end_date: str, *, limit: int = 300, cancel=None) -> dict[str, Any]:
        """Summarize every measurement independently; never compare unlike units.

        Statistics stream all rows, independent of the per-measurement detail
        limit. Trend values share a global MAX_ROWS allowance across measurements;
        no raw report detail is retained in the comprehensive result.
        """
        check_cancel(cancel)
        start, end = normalize_observation_date(start_date), normalize_observation_date(end_date)
        if not start or not end:
            raise ValueError('请选择有效的开始和结束日期。')
        if observation_sort_key(start) > observation_sort_key(end):
            raise ValueError('开始日期不能晚于结束日期。')
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError('最大条数必须是正整数。')
        warnings = ['综合分析仅使用原始监测数据；各测项按各自单位、基准和工程阈值独立统计，不合并跨测项极值。']
        measurements, rows, series, dates = [], [], [], set()
        count = len(self._measurements)
        if not count:
            warnings.append('当前工程没有可分析的测项。')
        if count > MAX_MODEL_MEASUREMENTS:
            warnings.append(f'测项超过 {MAX_MODEL_MEASUREMENTS} 项，AI 仅接收前 {MAX_MODEL_MEASUREMENTS} 项摘要；'
                            '其余测项仍在本地综合表和导出中，AI 不能据此给出全工程结论。')
        columns = ['测项', '测项标识', '点位数', '观测日期数', '有效行数', '统计行数', '总行数',
                   '累计变化绝对值最大', '极值点位', '极值日期', '单位', '阈值结论', '统计范围/提示']
        for index, item in enumerate(_checked(self._measurements, cancel)):
            key = item['key']
            unit = _METRICS.get(item['monitor_key'], ('', '', ''))[0]
            base = {'measurement_key': key, 'data_name': item['data_name'],
                    'measurement_name': item['label'], 'unit': unit}
            try:
                analysis = self._analyze_measurement(key, start, end, limit=limit,
                                                     cancel=cancel, full_statistics=True)
                raw, _ = self._load(key, cancel)
                dates.update(date for date in self._dates(raw, item['monitor_key'], cancel)
                             if observation_sort_key(start) <= observation_sort_key(date) <= observation_sort_key(end))
            except InterruptedError:
                raise
            except Exception as exc:
                check_cancel(cancel)
                error = str(exc) or type(exc).__name__
                measurements.append({**base, 'status': 'error', 'error': error})
                warnings.append(f"{item['label']}：分析失败，{error}；未纳入统计，不能视为正常。")
                rows.append({'测项': item['label'], '测项标识': key, '单位': unit,
                             '阈值结论': '未知（分析失败）', '统计范围/提示': error})
                continue
            summary = analysis['summary']
            # Distribute the fixed chart budget, preserving same-name identities
            # under their measurement keys. Summary extrema remain unaffected.
            allowance = MAX_ROWS // max(count, 1) + (index < MAX_ROWS % max(count, 1))
            visible = []
            for trend in analysis['series']:
                values = trend['values'][:allowance]
                if values:
                    visible.append({**trend, 'measurement_key': key,
                                    'measurement_name': item['label'], 'values': values})
                    allowance -= len(values)
            returned_values = sum(len(s['values']) for s in visible)
            item_warnings = list(analysis['warnings'])
            if returned_values < summary['returned_series_values']:
                item_warnings.append('综合图表全局上限导致趋势进一步截断；极值仍以本测项统计摘要为准。')
            measurements.append({**summary, **base, 'status': 'ok', 'warnings': item_warnings,
                                 'chart_returned_values': returned_values,
                                 'chart_truncated_values': summary['total_series_values'] - returned_values})
            series.extend(visible)
            warnings.extend(f"{item['label']}：{warning}" for warning in item_warnings)
            extreme = summary['cumulative']['maximum_absolute'] or {}
            conclusion = '；'.join(f'{status} {amount} 行' for status, amount in summary['conclusions'].items())
            rows.append({'测项': item['label'], '测项标识': key, '点位数': summary['point_count'],
                         '观测日期数': summary['date_count'],
                         '有效行数': summary['statistics_rows'] - summary['missing_rows'],
                         '统计行数': summary['statistics_rows'], '总行数': summary['total_rows'],
                         '累计变化绝对值最大': extreme.get('value'), '极值点位': extreme.get('point', ''),
                         '极值日期': extreme.get('date', ''), '单位': unit,
                         '阈值结论': conclusion or '未知（无区间数据）',
                         '统计范围/提示': '所选全区间全部点位'
                         + ('；明细/曲线显示已截断' if summary['truncated_rows'] or summary['truncated_series_values'] else '')
                         + ('；缺测未补零' if summary['missing_rows'] else '')})
        summary = {name: sum(m.get(name, 0) for m in measurements)
                   for name in ('point_count', 'identity_count', 'total_rows', 'returned_rows', 'truncated_rows',
                                'missing_rows', 'invalid_records', 'duplicate_records', 'total_series', 'total_series_values',
                                'statistics_rows', 'statistics_truncated_rows')}
        summary.update({'measurement_count': count, 'measurements': measurements, 'summary_row_count': len(rows),
                        'failed_measurements': sum(m['status'] == 'error' for m in measurements),
                        'date_count': len(dates), 'returned_series': len(series),
                        'returned_series_values': sum(len(s['values']) for s in series),
                        'statistics_complete': all(m.get('statistics_complete', False) for m in measurements),
                        'statistics_scope': '各成功测项所选全区间全部点位独立统计；同名点位按测项分别计数；失败测项未纳入计数。',
                        'threshold_source': '各测项工程报表配置（未与文档核验）'})
        summary['truncated_series_values'] = summary['total_series_values'] - summary['returned_series_values']
        if summary['truncated_series_values']:
            warnings.append(f"综合趋势已截断：返回 {summary['returned_series_values']}/{summary['total_series_values']} 个值；"
                            f'全局最多 {MAX_ROWS} 个值，各测项极值请查其独立摘要。')
        check_cancel(cancel)
        return _json_value({'project': self._project, 'measurement_key': ALL_MEASUREMENTS,
                            'data_name': '综合分析 · 全部测项', 'is_comprehensive': True,
                            'start_date': start, 'end_date': end, 'source': '原始监测数据',
                            'columns': columns, 'rows': rows, 'summary': summary, 'warnings': warnings, 'series': series})

    @staticmethod
    def _extrema(rows, column, unit):
        values = [{"value": _number(row.get(column)), "point": row["分析点位"], "date": row["日期"]}
                  for row in rows if _number(row.get(column)) is not None]
        return {"column": column, "unit": unit, "count": len(values),
                "minimum": min(values, key=lambda value: value["value"]) if values else None,
                "maximum": max(values, key=lambda value: value["value"]) if values else None,
                "maximum_absolute": max(values, key=lambda value: abs(value["value"])) if values else None}

    @staticmethod
    def _include_extreme(metric, row):
        value = _number(row.get(metric['column']))
        if value is None:
            return
        metric['count'] += 1
        item = {'value': value, 'point': row['分析点位'], 'date': row['日期']}
        if metric['minimum'] is None or value < metric['minimum']['value']:
            metric['minimum'] = item
        if metric['maximum'] is None or value > metric['maximum']['value']:
            metric['maximum'] = item
        if metric['maximum_absolute'] is None or abs(value) > abs(metric['maximum_absolute']['value']):
            metric['maximum_absolute'] = item
