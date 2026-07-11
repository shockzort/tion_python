"""Callbacks Яндекса: дебаунс, схлопывание, discovery, ретраи."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import (
    TOPIC_DEVICE_LIST_CHANGED,
    TOPIC_STATE_CHANGED,
)
from easy_breezy.integrations.yandex.callbacks import YandexNotifier
from easy_breezy.storage.repos import UserRepo
from tests.conftest import CoreEnv, wait_for_condition

MAC = "FA:KE:00:00:00:01"


class RequestLog:
    def __init__(self, fail_first: int = 0) -> None:
        self.requests: list[tuple[str, dict[str, Any], str]] = []
        self._fail_first = fail_first

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        self.requests.append((request.url.path, json.loads(request.content), auth))
        if self._fail_first > 0:
            self._fail_first -= 1
            return httpx.Response(500)
        return httpx.Response(200, json={"status": "ok"})


async def make_notifier(
    core: CoreEnv, log: RequestLog, **kwargs: Any
) -> YandexNotifier:
    async with core.db.session() as session:
        await UserRepo(session).create(
            username="admin", password_hash="x", created_at=1
        )
    notifier = YandexNotifier(
        core.db,
        core.events,
        core.cache,
        core.registry,
        skill_id="skill-1",
        callback_token="cb-token",
        client=httpx.AsyncClient(transport=httpx.MockTransport(log.handler)),
        debounce=0.05,
        **kwargs,
    )
    await notifier.start()
    return notifier


async def test_disabled_without_credentials(core: CoreEnv) -> None:
    notifier = YandexNotifier(
        core.db,
        core.events,
        core.cache,
        core.registry,
        skill_id=None,
        callback_token=None,
    )
    assert not notifier.enabled
    await notifier.start()  # no-op, задач нет
    core.events.publish(TOPIC_STATE_CHANGED, {"device_uuid": "d1"})
    await notifier.stop()


async def test_state_storm_coalesced_to_single_callback(core: CoreEnv) -> None:
    device = await core.registry.add_device(mac=MAC, name="Спальня")
    await wait_for_condition(
        lambda: core.registry.connection(device.uuid) is ConnectionState.ONLINE
    )
    log = RequestLog()
    notifier = await make_notifier(core, log)
    try:
        # шторм: три события одного устройства в окне дебаунса
        for _ in range(3):
            core.events.publish(
                TOPIC_STATE_CHANGED, {"device_uuid": device.uuid, "state": {}}
            )
        await wait_for_condition(lambda: len(log.requests) >= 1)
        await asyncio.sleep(0.15)  # окно, за которое дубли бы успели прилететь
        state_posts = [r for r in log.requests if r[0].endswith("/callback/state")]
        assert len(state_posts) == 1
        path, payload, auth = state_posts[0]
        assert path == "/api/v1/skills/skill-1/callback/state"
        assert auth == "OAuth cb-token"
        assert payload["payload"]["user_id"] == "1"
        devices = payload["payload"]["devices"]
        assert len(devices) == 1  # схлопнуто по устройству
        capabilities = {
            item["state"]["instance"]: item["state"]["value"]
            for item in devices[0]["capabilities"]
        }
        assert capabilities["on"] is True  # свежее состояние из кэша
    finally:
        await notifier.stop()


async def test_discovery_on_list_change_and_retry(core: CoreEnv) -> None:
    log = RequestLog(fail_first=2)  # два 500 → ретраи добивают
    notifier = await make_notifier(core, log)
    try:
        core.events.publish(TOPIC_DEVICE_LIST_CHANGED, {"action": "added"})
        await wait_for_condition(lambda: len(log.requests) >= 3, timeout=5.0)
        paths = {r[0] for r in log.requests}
        assert paths == {"/api/v1/skills/skill-1/callback/discovery"}
    finally:
        await notifier.stop()


async def test_offline_device_reported_unreachable(core: CoreEnv) -> None:
    log = RequestLog()
    notifier = await make_notifier(core, log)
    try:
        core.events.publish(
            TOPIC_STATE_CHANGED, {"device_uuid": "неизвестный", "state": {}}
        )
        await wait_for_condition(lambda: len(log.requests) >= 1)
        devices = log.requests[0][1]["payload"]["devices"]
        assert devices == [{"id": "неизвестный", "error_code": "DEVICE_UNREACHABLE"}]
    finally:
        await notifier.stop()
