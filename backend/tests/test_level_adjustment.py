from __future__ import annotations

import importlib
from typing import Any

import pytest


FILES = {
    "3标1工区 -z.BM1": "Z2,-16.8744\n".encode("gb18030"),
    "3标1工区 -z.DAT": "\n".join(
        [
            "For M5|Adr 196|KD1       Z2                123|                      |                      |Z       -16.87440 m   |",
            "For M5|Adr 197|KD1       Z2              1 123|Rb        1.45965 m   |HD         11.182 m   |                      |",
            "For M5|Adr 198|KD1       Z1              1 123|Rf        1.38073 m   |HD         12.485 m   |                      |",
            "For M5|Adr 199|KD1       Z1                123|                      |                      |Z       -16.79551 m   |",
            "For M5|Adr 200|KD1       Z1              1 123|Rb        1.38060 m   |HD         12.629 m   |                      |",
            "For M5|Adr 201|KD1       Z2              1 123|Rf        1.42533 m   |HD         11.207 m   |                      |",
            "For M5|Adr 202|KD1       Z2                123|                      |                      |Z       -16.87458 m   |",
            "For M5|Adr 203|KD1       Z2                123|Sh       -0.00018 m   |dz        0.00018 m   |Z       -16.87440 m   |",
        ]
    ).encode("gb18030"),
    "3标1工区 -z.hdf": "测站 后视 前视 测站高差 累计测距\n1 Z2 Z1 1.45965 23.666 0.07889\n2 Z1 Z2 1.38060 23.839 -0.07800\n".encode(
        "gb18030"
    ),
    "3标1工区 -z.in1": "Z2,-16.8744\nZ2,Z1,0.07889,0.024,1\nZ1,Z2,-0.07800,0.024,1\n".encode(
        "gb18030"
    ),
    "3标1工区 -z.gco": "闭合差： 0.89(MM)\n闭合路线长度： 0.0475(KM)\n以环线长度计算国家二等限差： 4.0000(MM)\n每公里水准测量全中误差： 0.15(MM/KM)\n".encode(
        "gb18030"
    ),
    "3标1工区 -z.ou1": "1 Z2 -16.8744\n2 Z1 -16.7955\n3 Z2 -16.8744\n".encode(
        "gb18030"
    ),
    "3标1工区 -z.our": "1,Z2,-16.87440,0.00,2026年10月12日\n2,Z1,-16.79550,0.03,2026年10月12日\n".encode(
        "gb18030"
    ),
}


def _module() -> Any:
    try:
        return importlib.import_module("app.level_adjustment")
    except ModuleNotFoundError:
        return None


def _function(name: str) -> Any:
    module = _module()
    assert module is not None, "level adjustment module is not implemented"
    function = getattr(module, name, None)
    assert callable(function), f"missing level adjustment function: {name}"
    return function


def test_parse_level_adjustment_group_reads_encoding_and_source_lines():
    parse = _function("parse_level_adjustment_files")
    parsed = parse(FILES)

    assert parsed.known_points["Z2"] == pytest.approx(-16.8744)
    assert parsed.route_start == "Z2"
    assert parsed.route_end == "Z2"
    assert parsed.encoding_by_file["3标1工区 -z.BM1"] == "gb18030"
    assert parsed.observations[0].source_line > 0
    assert parsed.observations[0].source_file.endswith(".in1")


def test_parse_rejects_missing_known_point_or_malformed_measurement():
    parse = _function("parse_level_adjustment_files")

    missing_bm1 = {key: value for key, value in FILES.items() if not key.endswith(".BM1")}
    with pytest.raises(ValueError, match="BM1"):
        parse(missing_bm1)

    malformed = dict(FILES)
    malformed["3标1工区 -z.in1"] = "Z2,Z1,不是数字,0.024,1\n".encode("gb18030")
    with pytest.raises(ValueError, match="in1"):
        parse(malformed)


def test_solve_level_network_distance_weight_matches_reference():
    parse = _function("parse_level_adjustment_files")
    solve = _function("solve_level_network")
    result = solve(parse(FILES), "distance")

    assert result.weight_mode == "distance"
    assert result.points["Z2"].elevation == pytest.approx(-16.8744)
    assert result.points["Z1"].elevation == pytest.approx(-16.7955, abs=5e-4)
    assert result.total_distance_km == pytest.approx(0.047505, abs=1e-5)
    assert result.quality.status in {"passed", "warning"}


def test_solve_level_network_station_weight_is_distinct_and_finite():
    parse = _function("parse_level_adjustment_files")
    solve = _function("solve_level_network")
    parsed = parse(FILES)
    distance = solve(parsed, "distance")
    station = solve(parsed, "station")

    assert station.weight_mode == "station"
    assert all(point.elevation == point.elevation for point in station.points.values())
    assert station.points["Z2"].elevation == pytest.approx(-16.8744)
    assert distance.points["Z1"].elevation != station.points["Z1"].elevation or distance.corrections != station.corrections


def test_cross_check_reports_gco_ou1_our_mismatch_without_silent_write():
    parse = _function("parse_level_adjustment_files")
    solve = _function("solve_level_network")
    cross_check = _function("cross_check_level_outputs")
    files = dict(FILES)
    files["3标1工区 -z.our"] = "1,Z2,-15.00000,0.00,2026年10月12日\n".encode("gb18030")

    parsed = parse(files)
    result = solve(parsed, "distance")
    checks = cross_check(parsed, result)

    assert any(check.status == "mismatch" and check.source == "our" for check in checks)
    assert result.quality.can_apply is False
