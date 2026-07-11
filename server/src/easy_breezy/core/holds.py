"""Manual-hold: окна ручного управления (ADR-0005, план §9).

Ручная команда (UI/Алиса/CLI/интент) ставит окно; автоматика (priority ≥ 1)
в окне пропускается со статусом ``skipped_hold``. Окна живут в памяти —
рестарт сервиса их снимает, это осознанно (окно короткое).
"""

from __future__ import annotations

import time
from collections.abc import Callable


class HoldManager:
    def __init__(
        self,
        *,
        duration_seconds: float,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._duration = duration_seconds
        self._now = now
        self._hold_until: dict[str, float] = {}

    def place(self, device_uuid: str) -> float:
        """Ставит/продлевает окно, возвращает unix-время его конца."""
        until = self._now() + self._duration
        self._hold_until[device_uuid] = until
        return until

    def release(self, device_uuid: str) -> None:
        """Кнопка «вернуть автоматику»."""
        self._hold_until.pop(device_uuid, None)

    def is_held(self, device_uuid: str) -> bool:
        return self.hold_until(device_uuid) is not None

    def hold_until(self, device_uuid: str) -> float | None:
        """Конец активного окна или None; истёкшие окна чистятся лениво."""
        until = self._hold_until.get(device_uuid)
        if until is None:
            return None
        if until <= self._now():
            del self._hold_until[device_uuid]
            return None
        return until
