"""Точка входа. Один процесс: вебхук ВК, фоновая отправка и уборка."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Config, load_config
from app.db.pool import apply_migrations, create_pool
from app.handlers.user import handle_event
from app.maintenance import run_housekeeping
from app.vk import outbox
from app.vk.callback import router as callback_router
from app.vk.client import build_client
from app.vk.longpoll import build_polling, run_longpoll

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)


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
    application.include_router(callback_router)

    @application.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    async def handler(event: dict) -> None:
        await handle_event(application.state.pool, cfg, event)

    application.state.handler = handler
    return application


def build_from_env() -> FastAPI:
    """Фабрика для uvicorn. Конфиг читается при запуске, а не при импорте,
    иначе модуль нельзя импортировать в тестах без полного окружения."""
    return create_app(load_config(os.environ))
