from test_projects import new_project, P


def test_membership_grants_shared_project_and_scan_access_then_revokes(client, accounts):
    admin, (owner, a), (member, b) = accounts
    project = new_project(client, a)
    url = P + "/" + project["id"]
    assert client.get(url, headers=b).status_code == 404
    added = client.post(url + "/members", headers=a, json={"email": member["email"]})
    assert added.status_code == 200, added.text
    assert client.get(P, headers=b).json()["data"][0]["id"] == project["id"]
    assert client.get(url, headers=b).json()["owner_id"] == owner["id"]
    saved = client.put(url + "/data", headers=b, json={"revision": 1, "measurement_key": "level:沉降", "rows": [
        {"时间": "2026-01-01", "点号": "A", "测量值": 10},
        {"时间": "2026-01-03", "点号": "A", "测量值": 9.99}]})
    assert saved.status_code == 200, saved.text
    for endpoint in ("/data", "/documents", "/export", "/charts?measurement_key=level:沉降", "/chart-link?measurement_key=level:沉降"):
        assert client.get(url + endpoint, headers=b).status_code == 200
    preferences = {"measurement_key": "level:沉降", "mode": "all", "points": []}
    assert client.put(url + "/chart-settings", headers=b, json=preferences).status_code == 200
    assert client.get(url + "/charts?measurement_key=level:沉降", headers=a).json()["settings"]["mode"] == "top10"
    scope = {"measurement_key": "level:沉降", "start_date": "2026-01-01", "end_date": "2026-01-03"}
    assert client.post(url + "/analysis", headers=b, json=scope).status_code == 200
    assert client.post(url + "/reports/preview", headers=b, json=scope).status_code == 200
    assert client.delete(url + "/members/" + member["id"], headers=a).status_code == 200
    assert client.get(P, headers=b).json()["count"] == 0
    assert client.get(url, headers=b).status_code == 404
    assert client.put(url + "/chart-settings", headers=b, json=preferences).status_code == 404


def test_only_owner_or_admin_manage_members_and_delete_project(client, accounts):
    admin, (owner, a), (member, b) = accounts
    project = new_project(client, a)
    url = P + "/" + project["id"]
    assert client.post(url + "/members", headers=b, json={"email": member["email"]}).status_code == 404
    assert client.post(url + "/members", headers=admin, json={"email": member["email"]}).status_code == 200
    assert client.get(url + "/members", headers=b).status_code == 403
    assert client.post(url + "/members", headers=b, json={"email": owner["email"]}).status_code == 403
    assert client.delete(url + "/members/" + member["id"], headers=b).status_code == 403
    assert client.delete(url + "?revision=1", headers=b).status_code == 403
    assert client.get(url + "/members", headers=admin).json()["count"] == 2
    assert client.delete(url + "/members/" + owner["id"], headers=a).status_code == 400
    assert client.get(url, headers=a).json()["revision"] == 1  # membership changes do not conflict with data drafts


def test_membership_is_idempotent_and_project_specific(client, accounts):
    admin, (_, a), (member, b) = accounts
    p1, p2 = new_project(client, a), new_project(client, a)
    url = P + "/" + p1["id"]
    for _ in range(2):
        assert client.post(url + "/members", headers=a, json={"email": member["email"]}).status_code == 200
    assert client.get(url + "/members", headers=a).json()["count"] == 2
    assert client.get(P, headers=b).json()["count"] == 1
    assert client.get(P + "/" + p2["id"], headers=b).status_code == 404
    assert client.post(url + "/members", headers=a, json={"email": "missing@example.com"}).status_code == 422
    assert client.patch("/api/v1/users/" + member["id"], headers=admin, json={"is_active": False}).status_code == 200
    assert client.get(url, headers=b).status_code == 403
    assert client.post(url + "/members", headers=a, json={"email": member["email"]}).status_code == 422
