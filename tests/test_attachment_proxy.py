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


class FakeFetcher:
    """Подменяет поход в интернет за содержимым вложения."""

    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    async def __call__(self, url: str):
        self.urls.append(url)
        return self.responses.pop(0)


@pytest.fixture
async def setup(pool):
    await q.upsert_user(pool, 1, "Максим", "Новиков")
    ticket_id = await q.create_ticket(pool, 1)
    message_id = await q.add_message(
        pool, ticket_id, "in", "вот файл",
        [{"type": "doc", "title": "счёт.pdf", "url": "https://vk.com/doc.pdf",
          "ext": "pdf", "size": 10}],
        vk_message_id=555,
    )

    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http, app, message_id


async def test_proxy_requires_session(setup):
    _, app, message_id = setup
    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    assert (await anonymous.get(f"/api/attachments/{message_id}/0")).status_code == 401


async def test_proxy_streams_content(setup, monkeypatch):
    http, _, message_id = setup
    fetch = FakeFetcher([(200, b"%PDF payload", "application/pdf")])
    monkeypatch.setattr(api, "_fetch_attachment", fetch)

    response = await http.get(f"/api/attachments/{message_id}/0")
    assert response.status_code == 200
    assert response.content == b"%PDF payload"
    assert fetch.urls == ["https://vk.com/doc.pdf"]


async def test_proxy_sets_filename(setup, monkeypatch):
    http, _, message_id = setup
    monkeypatch.setattr(api, "_fetch_attachment",
                        FakeFetcher([(200, b"x", "application/pdf")]))
    response = await http.get(f"/api/attachments/{message_id}/0")
    assert "content-disposition" in response.headers


async def test_expired_url_is_refreshed(setup, monkeypatch):
    """Подписанная ссылка протухла — берём свежую через messages.getById."""
    http, app, message_id = setup
    fetch = FakeFetcher([(403, b"", ""), (200, b"fresh file", "application/pdf")])
    monkeypatch.setattr(api, "_fetch_attachment", fetch)

    class FakeVK:
        async def call(self, method, **params):
            assert method == "messages.getById"
            return {"items": [{"attachments": [
                {"type": "doc", "doc": {"id": 1, "owner_id": 2, "title": "счёт.pdf",
                                        "ext": "pdf", "size": 10,
                                        "url": "https://vk.com/fresh.pdf"}}
            ]}]}

    app.state.client = FakeVK()
    response = await http.get(f"/api/attachments/{message_id}/0")
    assert response.status_code == 200
    assert response.content == b"fresh file"
    assert fetch.urls == ["https://vk.com/doc.pdf", "https://vk.com/fresh.pdf"]


async def test_refreshed_url_is_saved(setup, monkeypatch, pool):
    """Обновлённую ссылку сохраняем, чтобы не ходить в ВК на каждый показ."""
    http, app, message_id = setup
    monkeypatch.setattr(api, "_fetch_attachment",
                        FakeFetcher([(403, b"", ""), (200, b"x", "application/pdf")]))

    class FakeVK:
        async def call(self, method, **params):
            return {"items": [{"attachments": [
                {"type": "doc", "doc": {"id": 1, "owner_id": 2, "title": "счёт.pdf",
                                        "ext": "pdf", "size": 10,
                                        "url": "https://vk.com/fresh.pdf"}}
            ]}]}

    app.state.client = FakeVK()
    await http.get(f"/api/attachments/{message_id}/0")
    stored = await pool.fetchval(
        "SELECT attachments FROM ticket_messages WHERE id = $1", message_id)
    assert stored[0]["url"] == "https://vk.com/fresh.pdf"


async def test_unknown_message_is_404(setup):
    http, _, _ = setup
    assert (await http.get("/api/attachments/99999/0")).status_code == 404


async def test_index_out_of_range_is_404(setup):
    http, _, message_id = setup
    assert (await http.get(f"/api/attachments/{message_id}/7")).status_code == 404
