from conftest import login
from test_charts import populate
from test_projects import new_project, P


def test_default_permissions_are_enforced_even_for_project_owner(client, accounts):
    admin, (owner, a), _ = accounts
    url = populate(client, a)
    changed = client.patch('/api/v1/users/' + owner['id'], headers=admin,
                           json={'permissions': ['database_data', 'database_charts', 'analysis']})
    assert changed.status_code == 200, changed.text
    assert client.get(url, headers=a).json()['permissions'] == ['database_data', 'database_charts', 'analysis']
    assert client.get(url + '/charts?measurement_key=level:沉降', headers=a).status_code == 200
    assert client.post(url + '/analysis', headers=a, json={'measurement_key': 'level:沉降', 'start_date': '2026-01-01', 'end_date': '2026-01-03'}).status_code == 200
    assert client.put(url + '/data', headers=a, json={'revision': 2, 'measurement_key': 'level:沉降', 'rows': []}).status_code == 403
    assert client.put(url + '/database', headers=a, json={'revision': 2, 'measurement_key': 'level:沉降', 'date': '2026-01-03', 'rows': []}).status_code == 403
    assert client.post(url + '/import?revision=2', headers=a).status_code == 403
    assert client.patch(url, headers=a, json={'revision': 2, 'name': '无权修改'}).status_code == 403
    assert client.post(url + '/documents', headers=a).status_code == 403
    assert client.post(url + '/reports/preview', headers=a, json={}).status_code == 403
    assert client.patch('/api/v1/users/me', headers=a, json={'permissions': ['reports']}).status_code == 422
    assert client.get(url, headers=admin).json()['permissions'] == ['data_entry', 'database_data', 'database_charts', 'analysis', 'reports']


def test_project_permissions_override_defaults_only_admin_can_assign(client, accounts):
    admin, (_, a), (member, b) = accounts
    u1, u2 = populate(client, a), populate(client, a)
    assert client.patch('/api/v1/users/' + member['id'], headers=admin, json={'permissions': ['reports']}).status_code == 200
    for url in (u1, u2):
        assert client.post(url + '/members', headers=a, json={'email': member['email']}).status_code == 200
    override = {'permissions': ['data_entry', 'database_data']}
    assert client.patch(u1 + '/members/' + member['id'] + '/permissions', headers=a, json=override).status_code == 403
    assert client.post(u1 + '/members', headers=a, json={'email': member['email'], **override}).status_code == 403
    assert client.patch(u1 + '/members/' + member['id'] + '/permissions', headers=admin, json=override).status_code == 200
    assert client.get(u1, headers=b).json()['permissions'] == ['data_entry', 'database_data']
    assert client.get(u2, headers=b).json()['permissions'] == ['reports']
    assert client.get(u2 + '/catalog', headers=b).status_code == 200
    assert client.get(u2 + '/data', headers=b).status_code == 403
    assert client.get(u2 + '/charts?measurement_key=level:沉降', headers=b).status_code == 403
    assert client.get(u2 + '/chart-link?measurement_key=level:沉降', headers=b).status_code == 403
    assert client.get(u2 + '/export', headers=b).status_code == 403
    assert client.put(u2 + '/chart-settings', headers=b, json={'measurement_key': 'level:沉降'}).status_code == 403
    assert client.get(u2 + '/documents', headers=b).status_code == 403
    assert client.post(u2 + '/analysis', headers=b, json={}).status_code == 403
    assert client.post(u2 + '/ask', headers=b, json={'question': '分析'}).status_code == 403
    assert client.post(u2 + '/reports/preview', headers=b, json={'measurement_key': 'level:沉降', 'start_date': '2026-01-01', 'end_date': '2026-01-03'}).status_code == 200
    assert client.patch(u1 + '/members/' + member['id'] + '/permissions', headers=admin, json={'permissions': None}).status_code == 200
    assert client.get(u1, headers=b).json()['permissions'] == ['reports']


def test_new_account_permissions_roundtrip_and_revocation_with_existing_token(client, accounts):
    admin, _, _ = accounts
    r = client.post('/api/v1/users/', headers=admin, json={'email': 'restricted@example.com', 'password': 'Testing-user-5678!', 'permissions': ['reports']})
    assert r.status_code == 200, r.text
    user = r.json()
    assert user['permissions'] == ['reports']
    h = login(client, user['email'])
    assert client.post(P, headers=h, json={'name': '没有新建权限'}).status_code == 403
    p = new_project(client, admin)
    assert client.post(P + '/' + p['id'] + '/members', headers=admin, json={'email': user['email']}).status_code == 200
    assert client.get(P + '/' + p['id'] + '/catalog', headers=h).json()['measurements'] == {}
    assert client.patch('/api/v1/users/' + user['id'], headers=admin, json={'permissions': []}).status_code == 200
    assert client.get(P + '/' + p['id'] + '/catalog', headers=h).status_code == 403
    assert client.patch('/api/v1/users/' + user['id'], headers=admin, json={'permissions': ['unknown']}).status_code == 422


def test_owner_cannot_bypass_admin_restrictions_by_removing_and_readding_member(client, accounts):
    admin, (_, a), (member, b) = accounts
    project = new_project(client, a)
    url = P + '/' + project['id']
    assert client.post(url + '/members', headers=admin, json={'email': member['email'], 'permissions': ['reports']}).status_code == 200
    assert client.delete(url + '/members/' + member['id'], headers=a).status_code == 200
    assert client.get(url, headers=b).status_code == 404
    assert client.post(url + '/members', headers=a, json={'email': member['email']}).status_code == 200
    assert client.get(url, headers=b).json()['permissions'] == ['reports']
