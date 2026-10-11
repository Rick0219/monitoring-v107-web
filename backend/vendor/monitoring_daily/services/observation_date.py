from __future__ import annotations

from datetime import date, datetime
from typing import Any


INTENSIFIED_SUFFIX = "（加密）"


def split_observation_date(value: Any) -> tuple[str, str] | None:
    if isinstance(value, datetime):
        return value.date().isoformat(), ""
    if isinstance(value, date):
        return value.isoformat(), ""
    text = str(value or "").strip()
    intensified = False
    while text.endswith(INTENSIFIED_SUFFIX):
        intensified = True
        text = text[: -len(INTENSIFIED_SUFFIX)].strip()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            normalized = datetime.strptime(text, pattern).strftime("%Y-%m-%d")
            return normalized, INTENSIFIED_SUFFIX if intensified else ""
        except ValueError:
            continue
    return None


def normalize_observation_date(value: Any) -> str | None:
    parsed = split_observation_date(value)
    return f"{parsed[0]}{parsed[1]}" if parsed else None


def is_intensified_observation(value: Any) -> bool:
    parsed = split_observation_date(value)
    return bool(parsed and parsed[1])


def observation_sort_key(value: Any) -> tuple[date, int, str]:
    parsed = split_observation_date(value)
    if parsed is None:
        return date.max, 2, str(value or "")
    base, suffix = parsed
    return datetime.strptime(base, "%Y-%m-%d").date(), 1 if suffix else 0, suffix


def observation_datetime(value: Any) -> datetime:
    parsed = split_observation_date(value)
    if parsed is None:
        raise ValueError(f"无效的监测日期：{value}")
    return datetime.strptime(parsed[0], "%Y-%m-%d")


def observation_interval_days(current: Any, previous: Any) -> int:
    days = (observation_datetime(current) - observation_datetime(previous)).days
    if days == 0 and observation_sort_key(current) > observation_sort_key(previous):
        return 1
    return days
