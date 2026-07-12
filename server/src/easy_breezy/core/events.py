"""Шина событий: in-process async pub/sub (план §3).

Издатели (BLE-супервизоры, командная шина, датчики) не знают подписчиков
(WS-хаб, Яндекс-callbacks, телеметрия, триггеры). ``publish`` синхронный и
неблокирующий — зовётся из колбэков; медленный подписчик теряет старейшие
события своей очереди, но не тормозит остальных.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Self

import structlog

log = structlog.get_logger(__name__)

TOPIC_STATE_CHANGED = "device.state_changed"
TOPIC_CONNECTION_CHANGED = "device.connection_changed"
TOPIC_DEVICE_LIST_CHANGED = "device.list_changed"
TOPIC_COMMAND_FINISHED = "command.finished"
TOPIC_PAIRING_PROGRESS = "pairing.progress"
TOPIC_SENSOR_UPDATED = "sensor.updated"
TOPIC_AUTOMATION_CHANGED = "automation.changed"
TOPIC_BACKUP_FINISHED = "backup.finished"
TOPIC_BACKUP_FAILED = "backup.failed"


@dataclass(frozen=True, slots=True)
class Event:
    topic: str
    data: dict[str, Any] = field(default_factory=dict)


class Subscription:
    """Асинхронный итератор событий; создаётся через ``EventBus.subscribe``."""

    def __init__(
        self, bus: EventBus, topics: frozenset[str] | None, maxsize: int
    ) -> None:
        self._bus = bus
        self._topics = topics
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize)

    def _matches(self, topic: str) -> bool:
        return self._topics is None or topic in self._topics

    def _deliver(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            dropped = self._queue.get_nowait()  # свежее важнее старого
            self._queue.put_nowait(event)
            log.warning("event_queue_overflow", dropped_topic=dropped.topic)

    def close(self) -> None:
        self._bus._detach(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> Event:
        return await self._queue.get()

    async def get(self) -> Event:
        return await self._queue.get()


class EventBus:
    """Раздаёт события по индивидуальным очередям подписчиков."""

    def __init__(self) -> None:
        self._subscriptions: set[Subscription] = set()

    def subscribe(self, *topics: str, maxsize: int = 256) -> Subscription:
        """Подписка на темы (без аргументов — на все); закрывать через close()."""
        subscription = Subscription(
            self, frozenset(topics) if topics else None, maxsize
        )
        self._subscriptions.add(subscription)
        return subscription

    def _detach(self, subscription: Subscription) -> None:
        self._subscriptions.discard(subscription)

    def publish(self, topic: str, data: dict[str, Any] | None = None) -> None:
        event = Event(topic, data if data is not None else {})
        for subscription in tuple(self._subscriptions):
            if subscription._matches(topic):
                subscription._deliver(event)
