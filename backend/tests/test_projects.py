import uuid
import pytest
from conftest import login

P = "/api/v1/projects"

def new_project(client, headers):
    result = client.post(P, headers=headers, json={"name": "绿岛湖北站", "description": "施工监测", "location": "佛山"})
    assert result.status_code == 200, result.text
    return result.json()

def test_login_and_project_owner_is_written_by_server(client, accounts):
    admin, (alice, a), (bob, b) = accounts
    forged = client.post(P, headers=a, json={"name": "伪造", "owner_id": bob["id"]})
    assert forged.status_code == 422
    p = new_project(client, a)
    assert p["owner_id"] == alice["id"]
    assert client.get(P, headers=b).json()["count"] == 0
    assert client.get(P, headers=a).json()["count"] == 1
    assert client.get(P+"/all", headers=a).status_code == 403
    assert client.get(P+"/all", headers=admin).json()["count"] == 1
    assert client.get(P, headers=admin).json()["count"] == 0
    assert client.get(P+"/"+p["id"], headers=b).status_code == 404
    assert client.get(P+"/"+p["id"], headers=admin).status_code == 200

def test_ownership_blocks_every_project_subresource(client, accounts):
    admin, (_, a), (_, b) = accounts
    p = new_project(client, a)
    base = P+"/"+p["id"]
    calls = [
        ("get", "", None), ("patch", "", {"name": "盗改", "revision": 1}),
        ("delete", "?revision=1", None), ("get", "/data", None),
        ("put", "/data", {"revision": 1, "measurement_key": "level:建筑物位移", "rows": []}),
        ("get", "/export", None), ("post", "/import", None),
        ("get", "/documents", None), ("post", "/documents", None),
        ("delete", "/documents/"+str(uuid.uuid4()), None),
        ("post", "/analysis", {"measurement_key": "__all__", "start_date":"2026-01-01","end_date":"2026-02-01"}),
        ("post", "/ask", {"question": "最大变化", "mode":"data"}),
        ("get", "/twin/scene", None),
        ("post", "/twin/import", None),
        ("put", "/twin/scene", {"revision": 1, "scene": {}}),
        ("post", "/reports/preview", {"measurement_key": "__all__", "start_date":"2026-01-01","end_date":"2026-02-01"}),
        ("post", "/reports/download", {"measurement_key": "__all__", "start_date":"2026-01-01","end_date":"2026-02-01"}),
    ]
    for method, suffix, body in calls:
        response = client.request(method, base+suffix, headers=b, json=body)
        assert response.status_code == 404, (method, suffix, response.text)
    assert client.get(base, headers=a).json()["name"] == "绿岛湖北站"

def test_cannot_escalate_role_or_manage_users_and_disabled_tokens_stop(client, accounts):
    admin, (alice, a), (_, b) = accounts
    assert client.get("/api/v1/users/", headers=a).status_code == 403
    assert client.post("/api/v1/users/", headers=a, json={"email":"x@example.com","password":"Other-password-123"}).status_code == 403
    assert client.patch("/api/v1/users/me", headers=a, json={"is_superuser":True}).status_code == 422
    assert client.post("/api/v1/users/signup", json={"email":"x@example.com","password":"Other-password-123","is_superuser":True}).status_code in (404,405)
    assert client.patch("/api/v1/users/"+alice["id"], headers=admin, json={"is_active":False}).status_code == 200
    assert client.get(P, headers=a).status_code == 403
    assert client.get(P).status_code == 401
    assert client.post("/api/v1/login/access-token",data={"username":"bob@example.com","password":"wrong-password"}).status_code == 401

def test_password_reset_invalidates_existing_login(client,accounts):
    admin,(alice,a),_=accounts
    assert client.patch("/api/v1/users/"+alice["id"],headers=admin,json={"password":"Changed-password-123!"}).status_code==200
    assert client.get(P,headers=a).status_code==401
    assert client.get(P,headers=login(client,alice["email"],"Changed-password-123!")).status_code==200

def test_invalid_project_payload_is_rejected_without_replacing_previous_data(client,accounts):
    import json
    _,(_,a),_=accounts
    p=new_project(client,a);url=P+"/"+p["id"]
    body={"measurements":{"level:沉降":[{"点号":"X","时间":"2026-01-01","测量值":10}]},"water_parameters":"wrong-shape"}
    response=client.post(url+"/import?revision=1",headers=a,files={"file":("bad.proj",json.dumps(body).encode(),"application/json")})
    assert response.status_code==422
    assert client.get(url,headers=a).json()["revision"]==1


def test_only_creator_or_admin_can_delete_even_without_entry_permission(client, accounts):
    admin, (owner, user), (member, other) = accounts
    p = new_project(client, user)
    url = P + '/' + p['id']
    assert client.post(url + '/members', headers=user, json={'email': member['email']}).status_code == 200
    assert client.delete(url + '?revision=1', headers=other).status_code == 403
    assert client.patch('/api/v1/users/' + owner['id'], headers=admin, json={'permissions': []}).status_code == 200
    assert client.delete(url + '?revision=99', headers=user).status_code == 409
    assert client.delete(url + '?revision=1', headers=user).status_code == 200
    assert client.get(url, headers=user).status_code == 404
    p = new_project(client, other)
    assert client.delete(P + '/' + p['id'] + '?revision=1', headers=admin).status_code == 200
