import asyncio
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.vk.callback import router

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код42",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777", "DATABASE_URL": "postgresql://x",
    "SESSION_SECRET": "s" * 32,
}
CFG = load_config(ENV)


@pytest.fixture
def seen():
    return []


@pytest.fixture
def client(pool, seen):
    app = FastAPI()
    app.include_router(router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.background = set()

    async def handler(event):
        seen.append(event)

    app.state.handler = handler
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


async def drain(app):
    """Дожидаемся фоновых задач, порождённых запросом."""
    if app.state.background:
        await asyncio.gather(*list(app.state.background))


def event(**extra):
    base = {
        "type": "message_new", "group_id": 111, "secret": "Zx9KpQm2LtVn",
        "event_id": "evt-1",
        "object": {"message": {"id": 1, "from_id": 5, "peer_id": 5, "text": "привет"}},
    }
    base.update(extra)
    return base


async def test_confirmation_returns_plain_code(client):
    http, _ = client
    response = await http.post("/vk/callback",
                               json={"type": "confirmation", "group_id": 111})
    assert response.status_code == 200
    assert response.text == "код42"
    assert response.headers["content-type"].startswith("text/plain")


async def test_confirmation_from_wrong_group_rejected(client):
    http, _ = client
    response = await http.post("/vk/callback",
                               json={"type": "confirmation", "group_id": 999})
    assert response.status_code == 403


async def test_event_returns_ok(client):
    http, app = client
    response = await http.post("/vk/callback", json=event())
    assert response.status_code == 200
    assert response.text == "ok"
    await drain(app)


async def test_event_reaches_handler(client, seen):
    http, app = client
    await http.post("/vk/callback", json=event())
    await drain(app)
    assert seen[0]["type"] == "message_new"


async def test_wrong_secret_is_rejected(client, seen):
    http, _ = client
    response = await http.post("/vk/callback", json=event(secret="чужой"))
    assert response.status_code == 403
    assert seen == []


async def test_missing_secret_is_rejected(client):
    http, _ = client
    payload = event()
    del payload["secret"]
    assert (await http.post("/vk/callback", json=payload)).status_code == 403


async def test_wrong_group_is_rejected(client):
    http, _ = client
    assert (await http.post("/vk/callback", json=event(group_id=222))).status_code == 403


async def test_duplicate_event_is_handled_once(client, seen):
    """ВК повторяет событие, если не получил ok вовремя. Обработать надо один раз."""
    http, app = client
    for _ in range(5):
        response = await http.post("/vk/callback", json=event())
        assert response.text == "ok"
        await drain(app)
    assert len(seen) == 1


async def test_distinct_events_all_handled(client, seen):
    http, app = client
    for i in range(3):
        await http.post("/vk/callback", json=event(event_id=f"evt-{i}"))
        await drain(app)
    assert len(seen) == 3


async def test_event_without_event_id_is_still_handled(client, seen):
    http, app = client
    payload = event()
    del payload["event_id"]
    await http.post("/vk/callback", json=payload)
    await drain(app)
    assert len(seen) == 1


async def test_handler_failure_does_not_break_response(client, pool):
    """Падение обработчика не должно приводить к повторам от ВК."""
    app = FastAPI()
    app.include_router(router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.background = set()

    async def broken(_event):
        raise RuntimeError("что-то сломалось")

    app.state.handler = broken
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    response = await http.post("/vk/callback", json=event())
    assert response.text == "ok"
    await drain(app)


async def test_malformed_json_returns_400(client):
    http, _ = client
    response = await http.post(
        "/vk/callback", content="{не json".encode(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 400


async def test_response_is_fast(client):
    """Обработка уходит в фон: ВК ждёт ok, а не завершения работы."""
    http, app = client

    async def slow(_event):
        await asyncio.sleep(0.5)

    app.state.handler = slow
    started = time.monotonic()
    await http.post("/vk/callback", json=event())
    assert time.monotonic() - started < 0.1
    await drain(app)


async def test_logs_reason_for_group_mismatch(client, caplog):
    """Без причины в логе отладка сводится к угадыванию."""
    http, _ = client
    with caplog.at_level("WARNING"):
        await http.post("/vk/callback", json=event(group_id=222))
    assert "group_id" in caplog.text


async def test_logs_reason_for_secret_mismatch(client, caplog):
    http, _ = client
    with caplog.at_level("WARNING"):
        await http.post("/vk/callback", json=event(secret="чужой"))
    assert "секрет" in caplog.text


async def test_log_never_contains_secret_values(client, caplog):
    http, _ = client
    with caplog.at_level("WARNING"):
        await http.post("/vk/callback", json=event(secret="подсмотренный-секрет"))
    assert "подсмотренный-секрет" not in caplog.text
    assert CFG.vk_secret_key not in caplog.text


async def test_logs_when_secret_absent_entirely(client, caplog):
    """Пустое поле секрета в настройках ВК — самая частая причина 403."""
    http, _ = client
    payload = event()
    del payload["secret"]
    with caplog.at_level("WARNING"):
        await http.post("/vk/callback", json=payload)
    assert "не передан" in caplog.text
