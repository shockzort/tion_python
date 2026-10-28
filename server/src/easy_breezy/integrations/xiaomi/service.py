"""Приборы Xiaomi по Wi-Fi: опрос, кэш состояния, команды (docs/xiaomi.md).

Каждый прибор из ``EB_XIAOMI_DEVICES`` опрашивается своей задачей раз в
``poll_interval``; сбой опроса — переподключение с backoff 1→20 с и
джиттером, пауза обнуляется первым успешным опросом. Состояние живёт в
памяти (запросные пути читают кэш, а не сеть) и уходит в шину событием
``appliance.state_changed`` — WS-мост обновляет UI.

Опрос и команда одного прибора идут под общим замком: полный опрос — это
несколько запросов, и команда между ними давала бы в кэше смесь старого и
нового состояния (UI «дребезжал»). Прибор применяет запись не мгновенно,
поэтому после команды состояние перечитывается, пока не совпадёт с дельтой
(не дольше ``SETTLE_READS`` чтений).

Встроенные датчики прибора (влажность, температура, PM2.5) публикуются
через ``SensorIngest`` как датчик ``xiaomi_miio:<did>`` (регистрируется
сам) — так прибор сразу попадает в графики, карточки датчиков и триггеры.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import structlog

from easy_breezy.config import XiaomiDeviceConfig
from easy_breezy.core.events import TOPIC_APPLIANCE_STATE_CHANGED, EventBus
from easy_breezy.core.sensors import KIND_XIAOMI_MIIO, SensorIngest
from easy_breezy.integrations.xiaomi import ha2
from easy_breezy.integrations.xiaomi.ha2 import ApplianceDeltaError, Ha2Delta, Ha2State
from easy_breezy.integrations.xiaomi.miio import MiioKey
from easy_breezy.integrations.xiaomi.transport import MiioError, MiioTransport

log = structlog.get_logger(__name__)

SOURCE_PREFIX = "xiaomi_miio:"
POLL_INTERVAL = 15.0
SENSOR_EVERY = 60.0
"""Показания в реестр датчиков не чаще раза в минуту (как у Qingping)."""
MAX_PROPS_PER_REQUEST = 10
"""ha2 молча отбрасывает get_properties на 20 свойств (16 ещё принимает)."""
SETTLE_READS = 3
SETTLE_DELAY = 0.7
"""Пауза между перечитываниями после команды, с."""
_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 20.0

TransportFactory = Callable[[XiaomiDeviceConfig], MiioTransport]


class ApplianceError(Exception):
    """Команда прибору не выполнена."""


class ApplianceNotFoundError(ApplianceError):
    """Прибора с таким id нет в конфигурации."""


def sensor_source_key(did: int) -> str:
    return f"{SOURCE_PREFIX}{did}"


@dataclass(frozen=True, slots=True)
class ApplianceSnapshot:
    """Последнее известное состояние прибора."""

    id: str
    name: str
    model: str
    online: bool = False
    state: Ha2State | None = None
    state_at: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "online": self.online,
            "state": self.state.to_dict() if self.state is not None else None,
            "state_at": self.state_at,
            "error": self.error,
        }


def _default_transport(config: XiaomiDeviceConfig) -> MiioTransport:
    return MiioTransport(config.host, MiioKey.from_hex(config.token.get_secret_value()))


class ApplianceService:
    def __init__(
        self,
        sensors: SensorIngest,
        events: EventBus,
        configs: list[XiaomiDeviceConfig],
        *,
        transport_factory: TransportFactory | None = None,
        poll_interval: float = POLL_INTERVAL,
        now: Callable[[], float] = time.time,
        jitter: Callable[[], float] = random.random,
        settle_delay: float = SETTLE_DELAY,
    ) -> None:
        self._sensors = sensors
        self._events = events
        self._poll_interval = poll_interval
        self._now = now
        self._jitter = jitter
        self._settle_delay = settle_delay
        self._configs = {str(config.did): config for config in configs}
        self._transports = {
            appliance_id: (transport_factory or _default_transport)(config)
            for appliance_id, config in self._configs.items()
        }
        self._snapshots = {
            appliance_id: ApplianceSnapshot(
                id=appliance_id, name=config.name, model=config.model
            )
            for appliance_id, config in self._configs.items()
        }
        self._locks = {appliance_id: asyncio.Lock() for appliance_id in self._configs}
        self._sensor_at: dict[str, float] = {}
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        for config in self._configs.values():
            if config.model != ha2.MODEL:
                log.warning(
                    "appliance_model_unsupported", did=config.did, model=config.model
                )
                continue
            self._tasks.append(
                asyncio.create_task(
                    self._poll_loop(str(config.did)), name=f"miio-{config.did}"
                )
            )
        if self._tasks:
            log.info("appliances_started", count=len(self._tasks))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        for transport in self._transports.values():
            transport.close()

    def list(self) -> list[ApplianceSnapshot]:
        return sorted(self._snapshots.values(), key=lambda snapshot: snapshot.name)

    def get(self, appliance_id: str) -> ApplianceSnapshot | None:
        return self._snapshots.get(appliance_id)

    async def _poll_loop(self, appliance_id: str) -> None:
        backoff = _BACKOFF_INITIAL
        while True:
            try:
                await self.refresh(appliance_id)
            except (MiioError, ApplianceDeltaError):
                # причина уже в снапшоте и логе (refresh)
                pause = backoff * (0.5 + self._jitter())
                backoff = min(backoff * 2, _BACKOFF_MAX)
                await asyncio.sleep(pause)
                continue
            backoff = _BACKOFF_INITIAL  # прожившая сессия: опрос удался
            await asyncio.sleep(self._poll_interval)

    async def _read_state(self, appliance_id: str) -> Ha2State:
        transport = self._transports[appliance_id]
        request = ha2.property_request()
        result: list[Any] = []
        for start in range(0, len(request), MAX_PROPS_PER_REQUEST):
            chunk = await transport.call(
                "get_properties", request[start : start + MAX_PROPS_PER_REQUEST]
            )
            if not isinstance(chunk, list):
                raise MiioError(f"get_properties вернул {type(chunk).__name__}")
            result.extend(chunk)
        return ha2.parse_properties(result)

    async def refresh(self, appliance_id: str) -> ApplianceSnapshot:
        """Один опрос прибора: обновляет кэш, шлёт события и показания датчиков."""
        async with self._locks[appliance_id]:
            return await self._refresh_locked(appliance_id)

    async def _refresh_locked(self, appliance_id: str) -> ApplianceSnapshot:
        snapshot = self._snapshots[appliance_id]
        try:
            state = await self._read_state(appliance_id)
        except (MiioError, ApplianceDeltaError) as exc:
            if snapshot.online:
                log.warning(
                    "appliance_offline", appliance_id=appliance_id, error=str(exc)
                )
            elif snapshot.error != str(exc):
                # недоступен с самого старта (неверный токен, IP) — тоже в лог
                log.warning(
                    "appliance_unreachable", appliance_id=appliance_id, error=str(exc)
                )
            self._store(replace(snapshot, online=False, error=str(exc)))
            raise
        if not snapshot.online:
            log.info("appliance_online", appliance_id=appliance_id)
        updated = replace(
            snapshot, online=True, state=state, state_at=self._now(), error=None
        )
        self._store(updated)
        await self._ingest_sensors(appliance_id, state)
        return updated

    def _store(self, snapshot: ApplianceSnapshot) -> None:
        previous = self._snapshots[snapshot.id]
        self._snapshots[snapshot.id] = snapshot
        if (previous.online, previous.state) != (snapshot.online, snapshot.state):
            self._events.publish(TOPIC_APPLIANCE_STATE_CHANGED, snapshot.to_dict())

    async def _ingest_sensors(self, appliance_id: str, state: Ha2State) -> None:
        now = self._now()
        if now - self._sensor_at.get(appliance_id, -SENSOR_EVERY) < SENSOR_EVERY:
            return
        self._sensor_at[appliance_id] = now
        config = self._configs[appliance_id]
        await self._sensors.ingest(
            kind=KIND_XIAOMI_MIIO,
            source_key=sensor_source_key(config.did),
            metrics=state.sensor_metrics(),
            name=config.name,
            auto_register=True,
        )

    async def command(
        self, appliance_id: str, delta: Ha2Delta, *, source: str
    ) -> ApplianceSnapshot:
        """Применяет дельту и возвращает подтверждённое прибором состояние."""
        if appliance_id not in self._snapshots:
            raise ApplianceNotFoundError(f"прибор {appliance_id} не найден")
        if delta.is_empty():
            raise ApplianceError("пустая команда")
        log.info(
            "appliance_command",
            appliance_id=appliance_id,
            source=source,
            delta=delta.to_payload(),
        )
        async with self._locks[appliance_id]:
            return await self._command_locked(appliance_id, delta)

    async def _command_locked(
        self, appliance_id: str, delta: Ha2Delta
    ) -> ApplianceSnapshot:
        try:
            result = await self._transports[appliance_id].call(
                "set_properties", delta.to_properties()
            )
        except MiioError as exc:
            log.warning(
                "appliance_command_failed", appliance_id=appliance_id, error=str(exc)
            )
            raise ApplianceError(str(exc)) from exc
        rejected = (
            [
                item.get("did")
                for item in result
                if isinstance(item, dict) and item.get("code") != 0
            ]
            if isinstance(result, list)
            else []
        )
        if rejected:
            log.warning(
                "appliance_command_rejected", appliance_id=appliance_id, props=rejected
            )
        expected = {} if rejected else delta.to_payload()
        try:
            snapshot = await self._settle(appliance_id, expected)
        except (MiioError, ApplianceDeltaError) as exc:
            raise ApplianceError(
                f"команда ушла, но состояние не прочитано: {exc}"
            ) from exc
        if rejected:
            raise ApplianceError(f"прибор отклонил: {', '.join(map(str, rejected))}")
        return snapshot

    async def _settle(
        self, appliance_id: str, expected: dict[str, Any]
    ) -> ApplianceSnapshot:
        """Перечитывает состояние, пока прибор не применит ``expected``."""
        snapshot = await self._refresh_locked(appliance_id)
        for _ in range(SETTLE_READS - 1):
            state = snapshot.state
            if state is None or all(
                getattr(state, name) == value for name, value in expected.items()
            ):
                break
            await asyncio.sleep(self._settle_delay)
            snapshot = await self._refresh_locked(appliance_id)
        return snapshot

    async def action(
        self, appliance_id: str, name: str, *, source: str
    ) -> ApplianceSnapshot:
        """Действие обслуживания (самоочистка, сушка, сброс фильтра)."""
        if appliance_id not in self._snapshots:
            raise ApplianceNotFoundError(f"прибор {appliance_id} не найден")
        try:
            params = ha2.action_request(name)
        except ApplianceDeltaError as exc:
            raise ApplianceError(str(exc)) from exc
        log.info(
            "appliance_action", appliance_id=appliance_id, source=source, action=name
        )
        async with self._locks[appliance_id]:
            try:
                result = await self._transports[appliance_id].call("action", params)
            except MiioError as exc:
                log.warning(
                    "appliance_action_failed",
                    appliance_id=appliance_id,
                    error=str(exc),
                )
                raise ApplianceError(str(exc)) from exc
            code = result.get("code") if isinstance(result, dict) else None
            if code not in (0, None):
                raise ApplianceError(f"прибор отклонил действие {name}: code {code}")
            try:
                return await self._settle(appliance_id, {})
            except (MiioError, ApplianceDeltaError) as exc:
                raise ApplianceError(
                    f"действие ушло, но состояние не прочитано: {exc}"
                ) from exc
