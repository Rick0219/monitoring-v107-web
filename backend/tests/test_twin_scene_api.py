import json
import pytest

from test_projects import new_project, P


SCENE = {
    "schema_version": 1,
    "scene_id": "demo-scene",
    "layers": [{"id": "layer:boundary", "name": "基坑边界", "visible": True, "locked": False}],
    "objects": [{
        "id": "dwg:1", "layer_id": "layer:boundary", "source_type": "line",
        "geometry": {"kind": "line", "points": [[0.1, 0.2], [0.9, 0.2]]},
    }],
    "placed_points": [{
        "id": "point:level:地表位移:DBC-01", "measurement_key": "level:地表位移", "point": "DBC-01",
        "position": [0.35, 0.45], "elevation": 0.12,
    }],
}


def test_twin_scene_import_get_and_save_position(client, accounts):
    _, (_, owner), _ = accounts
    project = new_project(client, owner)
    url = P + "/" + project["id"]

    imported = client.post(
        url + "/twin/import",
        headers=owner,
        files={"file": ("scene.json", json.dumps(SCENE, ensure_ascii=False).encode("utf-8"), "application/json")},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["revision"] == 2

    loaded = client.get(url + "/twin/scene", headers=owner)
    assert loaded.status_code == 200
    assert loaded.json()["scene"]["scene_id"] == "demo-scene"
    assert loaded.json()["scene"]["placed_points"][0]["position"] == [0.35, 0.45]

    scene = json.loads(json.dumps(SCENE, ensure_ascii=False))
    scene["placed_points"][0]["position"] = [0.55, 0.65]
    saved = client.put(url + "/twin/scene", headers=owner, json={"revision": 2, "scene": scene})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 3
    assert client.get(url + "/twin/scene", headers=owner).json()["scene"]["placed_points"][0]["position"] == [0.55, 0.65]


def test_twin_scene_rejects_invalid_position_without_replacing_scene(client, accounts):
    _, (_, owner), _ = accounts
    project = new_project(client, owner)
    url = P + "/" + project["id"]
    assert client.post(
        url + "/twin/import",
        headers=owner,
        files={"file": ("scene.json", json.dumps(SCENE).encode(), "application/json")},
    ).status_code == 200
    invalid = json.loads(json.dumps(SCENE))
    invalid["placed_points"][0]["position"] = ["invalid", 0.5]
    response = client.put(url + "/twin/scene", headers=owner, json={"revision": 2, "scene": invalid})
    assert response.status_code == 422
    current = client.get(url + "/twin/scene", headers=owner).json()
    assert current["revision"] == 2
    assert current["scene"]["placed_points"][0]["position"] == [0.35, 0.45]


@pytest.mark.parametrize("position", [[1.25, -0.2]])
def test_twin_scene_allows_points_outside_structure_bounds(client, accounts, position):
    _, (_, owner), _ = accounts
    project = new_project(client, owner)
    url = P + "/" + project["id"]
    assert client.post(
        url + "/twin/import",
        headers=owner,
        files={"file": ("scene.json", json.dumps(SCENE).encode(), "application/json")},
    ).status_code == 200
    outside = json.loads(json.dumps(SCENE))
    outside["placed_points"][0]["position"] = position
    response = client.put(url + "/twin/scene", headers=owner, json={"revision": 2, "scene": outside})
    assert response.status_code == 200, response.text
    assert client.get(url + "/twin/scene", headers=owner).json()["scene"]["placed_points"][0]["position"] == position


def test_twin_scene_import_ignores_legacy_sensor_identification(client, accounts):
    _, (_, owner), _ = accounts
    project = new_project(client, owner)
    url = P + "/" + project["id"]
    legacy = json.loads(json.dumps(SCENE))
    legacy.pop("placed_points")
    legacy["sensors"] = [{
        "id": "sensor:legacy", "type_code": "DBC", "measurement_key": "level:地表位移",
        "point": "DBC-01", "position": [0.1, 0.2],
    }]
    response = client.post(url + "/twin/import", headers=owner,
                           files={"file": ("scene.json", json.dumps(legacy).encode(), "application/json")})
    assert response.status_code == 200, response.text
    scene = response.json()["scene"]
    assert scene["placed_points"] == []
    assert "sensors" not in scene


def test_twin_scene_post_compatibility_save(client, accounts):
    """Keep already-open browser bundles from failing while they refresh."""
    _, (_, owner), _ = accounts
    project = new_project(client, owner)
    url = P + "/" + project["id"]
    assert client.post(
        url + "/twin/import",
        headers=owner,
        files={"file": ("scene.json", json.dumps(SCENE).encode(), "application/json")},
    ).status_code == 200
    response = client.post(url + "/twin/scene", headers=owner, json={"revision": 2, "scene": SCENE})
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 3
