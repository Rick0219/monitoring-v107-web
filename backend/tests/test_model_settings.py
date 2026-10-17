from test_projects import P, new_project


def test_project_model_settings_are_scoped_and_api_key_is_masked(client, accounts):
    admin, (owner, owner_headers), (member, member_headers) = accounts
    project = new_project(client, owner_headers)
    url = P + "/" + project["id"]
    assert client.post(
        url + "/members",
        headers=owner_headers,
        json={"email": member["email"]},
    ).status_code == 200

    initial = client.get(url + "/model-settings", headers=owner_headers)
    assert initial.status_code == 200, initial.text
    assert initial.json() == {
        "base_url": "",
        "model": "",
        "timeout": 90,
        "api_key_configured": False,
        "editable": True,
        "source": "server",
        "revision": 1,
    }

    saved = client.put(
        url + "/model-settings",
        headers=owner_headers,
        json={
            "revision": 1,
            "base_url": "https://ark.example.test/v1",
            "model": "endpoint-demo",
            "api_key": "secret-project-key",
            "timeout": 120,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    result = client.get(url + "/model-settings", headers=member_headers)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "base_url": "https://ark.example.test/v1",
        "model": "endpoint-demo",
        "timeout": 120,
        "api_key_configured": True,
        "editable": False,
        "source": "project",
        "revision": 2,
    }
    assert "secret-project-key" not in result.text
    denied = client.put(
        url + "/model-settings",
        headers=member_headers,
        json={
            "revision": 2,
            "base_url": "https://other.example.test/v1",
            "model": "other-model",
            "timeout": 90,
        },
    )
    assert denied.status_code == 403
    assert client.get(url + "/model-settings", headers=admin).status_code == 200


def test_project_model_settings_reject_stale_revision(client, accounts):
    _, (owner, owner_headers), _ = accounts
    project = new_project(client, owner_headers)
    url = P + "/" + project["id"]
    body = {
        "revision": 1,
        "base_url": "https://ark.example.test/v1",
        "model": "endpoint-demo",
        "api_key": "secret-project-key",
        "timeout": 90,
    }
    assert client.put(url + "/model-settings", headers=owner_headers, json=body).status_code == 200
    assert client.put(url + "/model-settings", headers=owner_headers, json=body).status_code == 409
