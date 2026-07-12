"""Интенты: таблица «фраза → интент» (≥40 кейсов) + исполнение (FR-30/31)."""

from __future__ import annotations

from typing import Any

import pytest

from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.integrations.intents.model import (
    Catalog,
    CatalogDevice,
    CatalogScenario,
    CatalogSensor,
    Clarification,
    DeviceCommandIntent,
    ScenarioIntent,
    StatusIntent,
)
from easy_breezy.integrations.intents.rules import parse
from easy_breezy.integrations.intents.service import IntentService
from easy_breezy.storage.repos import RoomRepo, ScenarioRepo
from tests.conftest import CoreEnv, wait_for_condition

BEDROOM = CatalogDevice("dev-bed", "Спальня", "Спальня")
KIDS = CatalogDevice("dev-kids", "Детская", "Детская")
LIVING = CatalogDevice("dev-liv", "Гостиная", "Гостиная")

CATALOG = Catalog(
    devices=[BEDROOM, KIDS, LIVING],
    scenarios=[
        CatalogScenario(1, "Ночной режим"),
        CatalogScenario(2, "Проветривание"),
    ],
    sensors=[
        CatalogSensor(
            1, "MagicAir", "Гостиная", values={"co2": 675, "humidity": 61}, stale=False
        ),
        CatalogSensor(2, "Модуль CO₂+", "Детская", values={"co2": 811}, stale=False),
    ],
)

SINGLE = Catalog(devices=[BEDROOM], scenarios=[], sensors=[])


def cmd(outcome: Any) -> DeviceCommandIntent:
    assert isinstance(outcome, DeviceCommandIntent), outcome
    return outcome


# --- команды: скорость -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "fan"),
    [
        ("поставь скорость три в спальне", 3),
        ("скорость 5 в детской", 5),
        ("включи бризер в спальне на тройку", 3),
        ("бризер в гостиной на двойку", 2),
        ("поставь четвёрку в спальне", 4),
        ("скорость шесть в спальне", 6),
        ("сделай единичку в детской", 1),
        ("поставь на максимум в спальне", 6),
    ],
)
def test_fan_speed_phrases(text: str, fan: int) -> None:
    intent = cmd(parse(text, CATALOG))
    assert intent.delta_payload["fan_speed"] == fan


# --- команды: питание --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "uuids", "power"),
    [
        ("включи бризер в спальне", ["dev-bed"], True),
        ("выключи бризер в детской", ["dev-kids"], False),
        ("выключи все бризеры", ["dev-bed", "dev-kids", "dev-liv"], False),
        ("включи все", ["dev-bed", "dev-kids", "dev-liv"], True),
        ("вруби бризер в гостиной", ["dev-liv"], True),
        ("отключи бризер в спальне", ["dev-bed"], False),
        ("выключи везде", ["dev-bed", "dev-kids", "dev-liv"], False),
    ],
)
def test_power_phrases(text: str, uuids: list[str], power: bool) -> None:
    intent = cmd(parse(text, CATALOG))
    assert intent.device_uuids == uuids
    assert intent.delta_payload["power"] is power


# --- команды: нагрев и температура --------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("включи нагрев в спальне", {"heater": True}),
        ("выключи обогрев в детской", {"heater": False}),
        ("сделай 22 градуса в спальне", {"heater_temp": 22}),
        ("нагрей до 25 градусов в гостиной", {"heater_temp": 25, "heater": True}),
        ("поставь температуру 18 в спальне", {"heater_temp": 18}),
    ],
)
def test_heater_phrases(text: str, expected: dict[str, Any]) -> None:
    intent = cmd(parse(text, CATALOG))
    for field, value in expected.items():
        assert intent.delta_payload[field] == value, intent.delta_payload


# --- команды: звук, подсветка, режим -------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("выключи звук в спальне", {"sound": False}),
        ("включи звук в детской", {"sound": True}),
        ("выключи подсветку в гостиной", {"light": False}),
        ("включи свет на бризере в спальне", {"light": True}),
        ("включи рециркуляцию в спальне", {"mode": "recirculation"}),
        ("переключи на приток в детской", {"mode": "outside"}),
    ],
)
def test_toggle_phrases(text: str, expected: dict[str, Any]) -> None:
    intent = cmd(parse(text, CATALOG))
    for field, value in expected.items():
        assert intent.delta_payload[field] == value, intent.delta_payload
    # «выключи звук» не трогает питание
    if "sound" in expected or "light" in expected:
        assert "power" not in intent.delta_payload


def test_combined_phrase() -> None:
    intent = cmd(
        parse("включи бризер в спальне на тройку и сделай 22 градуса", CATALOG)
    )
    payload = intent.delta_payload
    assert payload["fan_speed"] == 3
    assert payload["heater_temp"] == 22
    assert payload["power"] is True


def test_heater_on_does_not_power_on() -> None:
    """«Включи нагрев» трогает только нагрев — питание не подразумевается."""
    payload = cmd(parse("включи нагрев в спальне", CATALOG)).delta_payload
    assert payload == {"heater": True}


# --- сценарии -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "scenario_id"),
    [
        ("ночной режим", 1),
        ("включи ночной режим", 1),
        ("запусти проветривание", 2),
        ("активируй сценарий проветривание", 2),
    ],
)
def test_scenario_phrases(text: str, scenario_id: int) -> None:
    outcome = parse(text, CATALOG)
    assert isinstance(outcome, ScenarioIntent), outcome
    assert outcome.scenario_id == scenario_id


# --- статус ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "metric", "room"),
    [
        ("какой co2 в детской", "co2", "Детская"),
        ("какая температура в спальне", "temperature", "Спальня"),
        ("сколько углекислого газа в гостиной", "co2", "Гостиная"),
        ("какая влажность", "humidity", None),
        ("покажи co2", "co2", None),
        ("какой статус бризера в спальне", None, "Спальня"),
    ],
)
def test_status_phrases(text: str, metric: str | None, room: str | None) -> None:
    outcome = parse(text, CATALOG)
    assert isinstance(outcome, StatusIntent), outcome
    assert outcome.metric == metric
    assert outcome.room == room


# --- неоднозначность и мусор ----------------------------------------------------


def test_ambiguous_target_asks_clarification() -> None:
    """Несколько бризеров, цель не названа — уточнение, не действие (FR-31)."""
    outcome = parse("поставь скорость три", CATALOG)
    assert isinstance(outcome, Clarification)
    assert "Спальня" in outcome.reply


def test_single_device_needs_no_target() -> None:
    intent = cmd(parse("включи бризер", SINGLE))
    assert intent.device_uuids == ["dev-bed"]


@pytest.mark.parametrize(
    "text",
    [
        "расскажи анекдот",
        "закажи пиццу",
        "",
        "апрлыор длоыр",
        "включи чайник",  # действие есть, но цель не бризер — уточнение/None
    ],
)
def test_garbage_not_executed(text: str) -> None:
    outcome = parse(text, CATALOG)
    assert outcome is None or isinstance(outcome, Clarification)


def test_room_morphology() -> None:
    """Формы «в спальне/в спальню» матчатся к комнате «Спальня»."""
    assert cmd(parse("включи в спальне", CATALOG)).device_uuids == ["dev-bed"]
    assert cmd(parse("выключи бризер в спальню", CATALOG)).device_uuids == ["dev-bed"]
    assert cmd(parse("включи в гостиной", CATALOG)).device_uuids == ["dev-liv"]


# --- сервис на фейках ------------------------------------------------------------


async def intent_env(core: CoreEnv) -> IntentService:
    from easy_breezy.automation.scenarios import ScenarioService

    return IntentService(
        core.db,
        core.registry,
        core.cache,
        core.bus,
        ScenarioService(core.db, core.bus),
        command_wait_seconds=5.0,
    )


async def add_device(core: CoreEnv, mac: str, name: str, room: str) -> str:
    device = await core.registry.add_device(mac=mac, name=name)
    async with core.db.session() as session:
        record = await RoomRepo(session).create(room)
        stored = await session.get(type(device), device.uuid)
        assert stored is not None
        stored.room_id = record.id
    await wait_for_condition(
        lambda: core.registry.connection(device.uuid) is ConnectionState.ONLINE
    )
    return device.uuid


async def test_service_executes_command_and_places_hold(core: CoreEnv) -> None:
    service = await intent_env(core)
    device_uuid = await add_device(core, "FA:KE:00:00:00:01", "Бризер", "Спальня")

    result = await service.execute("поставь скорость три в спальне")
    assert result.executed
    assert result.intent == "device_command"
    assert result.reply.startswith("Готово")
    assert "Спальня" in result.reply
    # интент — ручное управление: hold стоит (FR-23)
    assert core.holds.is_held(device_uuid)


async def test_service_runs_scenario(core: CoreEnv) -> None:
    service = await intent_env(core)
    device_uuid = await add_device(core, "FA:KE:00:00:00:01", "Бризер", "Спальня")
    async with core.db.session() as session:
        await ScenarioRepo(session).create(
            name="Ночной режим",
            actions=[
                {
                    "target_type": "device",
                    "target_id": device_uuid,
                    "delta": {"fan_speed": 1},
                }
            ],
        )
    result = await service.execute("включи ночной режим")
    assert result.executed
    assert result.intent == "scenario"
    assert "Ночной режим" in result.reply


async def test_service_status_and_help(core: CoreEnv) -> None:
    service = await intent_env(core)
    await add_device(core, "FA:KE:00:00:00:01", "Бризер", "Спальня")

    status = await service.execute("какой статус бризера в спальне")
    assert not status.executed
    assert status.intent == "status"
    assert "Бризер" in status.reply
    assert "скорость" in status.reply

    nothing = await service.execute("расскажи анекдот")
    assert not nothing.executed
    assert "Примеры" in nothing.reply


async def test_service_unreachable_device(core: CoreEnv) -> None:
    """Устройство зарегистрировано, но офлайн — честный отказ."""
    core.fleet.connect_failures["FA:KE:00:00:00:09"] = 10**6
    service = await intent_env(core)
    device = await core.registry.add_device(mac="FA:KE:00:00:00:09", name="Подвал")
    assert device is not None
    result = await service.execute("включи бризер")
    assert not result.executed
    assert result.reply.startswith("Не получилось")
