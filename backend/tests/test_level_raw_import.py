import pytest

from app.level_adjustment import parse_level_adjustment_files, solve_level_network
from test_projects import new_project


DAT = "\n".join([
    "For M5|Adr 1|TO Start-Line aBFFB 123|",
    "For M5|Adr 2|KD1 BM 123| | |Z 10.00000 m |",
    "For M5|Adr 3|KD1 BM 1 123|Rb 1.50000 m |HD 10.000 m | |",
    "For M5|Adr 4|KD1 P1 1 123|Rf 1.40000 m |HD 20.000 m | |",
    "For M5|Adr 5|KD1 P1 1 123|Rf 1.40020 m |HD 20.000 m | |",
    "For M5|Adr 6|KD1 BM 1 123|Rb 1.50000 m |HD 10.000 m | |",
    "For M5|Adr 7|KD1 P1 123| | |Z 10.09990 m |",
    "For M5|Adr 8|KD1 BM 1 123|Rf 1.60000 m |HD 30.000 m | |",
    "For M5|Adr 9|KD1 P1 1 123|Rb 1.50000 m |HD 30.000 m | |",
    "For M5|Adr 10|KD1 P1 1 123|Rb 1.50000 m |HD 30.000 m | |",
    "For M5|Adr 11|KD1 BM 1 123|Rf 1.60000 m |HD 30.000 m | |",
    "For M5|Adr 12|KD1 BM 123| | |Z 9.99990 m |",
    "For M5|Adr 13|KD1 BM 123|Sh -0.00010 m |dz 0.00010 m |Z 10.00000 m |",
    "For M5|Adr 14|TO End-Line 123|",
]).encode("gb18030")


def test_dat_bm1_computes_from_averaged_bffb_readings():
    parsed = parse_level_adjustment_files({"test.DAT": DAT, "test.BM1": b"BM,10\n"})
    assert len(parsed.observations) == 2
    assert parsed.observations[0].delta_h == pytest.approx(.09990)
    assert parsed.observations[0].distance_m == 30
    assert parsed.observations[1].delta_h == pytest.approx(-.1)
    result = solve_level_network(parsed, "distance")
    assert result.points["P1"].elevation == pytest.approx(10.099933333333)
    assert result.closure_error_mm == pytest.approx(-.1)
    station = solve_level_network(parsed, "station")
    assert station.points["P1"].elevation == pytest.approx(10.09995)


@pytest.mark.parametrize("with_control", [True, False])
def test_minimal_upload_preview_apply_and_generated_files(client, accounts, with_control):
    _, (_, user), _ = accounts
    project = new_project(client, user)
    url = "/api/v1/projects/" + project["id"]
    files = [("files", ("test.DAT", DAT, "text/plain"))]
    if with_control:
        files.append(("files", ("test.BM1", b"BM,10\n", "text/plain")))
    preview = client.post(url + "/level-adjustment/preview", headers=user, files=files,
                          data={"weight_mode": "distance", "observed_date": "2026-10-14"})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["mode"] == ("adjusted" if with_control else "raw")
    assert body["result"]["points"]["P1"]["elevation"] == pytest.approx(10.099933333333 if with_control else 10.09990)
    if with_control:
        assert {item["name"].rsplit(".", 1)[-1] for item in body["generated_files"]} == {"hdf", "in1", "gco", "ou1", "our"}
        for item in body["generated_files"]:
            response = client.get(item["url"], headers=user)
            assert response.status_code == 200
            assert response.content.decode("gb18030").strip()
    else:
        assert "不做平差" in body["message"]
        assert not body["generated_files"]
        assert body["result"]["points"]["BM"]["elevation"] == 10  # repeated closure doesn't replace initial height
    applied = client.put(url + "/level-adjustment/apply", headers=user, json={
        "revision": body["project_revision"], "import_id": body["import_id"],
        "measurement_key": "level:建筑物位移", "observed_date": "2026-10-14", "weight_mode": "distance",
        "mappings": [{"adjusted_point": "P1", "database_point": "P1"}],
    })
    assert applied.status_code == 200, applied.text
    rows = client.get(url + "/data", headers=user).json()["measurements"]["level:建筑物位移"]
    assert len(rows) == 1
    assert rows[0]["测量值"] == pytest.approx(body["result"]["points"]["P1"]["elevation"])
    assert "未平差" in rows[0]["备注"] if not with_control else "平差" in rows[0]["备注"]


def test_dat_only_no_elevations_reports_clear_error(client, accounts):
    _, (_, user), _ = accounts
    project = new_project(client, user)
    response = client.post("/api/v1/projects/" + project["id"] + "/level-adjustment/preview",
        headers=user, files=[("files", ("test.DAT", b"For M5|KD1 P1|Rb 1 m |HD 10 m |", "text/plain"))],
        data={"weight_mode": "distance", "observed_date": "2026-10-14"})
    assert response.status_code == 422
    assert "高程" in response.json()["detail"]
