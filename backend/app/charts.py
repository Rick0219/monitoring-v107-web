"""Full project chart data, independent of the AI context truncation limits."""
from datetime import timedelta
from app import monitoring as m
from app.project_models import ChartSettings
from app.database_view import raw_for_date
from monitoring_daily.services.report_data import build_report_rows, build_cumulative_series, export_columns_for_measurement
from monitoring_daily.services.alert_thresholds import alert_control_bounds
from monitoring_daily.services.observation_date import observation_datetime, observation_sort_key
from monitoring_daily.analysis.monitoring import _METRICS, _number, _json_value


def chart_data(project, preference: ChartSettings):
    service = m.service_for(project)
    reader = m.MonitoringReader(service)
    key = preference.measurement_key
    item = reader._measurement(key)
    monitor = item["monitor_key"]
    rows, invalid = reader._load(key)
    dates = reader.list_dates(key)
    warnings = [f"忽略了 {invalid} 条无效日期或深度记录。"] if invalid else []
    effective = preference.end_date if preference.end_date in dates else (dates[-1] if dates else "")
    if preference.end_date and preference.end_date not in dates:
        warnings.append("上次选择的日期已不存在，本次显示最新日期。")
        preference = preference.model_copy(update={"end_date": ""})
    unit, cumulative_column, _ = _METRICS[monitor]
    settings = service.report_alert_for(key)
    report, history_dates, groups = [], [], {}
    if effective:
        history = reader._history(rows, monitor, effective)
        history_dates = [d for d in dates if observation_sort_key(d) <= observation_sort_key(effective)]
        previous = history_dates[-2] if len(history_dates) > 1 else (observation_datetime(effective) - timedelta(days=1)).strftime("%Y-%m-%d")
        report = build_report_rows(history, effective, previous, settings, include_empty=True)
        # Group before constructing series: avoid a huge points × dates matrix.
        for row in history:
            identity = reader._identity(row, monitor)
            if all(identity):
                point = reader._selector(identity, monitor)
                groups.setdefault(point, []).append(row)
    def report_point(row):
        if monitor == "inclinometer":
            return str(row.get("深度（m）", ""))
        if monitor == "tilt":
            return f'{row.get("点号1", "")}-{row.get("点号2", "")}'
        return str(row.get("点位" if monitor == "water" else "点号", ""))
    current = {report_point(row): _number(row.get(cumulative_column)) for row in report}
    if monitor == "inclinometer":
        current = {_number(k): v for k, v in current.items()}
    points = []
    multi_sensor = False
    axial_numbers = {report_point(row): str(row.get("编号", "")).strip() for row in report} if monitor == "axial" else {}
    for point, point_rows in groups.items():
        if monitor == "water":
            point_rows = [{"点号": r["点位"], "时间": r["时间"], "测量值": reader._value(r, monitor, "xy")} for r in point_rows]
        elif monitor == "axial":
            # The desktop daily point chart keeps the last report row for a
            # point with several sensor numbers. Use that same sensor through
            # its full history rather than mixing different sensor baselines.
            multi_sensor |= len({str(r.get("编号", "")).strip() for r in point_rows}) > 1
            point_rows = [r for r in point_rows if str(r.get("编号", "")).strip() == axial_numbers.get(point)]
        series_dates, series = build_cumulative_series(point_rows, displacement_mode=str(settings.get("displacement_mode") or "xy"))
        values = next(iter(series.values()), [])
        if monitor == "tilt":
            values = [round(v, 2) if v is not None else None for v in values]
        points.append({"point": point, "depth": _number(point) if monitor == "inclinometer" else None,
                       "current": current.get(_number(point) if monitor == "inclinometer" else point),
                       "values": [{"date": d, "value": v} for d, v in zip(series_dates, values)]})
    if multi_sensor:
        warnings.append("同一轴力点包含多个编号，点位图沿用日报规则取该点最后一组编号；各编号完整数据可在“数据”中查看。")
    available = {p["point"] for p in points}
    stale = [p for p in preference.points if p not in available]
    if stale and preference.mode == "custom":
        warnings.append(f"有 {len(stale)} 个已选点在当前日期范围内无数据；保留设置，待有数据后恢复。")
    if preference.mode == "custom":
        selected = [p for p in dict.fromkeys(preference.points) if p in available]
    elif preference.mode == "all":
        selected = [p["point"] for p in points]
    else:
        def score(p):
            if preference.display == "history":
                return max((abs(v["value"]) for v in p["values"] if v["value"] is not None), default=-1)
            return abs(p["current"]) if p["current"] is not None else -1
        ranked = sorted((p for p in points if score(p) >= 0), key=lambda p: (-score(p), p["point"]))
        selected = [p["point"] for p in ranked[:10]]
    raw_rows, raw_columns = raw_for_date(project, key, effective)
    return _json_value({"measurement_key": key, "label": item["label"], "monitor": monitor, "unit": unit,
            "raw_rows": raw_rows, "raw_columns": raw_columns,
            "dates": dates, "history_dates": history_dates, "effective_date": effective,
            "settings": preference.model_dump(), "points": points, "selected_points": selected,
            "columns": export_columns_for_measurement(key), "rows": report, "warnings": warnings,
            "control_bounds": alert_control_bounds(settings), "available_points": reader.list_points(key)})
