"""In-memory synchronization for raw and beautified measurement datasets."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from statistics import fmean
from typing import Any

from monitoring_daily.domain.beautification import BeautificationConfig
from monitoring_daily.services.beautification.base import BeautificationContext, adapter_registry
from monitoring_daily.services.beautification.engine import (
    apply_constraints,
    generate_target_metric,
    mean_history_change,
)

# Importing the adapter module performs the explicit registry setup.  The sync
# service is also used by non-UI callers, so it must not depend on an editor
# module having imported the adapters first.
from monitoring_daily.services.beautification import adapters as _adapters  # noqa: F401


def sync_monitor_item(
    project_data: dict,
    monitor_key: str,
    *,
    changed_date: str | None = None,
) -> dict:
    """Synchronize one monitor item without writing the project file."""

    candidate = deepcopy(project_data)
    return recompute_from_date(candidate, monitor_key, start_date=changed_date or "")


def generate_date(
    project_data: dict,
    monitor_key: str,
    date_key: str,
    *,
    target_metric_overrides: dict[str, float] | None = None,
) -> dict:
    """Generate one beautified date without changing the original data."""

    candidate = deepcopy(project_data)
    return _generate_one_date(
        candidate,
        monitor_key,
        str(date_key),
        target_metric_overrides=target_metric_overrides,
    )


def generate_date_with_summary(
    project_data: dict,
    monitor_key: str,
    date_key: str,
    *,
    target_metric_overrides: dict[str, float] | None = None,
) -> tuple[dict, dict]:
    """Return a generated candidate plus a structured summary for the UI."""
    candidate = generate_date(
        project_data,
        monitor_key,
        date_key,
        target_metric_overrides=target_metric_overrides,
    )
    date_meta = (
        candidate.get("beautification_meta", {})
        .get("items", {})
        .get(monitor_key, {})
        .get(date_key, {})
    )
    details = date_meta.get("details", {}).get("series", {})
    failures = (
        candidate.get("beautification_meta", {})
        .get("failures", {})
        .get(monitor_key, {})
        .get(date_key, [])
    )
    config = _config_for(candidate, monitor_key)
    adapter = adapter_registry.get(monitor_key.partition(":")[0])
    known_count = len(
        _known_series_ids(
            adapter,
            candidate["measurements"].get(monitor_key, []),
            date_key,
        )
    )
    logs = [
        {
            "monitor_key": monitor_key,
            "date": date_key,
            "series_id": series_id,
            "trigger": detail.get("trigger", ""),
            "N": config.window_n,
            "S": config.threshold_s,
            "history_count": config.window_n,
            **detail,
        }
        for series_id, detail in details.items()
    ]
    return candidate, {
        "success_count": len(logs),
        "skipped_count": max(known_count - len(logs) - len(failures), 0),
        "failures": list(failures),
        "changed_dates": [date_key],
        "logs": logs,
    }


def recompute_from_date(project_data: dict, monitor_key: str, start_date: str) -> dict:
    """Recalculate one monitor item from ``start_date`` forward in date order."""

    candidate = deepcopy(project_data)
    excluded = set(
        candidate.get("beautification_meta", {})
        .get("excluded_dates", {})
        .get(monitor_key, [])
    )
    if excluded:
        remove_beautified_dates(candidate, monitor_key, excluded)
    for date_key in _ordered_dates_from(candidate, monitor_key, start_date):
        if date_key in excluded:
            continue
        candidate = _generate_one_date(candidate, monitor_key, date_key)
        if excluded:
            # Disabled beautification resets the entire store from raw rows.
            remove_beautified_dates(candidate, monitor_key, excluded)
    return candidate


def remove_beautified_dates(project_data: dict, monitor_key: str, dates: set[str]) -> None:
    """Remove selected dates from the derived store, in either row layout."""

    store = project_data.setdefault("beautified_measurements", {})
    rows = store.get(monitor_key, [])
    if any("时间" in row for row in rows if isinstance(row, dict)):
        store[monitor_key] = [
            row for row in rows
            if str(row.get("时间", "") or "") not in dates
        ]
    else:
        store[monitor_key] = [
            {column: value for column, value in row.items() if column not in dates}
            for row in rows
        ]


def _generate_one_date(
    candidate: dict,
    monitor_key: str,
    date_key: str,
    *,
    target_metric_overrides: dict[str, float] | None = None,
) -> dict:
    raw_measurements = candidate.setdefault("measurements", {})
    raw_rows = [
        dict(row)
        for row in raw_measurements.get(monitor_key, [])
        if isinstance(row, dict)
    ]
    beautified_measurements = candidate.setdefault("beautified_measurements", {})
    if monitor_key not in beautified_measurements:
        beautified_measurements[monitor_key] = deepcopy(raw_rows)

    config = _config_for(candidate, monitor_key)
    monitor_type = str(monitor_key).partition(":")[0]
    adapter = adapter_registry.get(monitor_type)

    if not config.enabled:
        beautified_measurements[monitor_key] = deepcopy(raw_rows)
        _write_date_meta(
            candidate,
            monitor_key,
            date_key,
            has_generated=False,
            trigger="disabled",
            details={},
        )
        _clear_failures(candidate, monitor_key, date_key)
        return candidate

    context = BeautificationContext(
        project=candidate,
        monitor_key=monitor_key,
        monitor_type=monitor_type,
        date_key=date_key,
    )
    raw_by_series = _records_by_series(adapter, raw_rows, date_key)
    known_series_ids = _selected_series_ids(adapter, raw_rows, date_key, config)
    previous_by_series = _previous_beautified_rows(
        adapter,
        beautified_measurements.get(monitor_key, []),
        date_key,
    )
    previous_order = {
        series_id: index
        for index, series_id in enumerate(known_series_ids)
    }
    output_rows: list[dict] = []
    failures: list[dict[str, str]] = []
    generated_details: dict[str, dict[str, Any]] = {}
    overrides = target_metric_overrides or {}
    lookback_count = max(int(config.window_n), 2)
    peer_trend = _peer_trend_change(
        adapter,
        context,
        beautified_measurements.get(monitor_key, []),
        _known_series_ids(adapter, raw_rows, date_key),
        date_key,
        lookback_count,
        config.window_n,
    )
    peer_cumulative_metric = _peer_cumulative_metric(
        adapter,
        context,
        beautified_measurements.get(monitor_key, []),
        _known_series_ids(adapter, raw_rows, date_key),
        date_key,
        lookback_count,
    )
    beautified_rows = beautified_measurements.get(monitor_key, [])

    def history_priority(series_id: str) -> int:
        history_rows = _beautified_history_rows(
            adapter,
            beautified_rows,
            series_id,
            date_key,
        )[-lookback_count:]
        try:
            metrics = _history_metrics(adapter, context, history_rows)
        except ValueError:
            return 1
        return 0 if previous_by_series.get(series_id) is not None and len(metrics) >= 2 else 1

    processing_series_ids = sorted(known_series_ids, key=history_priority)
    current_peer_changes: list[float] = []
    current_peer_metrics: list[float] = []

    for series_id in processing_series_ids:
        source_record = raw_by_series.get(series_id)
        previous_record = previous_by_series.get(series_id)
        history_records = _beautified_history_rows(
            adapter,
            beautified_measurements.get(monitor_key, []),
            series_id,
            date_key,
        )
        selected_history_records = history_records[-lookback_count:]
        history_metrics = _history_metrics(adapter, context, selected_history_records)
        history_changes = [
            current - previous
            for previous, current in zip(history_metrics, history_metrics[1:])
        ]

        try:
            insufficient_history = previous_record is None or len(history_metrics) < 2
            if insufficient_history and peer_trend is None:
                if source_record is not None:
                    output_rows.append(deepcopy(source_record))
                elif previous_record is not None:
                    failures.append(
                        {
                            "series_id": series_id,
                            "reason": "没有足够的历史数据，也没有可复用的同测项趋势",
                        }
                    )
                continue

            seed_record = previous_record or source_record
            if seed_record is None:
                failures.append({"series_id": series_id, "reason": "缺少可生成测值的基础数据"})
                continue
            previous_metric = (
                history_metrics[-1]
                if history_metrics
                else float(
                    adapter.raw_to_metric(
                        seed_record,
                        context=context,
                        history=selected_history_records,
                    )
                )
            )
            has_actual = bool(
                source_record is not None
                and adapter.has_actual_measurement(source_record, context=context)
            )
            actual_metric = (
                adapter.raw_to_metric(
                    source_record,
                    context=context,
                    history=selected_history_records,
                )
                if has_actual
                else None
            )
            interval_days, interval_fallback = calculate_interval_days(
                _record_date(previous_record or seed_record), date_key
            )
            active_peer_trend = _trend_for_basis(
                basis=config.peer_trend_basis,
                current_changes=current_peer_changes,
                current_metrics=current_peer_metrics,
                historical_change=peer_trend,
                historical_metric=peer_cumulative_metric,
            )
            if insufficient_history:
                if active_peer_trend is None:
                    if source_record is not None:
                        output_rows.append(deepcopy(source_record))
                    else:
                        failures.append(
                            {
                                "series_id": series_id,
                                "reason": "没有足够的历史数据，也没有可复用的同测项趋势",
                            }
                        )
                    continue
                simulation_factor = _stable_simulation_factor(
                    monitor_key,
                    date_key,
                    series_id,
                )
                target_change, target_metric = apply_constraints(
                    previous_beautified_metric=previous_metric,
                    candidate_change=float(active_peer_trend) * simulation_factor,
                    interval_days=interval_days,
                    config=config,
                )
                history_change = float(active_peer_trend)
                result_actual_change = None
                actual_weight = 0.0
                result_interval_days = max(float(interval_days), 1.0)
            else:
                result = generate_target_metric(
                    previous_beautified_metric=previous_metric,
                    actual_change=(
                        None
                        if actual_metric is None
                        else float(actual_metric) - previous_metric
                    ),
                    history_changes=history_changes,
                    interval_days=interval_days,
                    config=config,
                )
                target_change = result.target_change
                target_metric = result.target_metric
                history_change = result.history_change
                result_actual_change = result.actual_change
                actual_weight = result.actual_weight
                result_interval_days = result.interval_days
                current_peer_changes.append(float(result.target_change))
                current_peer_metrics.append(float(result.target_metric))
            manually_adjusted = series_id in overrides
            if manually_adjusted:
                target_change, target_metric = apply_constraints(
                    previous_beautified_metric=previous_metric,
                    candidate_change=float(overrides[series_id]) - previous_metric,
                    interval_days=interval_days,
                    config=config,
                )
            rebuilt = adapter.metric_to_record(
                target_metric,
                context=context,
                source_record=source_record,
                previous_record=previous_record,
            )
            _match_historical_precision(rebuilt, raw_rows)
            target_metric = float(
                adapter.raw_to_metric(
                    rebuilt,
                    context=context,
                    history=selected_history_records,
                )
            )
            target_change = target_metric - previous_metric
            rebuilt["时间"] = date_key
            output_rows.append(rebuilt)
            trigger = (
                "manual_adjusted"
                if manually_adjusted
                else (
                    "peer_trend"
                    if insufficient_history
                    else ("actual_weighted" if has_actual else "missing_actual")
                )
            )
            generated_details[series_id] = {
                "trigger": trigger,
                "target_change": target_change,
                "target_metric": target_metric,
                "raw_metric": actual_metric,
                "actual_change": result_actual_change,
                "history_change": history_change,
                "actual_weight": actual_weight,
                "rate": target_change / result_interval_days,
                "interval_days": result_interval_days,
                "history_count": len(selected_history_records),
                "interval_fallback": interval_fallback,
                **(
                    {
                        "peer_trend": float(active_peer_trend),
                        "simulation_factor": simulation_factor,
                        "peer_trend_basis": config.peer_trend_basis,
                    }
                    if insufficient_history
                    else {}
                ),
            }
        except ValueError as exc:
            failures.append({"series_id": series_id, "reason": str(exc)})

    _replace_date_rows(
        beautified_measurements,
        monitor_key,
        date_key,
        sorted(
            output_rows,
            key=lambda row: previous_order.get(adapter.series_id(row), len(previous_order)),
        ),
    )
    triggers = {detail["trigger"] for detail in generated_details.values()}
    _write_date_meta(
        candidate,
        monitor_key,
        date_key,
        has_generated=bool(generated_details),
        trigger=(next(iter(triggers)) if len(triggers) == 1 else "mixed"),
        details={"series": generated_details},
    )
    _write_failures(candidate, monitor_key, date_key, failures)
    return candidate


def _config_for(candidate: dict, monitor_key: str) -> BeautificationConfig:
    payload = candidate.setdefault("beautification_config", {}).get(monitor_key)
    if isinstance(payload, BeautificationConfig):
        return payload
    return BeautificationConfig.from_dict(payload if isinstance(payload, dict) else None)


def _ordered_dates_from(candidate: dict, monitor_key: str, start_date: str) -> list[str]:
    dates = set()
    for store_name in ("measurements", "beautified_measurements"):
        dates.update(
            _record_date(row)
            for row in candidate.setdefault(store_name, {}).get(monitor_key, [])
            if isinstance(row, dict) and _record_date(row)
        )
    return [date_key for date_key in sorted(dates) if not start_date or date_key >= start_date]


def _records_by_series(adapter: Any, rows: list[dict], date_key: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in rows:
        if _record_date(row) == date_key:
            result.setdefault(adapter.series_id(row), row)
    return result


def _known_series_ids(adapter: Any, rows: list[dict], date_key: str) -> list[str]:
    result: list[str] = []
    for row in rows:
        if _record_date(row) <= date_key:
            series_id = adapter.series_id(row)
            if series_id and series_id not in result:
                result.append(series_id)
    return result


def _selected_series_ids(
    adapter: Any,
    rows: list[dict],
    date_key: str,
    config: BeautificationConfig,
) -> list[str]:
    known = _known_series_ids(adapter, rows, date_key)
    if config.point_selection_mode == "all":
        return known
    if config.point_selection_mode == "custom":
        selected = set(config.custom_point_ids)
        return [series_id for series_id in known if series_id in selected]

    previous_dates = sorted(
        {
            _record_date(row)
            for row in rows
            if _record_date(row) and _record_date(row) < date_key
        }
    )
    selected_date = previous_dates[-1] if previous_dates else date_key
    result: list[str] = []
    for row in rows:
        if _record_date(row) != selected_date:
            continue
        series_id = adapter.series_id(row)
        if series_id and series_id not in result:
            result.append(series_id)
    return result


def _peer_trend_change(
    adapter: Any,
    context: BeautificationContext,
    rows: list[dict],
    series_ids: list[str],
    date_key: str,
    lookback_count: int,
    window_n: int,
) -> float | None:
    trends: list[float] = []
    for series_id in series_ids:
        history_rows = _beautified_history_rows(adapter, rows, series_id, date_key)[
            -lookback_count:
        ]
        metrics = _history_metrics(adapter, context, history_rows)
        if len(metrics) < 2:
            continue
        changes = [current - previous for previous, current in zip(metrics, metrics[1:])]
        trends.append(mean_history_change(changes, window_n))
    return float(fmean(trends)) if trends else None


def _peer_cumulative_metric(
    adapter: Any,
    context: BeautificationContext,
    rows: list[dict],
    series_ids: list[str],
    date_key: str,
    lookback_count: int,
) -> float | None:
    latest_metrics: list[float] = []
    for series_id in series_ids:
        history_rows = _beautified_history_rows(adapter, rows, series_id, date_key)[
            -lookback_count:
        ]
        metrics = _history_metrics(adapter, context, history_rows)
        if len(metrics) >= 2:
            latest_metrics.append(metrics[-1])
    return float(fmean(latest_metrics)) if latest_metrics else None


def _trend_for_basis(
    *,
    basis: str,
    current_changes: list[float],
    current_metrics: list[float],
    historical_change: float | None,
    historical_metric: float | None,
) -> float | None:
    if current_changes:
        if basis == "change":
            return float(fmean(current_changes))
        magnitude = float(fmean(abs(value) for value in current_changes))
        direction_source = float(fmean(current_metrics)) if current_metrics else 0.0
        if direction_source == 0.0:
            direction_source = float(fmean(current_changes))
        return magnitude if direction_source >= 0.0 else -magnitude

    if historical_change is None:
        return None
    if basis == "change" or historical_metric is None:
        return float(historical_change)
    magnitude = abs(float(historical_change))
    return magnitude if float(historical_metric) >= 0.0 else -magnitude


def _stable_simulation_factor(
    monitor_key: str,
    date_key: str,
    series_id: str,
) -> float:
    """Return a repeatable random-looking factor without preview/write drift."""

    seed = f"{monitor_key}|{date_key}|{series_id}".encode("utf-8")
    sample = int.from_bytes(sha256(seed).digest()[:8], "big") / float(2**64 - 1)
    return 0.65 + sample * 0.70


def _previous_beautified_rows(adapter: Any, rows: list[dict], date_key: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in sorted(rows, key=_record_date):
        row_date = _record_date(row)
        if row_date and row_date < date_key:
            result[adapter.series_id(row)] = row
    return result


def _beautified_history_rows(
    adapter: Any,
    rows: list[dict],
    series_id: str,
    date_key: str,
) -> list[dict]:
    return [
        row
        for row in sorted(rows, key=_record_date)
        if _record_date(row) < date_key and adapter.series_id(row) == series_id
    ]


def _history_metrics(adapter: Any, context: BeautificationContext, rows: list[dict]) -> list[float]:
    metrics: list[float] = []
    for index, row in enumerate(rows):
        metrics.append(
            float(adapter.raw_to_metric(row, context=context, history=rows[:index]))
        )
    return metrics


def _decimal_places(value: Any) -> int | None:
    if value in (None, "", "/") or isinstance(value, bool):
        return None
    try:
        decimal_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite():
        return None
    return max(-decimal_value.as_tuple().exponent, 0)


def _match_historical_precision(record: dict, historical_rows: list[dict]) -> None:
    """Round generated numeric fields to the precision used by historical rows."""

    for field, value in list(record.items()):
        if field == "时间" or isinstance(value, bool):
            continue
        precision_candidates = [
            precision
            for row in historical_rows
            for precision in [_decimal_places(row.get(field))]
            if precision is not None
        ]
        if not precision_candidates:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        record[field] = round(numeric, max(precision_candidates))


def _replace_date_rows(
    measurements: dict,
    monitor_key: str,
    date_key: str,
    replacement_rows: list[dict],
) -> None:
    remaining = [
        dict(row)
        for row in measurements.get(monitor_key, [])
        if isinstance(row, dict) and _record_date(row) != date_key
    ]
    remaining.extend(replacement_rows)
    measurements[monitor_key] = sorted(remaining, key=_record_date)


def _write_date_meta(
    candidate: dict,
    monitor_key: str,
    date_key: str,
    *,
    has_generated: bool,
    trigger: str,
    details: dict[str, Any],
) -> None:
    meta = candidate.setdefault("beautification_meta", {"version": 1, "items": {}})
    meta.setdefault("version", 1)
    item_meta = meta.setdefault("items", {}).setdefault(monitor_key, {})
    previous = item_meta.get(date_key, {})
    revision = int(previous.get("generation_revision", 0)) + 1 if isinstance(previous, dict) else 1
    item_meta[date_key] = {
        "has_generated": has_generated,
        "source": "system" if has_generated else "raw_mirror",
        "trigger": trigger,
        "algorithm": "weighted_delta_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generation_revision": revision,
        "details": details,
    }


def _clear_failures(candidate: dict, monitor_key: str, date_key: str) -> None:
    failures = candidate.setdefault("beautification_meta", {}).setdefault("failures", {})
    item_failures = failures.get(monitor_key, {})
    if isinstance(item_failures, dict):
        item_failures.pop(date_key, None)


def _write_failures(
    candidate: dict,
    monitor_key: str,
    date_key: str,
    failures: list[dict[str, str]],
) -> None:
    meta_failures = candidate.setdefault("beautification_meta", {}).setdefault("failures", {})
    item_failures = meta_failures.setdefault(monitor_key, {})
    if failures:
        item_failures[date_key] = failures
    else:
        item_failures.pop(date_key, None)


def _record_date(row: dict) -> str:
    return str(row.get("时间", "") or "")


def calculate_interval_days(previous_date: str, current_date: str) -> tuple[float, bool]:
    """Return a safe day interval and flag same-day/intensified fallbacks."""
    try:
        previous = date.fromisoformat(str(previous_date)[:10])
        current = date.fromisoformat(str(current_date)[:10])
    except ValueError:
        return 1.0, True
    interval = (current - previous).days
    return (float(interval), False) if interval > 0 else (1.0, True)
