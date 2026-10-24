"""Приём BLE CGDN1 с приоритетом подключений Tion и выборкой раз в 30 секунд."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import replace

import structlog
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

from easy_breezy.ble.coordinator import ScanCoordinator
from easy_breezy.core.discovery import DiscoveredSensor
from easy_breezy.core.events import TOPIC_DEVICE_LIST_CHANGED, EventBus, Subscription
from easy_breezy.core.sensors import KIND_QINGPING_BLE, SensorIngest, metric_is_stale
from easy_breezy.integrations.qingping.parser import (
    SERVICE_UUID,
    SOURCE_PREFIX,
    parse_advertisement,
)
from easy_breezy.storage import Database
from easy_breezy.storage.repos import SensorRepo

log = structlog.get_logger(__name__)
PUBLISH_INTERVAL = 30
SCAN_SESSION_SECONDS = 60


class QingpingListener:
    """Сканирует только при наличии зарегистрированного CGDN1 или запроса поиска."""

    def __init__(
        self,
        db: Database,
        ingest: SensorIngest,
        events: EventBus,
        gate: ScanCoordinator,
        *,
        enabled: bool = True,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._db = db
        self._ingest = ingest
        self._events = events
        self._gate = gate
        self._enabled = enabled
        self._now = now
        self._tasks: list[asyncio.Task[None]] = []
        self._subscription: Subscription | None = None
        self._allowed: set[str] = set()
        self._changed = asyncio.Event()
        self._discovery_count = 0
        self._discovered: dict[str, tuple[float, DiscoveredSensor]] = {}
        self._pending: dict[tuple[str, str], tuple[float, int]] = {}
        self._published: dict[tuple[str, str], float] = {}
        self.last_error: str | None = None

    async def start(self) -> None:
        self._subscription = self._events.subscribe(TOPIC_DEVICE_LIST_CHANGED)
        await self.reload()
        self._tasks = [
            asyncio.create_task(
                self._watch(self._subscription), name="qingping-registry"
            ),
            asyncio.create_task(self._scan_loop(), name="qingping-ble"),
            asyncio.create_task(self._flush_loop(), name="qingping-ingest"),
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

    async def reload(self) -> None:
        async with self._db.session() as session:
            sensors = await SensorRepo(session).list_all()
        self._allowed = {
            sensor.source_key for sensor in sensors if sensor.kind == KIND_QINGPING_BLE
        }
        self._pending = {
            k: v for k, v in self._pending.items() if k[0] in self._allowed
        }
        self._published = {
            k: v for k, v in self._published.items() if k[0] in self._allowed
        }
        self._changed.set()

    async def _watch(self, subscription: Subscription) -> None:
        async for _event in subscription:
            while True:
                try:
                    await self.reload()
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("qingping_registry_failed")
                    await asyncio.sleep(5)

    async def discover(self, duration: float = 15) -> list[DiscoveredSensor]:
        """Временно включает общий слушатель; никаких регистраций или соединений."""
        if not self._enabled:
            raise ValueError("поиск Qingping отключён в режиме эмуляторов")
        started = self._now()
        self._discovery_count += 1
        self._changed.set()
        try:
            await asyncio.sleep(duration)
            found = [
                replace(item, registered=item.source_key in self._allowed)
                for seen, item in self._discovered.values()
                if seen >= started
            ]
            if not found and self.last_error is not None:
                raise ValueError(self.last_error)
            return sorted(found, key=lambda item: item.signal_dbm or -999, reverse=True)
        finally:
            self._discovery_count -= 1
            self._changed.set()

    def receive(self, data: bytes, rssi: int = 0) -> None:
        """Синхронный callback: память ограничена, запись БД вынесена из Bleak."""
        reading = parse_advertisement(data, rssi=rssi)
        if reading is None:
            return
        now = self._now()
        if self._discovery_count:
            # Ограниченный кэш только на время поиска; чужие датчики не регистрируются.
            if len(self._discovered) >= 128:
                oldest = min(self._discovered, key=lambda k: self._discovered[k][0])
                del self._discovered[oldest]
            self._discovered[reading.source_key] = (
                now,
                DiscoveredSensor(
                    kind=KIND_QINGPING_BLE,
                    source_key=reading.source_key,
                    address=reading.source_key.removeprefix(SOURCE_PREFIX),
                    model="Qingping Air Monitor Lite",
                    signal_dbm=rssi,
                    metrics=reading.metrics,
                    registered=reading.source_key in self._allowed,
                ),
            )
        if reading.source_key in self._allowed:
            for metric, value in reading.metrics.items():
                self._pending[reading.source_key, metric] = (value, int(now))

    def _detect(self, _device: BLEDevice, adv: AdvertisementData) -> None:
        try:
            if (data := adv.service_data.get(SERVICE_UUID)) is not None:
                self.receive(data, adv.rssi)
        except Exception:
            log.exception("qingping_packet_failed")

    async def flush(self) -> None:
        """Публикует только полученные пакеты с их временем, включая равные значения."""
        now = self._now()
        grouped: dict[tuple[str, int], dict[str, float]] = {}
        for key, (value, ts) in list(self._pending.items()):
            if metric_is_stale(ts, now):
                self._pending.pop(key, None)
                continue
            if now - self._published.get(key, -float("inf")) < PUBLISH_INTERVAL:
                continue
            self._pending.pop(key, None)
            grouped.setdefault((key[0], ts), {})[key[1]] = value
        for (source_key, ts), metrics in grouped.items():
            await self._ingest.ingest(
                kind=KIND_QINGPING_BLE,
                source_key=source_key,
                metrics=metrics,
                observed_at=ts,
            )
            for metric in metrics:
                self._published[source_key, metric] = now

    async def _flush_loop(self) -> None:
        while True:
            try:
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("qingping_ingest_failed")
            await asyncio.sleep(1)

    def _needed(self) -> bool:
        return self._enabled and bool(self._allowed or self._discovery_count)

    async def _scan_loop(self) -> None:
        delay = 1.0
        while True:
            self._changed.clear()
            if not self._needed():
                await self._changed.wait()
                continue
            try:
                async with self._gate.background() as interrupted:
                    if not self._needed():
                        continue
                    scanner = BleakScanner(
                        detection_callback=self._detect,
                        # Равные показания тоже подтверждают свежесть датчика.
                        bluez={"filters": {"DuplicateData": True}},
                    )
                    try:
                        async with asyncio.timeout(10):
                            await scanner.start()
                        self.last_error = None
                        # BlueZ может исчезнуть без исключения в callback. Новая
                        # сессия восстанавливает подписку после такого рестарта.
                        loop = asyncio.get_running_loop()
                        until = loop.time() + SCAN_SESSION_SECONDS
                        while self._needed() and not interrupted.is_set():
                            remaining = until - loop.time()
                            if remaining <= 0:
                                break
                            with contextlib.suppress(TimeoutError):
                                await asyncio.wait_for(
                                    interrupted.wait(), min(1, remaining)
                                )
                    finally:
                        async with asyncio.timeout(10):
                            await scanner.stop()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except (BleakError, OSError, TimeoutError) as exc:
                self.last_error = (
                    "Не удалось запустить Bluetooth-поиск. Повторите позже."
                )
                log.warning("qingping_scan_failed", error=str(exc))
                await asyncio.sleep(delay)
                delay = min(delay * 2, 20)
            except Exception:
                self.last_error = "Ошибка Bluetooth-поиска. Повторите позже."
                log.exception("qingping_scan_crashed")
                await asyncio.sleep(5)
