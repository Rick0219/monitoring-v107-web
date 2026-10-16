from app.twin_dwg import build_scene_from_document
from test_projects import new_project, P


class FakeDxf:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def __getitem__(self, key):
        return self.values[key]


class FakeEntity:
    def __init__(self, kind, layer_handle, **values):
        self.dxftype = kind
        self.handle = values.pop("handle", kind.lower())
        self.dxf = FakeDxf(layer_handle=layer_handle, **values)


class FakeLayout:
    def __init__(self, entities):
        self.entities = entities

    def iter_entities(self, include_styles=True):
        return iter(self.entities)


class FakeDocument:
    version = "AC1018"
    units = "millimeters"

    def __init__(self):
        self._layers = {
            "基坑边界": {"handle": "L1", "color_index": 3},
            "文字标注": {"handle": "L2", "color_index": 7},
        }
        self._modelspace = FakeLayout([
            FakeEntity("LINE", "L1", handle="10", start=(10, 20, 0), end=(110, 20, 0)),
            FakeEntity("LWPOLYLINE", "L1", handle="11", points=[(10, 20), (110, 20), (110, 80)], flags=0),
            FakeEntity("TEXT", "L2", handle="12", insert=(20, 40), text="DBC-01"),
        ])

    def layers(self):
        return self._layers

    def modelspace(self):
        return self._modelspace


def test_build_scene_from_dwg_document_keeps_structure_and_leaves_points_unplaced():
    scene = build_scene_from_document(FakeDocument(), "plan.dwg")

    assert scene["schema_version"] == 1
    assert scene["source"]["filename"] == "plan.dwg"
    assert [layer["name"] for layer in scene["layers"]] == ["基坑边界"]
    assert {item["source_type"] for item in scene["objects"]} == {"LINE", "LWPOLYLINE"}
    assert scene["objects"][0]["geometry"]["points"][0] == [0.0, 1.0]
    assert scene["placed_points"] == []
    assert scene["recognition"]["status"] == "structural-only"


def test_dwg_preview_endpoint_returns_generated_scene_without_saving(client, accounts, monkeypatch):
    _, (_, owner), _ = accounts
    project = new_project(client, owner)
    fake_scene = {
        "schema_version": 1,
        "layers": [{"id": "layer:0", "name": "基坑边界"}],
        "objects": [{"id": "dwg:1", "layer_id": "layer:0", "geometry": {"kind": "line", "points": [[0, 0], [1, 1]]}}],
        "placed_points": [],
    }
    monkeypatch.setattr("app.api.routes.workspace.scene_from_dwg", lambda path, filename: fake_scene)
    response = client.post(P + "/" + project["id"] + "/twin/dwg-preview", headers=owner, files={"file": ("plan.dwg", b"fake-dwg", "application/octet-stream")})
    assert response.status_code == 200, response.text
    assert response.json()["scene"]["placed_points"] == []
    assert client.get(P + "/" + project["id"] + "/twin/scene", headers=owner).json()["scene"] is None
