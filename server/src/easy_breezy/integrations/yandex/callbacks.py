"""Уведомления платформы: callback state/discovery (план §6).

Подписчик событий шины с дебаунсом 1 с и схлопыванием по устройству: шторм
кадров состояния превращается в один POST со свежими значениями из кэша.
Без skill_id/токена нотификатор выключен (интеграция не настроена).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import (
    TOPIC_CONNECTION_CHANGED,
    TOPIC_DEVICE_LIST_CHANGED,
    TOPIC_SENSOR_UPDATED,
    TOPIC_STATE_CHANGED,
    EventBus,
    Subscription,
)
from easy_breezy.core.model import state_to_dict
from easy_breezy.core.registry import DeviceRegistry
from easy_breezy.core.state import StateCache
from easy_breezy.integrations.yandex import mapping
from easy_breezy.storage import Database
from easy_breezy.storage.repos import SensorRepo, UserRepo

SENSOR_ID_PREFIX = "sensor:"

log = structlog.get_logger(__name__)

DIALOGS_BASE_URL = "https://dialogs.yandex.net"
DEBOUNCE_SECONDS = 1.0
_RETRY_DELAYS = (1.0, 2.0, 4.0)


class YandexNotifier:
    def __init__(
        self,
        db: Database,
        events: EventBus,
        cache: StateCache,
        registry: DeviceRegistry,
        *,
        skill_id: str | None,
        callback_token: str | None,
        base_url: str = DIALOGS_BASE_URL,
        client: httpx.AsyncClient | None = None,
        debounce: float = DEBOUNCE_SECONDS,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._db = db
        self._events = events
        self._cache = cache
        self._registry = registry
        self._skill_id = skill_id
        self._callback_token = callback_token
        self._base_url = base_url
        self._external_client = client
        self._client: httpx.AsyncClient | None = None
        self._debounce = debounce
        self._now = now
        self._sleep = sleep
        self._subscription: Subscription | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._dirty: set[str] = set()
        self._dirty_flag = asyncio.Event()
        self._user_id: int | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._skill_id and self._callback_token)

    async def start(self) -> None:
        if not self.enabled:
            log.info("yandex_callbacks_disabled")
            return
        self._client = self._external_client or httpx.AsyncClient(timeout=10.0)
        self._subscription = self._events.subscribe(
            TOPIC_STATE_CHANGED,
            TOPIC_CONNECTION_CHANGED,
            TOPIC_DEVICE_LIST_CHANGED,
            TOPIC_SENSOR_UPDATED,
        )
        self._tasks = [
            asyncio.create_task(
                self._collect_loop(self._subscription), name="yandex-collector"
            ),
            asyncio.create_task(self._flush_loop(), name="yandex-flusher"),
        ]
        log.info("yandex_callbacks_started", skill_id=self._skill_id)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None
        if self._client is not None and self._external_client is None:
            await self._client.aclose()
        self._client = None

    async def _collect_loop(self, subscription: Subscription) -> None:
        async for event in subscription:
            if event.topic == TOPIC_DEVICE_LIST_CHANGED:
                await self._post_with_retries("/callback/discovery", self._envelope())
            elif event.topic == TOPIC_SENSOR_UPDATED:
                self._dirty.add(f"{SENSOR_ID_PREFIX}{event.data['sensor_id']}")
                self._dirty_flag.set()
            else:
                device_uuid = event.data.get("device_uuid")
                if isinstance(device_uuid, str):
                    self._dirty.add(device_uuid)
                    self._dirty_flag.set()

    async def _flush_loop(self) -> None:
        while True:
            await self._dirty_flag.wait()
            await self._sleep(self._debounce)  # окно схлопывания шторма
            self._dirty_flag.clear()
            batch, self._dirty = self._dirty, set()
            if not batch:
                continue
            payload = self._envelope()
            payload["payload"]["devices"] = [
                await self._entity_state(key) for key in sorted(batch)
            ]
            await self._post_with_retries("/callback/state", payload)

    async def _entity_state(self, key: str) -> dict[str, Any]:
        if key.startswith(SENSOR_ID_PREFIX):
            return await self._sensor_state(key)
        return self._device_state(key)

    async def _sensor_state(self, key: str) -> dict[str, Any]:
        sensor_id = int(key.removeprefix(SENSOR_ID_PREFIX))
        async with self._db.session() as session:
            sensor = await SensorRepo(session).get(sensor_id)
        if sensor is None or not sensor.last_values:
            return {"id": key, "error_code": "DEVICE_UNREACHABLE"}
        return {
            "id": key,
            "properties": mapping.sensor_property_states(sensor.last_values),
        }

    def _envelope(self) -> dict[str, Any]:
        return {
            "ts": int(self._now()),
            "payload": {"user_id": str(self._user_id or 0)},
        }

    def _device_state(self, device_uuid: str) -> dict[str, Any]:
        snapshot = self._cache.get(device_uuid)
        online = self._registry.connection(device_uuid) is ConnectionState.ONLINE
        if snapshot is None or snapshot.state is None or not online:
            return {"id": device_uuid, "error_code": "DEVICE_UNREACHABLE"}
        state = state_to_dict(snapshot.state)
        return {
            "id": device_uuid,
            "capabilities": mapping.capability_states(state),
            "properties": mapping.property_states(state),
        }

    async def _resolve_user_id(self) -> int:
        if self._user_id is None:
            async with self._db.session() as session:
                user = await UserRepo(session).first()
            self._user_id = user.id if user is not None else 0
        return self._user_id

    async def _post_with_retries(self, path: str, payload: dict[str, Any]) -> None:
        assert self._client is not None  # start() создал клиента
        await self._resolve_user_id()
        payload["payload"]["user_id"] = str(self._user_id or 0)
        url = f"{self._base_url}/api/v1/skills/{self._skill_id}{path}"
        headers = {"Authorization": f"OAuth {self._callback_token}"}
        for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
            try:
                response = await self._client.post(url, json=payload, headers=headers)
                if response.status_code < 400:
                    log.debug("yandex_callback_sent", path=path)
                    return
                error: str = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                error = str(exc)
            log.warning(
                "yandex_callback_failed", path=path, attempt=attempt, error=error
            )
            if delay is None:
                return
            await self._sleep(delay)
