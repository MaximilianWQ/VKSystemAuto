import asyncio

from app.web.bus import Bus


async def test_subscriber_receives_event():
    bus = Bus()
    queue = bus.subscribe()
    await bus.publish({"type": "message", "ticket_id": 1})
    assert (await asyncio.wait_for(queue.get(), timeout=1))["ticket_id"] == 1


async def test_every_subscriber_receives_event():
    bus = Bus()
    first, second = bus.subscribe(), bus.subscribe()
    delivered = await bus.publish({"type": "message"})
    assert delivered == 2
    assert first.qsize() == 1
    assert second.qsize() == 1


async def test_publish_without_subscribers_is_harmless():
    assert await Bus().publish({"type": "message"}) == 0


async def test_unsubscribe_stops_delivery():
    bus = Bus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    assert await bus.publish({"type": "message"}) == 0
    assert queue.empty()


async def test_subscriber_count():
    bus = Bus()
    assert bus.subscribers == 0
    queue = bus.subscribe()
    assert bus.subscribers == 1
    bus.unsubscribe(queue)
    assert bus.subscribers == 0


async def test_slow_subscriber_does_not_block_others():
    """Забитая очередь одного клиента не должна ломать доставку остальным."""
    bus = Bus(max_queue=2)
    slow, fast = bus.subscribe(), bus.subscribe()
    for i in range(5):
        await bus.publish({"type": "message", "n": i})
    assert slow.qsize() == 2
    assert fast.qsize() == 2


async def test_unsubscribe_twice_is_safe():
    bus = Bus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    bus.unsubscribe(queue)
