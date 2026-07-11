"""Интеграция API: полный цикл на dev-режиме EB_FAKE_DEVICES (без железа).

Фикстура ``client_app`` (conftest) поднимает настоящий lifespan: миграции,
фейковые бризеры, супервизоры, командную шину и WS-хаб — как боевой сервис.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from easy_breezy.app import create_app
from tests.conftest import (
    ClientAndApp,
    bootstrap_admin,
    container_of,
    test_settings,
    wait_devices_online,
)


def test_requires_auth(client_app: ClientAndApp) -> None:
    client, _ = client_app
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/system/health").status_code == 200  # health открыт


def test_setup_login_me(client_app: ClientAndApp) -> None:
    client, app = client_app
    setup_token = container_of(app).auth.setup_token
    assert setup_token is not None
    assert client.get("/api/auth/status").json() == {"setup_required": True}

    bad = client.post(
        "/api/auth/setup",
        json={"setup_token": "мимо", "username": "admin", "password": "password123"},
    )
    assert bad.status_code == 403

    bootstrap_admin(client, app)
    assert client.get("/api/auth/status").json() == {"setup_required": False}
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    wrong = client.post(
        "/api/auth/login", json={"username": "admin", "password": "мимо"}
    )
    assert wrong.status_code == 401

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_fake_devices_online_and_stats(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)
    assert len(devices) == 3
    assert {d["mac"] for d in devices} == {
        "FA:KE:00:00:00:01",
        "FA:KE:00:00:00:02",
        "FA:KE:00:00:00:03",
    }
    assert all(d["state"] is not None for d in devices)

    stats = client.get("/api/system/stats").json()
    assert stats["devices_total"] == 3
    assert stats["devices_online"] == 3


def test_command_ws_event_and_dedup(client_app: ClientAndApp) -> None:
    """Сквозной путь плана §14: «POST command → WS event» на fake."""
    client, app = client_app
    bootstrap_admin(client, app)
    device = wait_devices_online(client)[0]

    token_response = client.post("/api/tokens", json={"name": "тест"})
    assert token_response.status_code == 201
    api_token = token_response.json()["token"]

    with client.websocket_connect(f"/api/ws?token={api_token}") as ws:
        response = client.post(
            f"/api/devices/{device['uuid']}/command",
            json={"fan_speed": 5, "heater": True},
            headers={"Idempotency-Key": "ui:e2e-1"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "done"
        assert result["result_state"]["fan_speed"] == 5
        assert result["result_state"]["heater"] is True

        seen_topics: set[str] = set()
        finished: dict[str, Any] | None = None
        for _ in range(20):
            message = ws.receive_json()
            seen_topics.add(message["topic"])
            if message["topic"] == "command.finished":
                finished = message["data"]
                break
        assert finished is not None, f"только {seen_topics}"
        assert finished["command_id"] == result["command_id"]
        assert finished["status"] == "done"
        assert "device.state_changed" in seen_topics

    # дедуп: тот же Idempotency-Key возвращает тот же итог без исполнения
    replay = client.post(
        f"/api/devices/{device['uuid']}/command",
        json={"fan_speed": 5, "heater": True},
        headers={"Idempotency-Key": "ui:e2e-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["command_id"] == result["command_id"]

    # ручная команда поставила hold; снятие — кнопка «вернуть автоматику»
    view = client.get(f"/api/devices/{device['uuid']}").json()
    assert view["hold_until"] is not None
    assert client.delete(f"/api/devices/{device['uuid']}/hold").status_code == 204
    view = client.get(f"/api/devices/{device['uuid']}").json()
    assert view["hold_until"] is None


def test_command_validation_and_404(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    device = wait_devices_online(client)[0]

    empty = client.post(f"/api/devices/{device['uuid']}/command", json={})
    assert empty.status_code == 422

    out_of_range = client.post(
        f"/api/devices/{device['uuid']}/command", json={"fan_speed": 9}
    )
    assert out_of_range.status_code == 422

    ghost = client.post(
        "/api/devices/00000000000000000000000000000000/command",
        json={"fan_speed": 1},
    )
    assert ghost.status_code == 404


def test_ws_rejects_unauthenticated(client_app: ClientAndApp) -> None:
    client, _ = client_app
    with client.websocket_connect("/api/ws") as ws:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_text()
        assert excinfo.value.code == 4401


def test_groups_fanout_command(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)

    group = client.post("/api/groups", json={"name": "Все"})
    assert group.status_code == 201
    group_id = group.json()["id"]

    members = client.put(
        f"/api/groups/{group_id}/members",
        json={"device_uuids": [d["uuid"] for d in devices]},
    )
    assert members.status_code == 200
    assert len(members.json()["device_uuids"]) == 3

    fanout = client.post(f"/api/groups/{group_id}/command", json={"power": False})
    assert fanout.status_code == 200
    entries = fanout.json()
    assert len(entries) == 3
    for entry in entries:
        assert entry["rejected"] is None
        assert entry["result"]["status"] == "done"
        assert entry["result"]["result_state"]["power"] is False


def test_device_crud_rooms(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)
    target = devices[0]

    room = client.post("/api/rooms", json={"name": "Спальня"})
    assert room.status_code == 201
    room_id = room.json()["id"]

    patched = client.patch(
        f"/api/devices/{target['uuid']}",
        json={"name": "У окна", "room_id": room_id},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "У окна"
    assert patched.json()["room_id"] == room_id

    created = client.post(
        "/api/devices", json={"mac": "aa:bb:cc:dd:ee:01", "name": "Новый"}
    )
    assert created.status_code == 201
    assert created.json()["mac"] == "AA:BB:CC:DD:EE:01"  # нормализация
    dup = client.post(
        "/api/devices", json={"mac": "AA:BB:CC:DD:EE:01", "name": "Дубль"}
    )
    assert dup.status_code == 409
    bad_mac = client.post(
        "/api/devices", json={"mac": "FA:KE:00:00:00:09", "name": "Не hex"}
    )
    assert bad_mac.status_code == 422

    assert client.delete(f"/api/devices/{target['uuid']}").status_code == 204
    remaining = {d["uuid"] for d in client.get("/api/devices").json()}
    assert target["uuid"] not in remaining
    assert created.json()["uuid"] in remaining
    assert client.delete(f"/api/devices/{target['uuid']}").status_code == 404

    journal = client.get("/api/commands", params={"limit": 10})
    assert journal.status_code == 200


def test_spa_static_with_fallback(tmp_path: Path) -> None:
    """Собранный UI раздаётся сервером; клиентские маршруты → index.html."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>EB SPA</html>", encoding="utf-8")
    (dist / "app.js").write_text("console.log(1)", encoding="utf-8")

    app = create_app(
        test_settings(
            log_level="WARNING",
            data_dir=tmp_path / "data",
            fake_devices=0,
            ui_dist=dist,
        )
    )
    with TestClient(app) as client:
        assert "EB SPA" in client.get("/").text
        assert client.get("/app.js").text == "console.log(1)"
        # клиентский маршрут SPA отдаёт index, а не 404
        assert "EB SPA" in client.get("/devices").text
        # API живёт своей жизнью и не перехватывается статикой
        assert client.get("/api/system/health").status_code == 200
        assert client.get("/api/devices").status_code == 401
        # зарезервированные префиксы не маскируются под SPA (честный 404)
        assert client.get("/api/no-such-route").status_code == 404
        assert client.get("/v1.0/v1.0/user/devices").status_code == 404
        assert client.request("HEAD", "/v1.0/v1.0").status_code == 404
        assert client.get("/oauth/nonexistent").status_code == 404


def test_pairing_wizard_flow(client_app: ClientAndApp) -> None:
    """Мастер сопряжения на фейках: скан → pair → устройство в реестре."""
    client, app = client_app
    bootstrap_admin(client, app)
    wait_devices_online(client)

    found = client.post("/api/pairing/scan", json={"duration": 3}).json()
    assert len(found) == 2  # пул несопряжённых фейков за пределами сида
    assert all(not item["registered"] for item in found)
    assert all(item["pairing_mode"] for item in found)
    candidate = found[0]

    with client.websocket_connect(f"/api/ws?token={_api_token(client)}") as ws:
        paired = client.post(
            "/api/pairing/pair",
            json={"mac": candidate["mac"], "name": "Кухня"},
        )
        assert paired.status_code == 201, paired.text
        assert paired.json()["name"] == "Кухня"

        stages = []
        for _ in range(10):
            message = ws.receive_json()
            if message["topic"] == "pairing.progress":
                stages.append(message["data"]["stage"])
                if message["data"]["stage"] == "done":
                    break
        assert stages == ["pairing", "registering", "done"]

    # повторное сопряжение того же MAC — конфликт
    again = client.post(
        "/api/pairing/pair", json={"mac": candidate["mac"], "name": "Дубль"}
    )
    assert again.status_code == 409

    # новый бризер виден в списке и выходит в online
    devices = wait_devices_online(client)
    assert len(devices) == 4
    rescan = client.post("/api/pairing/scan", json={"duration": 3}).json()
    assert any(item["registered"] for item in rescan)


def _api_token(client: TestClient) -> str:
    response = client.post("/api/tokens", json={"name": "ws"})
    assert response.status_code == 201
    token: str = response.json()["token"]
    return token
