"""WebSocket-хаб: один мультиплекс-канал событий на клиента (план §3).

Клиент получает JSON ``{"topic": ..., "data": ...}`` для каждого события шины
(состояния устройств, соединения, итоги команд). Подписка индивидуальная с
вытеснением старейших событий — медленный клиент не тормозит остальных.
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from easy_breezy.api.deps import websocket_user
from easy_breezy.container import AppContainer
from easy_breezy.core.events import Subscription

log = structlog.get_logger(__name__)

router = APIRouter()

_WS_UNAUTHORIZED = 4401


@router.websocket("/api/ws")
async def websocket_events(websocket: WebSocket) -> None:
    user = await websocket_user(websocket)
    if user is None:
        # accept обязателен: иначе ASGI ответит 403 без нашего кода закрытия
        await websocket.accept()
        await websocket.close(code=_WS_UNAUTHORIZED, reason="не авторизован")
        return
    await websocket.accept()

    container: AppContainer = websocket.app.state.container
    container.ws_connections.add(websocket)
    try:
        with container.events.subscribe() as subscription:
            forward = asyncio.create_task(_forward_events(websocket, subscription))
            drain = asyncio.create_task(_drain_client(websocket))
            try:
                await asyncio.wait(
                    (forward, drain), return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                forward.cancel()
                drain.cancel()
                # завершившаяся задача могла упасть (send после close) — глотаем
                await asyncio.gather(forward, drain, return_exceptions=True)
    finally:
        container.ws_connections.discard(websocket)
        log.debug("ws_closed", user=user.username)


async def _forward_events(websocket: WebSocket, subscription: Subscription) -> None:
    async for event in subscription:
        await websocket.send_json({"topic": event.topic, "data": event.data})


async def _drain_client(websocket: WebSocket) -> None:
    """Читает входящие (клиент ничего не шлёт) — замечает разрыв соединения."""
    with contextlib.suppress(WebSocketDisconnect):
        while True:
            await websocket.receive_text()
