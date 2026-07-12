"""Web push (VAPID) о сбоях: бризер офлайн > 10 мин, провал бэкапа (FR-32).

VAPID-ключи генерируются при первом старте в ``data_dir/vapid_private.pem``.
Подписки живут в БД; мёртвые endpoint'ы (404/410 от пуш-сервиса) удаляются
при отправке. Надзор за офлайном — минутный цикл на инжектируемых часах:
уведомление один раз на эпизод офлайна, восстановление сбрасывает эпизод.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid
from pywebpush import WebPushException, webpush

from easy_breezy.automation.clock import Clock
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import TOPIC_BACKUP_FAILED, EventBus, Subscription
from easy_breezy.storage import Database
from easy_breezy.storage.repos import DeviceRepo
from easy_breezy.storage.repos.push import PushRepo

log = structlog.get_logger(__name__)

OFFLINE_NOTIFY_SECONDS = 600.0
_CHECK_INTERVAL = 60.0


def _load_or_create_vapid(pem_path: Path) -> Vapid:
    if pem_path.exists():
        return Vapid.from_file(str(pem_path))
    pem_path.parent.mkdir(parents=True, exist_ok=True)
    vapid = Vapid()
    vapid.generate_keys()
    vapid.save_key(str(pem_path))
    pem_path.chmod(0o600)
    log.info("push_vapid_generated", path=str(pem_path))
    return vapid


def _public_key_b64(vapid: Vapid) -> str:
    assert vapid.public_key is not None
    raw = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class PushService:
    def __init__(
        self,
        db: Database,
        events: EventBus,
        connections: Callable[[], dict[str, ConnectionState]],
        data_dir: Path,
        clock: Clock,
        *,
        contact: str,
        offline_after: float = OFFLINE_NOTIFY_SECONDS,
    ) -> None:
        self._db = db
        self._events = events
        self._connections = connections
        self._pem_path = data_dir / "vapid_private.pem"
        self._clock = clock
        self._contact = contact
        self._offline_after = offline_after
        self._vapid: Vapid | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._subscription: Subscription | None = None
        self._offline_since: dict[str, float] = {}
        self._notified: set[str] = set()

    @property
    def public_key(self) -> str:
        """applicationServerKey для браузера (base64url)."""
        assert self._vapid is not None, "PushService не запущен"
        return _public_key_b64(self._vapid)

    async def start(self) -> None:
        self._vapid = await asyncio.to_thread(_load_or_create_vapid, self._pem_path)
        self._subscription = self._events.subscribe(TOPIC_BACKUP_FAILED)
        self._tasks = [
            asyncio.create_task(
                self._watch_events(self._subscription), name="push-events"
            ),
            asyncio.create_task(self._offline_loop(), name="push-offline"),
        ]

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

    # --- подписки ----------------------------------------------------------------

    async def subscribe(self, *, endpoint: str, keys: dict[str, Any]) -> None:
        async with self._db.session() as session:
            await PushRepo(session).upsert(
                endpoint=endpoint, keys=keys, created_at=int(self._clock.now())
            )
        log.info("push_subscribed", endpoint=endpoint[:60])

    async def unsubscribe(self, endpoint: str) -> bool:
        async with self._db.session() as session:
            removed = await PushRepo(session).delete_by_endpoint(endpoint)
        if removed:
            log.info("push_unsubscribed", endpoint=endpoint[:60])
        return removed

    # --- отправка ------------------------------------------------------------------

    async def send_to_all(self, title: str, body: str) -> int:
        """Шлёт уведомление всем подпискам; возвращает число доставленных."""
        assert self._vapid is not None, "PushService не запущен"
        async with self._db.session() as session:
            subscriptions = [
                {"endpoint": record.endpoint, "keys": record.keys}
                for record in await PushRepo(session).list_all()
            ]
        if not subscriptions:
            return 0
        payload = json.dumps({"title": title, "body": body})
        delivered = 0
        dead: list[str] = []
        for info in subscriptions:
            try:
                await asyncio.to_thread(self._send_one, info, payload)
                delivered += 1
            except WebPushException as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status in (404, 410):  # подписка мертва — браузер её отозвал
                    dead.append(str(info["endpoint"]))
                else:
                    log.warning("push_send_failed", status=status, error=str(exc))
        for endpoint in dead:
            await self.unsubscribe(endpoint)
        log.info("push_sent", title=title, delivered=delivered, dead=len(dead))
        return delivered

    def _send_one(self, info: dict[str, Any], payload: str) -> None:
        webpush(
            subscription_info=info,
            data=payload,
            vapid_private_key=str(self._pem_path),
            vapid_claims={"sub": self._contact},
            timeout=10,
        )

    # --- источники уведомлений -------------------------------------------------------

    async def _watch_events(self, subscription: Subscription) -> None:
        async for event in subscription:
            try:
                error = str(event.data.get("error", ""))[:120]
                await self.send_to_all(
                    "Провал бэкапа", f"Снапшот БД не создан: {error}"
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # уведомитель не имеет права умирать молча (ADR-0007)
                log.exception("push_event_crashed")

    async def _offline_loop(self) -> None:
        while True:
            await self._clock.sleep(_CHECK_INTERVAL)
            try:
                await self.check_offline_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("push_offline_crashed")

    async def check_offline_once(self) -> None:
        """Шаг надзора за офлайном; выделен для time-travel тестов."""
        now = self._clock.now()
        connections = self._connections()
        overdue: list[str] = []
        for device_uuid, state in connections.items():
            if state is ConnectionState.ONLINE:
                self._offline_since.pop(device_uuid, None)
                self._notified.discard(device_uuid)
                continue
            since = self._offline_since.setdefault(device_uuid, now)
            if now - since >= self._offline_after and device_uuid not in self._notified:
                self._notified.add(device_uuid)
                overdue.append(device_uuid)
        for device_uuid in overdue:
            name = await self._device_name(device_uuid)
            minutes = int(self._offline_after // 60)
            await self.send_to_all(
                "Бризер не на связи",
                f"«{name}» офлайн дольше {minutes} минут.",
            )

    async def _device_name(self, device_uuid: str) -> str:
        async with self._db.session() as session:
            device = await DeviceRepo(session).get(device_uuid)
        return device.name if device is not None else device_uuid
