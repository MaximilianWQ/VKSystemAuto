"""Приём событий Callback API.

Правила ВК: на confirmation отвечаем строкой с кодом, на всё остальное — 'ok', и
быстро. Если ok не пришёл вовремя, ВК повторит событие, поэтому обработка уходит
в фон, а дубли отсекаются по event_id.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.db import queries as q

logger = logging.getLogger(__name__)

router = APIRouter()


def spawn(app, event: dict) -> asyncio.Task:
    """Запускает обработку в фоне, удерживая ссылку на задачу.

    Без сохранения ссылки сборщик мусора может убить задачу на середине —
    это известная ловушка asyncio.create_task.
    """

    async def guarded() -> None:
        try:
            await app.state.handler(event)
        except Exception:
            # Падение обработчика не должно превращаться в повтор события от ВК.
            logger.exception("обработка события %s провалилась", event.get("type"))

    task = asyncio.create_task(guarded())
    app.state.background.add(task)
    task.add_done_callback(app.state.background.discard)
    return task


@router.post("/vk/callback", response_class=PlainTextResponse)
async def vk_callback(request: Request) -> str:
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="bad request") from None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="bad request")

    cfg = request.app.state.cfg
    if event.get("group_id") != cfg.vk_group_id:
        raise HTTPException(status_code=403, detail="forbidden")

    if event.get("type") == "confirmation":
        # Секрет здесь не проверяем: при первичном подтверждении в настройках
        # сообщества он может быть ещё не сохранён. Group_id уже сверен выше.
        return cfg.vk_confirmation_code

    if event.get("secret") != cfg.vk_secret_key:
        raise HTTPException(status_code=403, detail="forbidden")

    event_id = event.get("event_id")
    if event_id and not await q.remember_event(request.app.state.pool, str(event_id)):
        return "ok"

    spawn(request.app, event)
    return "ok"
