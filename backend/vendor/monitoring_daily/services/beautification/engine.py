"""Shared weighted-delta calculation pipeline for beautified measurements."""

from __future__ import annotations

from statistics import fmean
from typing import Sequence

from monitoring_daily.domain.beautification import (
    BeautificationConfig,
    BeautificationResult,
    RangeLimit,
)


def clamp_optional(value: float, limit: RangeLimit) -> float:
    """Clamp a numeric value only where the corresponding boundary is set."""

    if limit.lower is not None:
        value = max(value, float(limit.lower))
    if limit.upper is not None:
        value = min(value, float(limit.upper))
    return value


def mean_history_change(history_changes: Sequence[float], window_n: int) -> float:
    """Return the arithmetic mean of the most recent N valid changes."""

    changes = [float(change) for change in history_changes][-int(window_n) :]
    if not changes:
        raise ValueError("没有可用于生成的历史变化量")
    return float(fmean(changes))


def calculate_actual_weight(actual_change: float, history_change: float, threshold_s: float) -> float:
    """Calculate the weighted_delta_v1 contribution of a raw observation."""

    if threshold_s <= 0:
        raise ValueError("S必须大于0")
    return float(threshold_s / (threshold_s + abs(actual_change - history_change)))


def apply_constraints(
    *,
    previous_beautified_metric: float,
    candidate_change: float,
    interval_days: float,
    config: BeautificationConfig,
) -> tuple[float, float]:
    """Apply change, rate and cumulative bounds in the required order."""

    effective_days = max(float(interval_days), 1.0)
    constrained_change = clamp_optional(candidate_change, config.max_single_change)

    rate_change_limit = RangeLimit(
        lower=(
            None
            if config.max_rate.lower is None
            else float(config.max_rate.lower) * effective_days
        ),
        upper=(
            None
            if config.max_rate.upper is None
            else float(config.max_rate.upper) * effective_days
        ),
    )
    constrained_change = clamp_optional(constrained_change, rate_change_limit)

    target_metric = clamp_optional(
        float(previous_beautified_metric) + constrained_change,
        config.cumulative_range,
    )
    return target_metric - float(previous_beautified_metric), target_metric


def generate_target_metric(
    *,
    previous_beautified_metric: float,
    actual_change: float | None,
    history_changes: Sequence[float],
    interval_days: float,
    config: BeautificationConfig,
) -> BeautificationResult:
    """Generate one beautified target metric without mutating raw observations."""

    config.validate()
    history_change = mean_history_change(history_changes, config.window_n)

    if actual_change is None:
        actual_weight = 0.0
        candidate_change = history_change
    else:
        if config.threshold_s is None:
            raise ValueError("启用美化时S必须大于0")
        actual_change = float(actual_change)
        actual_weight = calculate_actual_weight(
            actual_change,
            history_change,
            float(config.threshold_s),
        )
        candidate_change = actual_weight * actual_change + (1.0 - actual_weight) * history_change

    target_change, target_metric = apply_constraints(
        previous_beautified_metric=float(previous_beautified_metric),
        candidate_change=candidate_change,
        interval_days=float(interval_days),
        config=config,
    )
    return BeautificationResult(
        target_change=target_change,
        target_metric=target_metric,
        history_change=history_change,
        actual_change=actual_change,
        actual_weight=actual_weight,
        interval_days=max(float(interval_days), 1.0),
    )
