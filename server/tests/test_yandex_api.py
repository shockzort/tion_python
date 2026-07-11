"""Эндпоинты /v1.0: авторизация Bearer, devices/query/action/unlink на фейках."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import ClientAndApp, bootstrap_admin, wait_devices_online
from tests.test_oauth import link_account


def linked_headers(client: TestClient) -> dict[str, str]:
    tokens = link_account(client)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_ping_is_public(client_app: ClientAndApp) -> None:
    client, _ = client_app
    assert client.head("/v1.0/").status_code == 200
    assert client.head("/v1.0").status_code == 200


def test_endpoints_require_bearer(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    assert client.get("/v1.0/user/devices").status_code == 401
    assert (
        client.get(
            "/v1.0/user/devices", headers={"Authorization": "Bearer wrong-token"}
        ).status_code
        == 401
    )
    # сессия-cookie админа НЕ подходит для платформенных путей
    assert client.post("/v1.0/user/unlink").status_code == 401


def test_devices_list_and_query(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)
    headers = linked_headers(client)

    listing = client.get(
        "/v1.0/user/devices",
        headers={**headers, "X-Request-Id": "req-list"},
    ).json()
    assert listing["request_id"] == "req-list"
    payload_devices = listing["payload"]["devices"]
    assert len(payload_devices) == 3
    assert {d["id"] for d in payload_devices} == {d["uuid"] for d in devices}
    first = payload_devices[0]
    assert first["type"] == "devices.types.ventilation"
    capability_types = {c["type"] for c in first["capabilities"]}
    assert "devices.capabilities.on_off" in capability_types

    query = client.post(
        "/v1.0/user/devices/query",
        headers=headers,
        json={
            "devices": [{"id": devices[0]["uuid"]}, {"id": "неизвестное"}],
        },
    ).json()
    known, unknown = query["payload"]["devices"]
    states = {
        item["state"]["instance"]: item["state"]["value"]
        for item in known["capabilities"]
    }
    assert states["on"] is True
    assert states["fan_speed"] == "two"
    assert unknown == {"id": "неизвестное", "error_code": "DEVICE_NOT_FOUND"}


def test_action_applies_and_deduplicates(client_app: ClientAndApp) -> None:
    """Голосовой путь: все капабилити → одна команда; ретрай Алисы дедупится."""
    client, app = client_app
    bootstrap_admin(client, app)
    device = wait_devices_online(client)[0]
    headers = linked_headers(client)

    action: dict[str, Any] = {
        "payload": {
            "devices": [
                {
                    "id": device["uuid"],
                    "capabilities": [
                        {
                            "type": "devices.capabilities.mode",
                            "state": {"instance": "fan_speed", "value": "three"},
                        },
                        {
                            "type": "devices.capabilities.mode",
                            "state": {"instance": "thermostat", "value": "heat"},
                        },
                        {
                            "type": "devices.capabilities.range",
                            "state": {"instance": "temperature", "value": 22},
                        },
                    ],
                }
            ]
        }
    }
    response = client.post(
        "/v1.0/user/devices/action",
        headers={**headers, "X-Request-Id": "req-act-1"},
        json=action,
    ).json()
    assert response["request_id"] == "req-act-1"
    results = response["payload"]["devices"][0]["capabilities"]
    assert len(results) == 3
    assert all(item["state"]["action_result"] == {"status": "DONE"} for item in results)

    # состояние применилось (истина устройства через REST-кэш)
    view = client.get(f"/api/devices/{device['uuid']}").json()
    assert view["state"]["fan_speed"] == 3
    assert view["state"]["heater"] is True
    assert view["state"]["heater_temp"] == 22

    # ретрай того же X-Request-Id → дедуп: в журнале одна команда
    replay = client.post(
        "/v1.0/user/devices/action",
        headers={**headers, "X-Request-Id": "req-act-1"},
        json=action,
    ).json()
    assert (
        replay["payload"]["devices"][0]["capabilities"][0]["state"]["action_result"][
            "status"
        ]
        == "DONE"
    )
    journal = client.get("/api/commands", params={"device_uuid": device["uuid"]}).json()
    yandex_commands = [c for c in journal if c["source"] == "yandex"]
    assert len(yandex_commands) == 1

    # Алиса == ручное управление: hold поставлен (ADR-0005)
    assert client.get(f"/api/devices/{device['uuid']}").json()["hold_until"]


def test_action_error_paths(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    device = wait_devices_online(client)[0]
    headers = linked_headers(client)

    def act(device_id: str, capabilities: list[dict[str, Any]]) -> dict[str, Any]:
        response = client.post(
            "/v1.0/user/devices/action",
            headers=headers,
            json={
                "payload": {
                    "devices": [{"id": device_id, "capabilities": capabilities}]
                }
            },
        ).json()
        result: dict[str, Any] = response["payload"]["devices"][0]
        return result

    ghost = act(
        "нет-такого",
        [
            {
                "type": "devices.capabilities.on_off",
                "state": {"instance": "on", "value": True},
            }
        ],
    )
    assert (
        ghost["capabilities"][0]["state"]["action_result"]["error_code"]
        == "DEVICE_NOT_FOUND"
    )

    invalid = act(
        device["uuid"],
        [
            {
                "type": "devices.capabilities.mode",
                "state": {"instance": "fan_speed", "value": "turbo"},
            }
        ],
    )
    assert (
        invalid["capabilities"][0]["state"]["action_result"]["error_code"]
        == "INVALID_VALUE"
    )


def test_unlink_revokes_access(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    wait_devices_online(client)
    headers = linked_headers(client)

    assert client.get("/v1.0/user/devices", headers=headers).status_code == 200
    unlink = client.post("/v1.0/user/unlink", headers=headers)
    assert unlink.status_code == 200
    assert "request_id" in unlink.json()
    # токен погашен — платформа больше не ходит
    assert client.get("/v1.0/user/devices", headers=headers).status_code == 401
