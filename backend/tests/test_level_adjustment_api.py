from __future__ import annotations

from test_level_adjustment import FILES
from test_projects import new_project


def _files():
    return [
        ("files", (name, content, "text/plain"))
        for name, content in FILES.items()
    ]


def _url(client, user):
    return "/api/v1/projects/" + new_project(client, user)["id"]


def test_level_adjustment_preview_returns_results_and_mapping_candidates(client, accounts):
    _, (_, user), _ = accounts
    url = _url(client, user)
    response = client.post(
        url + "/level-adjustment/preview",
        headers=user,
        data={"weight_mode": "distance", "observed_date": "2026-10-12"},
        files=_files(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["import_id"]
    assert body["result"]["points"]["Z2"]["elevation"] == -16.8744
    assert body["mapping_candidates"]["Z1"]
    assert body["quality"]["can_apply"] is True


def test_level_adjustment_apply_writes_only_selected_date_and_mapping(client, accounts):
    _, (_, user), _ = accounts
    url = _url(client, user)
    preview = client.post(
        url + "/level-adjustment/preview",
        headers=user,
        data={"weight_mode": "distance", "observed_date": "2026-10-12"},
        files=_files(),
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    revision = client.get(url, headers=user).json()["revision"]
    response = client.put(
        url + "/level-adjustment/apply",
        headers=user,
        json={
            "revision": revision,
            "import_id": payload["import_id"],
            "measurement_key": "level:建筑物位移",
            "observed_date": "2026-10-12",
            "weight_mode": "distance",
            "allow_out_of_tolerance": False,
            "mappings": [
                {"adjusted_point": "Z2", "database_point": "Z2", "enabled": True},
                {"adjusted_point": "Z1", "database_point": "Z1", "enabled": True},
            ],
        },
    )

    assert response.status_code == 200, response.text
    data = client.get(url + "/data", headers=user).json()
    rows = data["measurements"]["level:建筑物位移"]
    assert {row["点号"] for row in rows} == {"Z1", "Z2"}
    assert all(row["时间"] == "2026-10-12" for row in rows)


def test_level_adjustment_apply_rejects_stale_revision_without_mutation(client, accounts):
    _, (_, user), _ = accounts
    url = _url(client, user)
    preview = client.post(
        url + "/level-adjustment/preview",
        headers=user,
        data={"weight_mode": "distance", "observed_date": "2026-10-12"},
        files=_files(),
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    response = client.put(
        url + "/level-adjustment/apply",
        headers=user,
        json={
            "revision": 99,
            "import_id": payload["import_id"],
            "measurement_key": "level:建筑物位移",
            "observed_date": "2026-10-12",
            "weight_mode": "distance",
            "allow_out_of_tolerance": False,
            "mappings": [{"adjusted_point": "Z2", "database_point": "Z2", "enabled": True}],
        },
    )

    assert response.status_code == 409
    assert client.get(url + "/data", headers=user).json()["measurements"] == {}
