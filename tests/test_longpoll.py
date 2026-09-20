import asyncio

from app.config import load_config
from app.vk.longpoll import run_longpoll

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код",
    "VK_SECRET_KEY": "секрет", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "VK_MODE": "longpoll",
}
CFG = load_config(ENV)


class FakePolling:
    def __init__(self, batches):
        self._batches = batches

    async def listen(self):
        for batch in self._batches:
            yield batch
            await asyncio.sleep(0)


async def test_longpoll_feeds_events_to_handler(pool):
    seen = []

    async def handler(event):
        seen.append(event)

    stop = asyncio.Event()
    polling = FakePolling([{"updates": [
        {"type": "message_new", "object": {"message": {"from_id": 1}}},
        {"type": "message_new", "object": {"message": {"from_id": 2}}},
    ]}])

    await run_longpoll(polling, handler, stop)
    assert [e["object"]["message"]["from_id"] for e in seen] == [1, 2]


async def test_longpoll_survives_handler_error(pool):
    seen = []

    async def handler(event):
        if event["object"]["message"]["from_id"] == 1:
            raise RuntimeError("сломалось")
        seen.append(event)

    polling = FakePolling([{"updates": [
        {"type": "message_new", "object": {"message": {"from_id": 1}}},
        {"type": "message_new", "object": {"message": {"from_id": 2}}},
    ]}])

    await run_longpoll(polling, handler, asyncio.Event())
    assert len(seen) == 1


async def test_longpoll_stops_on_event(pool):
    stop = asyncio.Event()
    stop.set()
    seen = []

    async def handler(event):
        seen.append(event)

    polling = FakePolling([{"updates": [{"type": "message_new", "object": {}}]}])
    await asyncio.wait_for(run_longpoll(polling, handler, stop), timeout=1)
    assert seen == []
