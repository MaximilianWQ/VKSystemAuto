import io

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.vk import attachments
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


class FakeUploader:
    """Подменяет аплоадеры vkbottle: в тестах в ВК не ходим."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def upload(self, file_source, peer_id=None, **params):
        self.calls.append((file_source, peer_id, params))
        return self.result


class FakeClient:
    def api_for_uploads(self):
        return None


def build_app(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.client = FakeClient()
    return app


@pytest.fixture
async def client(pool, monkeypatch):
    photo = FakeUploader("photo1_2")
    doc = FakeUploader("doc3_4")
    monkeypatch.setattr(attachments, "_photo_uploader", lambda api: photo)
    monkeypatch.setattr(attachments, "_doc_uploader", lambda api: doc)

    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http, photo, doc


def test_picks_photo_uploader_for_images():
    assert attachments.pick_uploader("image/png", "скрин.png") == "photo"
    assert attachments.pick_uploader("image/jpeg", "фото.jpg") == "photo"


def test_picks_doc_uploader_for_everything_else():
    assert attachments.pick_uploader("application/pdf", "счёт.pdf") == "doc"
    assert attachments.pick_uploader("", "архив.zip") == "doc"


def test_gif_goes_as_document():
    """ВК показывает гифку как документ, а не как фото."""
    assert attachments.pick_uploader("image/gif", "анимация.gif") == "doc"


def test_falls_back_to_extension_when_type_missing():
    assert attachments.pick_uploader("", "скрин.PNG") == "photo"


async def test_upload_image_returns_photo_attachment(client):
    http, photo, _ = client
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("скрин.png", io.BytesIO(b"\x89PNG data"), "image/png")},
    )
    assert response.status_code == 200
    assert response.json() == {"attachment": "photo1_2"}
    assert photo.calls[0][1] == 1


async def test_upload_pdf_returns_doc_attachment(client):
    http, _, doc = client
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("счёт.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.json() == {"attachment": "doc3_4"}
    assert doc.calls[0][1] == 1


async def test_upload_requires_session(pool):
    http = AsyncClient(transport=ASGITransport(app=build_app(pool)), base_url="https://test")
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("a.png", io.BytesIO(b"x"), "image/png")},
    )
    assert response.status_code == 401


async def test_empty_file_rejected(client):
    http, _, _ = client
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("пусто.png", io.BytesIO(b""), "image/png")},
    )
    assert response.status_code == 400


async def test_oversized_file_rejected(client, monkeypatch):
    http, _, _ = client
    monkeypatch.setattr(attachments, "MAX_UPLOAD_BYTES", 10)
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("большой.png", io.BytesIO(b"x" * 100), "image/png")},
    )
    assert response.status_code == 413


async def test_uploaded_attachment_can_be_sent(client, pool):
    """Полный круг: загрузили файл, приложили к ответу, ответ встал в очередь."""
    http, _, _ = client
    await q.upsert_user(pool, 1, "Максим", "Новиков")
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "in", "вопрос")

    uploaded = (await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("скрин.png", io.BytesIO(b"\x89PNG"), "image/png")},
    )).json()["attachment"]

    await http.post(f"/api/dialogs/{ticket_id}/reply",
                    json={"text": "вот так", "attachment": uploaded})
    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["payload"]["attachment"] == "photo1_2"
