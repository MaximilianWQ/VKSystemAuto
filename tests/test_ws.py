"""Тесты WebSocket.

TestClient крутит приложение в своём потоке и своём цикле событий, а пул
asyncpg привязан к циклу pytest — работать с настоящей базой отсюда нельзя.
Поэтому проверку сессии подменяем заглушкой: предмет этих тестов — авторизация
сокета, учёт подписчиков и ping/pong, а не драйвер БД. Доставка события
подписчику покрыта тестами шины.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from websockets.exceptions import WebSocketException

from app.web import sessions, ws
from app.web.bus import Bus

VALID = "valid-token"


@pytest.fixture
def app_with_ws(monkeypatch):
    async def fake_verify(pool, token):
        return {"id": "session"} if token == VALID else None

    monkeypatch.setattr(sessions, "verify", fake_verify)

    app = FastAPI()
    app.include_router(ws.router)
    app.state.pool = None
    app.state.bus = Bus()
    return app


def test_rejects_without_cookie(app_with_ws):
    with TestClient(app_with_ws) as http:
        with pytest.raises((WebSocketException, Exception)):  # noqa: B017
            with http.websocket_connect("/ws"):
                pass
    assert app_with_ws.state.bus.subscribers == 0


def test_rejects_bad_cookie(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, "garbage")
        with pytest.raises((WebSocketException, Exception)):  # noqa: B017
            with http.websocket_connect("/ws"):
                pass
    assert app_with_ws.state.bus.subscribers == 0


def test_accepts_valid_cookie_and_greets(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, VALID)
        with http.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "ready"


def test_subscriber_registered_and_released(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, VALID)
        with http.websocket_connect("/ws") as socket:
            socket.receive_json()
            assert app_with_ws.state.bus.subscribers == 1
    assert app_with_ws.state.bus.subscribers == 0


def test_ping_pong(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, VALID)
        with http.websocket_connect("/ws") as socket:
            socket.receive_json()
            socket.send_json({"type": "ping"})
            assert socket.receive_json()["type"] == "pong"
