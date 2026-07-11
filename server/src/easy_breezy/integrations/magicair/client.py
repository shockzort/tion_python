"""Опрос датчиков CO₂ через облако MagicAir (план §10, FR-25).

Протокол сверен с референсом github.com/airens/tion: OAuth2 password grant
с публичными кредами мобильного приложения, затем ``GET /location`` —
иерархия локация → зоны → устройства. Датчиками считаются устройства,
у которых ``type`` содержит ``co2`` (CO2+, MagicAir-станция); их ``data``
несёт co2/temperature/humidity (NaN отбрасывает ``clean_metrics``).

Деградация по NFR: облако недоступно — warning с растущим backoff,
сервис живёт, триггер-защёлки держатся (минутный sweep движка отметит
молчание датчиков).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import structlog

from easy_breezy.core.sensors import KIND_MAGICAIR, SensorIngest

log = structlog.get_logger(__name__)

TOKEN_URL = "https://api2.magicair.tion.ru/idsrv/oauth2/token"
LOCATION_URL = "https://api2.magicair.tion.ru/location"
# публичные креды мобильного приложения Tion (референс airens/tion)
CLIENT_ID = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
CLIENT_SECRET = "syRxSrT77P"

POLL_INTERVAL_SECONDS = 60.0
_BACKOFF_MAX = 600.0
_HTTP_TIMEOUT = 15.0


class MagicAirPoller:
    def __init__(
        self,
        ingest: SensorIngest,
        *,
        email: str | None,
        password: str | None,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._ingest = ingest
        self._email = email
        self._password = password
        self._client = client
        self._owns_client = client is None
        self._sleep = sleep
        self._now = now
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._email and self._password)

    async def start(self) -> None:
        if not self.enabled:
            log.info("magicair_disabled")
            return
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        self._task = asyncio.create_task(self._poll_loop(), name="magicair-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _poll_loop(self) -> None:
        backoff = POLL_INTERVAL_SECONDS
        while True:
            try:
                ingested = await self.poll_once()
                log.debug("magicair_polled", sensors=ingested)
                backoff = POLL_INTERVAL_SECONDS
            except asyncio.CancelledError:
                raise
            except httpx.HTTPError as exc:
                self._token = None  # возможно, протух — перелогин на следующем круге
                log.warning("magicair_poll_failed", error=str(exc))
                backoff = min(backoff * 2, _BACKOFF_MAX)
            except Exception:
                # опрос не имеет права умирать молча (ADR-0007)
                log.exception("magicair_poll_crashed")
                backoff = min(backoff * 2, _BACKOFF_MAX)
            await self._sleep(backoff)

    async def poll_once(self) -> int:
        """Один проход опроса; возвращает число принятых датчиков."""
        assert self._client is not None  # start() создал клиента
        token = await self._ensure_token()
        response = await self._client.get(
            LOCATION_URL, headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 401:  # токен отозван — один перелогин
            self._token = None
            token = await self._ensure_token()
            response = await self._client.get(
                LOCATION_URL, headers={"Authorization": f"Bearer {token}"}
            )
        response.raise_for_status()
        ingested = 0
        for device in _iter_co2_devices(response.json()):
            sensor_id = await self._ingest.ingest(
                kind=KIND_MAGICAIR,
                source_key=f"magicair:{device['guid']}",
                name=device.get("name") or f"MagicAir {str(device['guid'])[:8]}",
                metrics=device.get("data") or {},
                auto_register=True,
            )
            if sensor_id is not None:
                ingested += 1
        return ingested

    async def _ensure_token(self) -> str:
        assert self._client is not None
        if self._token is not None and self._now() < self._token_expires_at:
            return self._token
        response = await self._client.post(
            TOKEN_URL,
            data={
                "username": self._email,
                "password": self._password,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "password",
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._token = str(payload["access_token"])
        expires_in = float(payload.get("expires_in", 3600))
        self._token_expires_at = self._now() + expires_in - 60
        log.info("magicair_authenticated")
        return self._token


def _iter_co2_devices(locations: Any) -> list[dict[str, Any]]:
    """CO₂-датчики из ответа /location (устойчиво к кривым записям)."""
    found: list[dict[str, Any]] = []
    if not isinstance(locations, list):
        return found
    for location in locations:
        if not isinstance(location, dict):
            continue
        for zone in location.get("zones") or []:
            if not isinstance(zone, dict):
                continue
            for device in zone.get("devices") or []:
                if not isinstance(device, dict) or "guid" not in device:
                    continue
                if "co2" in str(device.get("type", "")).lower():
                    found.append(device)
    return found
