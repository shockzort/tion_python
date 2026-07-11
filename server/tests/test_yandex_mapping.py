"""Маппинг S4 ↔ Умный дом: contract-golden и разбор action в дельту."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from easy_breezy.ble.fake import DEFAULT_STATE
from easy_breezy.core.model import StateDelta, state_to_dict
from easy_breezy.integrations.yandex import mapping

GOLDEN = Path(__file__).parent / "golden"


def test_device_descriptor_matches_golden() -> None:
    """Контракт /user/devices зафиксирован golden-файлом (не менять руками)."""
    descriptor = mapping.device_descriptor("dev-uuid-1", "Спальня", "Спальня (комната)")
    golden = json.loads(
        (GOLDEN / "yandex_device_descriptor.json").read_text(encoding="utf-8")
    )
    assert descriptor == golden


def test_descriptor_without_room() -> None:
    descriptor = mapping.device_descriptor("d1", "Кухня", None)
    assert "room" not in descriptor


def test_capability_states_values() -> None:
    state = state_to_dict(DEFAULT_STATE)  # power on, fan 2, heater off, sound on
    states = {
        (item["type"], item["state"]["instance"]): item["state"]["value"]
        for item in mapping.capability_states(state)
    }
    assert states[(mapping.CAP_ON_OFF, "on")] is True
    assert states[(mapping.CAP_MODE, "fan_speed")] == "two"
    assert states[(mapping.CAP_MODE, "thermostat")] == "fan_only"
    assert states[(mapping.CAP_RANGE, "temperature")] == 20
    assert states[(mapping.CAP_TOGGLE, "mute")] is False  # звук вкл → mute выкл
    assert states[(mapping.CAP_TOGGLE, "backlight")] is False

    properties = mapping.property_states(state)
    assert properties[0]["state"] == {"instance": "temperature", "value": 18.0}


def _cap(cap_type: str, instance: str, value: object, **extra: object) -> dict:
    return {"type": cap_type, "state": {"instance": instance, "value": value, **extra}}


def test_actions_to_delta_full_set() -> None:
    delta = mapping.actions_to_delta(
        [
            _cap(mapping.CAP_ON_OFF, "on", True),
            _cap(mapping.CAP_MODE, "fan_speed", "three"),
            _cap(mapping.CAP_MODE, "thermostat", "heat"),
            _cap(mapping.CAP_RANGE, "temperature", 22),
            _cap(mapping.CAP_TOGGLE, "mute", True),
            _cap(mapping.CAP_TOGGLE, "backlight", False),
        ],
        current=None,
    )
    assert delta == StateDelta(
        power=True,
        fan_speed=3,
        heater=True,
        heater_temp=22,
        sound=False,  # mute=True → звук выкл
        light=False,
    )
    assert delta.mode is None  # рециркуляцию Алиса не трогает


def test_range_relative_and_clamping() -> None:
    current = state_to_dict(DEFAULT_STATE)  # heater_temp 20
    plus = mapping.actions_to_delta(
        [_cap(mapping.CAP_RANGE, "temperature", 2, relative=True)], current
    )
    assert plus.heater_temp == 22

    clamped = mapping.actions_to_delta(
        [_cap(mapping.CAP_RANGE, "temperature", 99)], None
    )
    assert clamped.heater_temp == 30  # верхняя граница диапазона

    with pytest.raises(mapping.ActionError) as excinfo:
        mapping.actions_to_delta(
            [_cap(mapping.CAP_RANGE, "temperature", 2, relative=True)], None
        )
    assert excinfo.value.error_code == mapping.ERROR_INVALID_VALUE


def test_invalid_actions_rejected() -> None:
    with pytest.raises(mapping.ActionError) as bad_speed:
        mapping.actions_to_delta([_cap(mapping.CAP_MODE, "fan_speed", "turbo")], None)
    assert bad_speed.value.error_code == mapping.ERROR_INVALID_VALUE

    with pytest.raises(mapping.ActionError) as unknown:
        mapping.actions_to_delta(
            [_cap("devices.capabilities.color_setting", "rgb", 255)], None
        )
    assert unknown.value.error_code == mapping.ERROR_INVALID_ACTION


def test_fan_mode_roundtrip() -> None:
    """Скорости 1–6 ↔ one…six без потерь (голосовое «скорость три»)."""
    for speed, word in enumerate(mapping.FAN_MODES, start=1):
        delta = mapping.actions_to_delta(
            [_cap(mapping.CAP_MODE, "fan_speed", word)], None
        )
        assert delta.fan_speed == speed
        state = state_to_dict(dataclasses.replace(DEFAULT_STATE, fan_speed=speed))
        values = {
            item["state"]["instance"]: item["state"]["value"]
            for item in mapping.capability_states(state)
        }
        assert values["fan_speed"] == word
