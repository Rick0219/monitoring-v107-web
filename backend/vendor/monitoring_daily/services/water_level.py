from __future__ import annotations

from typing import Any


WATER_POINT_COLUMN = "点位"
PIPE_ELEVATION_COLUMN = "管口高程（m）"
WATER_READING_COLUMN = "水位读数（m）"
WATER_PARAMETER_COLUMNS = [WATER_POINT_COLUMN, PIPE_ELEVATION_COLUMN]


def normalize_water_parameter(
    row: dict[str, Any],
    *,
    strict: bool = True,
) -> dict[str, Any]:
    point = str(row.get(WATER_POINT_COLUMN, row.get("点号", "")) or "").strip()
    raw_elevation = row.get(PIPE_ELEVATION_COLUMN, row.get("洞口高程", ""))
    if strict and not point:
        raise ValueError("水位点位不能为空。")
    if raw_elevation in (None, ""):
        if strict:
            raise ValueError(f"点位“{point}”的管口高程不能为空。")
        elevation: float | str = ""
    else:
        try:
            elevation = float(raw_elevation)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"点位“{point}”的管口高程必须是数字。") from exc
    return {
        WATER_POINT_COLUMN: point,
        PIPE_ELEVATION_COLUMN: elevation,
    }


def normalize_water_measurement(
    row: dict[str, Any],
    parameter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = dict(row)
    point = str(
        source.get(WATER_POINT_COLUMN, source.get("点号", "")) or ""
    ).strip()
    reading = source.get(WATER_READING_COLUMN, source.get("水深", ""))
    elevation = (
        parameter.get(PIPE_ELEVATION_COLUMN, "")
        if parameter is not None
        else source.get(PIPE_ELEVATION_COLUMN, source.get("洞口高程", ""))
    )
    normalized: dict[str, Any] = {}
    if "序号" in source:
        normalized["序号"] = source.get("序号", "")
    if "时间" in source:
        normalized["时间"] = source.get("时间", "")
    normalized[WATER_POINT_COLUMN] = point
    normalized[PIPE_ELEVATION_COLUMN] = elevation
    normalized[WATER_READING_COLUMN] = reading
    normalized["备注"] = source.get("备注", "")
    legacy_fields = {
        "序号",
        "时间",
        "点号",
        WATER_POINT_COLUMN,
        "洞口高程",
        PIPE_ELEVATION_COLUMN,
        "水深",
        WATER_READING_COLUMN,
        "备注",
    }
    normalized.update(
        {key: value for key, value in source.items() if key not in legacy_fields}
    )
    return normalized
