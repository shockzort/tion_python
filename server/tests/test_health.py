"""Смоук-тест каркаса: приложение поднимается, health отвечает."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from easy_breezy import __version__
from easy_breezy.app import create_app
from tests.conftest import test_settings


def test_health_ok(tmp_path: Path) -> None:
    app = create_app(test_settings(log_level="WARNING", data_dir=tmp_path))
    with TestClient(app) as client:
        response = client.get("/api/system/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["uptime_seconds"] >= 0
