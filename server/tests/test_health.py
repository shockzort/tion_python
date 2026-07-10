"""Смоук-тест каркаса: приложение поднимается, health отвечает."""

from __future__ import annotations

from fastapi.testclient import TestClient

from easy_breezy import __version__
from easy_breezy.app import create_app
from easy_breezy.config import Settings


def test_health_ok() -> None:
    app = create_app(Settings(log_level="WARNING"))
    with TestClient(app) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["uptime_seconds"] >= 0
