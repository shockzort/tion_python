"""REST Фазы 6: датчики/триггеры CRUD + датчики в Яндексе."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import ClientAndApp, bootstrap_admin, wait_devices_online
from tests.test_yandex_api import linked_headers


def create_sensor(client: TestClient, **overrides: Any) -> dict[str, Any]:
    body = {"name": "CO₂ спальня", "source_key": "home/bedroom/air"}
    body.update(overrides)
    response = client.post("/api/sensors", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_sensor_crud(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)

    sensor = create_sensor(client)
    assert sensor["kind"] == "mqtt"
    assert sensor["stale"] is True  # данных ещё не было

    duplicate = client.post(
        "/api/sensors",
        json={"name": "Дубль", "source_key": "home/bedroom/air"},
    )
    assert duplicate.status_code == 409

    renamed = client.patch(
        f"/api/sensors/{sensor['id']}", json={"name": "Спальня · воздух"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Спальня · воздух"

    listed = client.get("/api/sensors").json()
    assert [item["id"] for item in listed] == [sensor["id"]]

    assert client.delete(f"/api/sensors/{sensor['id']}").status_code == 204
    assert client.get("/api/sensors").json() == []
    assert client.delete(f"/api/sensors/{sensor['id']}").status_code == 404


def test_trigger_crud_and_validation(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)
    sensor = create_sensor(client)

    base: dict[str, Any] = {
        "name": "CO₂ турбо",
        "sensor_id": sensor["id"],
        "metric": "co2",
        "op": ">",
        "threshold": 1000,
        "hysteresis": 200,
        "enter_actions": [
            {
                "target_type": "device",
                "target_id": devices[0]["uuid"],
                "delta": {"fan_speed": 6},
            }
        ],
    }

    # окно одной границей — ошибка
    invalid_window = client.post(
        "/api/triggers", json={**base, "window_start": "08:00"}
    )
    assert invalid_window.status_code == 422

    # без действий вообще — ошибка
    no_actions = client.post(
        "/api/triggers",
        json={k: v for k, v in base.items() if k != "enter_actions"},
    )
    assert no_actions.status_code == 422

    # враждебное сочетание сценария и действий на одном фронте — ошибка
    both = client.post("/api/triggers", json={**base, "enter_scenario_id": 1})
    assert both.status_code == 422

    # неизвестный датчик / сценарий — 404
    assert (
        client.post("/api/triggers", json={**base, "sensor_id": 999}).status_code == 404
    )
    assert (
        client.post(
            "/api/triggers",
            json={
                **{k: v for k, v in base.items() if k != "enter_actions"},
                "enter_scenario_id": 999,
            },
        ).status_code
        == 404
    )

    created = client.post(
        "/api/triggers",
        json={**base, "window_start": "08:00", "window_end": "22:00"},
    )
    assert created.status_code == 201, created.text
    trigger = created.json()
    assert trigger["is_active"] is False

    # правка сбрасывает защёлку и меняет поля
    updated = client.put(
        f"/api/triggers/{trigger['id']}",
        json={**base, "threshold": 900, "cooldown_s": 120},
    )
    assert updated.status_code == 200
    assert updated.json()["threshold"] == 900
    assert updated.json()["cooldown_s"] == 120
    assert updated.json()["is_active"] is False

    assert client.delete(f"/api/triggers/{trigger['id']}").status_code == 204
    assert client.get("/api/triggers").json() == []


def test_sensor_delete_cascades_triggers(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)
    sensor = create_sensor(client)
    created = client.post(
        "/api/triggers",
        json={
            "name": "T",
            "sensor_id": sensor["id"],
            "metric": "co2",
            "op": ">",
            "threshold": 1000,
            "enter_actions": [
                {
                    "target_type": "device",
                    "target_id": devices[0]["uuid"],
                    "delta": {"power": True},
                }
            ],
        },
    )
    assert created.status_code == 201
    assert client.delete(f"/api/sensors/{sensor['id']}").status_code == 204
    assert client.get("/api/triggers").json() == []


def test_yandex_exposes_sensor(client_app: ClientAndApp) -> None:
    """Датчик виден платформе: descriptor, query, отказ action (Фаза 6)."""
    client, app = client_app
    bootstrap_admin(client, app)
    wait_devices_online(client)
    sensor = create_sensor(client)
    headers = linked_headers(client)
    yandex_id = f"sensor:{sensor['id']}"

    listing = client.get("/v1.0/user/devices", headers=headers).json()
    entries = {d["id"]: d for d in listing["payload"]["devices"]}
    assert yandex_id in entries
    descriptor = entries[yandex_id]
    assert descriptor["type"] == "devices.types.sensor.climate"
    assert descriptor["capabilities"] == []
    instances = {
        p["parameters"]["instance"]: p["parameters"]["unit"]
        for p in descriptor["properties"]
    }
    assert instances == {
        "co2_level": "unit.ppm",
        "temperature": "unit.temperature.celsius",
        "humidity": "unit.percent",
    }

    # данных ещё нет — датчик недоступен
    query = client.post(
        "/v1.0/user/devices/query",
        headers=headers,
        json={"devices": [{"id": yandex_id}]},
    ).json()
    assert query["payload"]["devices"][0]["error_code"] == "DEVICE_UNREACHABLE"

    # свежее измерение — прямо в файл БД (не трогаем loop приложения)
    import json
    import sqlite3
    import time

    db_path = app.state.settings.data_dir / "easy_breezy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE sensors SET last_values = ?, last_seen_at = ? WHERE id = ?",
            (json.dumps({"co2": 850, "humidity": 41}), int(time.time()), sensor["id"]),
        )

    query_after = client.post(
        "/v1.0/user/devices/query",
        headers=headers,
        json={"devices": [{"id": yandex_id}]},
    ).json()
    states = {
        p["state"]["instance"]: p["state"]["value"]
        for p in query_after["payload"]["devices"][0]["properties"]
    }
    assert states == {"co2_level": 850.0, "humidity": 41.0}

    # действия на датчик отклоняются
    action = client.post(
        "/v1.0/user/devices/action",
        headers=headers,
        json={
            "payload": {
                "devices": [
                    {
                        "id": yandex_id,
                        "capabilities": [
                            {
                                "type": "devices.capabilities.on_off",
                                "state": {"instance": "on", "value": True},
                            }
                        ],
                    }
                ]
            }
        },
    ).json()
    result = action["payload"]["devices"][0]["capabilities"][0]["state"]
    assert result["action_result"]["status"] == "ERROR"
    assert result["action_result"]["error_code"] == "INVALID_ACTION"

    # незнакомый sensor-id
    ghost = client.post(
        "/v1.0/user/devices/query",
        headers=headers,
        json={"devices": [{"id": "sensor:999"}]},
    ).json()
    assert ghost["payload"]["devices"][0]["error_code"] == "DEVICE_NOT_FOUND"
