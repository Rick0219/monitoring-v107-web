import uuid
import pytest
from sqlmodel import Session
from app.core.db import engine
from app.permission_models import AccountPermission, ProjectPermission
from test_charts import populate


FEATURES = ['data_entry', 'database_data', 'database_charts', 'analysis', 'reports']
KEY = 'level:沉降'


@pytest.mark.parametrize('feature', FEATURES)
def test_each_feature_is_independent_and_protected_on_server(client, accounts, feature):
    admin, (owner, user), _ = accounts
    url = populate(client, user)
    changed = client.patch('/api/v1/users/' + owner['id'], headers=admin,
                           json={'permissions': [feature]})
    assert changed.status_code == 200, changed.text
    assert client.get(url, headers=user).json()['permissions'] == [feature]
    assert client.get(url + '/catalog', headers=user).status_code == 200
    for path, allowed in [('/data', 'data_entry'), ('/export', 'data_entry'),
                          ('/database', 'database_data'), ('/charts', 'database_charts'),
                          ('/chart-link', 'database_charts'), ('/documents', 'analysis')]:
        response = client.get(url + path, headers=user, params={'measurement_key': KEY})
        assert response.status_code == (200 if feature == allowed else 403), (path, response.text)
    for path, allowed, body in [
        ('/database-date', 'database_data', {'measurement_key': KEY, 'end_date': '2026-01-01'}),
        ('/chart-settings', 'database_charts', {'measurement_key': KEY, 'mode': 'all'}),
    ]:
        response = client.put(url + path, headers=user, json=body)
        assert response.status_code == (200 if feature == allowed else 403), (path, response.text)
    scope = {'measurement_key': KEY, 'start_date': '2026-01-01', 'end_date': '2026-01-03'}
    for path, allowed in [('/analysis', 'analysis'), ('/reports/preview', 'reports'), ('/reports/download', 'reports')]:
        response = client.post(url + path, headers=user, json=scope)
        assert response.status_code == (200 if feature == allowed else 403), (path, response.text)
    if feature != 'data_entry':
        for path, body in [('/data', {'revision': 2, 'measurement_key': KEY, 'rows': []}),
                           ('/database', {'revision': 2, 'measurement_key': KEY, 'date': '2026-01-03', 'rows': []})]:
            assert client.put(url + path, headers=user, json=body).status_code == 403
        assert client.post('/api/v1/projects', headers=user, json={'name': '不能新建'}).status_code == 403


def test_table_and_chart_payloads_are_separate_and_date_preserves_preferences(client, accounts):
    admin, (owner, user), _ = accounts
    url = populate(client, user)
    preference = {'measurement_key': KEY, 'mode': 'custom', 'points': ['P01'], 'display': 'history'}
    assert client.put(url + '/chart-settings', headers=user, json=preference).status_code == 200
    chart = client.get(url + '/charts', headers=user, params={'measurement_key': KEY}).json()
    assert not {'rows', 'columns', 'raw_rows', 'raw_columns'}.intersection(chart)
    assert client.patch('/api/v1/users/' + owner['id'], headers=admin,
                        json={'permissions': ['database_data']}).status_code == 200
    assert client.put(url + '/database-date', headers=user, json={'measurement_key': KEY, 'end_date': '2026-01-01'}).status_code == 200
    table = client.get(url + '/database', headers=user, params={'measurement_key': KEY}).json()
    assert table['effective_date'] == '2026-01-01'
    assert {row['时间'] for row in table['raw_rows']} == {'2026-01-01'}
    assert not {'points', 'history_dates', 'selected_points'}.intersection(table)
    assert client.put(url + '/database-date', headers=user, json={'measurement_key': KEY, 'end_date': 'bad'}).status_code == 422
    assert client.put(url + '/database-date', headers=user, json={'measurement_key': KEY, 'end_date': '', 'mode': 'all'}).status_code == 422
    assert client.patch('/api/v1/users/' + owner['id'], headers=admin,
                        json={'permissions': ['database_charts']}).status_code == 200
    saved = client.get(url + '/charts', headers=user, params={'measurement_key': KEY}).json()['settings']
    assert saved == {**preference, 'end_date': '2026-01-01'}


def test_legacy_database_grants_remain_readable_without_granting_new_write_access(client, accounts):
    admin, (owner, user), _ = accounts
    url = populate(client, user)
    with Session(engine) as session:
        record = session.get(AccountPermission, uuid.UUID(owner['id']))
        record.permissions = ['database', 'analysis']
        session.add(record)
        session.commit()
    assert client.get(url, headers=user).json()['permissions'] == ['database_data', 'database_charts', 'analysis']
    with Session(engine) as session:
        session.add(ProjectPermission(project_id=uuid.UUID(url.rsplit('/', 1)[-1]),
                                      user_id=uuid.UUID(owner['id']), permissions=['database_edit']))
        session.commit()
    assert client.get(url, headers=user).json()['permissions'] == ['database_data']
    assert client.patch('/api/v1/users/' + owner['id'], headers=admin,
                        json={'permissions': ['database_edit']}).status_code == 422
