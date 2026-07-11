"""Manual-hold окна: постановка, истечение, ручное снятие."""

from __future__ import annotations

from easy_breezy.core.holds import HoldManager


class FakeNow:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_place_and_expiry() -> None:
    now = FakeNow()
    holds = HoldManager(duration_seconds=3600, now=now)
    assert not holds.is_held("d1")

    until = holds.place("d1")
    assert until == 1000.0 + 3600
    assert holds.is_held("d1")
    assert not holds.is_held("d2")

    now.value = until - 1
    assert holds.is_held("d1")
    now.value = until
    assert not holds.is_held("d1")
    assert holds.hold_until("d1") is None


def test_replace_extends_window() -> None:
    now = FakeNow()
    holds = HoldManager(duration_seconds=100, now=now)
    holds.place("d1")
    now.value = 1050
    assert holds.place("d1") == 1150  # повторная ручная команда продлевает


def test_release() -> None:
    holds = HoldManager(duration_seconds=100, now=FakeNow())
    holds.place("d1")
    holds.release("d1")
    assert not holds.is_held("d1")
    holds.release("d1")  # идемпотентно
