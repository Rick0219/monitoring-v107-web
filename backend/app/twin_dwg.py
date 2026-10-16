"""Convert a read-only DWG document into the web digital-twin scene schema."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any


GEOMETRY_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "HATCH"}
STRUCTURAL_LAYER_NAMES = {
    "地下连续墙", "地连墙分幅", "冠梁", "砼支撑", "钢支撑", "钢围檩",
    "支撑中心线", "旋喷桩", "围护结构", "主体", "结构", "细线", "THIN",
    "hatch", "基坑边界", "围护", "支撑", "围檩",
}
STRUCTURAL_KEYWORDS = ("连续墙", "地连墙", "围护", "支撑", "冠梁", "围檩", "旋喷", "结构", "基坑", "hatch")


class TwinDwgError(ValueError):
    """A user-facing DWG conversion error."""


def _xy(value: Any) -> tuple[float, float] | None:
    if hasattr(value, "x") and hasattr(value, "y"):
        candidate = (value.x, value.y)
    elif isinstance(value, (tuple, list)) and len(value) >= 2:
        candidate = (value[0], value[1])
    else:
        return None
    if not all(isinstance(item, (int, float)) and math.isfinite(item) for item in candidate):
        return None
    return float(candidate[0]), float(candidate[1])


def _layer_is_structural(name: str) -> bool:
    return name in STRUCTURAL_LAYER_NAMES or any(keyword in name for keyword in STRUCTURAL_KEYWORDS)


def _entity_points(entity: Any) -> list[tuple[float, float]]:
    dxf = entity.dxf
    points: list[tuple[float, float]] = []
    for key in ("start", "end", "center", "insert", "location", "point"):
        value = dxf.get(key)
        parsed = _xy(value)
        if parsed:
            points.append(parsed)
    values = dxf.get("points") or []
    if isinstance(values, list):
        for value in values:
            parsed = _xy(value)
            if parsed:
                points.append(parsed)
    for path in dxf.get("paths") or []:
        path_values = path.get("points", []) if isinstance(path, dict) else []
        for value in path_values:
            parsed = _xy(value)
            if parsed:
                points.append(parsed)
    return points


def _normalize(x: float, y: float, bounds: tuple[float, float, float, float]) -> list[float]:
    xmin, ymin, xmax, ymax = bounds
    width = xmax - xmin or 1.0
    height = ymax - ymin or 1.0
    return [round((x - xmin) / width, 7), round(1 - (y - ymin) / height, 7)]


def _angle(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _geometry(entity: Any, bounds: tuple[float, float, float, float]) -> dict[str, Any] | None:
    dxf = entity.dxf
    kind = str(entity.dxftype).upper()
    if kind == "LINE":
        start, end = _xy(dxf.get("start")), _xy(dxf.get("end"))
        return {"kind": "line", "points": [_normalize(*start, bounds), _normalize(*end, bounds)]} if start and end else None
    if kind in {"LWPOLYLINE", "POLYLINE"}:
        points = [_normalize(*parsed, bounds) for value in (dxf.get("points") or []) if (parsed := _xy(value))]
        if len(points) < 2:
            return None
        return {"kind": "polyline", "points": points, "closed": bool(dxf.get("flags", 0) & 1)}
    if kind == "CIRCLE":
        center = _xy(dxf.get("center"))
        if not center:
            return None
        scale = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) or 1.0
        return {"kind": "circle", "center": _normalize(*center, bounds), "radius": round(float(dxf.get("radius", 0)) / scale, 7)}
    if kind == "ARC":
        center = _xy(dxf.get("center"))
        if not center:
            return None
        radius = float(dxf.get("radius", 0) or 0)
        start = math.radians(_angle(dxf.get("start_angle"), 0))
        end = math.radians(_angle(dxf.get("end_angle"), 360))
        while end < start:
            end += 2 * math.pi
        samples = max(8, min(64, round((end - start) * 16)))
        points = [_normalize(center[0] + radius * math.cos(start + (end - start) * i / samples), center[1] + radius * math.sin(start + (end - start) * i / samples), bounds) for i in range(samples + 1)]
        return {"kind": "polyline", "points": points, "closed": False}
    if kind == "HATCH":
        polygons = []
        for path in dxf.get("paths") or []:
            values = path.get("points", []) if isinstance(path, dict) else []
            polygon = [_normalize(*parsed, bounds) for value in values if (parsed := _xy(value))]
            if len(polygon) >= 3:
                polygons.append(polygon)
        return {"kind": "hatch", "pattern": dxf.get("pattern_name"), "solid": bool(dxf.get("solid_fill")), "polygons": polygons}
    return None


def build_scene_from_document(document: Any, filename: str) -> dict[str, Any]:
    layer_table = document.layers()
    layer_by_handle = {value.get("handle"): name for name, value in layer_table.items()}
    candidates = []
    for entity in document.modelspace().iter_entities(include_styles=True):
        kind = str(entity.dxftype).upper()
        layer = layer_by_handle.get(entity.dxf.get("layer_handle"), "0")
        if kind in GEOMETRY_TYPES and _layer_is_structural(layer):
            candidates.append((entity, layer))
    # Some drawings use arbitrary layer names. If the semantic layer filter
    # found nothing, retain every supported geometry entity rather than making
    # the user discover an empty scene.
    if not candidates:
        for entity in document.modelspace().iter_entities(include_styles=True):
            kind = str(entity.dxftype).upper()
            layer = layer_by_handle.get(entity.dxf.get("layer_handle"), "0")
            if kind in GEOMETRY_TYPES:
                candidates.append((entity, layer))
    all_points = [point for entity, _ in candidates for point in _entity_points(entity)]
    if not all_points:
        raise TwinDwgError("DWG 中没有可转换的二维结构几何图形")
    bounds = (min(x for x, _ in all_points), min(y for _, y in all_points), max(x for x, _ in all_points), max(y for _, y in all_points))
    layer_names = list(dict.fromkeys(layer for _, layer in candidates))
    layer_ids = {name: f"layer:{index}" for index, name in enumerate(layer_names)}
    layers = [{"id": layer_ids[name], "name": name, "visible": True, "locked": False, "color_index": layer_table.get(name, {}).get("color_index")} for name in layer_names]
    objects = []
    for index, (entity, layer) in enumerate(candidates):
        geometry = _geometry(entity, bounds)
        if geometry is None:
            continue
        objects.append({"id": f"dwg:{entity.handle or index}", "layer_id": layer_ids[layer], "source_handle": entity.handle, "source_type": str(entity.dxftype).upper(), "geometry": geometry})
    if not objects:
        raise TwinDwgError("DWG 中没有可转换的二维结构几何图形")
    digest = hashlib.sha1(filename.encode("utf-8", "replace")).hexdigest()[:12]
    return {
        "schema_version": 1,
        "scene_id": f"dwg-{digest}",
        "source": {"filename": Path(filename).name, "dwg_version": getattr(document, "version", None), "units": getattr(document, "units", None), "layout": "Model"},
        "coordinate_system": {"kind": "dwg-modelspace-normalized", "axis": "x-right/y-down", "bounds": [round(value, 3) for value in bounds], "width_native": round(bounds[2] - bounds[0], 3), "height_native": round(bounds[3] - bounds[1], 3)},
        "layers": layers,
        "objects": objects,
        "placed_points": [],
        "recognition": {"status": "structural-only", "warnings": ["测点不从 DWG 识别；请在网页中从当前工程数据库选择并放置。"]},
    }


def scene_from_dwg(path: Path, filename: str | None = None) -> dict[str, Any]:
    try:
        import ezdwg
    except ImportError as exc:
        raise TwinDwgError("服务器未安装 DWG 解析组件，请安装 ezdwg 后重试") from exc
    try:
        document = ezdwg.read(str(path))
        return build_scene_from_document(document, filename or path.name)
    except TwinDwgError:
        raise
    except Exception as exc:
        raise TwinDwgError(f"DWG 解析失败：{exc}") from exc
