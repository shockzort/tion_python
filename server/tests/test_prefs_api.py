"""REST /api/prefs: per-user key/value JSON для настроек UI."""

from __future__ import annotations

from tests.conftest import ClientAndApp, bootstrap_admin


def test_prefs_requires_auth(client_app: ClientAndApp) -> None:
    client, _app = client_app
    # до логина cookie нет — 401
    assert client.get("/api/prefs/charts").status_code == 401
    assert client.put("/api/prefs/charts", json={"value": 1}).status_code == 401


def test_prefs_roundtrip_and_overwrite(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)

    # отсутствующий ключ — value=null, не 404 (UI не хочет error-путь)
    missing = client.get("/api/prefs/charts")
    assert missing.status_code == 200
    assert missing.json() == {"key": "charts", "value": None}

    panels = [{"id": "p1", "source": "sensor:1", "metric": "co2", "period": "24h"}]
    stored = client.put("/api/prefs/charts", json={"value": panels})
    assert stored.status_code == 200, stored.text
    assert stored.json() == {"key": "charts", "value": panels}
    assert client.get("/api/prefs/charts").json()["value"] == panels

    # перезапись
    updated = client.put("/api/prefs/charts", json={"value": []})
    assert updated.status_code == 200
    assert client.get("/api/prefs/charts").json()["value"] == []

    # null-значение допустимо (сброс)
    cleared = client.put("/api/prefs/charts", json={"value": None})
    assert cleared.status_code == 200
    assert client.get("/api/prefs/charts").json()["value"] is None


def test_prefs_validation(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)

    # ключ вне [a-z0-9_-]{1,50} — 422
    assert client.get("/api/prefs/ЧартЫ").status_code == 422
    assert client.put("/api/prefs/UPPER", json={"value": 1}).status_code == 422
    assert client.put(f"/api/prefs/{'x' * 51}", json={"value": 1}).status_code == 422

    # значение больше 16 КиБ — 413
    huge = client.put("/api/prefs/charts", json={"value": "x" * 17_000})
    assert huge.status_code == 413
