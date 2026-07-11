"""MQTT-инжест сторонних датчиков (план §10, FR-26).

Датчик регистрируется в UI с ``source_key`` = базовый топик; клиент
подписывается на сам топик и на ``{топик}/+``:

- сообщение в базовый топик — JSON ``{"co2": ..., "temperature": ...,
  "humidity": ...}`` или голое число (число трактуется как CO₂ —
  главная метрика сервиса);
- сообщение в ``{топик}/co2|temperature|humidity`` — голое число этой
  метрики (стиль tasmota/zigbee2mqtt с раздельными топиками).

Недоступный брокер не валит сервис: реконнект-цикл с backoff (NFR-4).
Появление нового датчика в реестре разрывает сессию — переподключение
подписывается по свежему списку.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import aiomqtt
import structlog

from easy_breezy.core.events import TOPIC_DEVICE_LIST_CHANGED, EventBus, Subscription
from easy_breezy.core.sensors import KIND_MQTT, METRICS, SensorIngest
from easy_breezy.storage import Database
from easy_breezy.storage.models import Sensor
from easy_breezy.storage.repos import SensorRepo

log = structlog.get_logger(__name__)

_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 60.0


def parse_payload(metric_suffix: str | None, payload: bytes) -> dict[str, float]:
    """Метрики из MQTT-сообщения; кривой payload — пустой словарь."""
    text = payload.decode("utf-8", "replace").strip()
    if metric_suffix is not None:
        if metric_suffix not in METRICS:
            return {}
        try:
            return {metric_suffix: float(text)}
        except ValueError:
            return {}
    try:
        decoded = json.loads(text)
    except ValueError:
        return {}
    if isinstance(decoded, dict):
        return {key: value for key, value in decoded.items() if key in METRICS}
    if isinstance(decoded, (int, float)) and not isinstance(decoded, bool):
        return {"co2": float(decoded)}  # голое число — CO₂ по умолчанию
    return {}


class MqttIngest:
    def __init__(
        self,
        db: Database,
        ingest: SensorIngest,
        events: EventBus,
        *,
        url: str | None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._db = db
        self._ingest = ingest
        self._events = events
        self._url = url
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._registry_changed = asyncio.Event()
        self._subscription: Subscription | None = None
        self._watch_task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    async def start(self) -> None:
        if not self.enabled:
            log.info("mqtt_disabled")
            return
        self._subscription = self._events.subscribe(TOPIC_DEVICE_LIST_CHANGED)
        self._watch_task = asyncio.create_task(
            self._watch_registry(self._subscription), name="mqtt-registry-watch"
        )
        self._task = asyncio.create_task(self._loop(), name="mqtt-ingest")

    async def stop(self) -> None:
        for task in (self._task, self._watch_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = None
        self._watch_task = None
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None

    async def _watch_registry(self, subscription: Subscription) -> None:
        async for _ in subscription:
            self._registry_changed.set()

    async def _loop(self) -> None:
        backoff = _BACKOFF_INITIAL
        while True:
            try:
                await self._session()
                backoff = _BACKOFF_INITIAL  # сессию разорвал реестр — сразу назад
            except asyncio.CancelledError:
                raise
            except aiomqtt.MqttError as exc:
                log.warning("mqtt_disconnected", error=str(exc))
                await self._sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)
            except Exception:
                # инжест не имеет права умирать молча (ADR-0007)
                log.exception("mqtt_session_crashed")
                await self._sleep(backoff)
                backoff = min(backoff * 2, _BACKOFF_MAX)

    async def _session(self) -> None:
        assert self._url is not None
        parsed = urlparse(self._url)
        async with aiomqtt.Client(
            hostname=parsed.hostname or "localhost",
            port=parsed.port or 1883,
            username=parsed.username,
            password=parsed.password,
        ) as client:
            topics = await self._mqtt_topics()
            for topic in topics:
                await client.subscribe(topic)
                await client.subscribe(f"{topic}/+")
            log.info("mqtt_connected", topics=len(topics))
            self._registry_changed.clear()
            reader = asyncio.ensure_future(self._read_messages(client, set(topics)))
            changed = asyncio.ensure_future(self._registry_changed.wait())
            try:
                await asyncio.wait(
                    (reader, changed), return_when=asyncio.FIRST_COMPLETED
                )
                if reader.done():
                    reader.result()  # пробросить MqttError из чтения
                log.info("mqtt_resubscribe", reason="реестр датчиков изменился")
            finally:
                for task in (reader, changed):
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    async def _read_messages(
        self, client: aiomqtt.Client, base_topics: set[str]
    ) -> None:
        async for message in client.messages:
            topic = str(message.topic)
            payload = message.payload
            if not isinstance(payload, bytes):
                payload = str(payload).encode()
            try:
                await self._handle(topic, payload, base_topics)
            except Exception:
                log.exception("mqtt_message_failed", topic=topic)

    async def _handle(self, topic: str, payload: bytes, base_topics: set[str]) -> None:
        if topic in base_topics:
            source_key, suffix = topic, None
        else:
            source_key, _, suffix = topic.rpartition("/")
            if source_key not in base_topics:
                log.debug("mqtt_topic_unknown", topic=topic)
                return
        metrics = parse_payload(suffix, payload)
        if not metrics:
            log.warning("mqtt_payload_invalid", topic=topic)
            return
        await self._ingest.ingest(
            kind=KIND_MQTT, source_key=source_key, metrics=metrics
        )

    async def _mqtt_topics(self) -> list[str]:
        async with self._db.session() as session:
            sensors = await SensorRepo(session).list_all()
        return [sensor.source_key for sensor in sensors if _is_mqtt_sensor(sensor)]


def _is_mqtt_sensor(sensor: Sensor) -> bool:
    return sensor.kind == KIND_MQTT
