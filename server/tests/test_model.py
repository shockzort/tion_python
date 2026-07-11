"""Дельта состояния: мерж, сериализация журнала, валидация."""

from __future__ import annotations

import pytest

from easy_breezy.ble.fake import DEFAULT_STATE
from easy_breezy.ble.protocol.s4 import Mode
from easy_breezy.core.model import DeltaError, StateDelta, state_to_dict


def test_apply_merges_over_actual_state() -> None:
    delta = StateDelta(fan_speed=5, heater=True)
    merged = delta.apply_to(DEFAULT_STATE)
    assert merged.fan_speed == 5
    assert merged.heater is True
    # незаданные поля не тронуты
    assert merged.power == DEFAULT_STATE.power
    assert merged.mode == DEFAULT_STATE.mode
    assert merged.in_temp == DEFAULT_STATE.in_temp


def test_payload_roundtrip() -> None:
    delta = StateDelta(power=True, mode=Mode.RECIRCULATION, heater_temp=22)
    payload = delta.to_payload()
    assert payload == {"power": True, "mode": "recirculation", "heater_temp": 22}
    assert StateDelta.from_payload(payload) == delta


def test_empty_delta() -> None:
    assert StateDelta().is_empty()
    assert not StateDelta(fan_speed=1).is_empty()
    assert StateDelta.from_payload({}).is_empty()


def test_from_payload_rejects_unknown_fields() -> None:
    with pytest.raises(DeltaError, match="неизвестные поля"):
        StateDelta.from_payload({"fan": 3})


def test_from_payload_rejects_bad_mode() -> None:
    with pytest.raises(DeltaError, match="недопустимый mode"):
        StateDelta.from_payload({"mode": "turbo"})


def test_state_to_dict_serializable() -> None:
    data = state_to_dict(DEFAULT_STATE)
    assert data["mode"] == "outside"
    assert data["filter_remain_days"] == 180.0
    assert set(data) == {
        "power",
        "sound",
        "light",
        "heater",
        "mode",
        "heater_temp",
        "fan_speed",
        "in_temp",
        "out_temp",
        "filter_remain_days",
    }
