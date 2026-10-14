"""Build import previews from instrument observations, and export text reports."""
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Mapping

from app.level_adjustment import (
    AdjustmentPointResult, LevelAdjustmentError, LevelAdjustmentResult,
    ParsedLevelAdjustment, QualityResult, _DAT_POINT, _DAT_ELEVATION,
    _clean_dat_point, _decode_text, _solve_linear_system, cross_check_level_outputs,
    parse_level_adjustment_files, solve_level_network,
)


def prepare_level_import(files: Mapping[str, bytes], weight_mode: str):
    dat_name = next((n for n in files if n.lower().endswith(".dat")), None)
    with_control = any(n.lower().endswith(".bm1") for n in files)
    if with_control:
        parsed = parse_level_adjustment_files(files)
        result = solve_level_network(parsed, weight_mode)
        return "adjusted", parsed, result, cross_check_level_outputs(parsed, result)
    if not dat_name:
        raise LevelAdjustmentError("请上传 DAT 观测文件")
    text, encoding = _decode_text(dat_name, files[dat_name])
    points: dict[str, AdjustmentPointResult] = {}
    # Only read recorded KD1 Z elevations. Closing repetitions and Sh/dz
    # instrument corrections must not overwrite the first observed elevation.
    for line in text.splitlines():
        point = _DAT_POINT.search(line)
        elevation = _DAT_ELEVATION.search(line)
        if point and elevation and "|Sh" not in line:
            if "#" in point.group("point"):
                continue
            name = _clean_dat_point(point.group("point"))
            points.setdefault(name, AdjustmentPointResult(name, float(elevation.group("value")), False))
    if not points:
        raise LevelAdjustmentError(f"{dat_name}: 未找到点号和 Z 高程记录，不能直接映射")
    parsed = ParsedLevelAdjustment({}, [], [], {dat_name: encoding}, {}, "", "")
    quality = QualityResult(closure_error_mm=None, warnings=["未上传控制点文件，不做平差处理，直接使用 DAT 中的高程值"])
    result = LevelAdjustmentResult(weight_mode, points, [], {}, 0, None, quality)
    return "raw", parsed, result, []


def generate_level_reports(dat_name: str, parsed: ParsedLevelAdjustment,
                           result: LevelAdjustmentResult, observed_date: str) -> dict[str, bytes]:
    """Emit GB18030 files with LEVELADJUST column order, using recomputed values."""
    base = Path(dat_name).stem
    day = date.fromisoformat(observed_date)
    date_text = f"{day.year}年{day.month:02d}月{day.day:02d}日"
    station_lines = [" 测站 后视 前视 后尺读数1 后视距1 前尺读数1 前视距1 后尺读数2 后视距2 前尺读数2 前视距2 视距长 累计视距长 测站高差 累计高差", "Start-Line"]
    cumulative_distance = cumulative_height = 0.0
    for i, station in enumerate(parsed.station_observations, 1):
        cumulative_distance += station.distance_m
        cumulative_height += station.delta_h
        readings = []
        for repeat in range(2):
            for records in (station.backsights, station.foresights):
                reading, distance = records[min(repeat, len(records)-1)]
                readings.extend([f"{reading:.5f}", f"{distance:.3f}"])
        station_lines.append(f"{i} {station.from_point} {station.to_point} " + " ".join(readings) +
            f" {station.distance_m:.3f} {cumulative_distance:.3f} {station.delta_h:.5f} {cumulative_height:.5f}")
    station_lines.append("End-Line")
    in1 = [f"{point},{height:.4f}" for point, height in parsed.known_points.items()]
    in1.extend(f"{o.from_point},{o.to_point},{o.delta_h:.5f},{(o.distance_m / 1000 if result.weight_mode == 'distance' else o.station_count):.3f},1" for o in parsed.observations)

    unknown = [p for p in result.points if p not in parsed.known_points]
    index = {p: i for i, p in enumerate(unknown)}
    normal = [[0.0]*len(unknown) for _ in unknown]
    design_rows = []
    for observation in result.observations:
        row = [0.0]*len(unknown)
        if observation.from_point in index:
            row[index[observation.from_point]] -= 1
        if observation.to_point in index:
            row[index[observation.to_point]] += 1
        design_rows.append(row)
        for i, a in enumerate(row):
            if a:
                for j, b in enumerate(row):
                    normal[i][j] += observation.weight * a * b
    columns = [_solve_linear_system(normal, [float(i == j) for i in range(len(unknown))]) for j in range(len(unknown))]
    dof = len(result.observations) - len(unknown)
    pvv = sum(o.weight * o.residual**2 for o in result.observations)
    variance = pvv / dof if dof > 0 else None
    errors = {p: (variance * columns[i][i])**.5 if variance is not None else None for p, i in index.items()}
    errors.update({p: 0.0 for p in parsed.known_points})
    def mm(value):
        return f"{value * 1000:.2f}" if value is not None else "--"
    limit = result.quality.closure_limit_mm
    closure = f"{result.closure_error_mm:.2f}" if result.closure_error_mm is not None else "未形成已知点闭合路线"
    gco = ["高差闭合差计算结果", "闭合环环号：1", "线路点名：" + " ".join(result.points),
           f"高差闭合差：{closure}(MM)", f"闭合环长度：{result.total_distance_km:.4f}(KM)",
           f"以线路长度计算国家二等限差：{limit:.4f}(MM)", f"定权方式：{result.weight_mode}"]
    ou1 = ["已知高程", "序号 点号 高程(m)"]
    ou1.extend(f"{i} {p} {h:.5f}" for i, (p, h) in enumerate(parsed.known_points.items(), 1))
    ou1 += ["平差高程及其精度", "序号 点号 高程(m) 中误差(mm)"]
    ou1.extend(f"{i} {p} {v.elevation:.5f} {mm(errors[p])}" for i, (p, v) in enumerate(result.points.items(), 1))
    ou1 += ["高差平差值及其精度", "序号 起点 终点 高差平差值(m) 改正数(mm) 中误差(mm) 距离(km)"]
    for i, (observation, source, row) in enumerate(zip(result.observations, parsed.observations, design_rows), 1):
        q = sum(a * columns[j][k] * b for j, a in enumerate(row) for k, b in enumerate(row) if a and b)
        error = (max(0, variance * q))**.5 if variance is not None else None
        ou1.append(f"{i} {observation.from_point} {observation.to_point} {observation.adjusted_delta_h:.5f} {observation.correction * 1000:.2f} {mm(error)} {source.distance_m/1000:.4f}")
    ou1 += ["高程控制网总体信息", f"已知高程点：{len(parsed.known_points)}", f"未知高程点：{len(unknown)}", f"高差测段数：{len(parsed.observations)}", f"PVV：{pvv:.10g}", f"自由度：{dof}", "验后单位权中误差(mm)：" + mm(variance**.5 if variance is not None else None)]
    our = ["序号,观测点号,高程,中误差,观测日期"]
    our.extend(f"{i},{p},{v.elevation:.5f},{mm(errors[p])},{date_text}" for i, (p, v) in enumerate(result.points.items(), 1))
    return {f"{base}.{ext}": ("\r\n".join(lines) + "\r\n").encode("gb18030")
            for ext, lines in {"hdf": station_lines, "in1": in1, "gco": gco, "ou1": ou1, "our": our}.items()}
