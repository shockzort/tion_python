"""Qingping по Wi-Fi: «Self-built MQTT» с портала разработчика (docs/qingping.md).

Протокол — «Qingping Air Monitor Lite MQTT Protocol» (developer.qingping.co,
сверен с CGDN1, прошивка 4.8.5). Датчик публикует JSON в ``qingping/<MAC>/up``:

- ``type=13`` — heartbeat раз в минуту (прошивка, Wi-Fi RSSI): по нему
  датчик находится поиском ещё до регистрации;
- ``type=10`` — запрос BLE-подустройств; по протоколу показания идут
  нормально только после ответа ``type=11`` (его ``timestamp`` датчик
  берёт для синхронизации часов), поэтому отвечаем всем датчикам;
- ``type=12`` — текущие показания, ``sensorData`` из одного элемента
  ``{"co2": {"value": 817, "status": 0}, ...}``;
- ``type=17`` — история по интервалу портала, при ``need_ack`` ждёт
  подтверждения ``type=18``; принимается последняя точка — более старые
  не подтверждают свежесть (FR-25).

Режим реального времени (``type=12`` в ``.../down``) действует не дольше
часа: сервис шлёт запрос зарегистрированным датчикам при подключении,
продлевает по таймеру и повторяет сразу, если датчик жив (heartbeat), а
показаний давно нет — например, после его перезагрузки.

Недоступный брокер не валит сервис: реконнект с backoff (NFR-4).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

import aiomqtt
import structlog

from easy_breezy.core.discovery import DiscoveredSensor
from easy_breezy.core.events import TOPIC_DEVICE_LIST_CHANGED, EventBus, Subscription
from easy_breezy.core.sensors import KIND_QINGPING_MQTT, SensorIngest, in_range
from easy_breezy.integrations.qingping.parser import normalize_mac
from easy_breezy.storage import Database
from easy_breezy.storage.repos import SensorRepo

log = structlog.get_logger(__name__)

SOURCE_PREFIX = "qingping_mqtt:"
UP_TOPIC = "qingping/+/up"
REALTIME_DURATION = 3600
"""Сколько секунд датчик шлёт показания после одного запроса."""
RENEW_EVERY = 1800
"""Плановое продление запроса — с запасом до истечения ``duration``."""
NUDGE_AFTER = 180
"""Heartbeat есть, показаний нет дольше — повторить запрос немедленно."""
DISCOVERY_WINDOW = 600
"""Поиск показывает датчики, слышанные за последние 10 минут."""
_BACKOFF_INITIAL = 1.0
_BACKOFF_MAX = 60.0

_METRICS = ("co2", "temperature", "humidity", "pm25", "pm10", "battery")
_STATUS_OK = 0


def source_key(value: str) -> str:
    """Ключ реестра из MAC Wi-Fi модуля (как в топике и на портале)."""
    return SOURCE_PREFIX + normalize_mac(value.removeprefix(SOURCE_PREFIX))


def topic_mac(source: str) -> str:
    """MAC в написании топика: заглавные без двоеточий."""
    return source.removeprefix(SOURCE_PREFIX).replace(":", "")


@dataclass(frozen=True)
class QingpingMessage:
    """Разобранное uplink-сообщение датчика."""

    source_key: str
    type: str
    metrics: dict[str, float]
    model_version: str | None
    signal_dbm: int | None
    observed_at: int | None = None
    """Время измерения по часам датчика (``sensorData[].timestamp``)."""
    message_id: int | None = None
    need_ack: bool = False


def parse_message(topic: str, payload: bytes) -> QingpingMessage | None:
    """Разбор ``qingping/<MAC>/up``; чужое и повреждённое — ``None``."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "qingping" or parts[2] != "up":
        return None
    try:
        key = source_key(parts[1])
        data = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    kind = str(data.get("type", ""))
    metrics: dict[str, float] = {}
    observed_at: int | None = None
    entries = data.get("sensorData")
    if kind in ("12", "17") and isinstance(entries, list) and entries:
        # история приходит пачкой — свежесть подтверждает только последняя
        latest = max(
            (entry for entry in entries if isinstance(entry, dict)),
            key=_entry_time,
            default=None,
        )
        if latest is not None:
            metrics = _entry_metrics(latest)
            observed_at = _entry_time(latest) or None
    message_id = data.get("id")
    return QingpingMessage(
        source_key=key,
        type=kind,
        metrics=metrics,
        model_version=_str_or_none(data.get("sw_version") or data.get("version")),
        signal_dbm=_wifi_rssi(data.get("wifi_info")),
        observed_at=observed_at,
        message_id=message_id if isinstance(message_id, int) else None,
        need_ack=bool(data.get("need_ack")),
    )


def _entry_time(entry: dict[str, Any]) -> int:
    stamp = entry.get("timestamp")
    value = stamp.get("value") if isinstance(stamp, dict) else stamp
    return int(value) if isinstance(value, int) and value > 0 else 0


def _entry_metrics(entry: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for metric in _METRICS:
        item = entry.get(metric)
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        # у батареи status — режим питания (2 — от USB), а не качество
        if metric != "battery" and item.get("status", _STATUS_OK) != _STATUS_OK:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if in_range(metric, float(value)):
            metrics[metric] = float(value)
    return metrics


def _wifi_rssi(info: Any) -> int | None:
    """``"SSID,-40,3,BSSID"`` → -40; формат прошивки 4.8.x."""
    if not isinstance(info, str):
        return None
    for field in info.split(","):
        with contextlib.suppress(ValueError):
            value = int(field)
            if value < 0:
                return value
    return None


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def bind_reply(now: float) -> bytes:
    """Ответ на ``type=10``: подустройств нет, текущее время для датчика."""
    return json.dumps(
        {
            "code": 0,
            "desc": "",
            "dev_list": ["FFFFFFFFFFFF"],
            "timestamp": int(now),
            "type": "11",
        }
    ).encode()


def history_ack(message_id: int, now: float) -> bytes:
    """Подтверждение пачки истории ``type=17``."""
    return json.dumps(
        {
            "ack_id": message_id,
            "code": 0,
            "desc": "",
            "timestamp": int(now),
            "type": "18",
        }
    ).encode()


def realtime_request(interval: int) -> bytes:
    """Команда «показания каждые ``interval`` секунд в течение часа»."""
    return json.dumps(
        {
            "type": "12",
            "up_itvl": str(interval),
            "duration": str(REALTIME_DURATION),
        }
    ).encode()


class QingpingMqttListener:
    """Приём показаний Qingping через брокер; поиск — по heartbeat."""

    def __init__(
        self,
        db: Database,
        ingest: SensorIngest,
        events: EventBus,
        *,
        url: str | None,
        interval: int = 60,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._db = db
        self._ingest = ingest
        self._events = events
        self._url = url
        self._interval = interval
        self._sleep = sleep
        self._now = now
        self._tasks: list[asyncio.Task[None]] = []
        self._subscription: Subscription | None = None
        self._allowed: set[str] = set()
        self._seen: dict[str, tuple[float, QingpingMessage]] = {}
        self._last_data: dict[str, float] = {}
        self._last_request: dict[str, float] = {}
        self._client: aiomqtt.Client | None = None
        self.connected = False

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    async def start(self) -> None:
        if not self.enabled:
            log.info("qingping_mqtt_disabled")
            return
        self._subscription = self._events.subscribe(TOPIC_DEVICE_LIST_CHANGED)
        await self.reload()
        self._tasks = [
            asyncio.create_task(
                self._watch(self._subscription), name="qingping-mqtt-registry"
            ),
            asyncio.create_task(self._loop(), name="qingping-mqtt"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None

    async def reload(self) -> None:
        async with self._db.session() as session:
            sensors = await SensorRepo(session).list_all()
        allowed = {s.source_key for s in sensors if s.kind == KIND_QINGPING_MQTT}
        added = allowed - self._allowed
        self._allowed = allowed
        # только что добавленный датчик не ждёт планового продления
        for key in added:
            self._last_request.pop(key, None)
        if added:
            await self._request_due()

    async def _watch(self, subscription: Subscription) -> None:
        async for _event in subscription:
            try:
                await self.reload()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("qingping_mqtt_registry_failed")

    async def discover(self) -> list[DiscoveredSensor]:
        """Датчики, слышанные недавно; ждать не нужно — heartbeat ежеминутный."""
        if not self.enabled:
            raise ValueError("брокер MQTT не настроен (EB_MQTT_URL)")
        if not self.connected:
            raise ValueError("нет связи с брокером MQTT. Повторите позже.")
        since = self._now() - DISCOVERY_WINDOW
        found = [
            DiscoveredSensor(
                kind=KIND_QINGPING_MQTT,
                source_key=message.source_key,
                address=message.source_key.removeprefix(SOURCE_PREFIX),
                model="Qingping Air Monitor Lite",
                signal_dbm=message.signal_dbm,
                metrics=message.metrics,
                registered=message.source_key in self._allowed,
            )
            for seen, message in self._seen.values()
            if seen >= since
        ]
        return sorted(found, key=lambda item: item.address)

    async def handle(self, topic: str, payload: bytes) -> None:
        """Одно uplink-сообщение: кэш поиска, приём показаний, продление."""
        message = parse_message(topic, payload)
        if message is None:
            log.debug("qingping_mqtt_ignored", topic=topic)
            return
        now = self._now()
        key = message.source_key
        if message.type == "10":
            await self._publish(key, bind_reply(now))
        elif message.type == "17" and message.need_ack and message.message_id:
            await self._publish(key, history_ack(message.message_id, now))
        fresh = message.metrics
        previous = self._seen.get(key)
        if previous is not None:
            # heartbeat не затирает последние показания в выдаче поиска
            message = replace(
                message,
                metrics=message.metrics or previous[1].metrics,
                model_version=message.model_version or previous[1].model_version,
                signal_dbm=message.signal_dbm or previous[1].signal_dbm,
            )
        self._seen[key] = (now, message)
        if key not in self._allowed:
            return
        if message.type in ("12", "17") and fresh:
            self._last_data[key] = now
            observed: int | None = None
            if message.type == "17" and message.observed_at is not None:
                # история — по часам датчика; чуть спешащие часы не дают
                # будущего времени, старая пачка отсеется как устаревшая
                observed = min(message.observed_at, int(now))
            await self._ingest.ingest(
                kind=KIND_QINGPING_MQTT,
                source_key=key,
                metrics=fresh,
                observed_at=observed,
            )
        elif (
            now - self._last_data.get(key, -float("inf")) > NUDGE_AFTER
            and now - self._last_request.get(key, -float("inf")) > NUDGE_AFTER
        ):
            # жив (heartbeat), но молчит: запрос реального времени истёк
            await self._request(key)

    async def _publish(self, key: str, payload: bytes) -> None:
        if self._client is not None:
            await self._client.publish(
                f"qingping/{topic_mac(key)}/down", payload, qos=1
            )

    async def _request(self, key: str) -> None:
        self._last_request[key] = self._now()
        await self._publish(key, realtime_request(self._interval))
        log.debug("qingping_mqtt_realtime_requested", source_key=key)

    async def _request_due(self) -> None:
        now = self._now()
        for key in sorted(self._allowed):
            if now - self._last_request.get(key, -float("inf")) >= RENEW_EVERY:
                await self._request(key)

    async def _loop(self) -> None:
        backoff = _BACKOFF_INITIAL
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except aiomqtt.MqttError as exc:
                log.warning("qingping_mqtt_disconnected", error=str(exc))
            except Exception:
                # приём не имеет права умирать молча (ADR-0007)
                log.exception("qingping_mqtt_crashed")
            finally:
                self._client = None
                self.connected = False
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
            identifier="easy-breezy-qingping",
            timeout=10,
        ) as client:
            await client.subscribe(UP_TOPIC, qos=1)
            self._client = client
            self.connected = True
            # после разрыва датчики могли досидеть запрос — продлить сразу
            self._last_request.clear()
            log.info("qingping_mqtt_connected", sensors=len(self._allowed))
            renew = asyncio.create_task(self._renew_loop(), name="qingping-renew")
            try:
                async for message in client.messages:
                    payload = message.payload
                    if not isinstance(payload, bytes):
                        payload = str(payload).encode()
                    try:
                        await self.handle(str(message.topic), payload)
                    except aiomqtt.MqttError:
                        raise
                    except Exception:
                        log.exception("qingping_mqtt_message_failed")
            finally:
                renew.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await renew

    async def _renew_loop(self) -> None:
        while True:
            await self._request_due()
            await self._sleep(60)
