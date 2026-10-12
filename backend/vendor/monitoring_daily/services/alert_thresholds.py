from __future__ import annotations

import math
import re
from typing import Any, Mapping


_NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def parse_threshold_range(
    value: Any,
    label: str,
) -> tuple[float | None, float | None]:
    """Parse '/', a symmetric magnitude, or a signed lower/upper pair."""
    text = str(value if value is not None else "").strip()
    text = text.replace(" ", "").replace("／", "/").replace("﹢", "+").replace("﹣", "-")
    if text in {"", "/"}:
        return None, None
    if text.startswith("±"):
        text = text[1:]
    if "/" not in text:
        number = _parse_finite_number(text, label)
        magnitude = abs(number)
        return -magnitude, magnitude

    parts = text.split("/")
    if len(parts) != 2:
        raise _format_error(label)
    first = _parse_finite_number(parts[0], label)
    second = _parse_finite_number(parts[1], label)
    if first == 0 and second == 0:
        return 0.0, 0.0
    if first * second > 0 or (first == 0 and second == 0):
        raise _format_error(label)
    lower = min(first, second)
    upper = max(first, second)
    if lower > 0 or upper < 0:
        raise _format_error(label)
    return lower, upper


def format_threshold_range(
    lower: Any,
    upper: Any,
) -> str:
    if lower in (None, "", "/") and upper in (None, "", "/"):
        return "/"
    try:
        low = float(lower) if lower not in (None, "", "/") else None
        high = float(upper) if upper not in (None, "", "/") else None
    except (TypeError, ValueError):
        return "/"
    if low is None and high is not None:
        low = -abs(high)
    if high is None and low is not None:
        high = abs(low)
    if low is None or high is None or not math.isfinite(low) or not math.isfinite(high):
        return "/"
    low = min(low, -abs(high)) if low > 0 else low
    high = max(high, abs(low)) if high < 0 else high
    return f"{_signed_text(low)}/{_signed_text(high)}"


def threshold_range_from_settings(
    settings: Mapping[str, Any] | None,
    base_key: str,
) -> str:
    values = settings or {}
    up_key = f"{base_key}_up"
    down_key = f"{base_key}_down"
    if up_key in values or down_key in values:
        return format_threshold_range(values.get(down_key), values.get(up_key))
    base = values.get(base_key)
    if base in (None, "", "/"):
        return "/"
    try:
        magnitude = abs(float(base))
    except (TypeError, ValueError):
        return "/"
    return format_threshold_range(-magnitude, magnitude)


def alert_control_bounds(
    settings: Mapping[str, Any] | None,
) -> tuple[float | None, float | None]:
    values = settings or {}
    base = _optional_number(values.get("cumulative_warning"))
    upper = _optional_number(values.get("cumulative_warning_up"))
    lower = _optional_number(values.get("cumulative_warning_down"))
    if upper is None and base is not None:
        upper = abs(base)
    if lower is None and base is not None:
        lower = -abs(base)
    if upper is None and lower is None:
        return None, None
    if upper is None:
        upper = abs(lower or 0.0)
    if lower is None:
        lower = -abs(upper)
    if upper <= 0:
        upper = abs(upper) or abs(lower)
    if lower >= 0:
        lower = -abs(lower) or -abs(upper)
    if lower >= upper:
        extent = max(abs(lower), abs(upper), 1.0)
        return -extent, extent
    return float(lower), float(upper)


def alert_status(
    cumulative_value: Any,
    rate_value: Any,
    settings: Mapping[str, Any] | None,
) -> str:
    """Return the highest alert level reached by cumulative or rate data."""
    values = settings or {}
    checks = (
        ("红色预警", "cumulative_warning", cumulative_value),
        ("红色预警", "rate_limit", rate_value),
        ("黄色预警", "cumulative_alarm", cumulative_value),
        ("黄色预警", "rate_alarm", rate_value),
    )
    for status, base_key, value in checks:
        number = _optional_number(value)
        if number is None:
            continue
        lower, upper = threshold_bounds_from_settings(values, base_key)
        if lower is None or upper is None:
            continue
        if number < lower or number > upper:
            return status
    return "正常"


def threshold_bounds_from_settings(
    settings: Mapping[str, Any] | None,
    base_key: str,
) -> tuple[float | None, float | None]:
    try:
        return parse_threshold_range(
            threshold_range_from_settings(settings, base_key),
            base_key,
        )
    except ValueError:
        return None, None


def _parse_finite_number(value: str, label: str) -> float:
    if not value or not _NUMBER_PATTERN.fullmatch(value):
        raise _format_error(label)
    number = float(value)
    if not math.isfinite(number):
        raise _format_error(label)
    return number


def _optional_number(value: Any) -> float | None:
    if value in (None, "", "/"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _signed_text(value: float) -> str:
    text = f"{abs(value):.6f}".rstrip("0").rstrip(".") or "0"
    return f"{'-' if value < 0 else '+'}{text}"


def _format_error(label: str) -> ValueError:
    return ValueError(
        f"{label}格式不正确，请输入“/”、“±3”、“40”或“-40/+40”这样的数值范围。"
    )
