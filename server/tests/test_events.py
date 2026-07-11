"""Шина событий: fan-out, фильтр тем, переполнение, отписка."""

from __future__ import annotations

import asyncio

from easy_breezy.core.events import (
    TOPIC_COMMAND_FINISHED,
    TOPIC_STATE_CHANGED,
    EventBus,
)


async def test_fanout_to_all_subscribers() -> None:
    bus = EventBus()
    with bus.subscribe() as first, bus.subscribe() as second:
        bus.publish(TOPIC_STATE_CHANGED, {"device": "d1"})
        for subscription in (first, second):
            event = await asyncio.wait_for(subscription.get(), 1)
            assert event.topic == TOPIC_STATE_CHANGED
            assert event.data == {"device": "d1"}


async def test_topic_filter() -> None:
    bus = EventBus()
    with bus.subscribe(TOPIC_COMMAND_FINISHED) as commands_only:
        bus.publish(TOPIC_STATE_CHANGED, {"device": "d1"})
        bus.publish(TOPIC_COMMAND_FINISHED, {"command_id": 7})
        event = await asyncio.wait_for(commands_only.get(), 1)
        assert event.topic == TOPIC_COMMAND_FINISHED
        assert commands_only._queue.empty()


async def test_overflow_drops_oldest() -> None:
    bus = EventBus()
    with bus.subscribe(maxsize=2) as slow:
        for i in range(4):
            bus.publish(TOPIC_STATE_CHANGED, {"seq": i})
        received = [await slow.get() for _ in range(2)]
    # старейшие (0, 1) вытеснены — медленный клиент видит свежие
    assert [event.data["seq"] for event in received] == [2, 3]


async def test_closed_subscription_not_delivered() -> None:
    bus = EventBus()
    subscription = bus.subscribe()
    subscription.close()
    bus.publish(TOPIC_STATE_CHANGED, {})
    assert subscription._queue.empty()


async def test_async_iteration() -> None:
    bus = EventBus()
    with bus.subscribe() as subscription:
        bus.publish(TOPIC_STATE_CHANGED, {"seq": 1})
        bus.publish(TOPIC_STATE_CHANGED, {"seq": 2})
        seen = []
        async for event in subscription:
            seen.append(event.data["seq"])
            if len(seen) == 2:
                break
        assert seen == [1, 2]
