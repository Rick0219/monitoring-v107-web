"""Parsing and deterministic adjustment for LEVELADJUST text exports.

The desktop program stores these files as text.  This module deliberately
does not execute the desktop binary; it parses the observed network and solves
the height equations locally so the web application can show the evidence used
for each result.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Literal, Mapping

WeightMode = Literal["distance", "station"]


class LevelAdjustmentError(ValueError):
    """A user-correctable import or adjustment error."""


@dataclass(frozen=True)
class KnownPoint:
    point: str
    elevation: float
    source_file: str
    source_line: int


@dataclass(frozen=True)
class LevelObservation:
    from_point: str
    to_point: str
    delta_h: float
    distance_m: float | None
    station_count: float | None
    source_file: str
    source_line: int


@dataclass(frozen=True)
class StationObservation:
    from_point: str
    to_point: str
    distance_m: float | None
    delta_h: float | None
    source_file: str
    source_line: int


@dataclass(frozen=True)
class CrossCheck:
    source: str
    status: Literal["matched", "mismatch", "missing"]
    detail: str
    difference: float | None = None


@dataclass
class ParsedLevelAdjustment:
    known_points: dict[str, float]
    observations: list[LevelObservation]
    station_observations: list[StationObservation]
    encoding_by_file: dict[str, str]
    file_digests: dict[str, str]
    route_start: str
    route_end: str
    hdf_outputs: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)
    gco_closure_mm: float | None = None
    gco_distance_km: float | None = None
    gco_limit_mm_per_km: float | None = None
    ou1_points: dict[str, float] = field(default_factory=dict)
    our_points: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AdjustmentPointResult:
    point: str
    elevation: float
    fixed: bool


@dataclass(frozen=True)
class AdjustmentObservationResult:
    from_point: str
    to_point: str
    observed_delta_h: float
    adjusted_delta_h: float
    correction: float
    residual: float
    weight: float


@dataclass
class QualityResult:
    status: Literal["passed", "warning", "blocked"] = "passed"
    can_apply: bool = True
    closure_error_mm: float | None = None
    limit_mm_per_km: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class LevelAdjustmentResult:
    weight_mode: WeightMode
    points: dict[str, AdjustmentPointResult]
    observations: list[AdjustmentObservationResult]
    corrections: dict[str, float]
    total_distance_km: float
    closure_error_mm: float
    quality: QualityResult


_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_DAT_POINT = re.compile(r"\|KD1\s+(?P<point>\S+)")
_DAT_VALUE = re.compile(r"\|(?P<kind>Rb|Rf)\s+(?P<value>%s)\s+m\s+\|.*?\|HD\s+(?P<distance>%s)\s+m" % (_NUMBER, _NUMBER))
_DAT_ELEVATION = re.compile(r"\|Z\s+(?P<value>%s)\s+m" % _NUMBER)


def parse_level_adjustment_files(files: Mapping[str, bytes]) -> ParsedLevelAdjustment:
    normalized = {_basename(name): value for name, value in files.items()}
    if not any(name.lower().endswith(".bm1") for name in normalized):
        raise LevelAdjustmentError("缺少 BM1 控制点文件")
    known_name = next(name for name in normalized if name.lower().endswith(".bm1"))
    known_points = _parse_bm1(known_name, normalized[known_name])
    if not known_points:
        raise LevelAdjustmentError(f"{known_name}: 未找到有效控制点")

    encodings: dict[str, str] = {}
    digests: dict[str, str] = {}
    text_by_name: dict[str, list[str]] = {}
    for name, content in normalized.items():
        text, encoding = _decode_text(name, content)
        encodings[name] = encoding
        digests[name] = hashlib.sha256(content).hexdigest()
        text_by_name[name] = text.splitlines()

    in1_name = _find_extension(normalized, ".in1")
    hdf_name = _find_extension(normalized, ".hdf")
    dat_name = _find_extension(normalized, ".dat")
    if not in1_name and not hdf_name:
        raise LevelAdjustmentError("至少需要 IN1 或 HDF 高差文件")

    hdf_outputs = _parse_hdf(hdf_name, text_by_name[hdf_name]) if hdf_name else {}
    observations = (
        _parse_in1(in1_name, text_by_name[in1_name], hdf_outputs)
        if in1_name
        else _observations_from_hdf(hdf_name, text_by_name[hdf_name], hdf_outputs)
    )
    station_observations = _parse_dat(dat_name, text_by_name[dat_name]) if dat_name else []
    if not observations:
        raise LevelAdjustmentError("没有可用于平差的测段观测")
    if len({obs.from_point for obs in observations} | {obs.to_point for obs in observations}) < 2:
        raise LevelAdjustmentError("平差网络的点号不足")

    gco_name = _find_extension(normalized, ".gco")
    ou1_name = _find_extension(normalized, ".ou1")
    our_name = _find_extension(normalized, ".our")
    gco = _parse_gco(text_by_name[gco_name]) if gco_name else {}
    route_start = observations[0].from_point
    route_end = observations[-1].to_point
    return ParsedLevelAdjustment(
        known_points=known_points,
        observations=observations,
        station_observations=station_observations,
        encoding_by_file=encodings,
        file_digests=digests,
        route_start=route_start,
        route_end=route_end,
        hdf_outputs=hdf_outputs,
        gco_closure_mm=gco.get("closure_mm"),
        gco_distance_km=gco.get("distance_km"),
        gco_limit_mm_per_km=gco.get("limit_mm_per_km"),
        ou1_points=_parse_result_points(text_by_name[ou1_name], "ou1") if ou1_name else {},
        our_points=_parse_result_points(text_by_name[our_name], "our") if our_name else {},
    )


def solve_level_network(parsed: ParsedLevelAdjustment, weight_mode: WeightMode) -> LevelAdjustmentResult:
    if weight_mode not in ("distance", "station"):
        raise LevelAdjustmentError("weight_mode 必须是 distance 或 station")
    all_points = list(dict.fromkeys([*parsed.known_points, *[o.from_point for o in parsed.observations], *[o.to_point for o in parsed.observations]]))
    unknown = [point for point in all_points if point not in parsed.known_points]
    if not unknown:
        raise LevelAdjustmentError("没有需要平差的未知点")
    index = {point: position for position, point in enumerate(unknown)}
    normal = [[0.0 for _ in unknown] for _ in unknown]
    rhs = [0.0 for _ in unknown]
    weights: list[float] = []
    for observation in parsed.observations:
        weight = _observation_weight(observation, parsed, weight_mode)
        weights.append(weight)
        row = [0.0 for _ in unknown]
        known_contribution = 0.0
        if observation.to_point in index:
            row[index[observation.to_point]] += 1.0
        else:
            known_contribution += parsed.known_points[observation.to_point]
        if observation.from_point in index:
            row[index[observation.from_point]] -= 1.0
        else:
            known_contribution -= parsed.known_points[observation.from_point]
        target = observation.delta_h - known_contribution
        for i, value in enumerate(row):
            if value == 0:
                continue
            rhs[i] += weight * value * target
            for j, other in enumerate(row):
                if other:
                    normal[i][j] += weight * value * other
    solved = _solve_linear_system(normal, rhs)
    elevations = {**parsed.known_points, **dict(zip(unknown, solved, strict=True))}
    point_results = {point: AdjustmentPointResult(point, elevation, point in parsed.known_points) for point, elevation in elevations.items()}
    observation_results: list[AdjustmentObservationResult] = []
    corrections: dict[str, float] = {}
    for number, (observation, weight) in enumerate(zip(parsed.observations, weights, strict=True), start=1):
        adjusted = elevations[observation.to_point] - elevations[observation.from_point]
        correction = adjusted - observation.delta_h
        key = f"{number}:{observation.from_point}->{observation.to_point}"
        corrections[key] = correction
        observation_results.append(AdjustmentObservationResult(observation.from_point, observation.to_point, observation.delta_h, adjusted, correction, correction, weight))
    total_m = sum(_distance_for(observation, parsed) for observation in parsed.observations)
    closure_mm = (elevations[parsed.route_end] - elevations[parsed.route_start]) * 1000.0 if parsed.route_start == parsed.route_end else sum(item.adjusted_delta_h for item in observation_results) * 1000.0
    quality = QualityResult(closure_error_mm=closure_mm, limit_mm_per_km=parsed.gco_limit_mm_per_km)
    if parsed.gco_limit_mm_per_km is not None and total_m > 0:
        allowed = parsed.gco_limit_mm_per_km * (total_m / 1000.0)
        if abs(closure_mm) > allowed:
            quality.status = "warning"
            quality.warnings.append(f"闭合差 {closure_mm:.4f} mm 超过限差 {allowed:.4f} mm")
            quality.can_apply = False
    return LevelAdjustmentResult(weight_mode, point_results, observation_results, corrections, total_m / 1000.0, closure_mm, quality)


def cross_check_level_outputs(parsed: ParsedLevelAdjustment, result: LevelAdjustmentResult) -> list[CrossCheck]:
    checks: list[CrossCheck] = []
    if parsed.gco_closure_mm is None:
        checks.append(CrossCheck("gco", "missing", "未提供闭合差报告"))
    else:
        observed_closure_mm = sum(observation.delta_h for observation in parsed.observations) * 1000.0
        difference = observed_closure_mm - parsed.gco_closure_mm
        checks.append(CrossCheck("gco", "matched" if abs(difference) <= 0.02 else "mismatch", f"闭合差差异 {difference:.4f} mm", difference))
    if not parsed.our_points:
        checks.append(CrossCheck("our", "missing", "未提供最终高程文件"))
    else:
        differences = [abs(result.points[point].elevation - elevation) for point, elevation in parsed.our_points.items() if point in result.points]
        difference = max(differences, default=math.inf)
        checks.append(CrossCheck("our", "matched" if difference <= 0.0005 else "mismatch", f"最大高程差异 {difference:.6f} m", difference))
    if not parsed.ou1_points:
        checks.append(CrossCheck("ou1", "missing", "未提供平差表"))
    else:
        checks.append(CrossCheck("ou1", "matched", "已读取平差表点号"))
    if any(check.status == "mismatch" for check in checks):
        result.quality.status = "blocked"
        result.quality.can_apply = False
        result.quality.warnings.extend(check.detail for check in checks if check.status == "mismatch")
    return checks


def _basename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _find_extension(files: Mapping[str, bytes], extension: str) -> str | None:
    return next((name for name in files if name.lower().endswith(extension)), None)


def _decode_text(name: str, content: bytes) -> tuple[str, str]:
    for encoding in ("gb18030", "utf-8-sig", "utf-8"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise LevelAdjustmentError(f"{name}: 无法按 GB18030 或 UTF-8 解码")


def _parse_bm1(name: str, content: bytes) -> dict[str, float]:
    text, _ = _decode_text(name, content)
    result: dict[str, float] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            raise LevelAdjustmentError(f"{name}:{line_number}: BM1 行应为点号,高程")
        result[parts[0]] = _number(parts[1], name, line_number)
    return result


def _parse_in1(name: str, lines: list[str], hdf: dict[tuple[str, str], tuple[float, float]]) -> list[LevelObservation]:
    result: list[LevelObservation] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip() or not "," in line:
            continue
        parts = [part.strip() for part in line.split(",")]
        # LEVELADJUST exports the starting control point as the first IN1 row
        # (`point,elevation`) before the five-column observation rows.
        if len(parts) == 2:
            if not parts[0] or _float_or_none(parts[1]) is None:
                raise LevelAdjustmentError(f"{name}:{line_number}: IN1 控制点行无效")
            continue
        if len(parts) < 4:
            raise LevelAdjustmentError(f"{name}:{line_number}: IN1 行字段不足")
        from_point, to_point = parts[0], parts[1]
        delta_h = _number(parts[2], name, line_number)
        weight_value = _number(parts[3], name, line_number)
        hdf_value = hdf.get((from_point, to_point))
        distance_m = hdf_value[0] if hdf_value else weight_value * 1000.0
        result.append(LevelObservation(from_point, to_point, delta_h, distance_m, 1.0, name, line_number))
    return result


def _parse_hdf(name: str, lines: list[str]) -> dict[tuple[str, str], tuple[float, float]]:
    result: dict[tuple[str, str], tuple[float, float]] = {}
    for line_number, line in enumerate(lines, start=1):
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        from_point, to_point = parts[1], parts[2]
        numbers = [_float_or_none(value) for value in parts[3:]]
        values = [value for value in numbers if value is not None]
        if len(values) < 2:
            continue
        distance_m = values[-4] if len(values) >= 4 else values[-2]
        delta_h = values[-2] if len(values) >= 4 else values[-1]
        result[(from_point, to_point)] = (distance_m, delta_h)
    return result


def _observations_from_hdf(name: str, lines: list[str], hdf: dict[tuple[str, str], tuple[float, float]]) -> list[LevelObservation]:
    result: list[LevelObservation] = []
    for line_number, line in enumerate(lines, start=1):
        parts = line.split()
        if len(parts) < 5 or not parts[0].isdigit():
            continue
        from_point, to_point = parts[1], parts[2]
        distance_m, delta_h = hdf[(from_point, to_point)]
        result.append(LevelObservation(from_point, to_point, delta_h, distance_m, 1.0, name, line_number))
    return result


def _parse_dat(name: str | None, lines: list[str] | None) -> list[StationObservation]:
    if not name or lines is None:
        return []
    result: list[StationObservation] = []
    previous: tuple[str, float, float] | None = None
    current: tuple[str, float, float] | None = None
    for line_number, line in enumerate(lines, start=1):
        point_match = _DAT_POINT.search(line)
        value_match = _DAT_VALUE.search(line)
        if point_match and value_match:
            point = point_match.group("point")
            reading = float(value_match.group("value"))
            distance = float(value_match.group("distance"))
            if value_match.group("kind") == "Rb":
                previous = (point, reading, distance)
            else:
                current = (point, reading, distance)
                if previous and previous[0] != point:
                    result.append(StationObservation(previous[0], point, previous[2] + distance, previous[1] - reading, name, line_number))
                previous = None
                current = None
    return result


def _parse_gco(lines: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for line in lines:
        values = re.findall(_NUMBER, line)
        if not values:
            continue
        value = float(values[-1])
        if "闭合差" in line and "每公里" not in line:
            result["closure_mm"] = value
        elif "路线长度" in line:
            result["distance_km"] = value
        elif "每公里" in line:
            result["limit_mm_per_km"] = value
    return result


def _parse_result_points(lines: list[str], source: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for line in lines:
        parts = [part.strip() for part in line.split(",")] if source == "our" else line.split()
        if len(parts) < 3 or not parts[0].strip().lstrip("+-").isdigit():
            continue
        point = parts[1]
        elevation_index = 2 if source == "our" else (3 if _float_or_none(parts[2]) is None and len(parts) > 3 else 2)
        value = _float_or_none(parts[elevation_index])
        if point and value is not None:
            result[point] = value
    return result


def _number(value: str, name: str, line_number: int) -> float:
    parsed = _float_or_none(value)
    if parsed is None:
        raise LevelAdjustmentError(f"{name}:{line_number}: 数值无效：{value}")
    return parsed


def _float_or_none(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _distance_for(observation: LevelObservation, parsed: ParsedLevelAdjustment) -> float:
    if observation.distance_m is not None and observation.distance_m > 0:
        return observation.distance_m
    hdf = parsed.hdf_outputs.get((observation.from_point, observation.to_point))
    if hdf and hdf[0] > 0:
        return hdf[0]
    raise LevelAdjustmentError(f"{observation.from_point}->{observation.to_point}: 缺少有效测段距离")


def _observation_weight(observation: LevelObservation, parsed: ParsedLevelAdjustment, mode: WeightMode) -> float:
    if mode == "distance":
        return 1.0 / _distance_for(observation, parsed)
    station_count = observation.station_count or 1.0
    if station_count <= 0:
        raise LevelAdjustmentError(f"{observation.from_point}->{observation.to_point}: 测站数必须为正")
    return 1.0 / station_count


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    size = len(vector)
    augmented = [row[:] + [value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise LevelAdjustmentError("平差矩阵秩不足，无法唯一求解")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [left - factor * right for left, right in zip(augmented[row], augmented[column], strict=True)]
    return [augmented[row][-1] for row in range(size)]
