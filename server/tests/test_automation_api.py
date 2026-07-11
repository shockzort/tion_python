"""REST Фазы 5: сценарии/расписания, телеметрия, смена пароля."""

from __future__ import annotations

import time
from typing import Any

from tests.conftest import (
    ClientAndApp,
    bootstrap_admin,
    wait_devices_online,
)


def make_scenario_body(devices: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "Ночной режим",
        "actions": [
            {
                "target_type": "device",
                "target_id": device["uuid"],
                "delta": {"fan_speed": 1, "sound": False},
            }
            for device in devices
        ],
    }


def test_scenario_crud_and_run(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)

    # цель должна существовать
    missing = client.post(
        "/api/scenarios",
        json={
            "name": "Битый",
            "actions": [
                {"target_type": "device", "target_id": "нет", "delta": {"power": True}}
            ],
        },
    )
    assert missing.status_code == 404

    created = client.post("/api/scenarios", json=make_scenario_body(devices))
    assert created.status_code == 201, created.text
    scenario = created.json()

    duplicate = client.post("/api/scenarios", json=make_scenario_body(devices))
    assert duplicate.status_code == 409

    listed = client.get("/api/scenarios").json()
    assert [item["id"] for item in listed] == [scenario["id"]]

    renamed = client.put(
        f"/api/scenarios/{scenario['id']}",
        json={**make_scenario_body(devices), "name": "Ночь"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Ночь"

    # запуск кнопкой: команды исполняются, ручной hold ставится (FR-23)
    run = client.post(f"/api/scenarios/{scenario['id']}/run")
    assert run.status_code == 200, run.text
    results = run.json()
    assert len(results) == len(devices)
    assert all(entry["result"]["status"] == "done" for entry in results)
    assert all(entry["result"]["result_state"]["fan_speed"] == 1 for entry in results)
    refreshed = client.get("/api/devices").json()
    assert all(device["hold_until"] is not None for device in refreshed)

    deleted = client.delete(f"/api/scenarios/{scenario['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/scenarios").json() == []
    assert client.post(f"/api/scenarios/{scenario['id']}/run").status_code == 404


def test_schedule_crud_validation(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)
    scenario = client.post("/api/scenarios", json=make_scenario_body(devices)).json()

    bad_cron = client.post(
        "/api/schedules",
        json={
            "name": "Ночь",
            "cron": "мусор тут не к месту и",
            "scenario_id": scenario["id"],
        },
    )
    assert bad_cron.status_code == 422

    both_targets = client.post(
        "/api/schedules",
        json={
            "name": "Ночь",
            "cron": "0 23 * * *",
            "scenario_id": scenario["id"],
            "actions": make_scenario_body(devices)["actions"],
        },
    )
    assert both_targets.status_code == 422

    unknown_scenario = client.post(
        "/api/schedules",
        json={"name": "Ночь", "cron": "0 23 * * *", "scenario_id": 999},
    )
    assert unknown_scenario.status_code == 404

    created = client.post(
        "/api/schedules",
        json={"name": "Ночь", "cron": "0 23 * * *", "scenario_id": scenario["id"]},
    )
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["enabled"] is True

    toggled = client.put(
        f"/api/schedules/{schedule['id']}",
        json={
            "name": "Ночь",
            "cron": "30 22 * * 1,2,3,4,5",
            "scenario_id": scenario["id"],
            "enabled": False,
        },
    )
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False
    assert toggled.json()["cron"] == "30 22 * * 1,2,3,4,5"

    # удаление сценария каскадом сносит его расписания (FK)
    assert client.delete(f"/api/scenarios/{scenario['id']}").status_code == 204
    assert client.get("/api/schedules").json() == []


def test_telemetry_endpoint(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    devices = wait_devices_online(client)
    device_uuid = devices[0]["uuid"]

    series: dict[str, Any] = {}
    for _ in range(100):  # рекордер пишет точки из событий подключения
        series = client.get(
            "/api/telemetry",
            params={"source_id": device_uuid, "metric": "fan_speed"},
        ).json()
        if series["raw"]:
            break
        time.sleep(0.05)
    assert series["raw"], "телеметрия не записала ни одной точки"
    assert series["agg"] == "raw"
    assert all(point["value"] >= 1 for point in series["raw"])

    hourly = client.get(
        "/api/telemetry",
        params={"source_id": device_uuid, "metric": "fan_speed", "agg": "hourly"},
    ).json()
    assert hourly["hourly"] == []  # час ещё не агрегирован

    invalid = client.get(
        "/api/telemetry",
        params={
            "source_id": device_uuid,
            "metric": "fan_speed",
            "from_ts": 100,
            "to_ts": 100,
        },
    )
    assert invalid.status_code == 422


def test_password_change(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    old_cookie = client.cookies["eb_session"]

    wrong = client.post(
        "/api/auth/password",
        json={"current_password": "не тот пароль", "new_password": "newpassword456"},
    )
    assert wrong.status_code == 403

    changed = client.post(
        "/api/auth/password",
        json={"current_password": "password123", "new_password": "newpassword456"},
    )
    assert changed.status_code == 200, changed.text

    # свежая cookie работает, старая сессия сброшена
    assert client.get("/api/auth/me").status_code == 200
    assert client.cookies["eb_session"] != old_cookie
    stale = client.get("/api/auth/me", cookies={"eb_session": old_cookie})
    assert stale.status_code == 401

    # логин: старый пароль недействителен, новый работает
    old_login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "password123"}
    )
    assert old_login.status_code == 401
    new_login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "newpassword456"}
    )
    assert new_login.status_code == 200
