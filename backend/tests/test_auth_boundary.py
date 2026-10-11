def test_project_list_requires_login(client):
    assert client.get('/api/v1/projects').status_code == 401
