from urllib.parse import urlsplit, parse_qs
from test_projects import P
from test_charts import populate


def test_chart_link_is_authenticated_and_scoped(client, accounts, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://monitor.example.com")
    _, (_, user), (_, other) = accounts
    url = populate(client, user)
    params = {"measurement_key": "level:沉降"}
    assert client.get(url + "/chart-link", params=params).status_code == 401
    assert client.get(url + "/chart-link", params=params, headers=other).status_code == 404
    response = client.get(url + "/chart-link", params=params, headers=user)
    assert response.status_code == 200, response.text
    value = response.json()
    parsed = urlsplit(value["url"])
    assert parsed.netloc == "monitor.example.com"
    assert parsed.path == "/charts/" + url.rsplit("/", 1)[-1]
    assert parse_qs(parsed.query) == {"measurement": ["level:沉降"]}
    assert "token" not in value["url"]
    assert client.get(url + "/chart-link", params={"measurement_key": "level:不存在"}, headers=user).status_code == 422


def test_local_chart_link_uses_lan_address_and_actual_port(client, accounts, monkeypatch):
    from app.core.config import settings
    from app import chart_links
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "WEB_BIND_HOST", "0.0.0.0")
    monkeypatch.setattr(chart_links, "lan_addresses", lambda: ["192.168.1.4"])
    _, (_, user), _ = accounts
    url = populate(client, user)
    response = client.get("http://127.0.0.1:8009" + url + "/chart-link", params={"measurement_key": "level:沉降"}, headers=user)
    assert response.status_code == 200
    assert response.json()["url"].startswith("http://192.168.1.4:8009/")
    assert response.json()["network"] == "lan"
    monkeypatch.setattr(settings, "WEB_BIND_HOST", "127.0.0.1")
    response = client.get("http://127.0.0.1:8009" + url + "/chart-link", params={"measurement_key": "level:沉降"}, headers=user)
    assert response.json()["url"] is None
    assert response.json()["network"] == "local_only"


def test_public_origin_rejects_credentials_and_non_web_urls():
    import pytest
    from app.core.config import Settings
    for value in ("javascript:alert(1)", "https://user:password@example.com", "https://example.com/?token=secret", "https://example.com/app"):
        with pytest.raises(ValueError):
            Settings(PUBLIC_BASE_URL=value)
