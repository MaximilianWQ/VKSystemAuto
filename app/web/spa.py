"""Отдача собранной PWA.

SPA-фолбэк обязан пропускать /api, /ws и /vk: иначе он перехватит вебхук ВК и
вернёт ему HTML вместо 'ok', а ВК начнёт бесконечно повторять события.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
RESERVED_PREFIXES = ("api/", "ws", "vk/", "healthz", "docs", "redoc", "openapi.json")


def is_reserved(path: str) -> bool:
    cleaned = path.lstrip("/")
    return any(
        cleaned == prefix.rstrip("/") or cleaned.startswith(prefix)
        for prefix in RESERVED_PREFIXES
    )


def _collect(dist: Path) -> dict[str, Path]:
    """Составляет карту «путь → файл» один раз при старте.

    Состав сборки в контейнере неизменен, поэтому обходить файловую систему на
    каждый запрос незачем: в асинхронном обработчике это блокирующие вызовы.
    """
    root = dist.resolve()
    return {
        str(item.relative_to(root)): item
        for item in root.rglob("*")
        if item.is_file()
    }


def mount(app: FastAPI, dist: Path = DIST) -> bool:
    """Подключает статику. Возвращает False, если сборки нет.

    Отсутствие сборки — не повод падать: бот должен работать и без дашборда.
    """
    if not (dist / "index.html").exists():
        logger.warning("сборка дашборда не найдена в %s, отдаём только API", dist)
        return False

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    files = _collect(dist)
    index = dist / "index.html"
    logger.info("дашборд подключён, файлов в сборке: %s", len(files))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(request: Request, full_path: str) -> FileResponse:  # noqa: ARG001
        if is_reserved(full_path):
            raise HTTPException(status_code=404, detail="not found")
        # Только то, что реально лежит в сборке. Обхода каталога не существует:
        # путь ищется в заранее составленной карте, а не склеивается с диском.
        target = files.get(full_path.lstrip("/"))
        return FileResponse(target if target is not None else index)

    return True
