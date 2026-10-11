from test_projects import new_project, P
import pytest
import json


def populate(client, headers, key="level:沉降", rows=None):
    project = new_project(client, headers)
    url = P + "/" + project["id"]
    if rows is None:
        rows = [{"时间": date, "点号": f"P{i:02}", "测量值": value}
                for i in range(1, 42)
                for date, value in [("2026-01-01", 10), ("2026-01-03", 10 - i / 1000)]]
    r = client.put(url + "/data", headers=headers,
                   json={"revision": 1, "measurement_key": key, "rows": rows})
    assert r.status_code == 200, r.text
    return url


def test_chart_ranking_uses_all_points_and_daily_report_values(client, accounts):
    _, (_, user), _ = accounts
    url = populate(client, user)
    r = client.get(url + "/charts", headers=user, params={"measurement_key": "level:沉降"})
    assert r.status_code == 200, r.text
    chart = r.json()
    assert chart["settings"]["mode"] == "top10"
    assert chart["selected_points"] == [f"P{i:02}" for i in range(41, 31, -1)]
    assert len(chart["points"]) == 41
    assert chart["points"][-1]["current"] == -41
    assert chart["points"][-1]["values"][-1]["value"] == -41
    table = client.get(url + '/database', headers=user, params={'measurement_key': 'level:沉降'}).json()
    assert table["rows"][-1]["本次累计变化量（mm）"] == -41


def test_settings_persist_and_are_user_project_scoped(client, accounts):
    admin, (_, user), (_, other) = accounts
    url = populate(client, user)
    body = {"measurement_key": "level:沉降", "mode": "custom", "points": ["P03", "P41"], "display": "history", "end_date": ""}
    assert client.put(url + "/chart-settings", headers=user, json=body).status_code == 200
    chart = client.get(url + "/charts", headers=user, params={"measurement_key": "level:沉降"}).json()
    assert chart["selected_points"] == ["P03", "P41"]
    assert chart["settings"]["display"] == "history"
    assert client.get(url + "/charts", headers=admin, params={"measurement_key": "level:沉降"}).json()["settings"]["mode"] == "top10"
    assert client.get(url + "/charts", headers=other, params={"measurement_key": "level:沉降"}).status_code == 404
    assert client.put(url + "/chart-settings", headers=other, json=body).status_code == 404
    assert client.put(url + "/chart-settings", headers=user, json={**body, "mode": "bad"}).status_code == 422
    assert client.put(url + "/chart-settings", headers=user, json={**body, "points": ["not-in-project"]}).status_code == 422
    assert client.put(url + "/chart-settings", headers=user, json={**body, "end_date": "bad"}).status_code == 422


def test_chart_date_keeps_original_baseline_and_missing_values(client, accounts):
    _, (_, user), _ = accounts
    url = populate(client, user, rows=[
        {"时间": "2026-01-01", "点号": "A", "测量值": 10},
        {"时间": "2026-01-03", "点号": "A", "测量值": 9.99},
        {"时间": "2026-01-05", "点号": "B", "测量值": 7},
    ])
    body = {"measurement_key": "level:沉降", "mode": "all", "points": [], "display": "daily", "end_date": "2026-01-03"}
    assert client.put(url + "/chart-settings", headers=user, json=body).status_code == 200
    chart = client.get(url + "/charts", headers=user, params={"measurement_key": "level:沉降"}).json()
    assert chart["points"][0]["current"] == -10
    assert chart["effective_date"] == "2026-01-03"
    body["end_date"] = ""
    client.put(url + "/chart-settings", headers=user, json=body)
    chart = client.get(url + "/charts", headers=user, params={"measurement_key": "level:沉降"}).json()
    assert chart["points"][0]["current"] is None  # never carry a stale reading forward


def test_depth_profile_retains_numeric_depth_and_signed_displacement(client, accounts):
    _, (_, user), _ = accounts
    url = populate(client, user, key="inclinometer:CX01", rows=[
        {"深度": "1", "2026-01-01": 5, "2026-01-03": 3},
        {"深度": "10", "2026-01-01": 2, "2026-01-03": 8},
    ])
    chart = client.get(url + "/charts", headers=user, params={"measurement_key": "inclinometer:CX01"}).json()
    assert chart["unit"] == "mm"
    assert [p["depth"] for p in chart["points"]] == [1, 10]
    assert [p["current"] for p in chart["points"]] == [-2, 6]
    assert chart["selected_points"] == ["10", "1"]


@pytest.mark.parametrize("key,base,first,last,unit,expected", [
    ("water", {"点位": "W1", "管口高程（m）": 10}, {"水位读数（m）": 1}, {"水位读数（m）": 0.95}, "mm", 50),
    ("horizontal", {"点号": "H1"}, {"X 坐标": 0, "Y 坐标": 0}, {"X 坐标": .003, "Y 坐标": .004}, "mm", 5),
    ("axial", {"点号": "Z1", "编号": "N1"}, {"轴力（kN）": 100}, {"轴力（kN）": 125}, "kN", 25),
    ("tilt", {"点号1": "T1", "点号2": "T2"}, {"倾斜度（‰）": 0}, {"倾斜度（‰）": 1.234}, "‰", 1.23),
])
def test_every_measurement_uses_report_units_and_values(client, accounts, key, base, first, last, unit, expected):
    _, (_, user), _ = accounts
    url = populate(client, user, key=key, rows=[
        {**base, **first, "时间": "2026-01-01"}, {**base, **last, "时间": "2026-01-03"}])
    r = client.get(url + "/charts", headers=user, params={"measurement_key": key})
    assert r.status_code == 200, r.text
    chart = r.json()
    assert chart["unit"] == unit
    assert chart["points"][0]["current"] == expected
    assert chart["points"][0]["values"][-1]["value"] == expected


def test_axial_multi_sensor_history_matches_daily_point_chart(client, accounts):
    _, (_, user), _ = accounts
    url = populate(client, user, key="axial", rows=[
        {"点号": "Z1", "编号": number, "时间": date, "轴力（kN）": value}
        for number, delta in [("A", 10), ("B", 20)]
        for date, value in [("2026-01-01", 100), ("2026-01-03", 100 + delta)]])
    chart = client.get(url + "/charts", headers=user, params={"measurement_key": "axial"}).json()
    table = client.get(url + '/database', headers=user, params={'measurement_key': 'axial'}).json()
    assert len(table["rows"]) == 2  # retain both sensors in the data table
    assert chart["points"][0]["current"] == 20
    assert chart["points"][0]["values"][-1]["value"] == 20


def test_imported_daily_control_bounds_are_used_by_chart(client, accounts):
    _, (_, user), _ = accounts
    url = populate(client, user)
    payload = client.get(url + "/export", headers=user).json()
    payload["report_settings"] = {"alerts": {"level:沉降": {"cumulative_warning_down": -12, "cumulative_warning_up": 18}}}
    imported = client.post(url + "/import?revision=2", headers=user,
                           files={"file": ("thresholds.proj", json.dumps(payload).encode(), "application/json")})
    assert imported.status_code == 200, imported.text
    chart = client.get(url + "/charts", headers=user, params={"measurement_key": "level:沉降"}).json()
    assert chart["control_bounds"] == [-12, 18]


def test_database_date_filters_raw_and_report_without_changing_baseline(client, accounts):
    _, (_, user), _ = accounts
    url = populate(client, user, rows=[
        {"时间": "2026-01-01", "点号": "A", "测量值": 10},
        {"时间": "2026-01-03", "点号": "A", "测量值": 9.99},
        {"时间": "2026-01-05", "点号": "A", "测量值": 9.98}])
    client.put(url + '/chart-settings', headers=user, json={'measurement_key': 'level:沉降', 'end_date': '2026-01-03'})
    chart = client.get(url + '/database?measurement_key=level:沉降', headers=user).json()
    assert chart['raw_rows'] == [{"时间": "2026-01-03", "点号": "A", "测量值": 9.99}]
    assert chart['rows'][0]['本次累计变化量（mm）'] == -10


def test_inclinometer_raw_date_edit_preserves_other_periods(client, accounts):
    _, (_, user), _ = accounts
    url = populate(client, user, key='inclinometer:CX01', rows=[
        {'深度': '1', '2026-01-01': 5, '2026-01-03': 3, '2026-01-05': 9},
        {'深度': '10', '2026-01-01': 2, '2026-01-03': 8, '2026-01-05': 11}])
    client.put(url + '/chart-settings', headers=user, json={'measurement_key': 'inclinometer:CX01', 'end_date': '2026-01-03'})
    chart = client.get(url + '/database?measurement_key=inclinometer:CX01', headers=user).json()
    assert chart['raw_columns'] == ['深度', '2026-01-03']
    assert chart['raw_rows'][0] == {'深度': '1', '2026-01-03': 3}
    body = {'revision': 2, 'measurement_key': 'inclinometer:CX01', 'date': '2026-01-03', 'rows': [
        {'深度': '1', '2026-01-03': 4}, {'深度': '10', '2026-01-03': 7}]}
    response = client.put(url + '/database', headers=user, json=body)
    assert response.status_code == 200, response.text
    saved = client.get(url + '/data', headers=user).json()['measurements']['inclinometer:CX01']
    assert saved[0] == {'深度': '1', '2026-01-01': 5, '2026-01-03': 4, '2026-01-05': 9}
    assert client.put(url + '/database', headers=user, json=body).status_code == 409
    body['revision'] = 3
    body['rows'][0]['2026-01-01'] = 999
    assert client.put(url + '/database', headers=user, json=body).status_code == 422
