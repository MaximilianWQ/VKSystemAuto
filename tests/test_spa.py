from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.web import spa


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Поддержка</title>", "utf-8")
    (tmp_path / "manifest.webmanifest").write_text('{"name":"Поддержка"}', "utf-8")
    (tmp_path / "sw.js").write_text("// worker", "utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", "utf-8")
    return tmp_path


@pytest.fixture
def client(dist):
    app = FastAPI()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/api/dialogs")
    async def dialogs():
        return []

    assert spa.mount(app, dist) is True
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


def test_reserved_paths_recognised():
    for path in ("api/dialogs", "/api/dialogs", "ws", "vk/callback", "healthz"):
        assert spa.is_reserved(path), path


def test_app_paths_are_not_reserved():
    for path in ("", "login", "setup", "stats", "manifest.webmanifest"):
        assert not spa.is_reserved(path), path


async def test_root_serves_index(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "Поддержка" in response.text


async def test_unknown_route_falls_back_to_index(client):
    """Маршруты приложения обслуживает сам фронт, сервер отдаёт оболочку."""
    response = await client.get("/stats")
    assert response.status_code == 200
    assert "Поддержка" in response.text


async def test_setup_link_opens(client):
    response = await client.get("/setup?token=abc")
    assert response.status_code == 200


async def test_real_file_is_served(client):
    assert (await client.get("/sw.js")).status_code == 200


async def test_manifest_is_served(client):
    response = await client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert "Поддержка" in response.text


async def test_api_is_not_swallowed(client):
    """Главная опасность фолбэка — перехватить API и вернуть HTML."""
    response = await client.get("/api/dialogs")
    assert response.status_code == 200
    assert response.json() == []


async def test_unknown_api_path_is_404_not_html(client):
    response = await client.get("/api/выдуманное")
    assert response.status_code == 404
    assert "<!doctype" not in response.text.lower()


async def test_healthz_still_works(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}


async def test_vk_callback_path_never_gets_html(client):
    """Если вебхук получит HTML вместо 'ok', ВК зациклит повторы событий."""
    response = await client.get("/vk/callback")
    assert response.status_code in (404, 405)
    assert "<!doctype" not in response.text.lower()


async def test_directory_traversal_is_blocked(client):
    response = await client.get("/../../etc/passwd")
    assert "root:" not in response.text


async def test_missing_build_is_tolerated(tmp_path):
    """Бот обязан работать, даже если фронт не собран."""
    app = FastAPI()
    assert spa.mount(app, tmp_path) is False
