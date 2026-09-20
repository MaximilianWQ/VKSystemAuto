"""WebSocket для дашборда.

Авторизация той же сессионной кукой, что и REST: отдельный токен в адресе
светил бы сессию в логах прокси.
"""

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.web import sessions

logger = logging.getLogger(__name__)

router = APIRouter()

PING_INTERVAL = 25.0


@router.websocket("/ws")
async def dashboard_socket(socket: WebSocket) -> None:
    token = socket.cookies.get(sessions.COOKIE_NAME, "")
    if await sessions.verify(socket.app.state.pool, token) is None:
        await socket.close(code=4401)
        return

    await socket.accept()
    bus = socket.app.state.bus
    queue = bus.subscribe()
    await socket.send_json({"type": "ready"})

    async def pump() -> None:
        while True:
            event = await queue.get()
            await socket.send_json(event)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    socket.receive_json(), timeout=PING_INTERVAL
                )
            except TimeoutError:
                # Тишина в обе стороны убивает соединение на прокси Railway.
                await socket.send_json({"type": "ping"})
                continue
            if message.get("type") == "ping":
                await socket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("websocket оборвался с ошибкой")
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        bus.unsubscribe(queue)
