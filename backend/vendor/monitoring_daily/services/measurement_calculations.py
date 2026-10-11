from __future__ import annotations

from math import hypot
from typing import Any


def calculate_difference(
    current: float | None,
    previous: float | None,
    *,
    multiplier: float = 1.0,
) -> float | None:
    """Calculate a monitored change without applying display rounding."""
    if current is None or previous is None:
        return None
    return (float(current) - float(previous)) * float(multiplier)


def calculate_water_elevation(
    pipe_elevation: float | None,
    water_reading: float | None,
) -> float | None:
    """Water elevation uses the existing rule: pipe elevation minus reading."""
    return calculate_difference(pipe_elevation, water_reading)


def calculate_horizontal_displacement_mm(
    initial: dict[str, Any] | None,
    measured: dict[str, Any] | None,
    mode: str,
) -> float | None:
    """Return X/Y/vector displacement in millimetres using stored metre values."""
    if not initial or not measured:
        return None
    initial_x = _number(initial.get("x"))
    initial_y = _number(initial.get("y"))
    measured_x = _number(measured.get("x"))
    measured_y = _number(measured.get("y"))
    if mode == "x":
        return calculate_difference(measured_x, initial_x, multiplier=1000.0)
    if mode == "y":
        return calculate_difference(measured_y, initial_y, multiplier=1000.0)
    if None in (initial_x, initial_y, measured_x, measured_y):
        return None
    return hypot(measured_x - initial_x, measured_y - initial_y) * 1000.0


def _number(value: Any) -> float | None:
    if value in (None, "", "/"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
