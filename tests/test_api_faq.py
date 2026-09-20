import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


def build_app(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return app


@pytest.fixture
async def client(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


async def test_faq_requires_session(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    assert (await http.get("/api/faq")).status_code == 401
    assert (await http.post("/api/faq", json={"title": "x", "answer": "y"})).status_code == 401


async def test_empty_list(client):
    assert (await client.get("/api/faq")).json() == []


async def test_create_returns_item(client):
    response = await client.post(
        "/api/faq", json={"title": "Подписка", "answer": "Оплатите картой"})
    assert response.status_code == 200
    item = response.json()
    assert item["title"] == "Подписка"
    assert item["answer"] == "Оплатите картой"
    assert item["is_active"] is True


async def test_created_items_keep_order(client):
    for title in ("Первая", "Вторая", "Третья"):
        await client.post("/api/faq", json={"title": title, "answer": "ответ"})
    assert [i["title"] for i in (await client.get("/api/faq")).json()] == [
        "Первая", "Вторая", "Третья"]


async def test_create_rejects_empty_fields(client):
    assert (await client.post("/api/faq", json={"title": "", "answer": "y"})).status_code == 400
    assert (await client.post("/api/faq", json={"title": "x", "answer": " "})).status_code == 400


async def test_create_rejects_overlong_title(client):
    """Длинная тема не влезет в кнопку ВК."""
    response = await client.post("/api/faq", json={"title": "я" * 201, "answer": "ответ"})
    assert response.status_code == 400


async def test_update_changes_fields(client):
    created = (await client.post("/api/faq", json={"title": "Старое", "answer": "старый"})).json()
    updated = (await client.patch(
        f"/api/faq/{created['id']}", json={"title": "Новое"})).json()
    assert updated["title"] == "Новое"
    assert updated["answer"] == "старый"


async def test_update_can_hide_topic(client, pool):
    """Выключенная тема исчезает у клиента, но остаётся у оператора."""
    created = (await client.post("/api/faq", json={"title": "Тема", "answer": "ответ"})).json()
    await client.patch(f"/api/faq/{created['id']}", json={"is_active": False})

    assert await q.list_active_faq(pool) == []
    assert len((await client.get("/api/faq")).json()) == 1


async def test_update_rejects_empty_values(client):
    created = (await client.post("/api/faq", json={"title": "Тема", "answer": "ответ"})).json()
    assert (await client.patch(f"/api/faq/{created['id']}", json={"title": " "})).status_code == 400
    assert (await client.patch(f"/api/faq/{created['id']}", json={"answer": ""})).status_code == 400


async def test_update_unknown_is_404(client):
    assert (await client.patch("/api/faq/999", json={"title": "x"})).status_code == 404


async def test_delete_removes_topic(client):
    created = (await client.post("/api/faq", json={"title": "Тема", "answer": "ответ"})).json()
    assert (await client.delete(f"/api/faq/{created['id']}")).status_code == 200
    assert (await client.get("/api/faq")).json() == []


async def test_delete_unknown_is_404(client):
    assert (await client.delete("/api/faq/999")).status_code == 404


async def test_reorder_applies_new_order(client):
    ids = []
    for title in ("Первая", "Вторая", "Третья"):
        ids.append((await client.post(
            "/api/faq", json={"title": title, "answer": "ответ"})).json()["id"])

    await client.post("/api/faq/reorder", json={"ids": [ids[2], ids[0], ids[1]]})
    assert [i["title"] for i in (await client.get("/api/faq")).json()] == [
        "Третья", "Первая", "Вторая"]


async def test_reorder_rejects_garbage(client):
    assert (await client.post("/api/faq/reorder", json={"ids": "нет"})).status_code == 400
    assert (await client.post("/api/faq/reorder", json={"ids": ["a"]})).status_code == 400


async def test_topics_reach_the_bot(client, pool):
    """Главное: созданная тема появляется у клиента в боте."""
    await client.post("/api/faq", json={"title": "Оплата", "answer": "Платите картой"})
    items = await q.list_active_faq(pool)
    assert [i["title"] for i in items] == ["Оплата"]
    assert items[0]["answer"] == "Платите картой"
