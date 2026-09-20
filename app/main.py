"""Точка входа. Один процесс: вебхук ВК, фоновая отправка и уборка."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Config, load_config
from app.db.pool import apply_migrations, create_pool
from app.handlers.user import handle_event
from app.maintenance import run_housekeeping
from app.vk import outbox
from app.vk.attachments import describe
from app.vk.callback import router as callback_router
from app.vk.client import build_client
from app.vk.longpoll import build_polling, run_longpoll
from app.web import push as web_push
from app.web.api import router as api_router
from app.web.auth import router as auth_router
from app.web.bus import Bus
from app.web.push import router as push_router
from app.web.ws import router as ws_router

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)


PUSH_PREVIEW_LIMIT = 120


def build_notifier(
    pool, cfg: Config, bus: Bus,
    send_push: Callable[[dict], Awaitable[None]] | None,
):
    """Событие уходит в открытый дашборд, а если его никто не смотрит — в пуш."""

    async def notify(event: dict) -> None:
        delivered = await bus.publish(event)
        if delivered or send_push is None:
            return

        text = (event.get("text") or "").strip()
        summary = describe(event.get("attachments") or [])
        body = ", ".join(part for part in (text[:PUSH_PREVIEW_LIMIT], summary) if part)
        await send_push({
            "title": "Новое сообщение",
            "body": body or "Вложение",
            "ticket_id": event.get("ticket_id"),
        })

    return notify


def create_app(cfg: Config) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.pool = await create_pool(cfg.database_url)
        await apply_migrations(application.state.pool)
        # Строки, застрявшие в 'sending' после прошлого падения, возвращаем в работу.
        await outbox.recover_stuck(application.state.pool)

        client = build_client(cfg)
        application.state.client = client
        stop = asyncio.Event()
        application.state.stop = stop

        tasks = [
            asyncio.create_task(outbox.run_worker(application.state.pool, client, stop)),
            asyncio.create_task(run_housekeeping(application.state.pool, stop)),
        ]
        if cfg.vk_mode == "longpoll":
            tasks.append(asyncio.create_task(
                run_longpoll(build_polling(cfg), application.state.handler, stop)
            ))
        application.state.tasks = tasks
        logger.info("бот запущен в режиме %s", cfg.vk_mode)

        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await application.state.pool.close()

    application = FastAPI(title="VK Support Bot", lifespan=lifespan)
    application.state.cfg = cfg
    application.state.background = set()
    application.state.bus = Bus()
    application.include_router(callback_router)
    application.include_router(auth_router)
    application.include_router(api_router)
    application.include_router(push_router)
    application.include_router(ws_router)

    @application.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    async def handler(event: dict) -> None:
        async def send_push(payload: dict) -> None:
            await web_push.send_to_all(application.state.pool, cfg, payload)

        notify = build_notifier(
            application.state.pool, cfg, application.state.bus,
            send_push if cfg.dashboard_ready else None,
        )
        await handle_event(application.state.pool, cfg, event, notify=notify)

    application.state.handler = handler
    return application


def build_from_env() -> FastAPI:
    """Фабрика для uvicorn. Конфиг читается при запуске, а не при импорте,
    иначе модуль нельзя импортировать в тестах без полного окружения."""
    return create_app(load_config(os.environ))
