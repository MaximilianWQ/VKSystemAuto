"""REST дашборда. Всё закрыто сессией."""

import logging
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response as RawResponse

from app import texts
from app.db import queries as q
from app.vk import attachments as vk_attachments
from app.vk import keyboards as kb
from app.vk import outbox
from app.vk.attachments import parse_attachments
from app.web import sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(sessions.require_session)])


def _full_name(first: str, last: str) -> str:
    return " ".join(part for part in (first, last) if part) or "Без имени"


def _dialog(row) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "unread": row["unread_count"],
        "preview": row["preview"] or "",
        "preview_attachments": row["preview_attachments"] or [],
        "waiting_seconds": row["waiting_seconds"],
        "created_at": row["created_at"].isoformat(),
        "last_message_at": row["last_message_at"].isoformat(),
        "rating": row["rating"],
        "user": {
            "vk_id": row["vk_id"],
            "name": _full_name(row["first_name"], row["last_name"]),
            "photo_url": row["photo_url"],
            "can_write": row["can_write"],
        },
    }


def _message(row) -> dict:
    return {
        "id": row["id"],
        "direction": row["direction"],
        "text": row["text"],
        "attachments": row["attachments"] or [],
        "created_at": row["created_at"].isoformat(),
        "read_at": row["read_at"].isoformat() if row["read_at"] else None,
    }


@router.get("/dialogs")
async def list_dialogs(request: Request, status: str = "open") -> list[dict]:
    rows = await q.list_dialogs(request.app.state.pool, status=status)
    return [_dialog(row) for row in rows]


@router.get("/dialogs/{ticket_id}/messages")
async def list_messages(request: Request, ticket_id: int) -> dict:
    pool = request.app.state.pool
    ticket = await q.get_ticket(pool, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="обращение не найдено")
    rows = await q.list_messages(pool, ticket_id)
    return {
        "ticket": {
            "id": ticket["id"],
            "status": ticket["status"],
            "rating": ticket["rating"],
            "user": {
                "vk_id": ticket["user_id"],
                "name": _full_name(ticket["first_name"], ticket["last_name"]),
                "photo_url": ticket["photo_url"],
                "can_write": ticket["can_write"],
            },
        },
        "messages": [_message(row) for row in rows],
    }


@router.post("/dialogs/{ticket_id}/read")
async def mark_read(request: Request, ticket_id: int) -> dict:
    pool = request.app.state.pool
    if await q.get_ticket(pool, ticket_id) is None:
        raise HTTPException(status_code=404, detail="обращение не найдено")
    await q.mark_read(pool, ticket_id)
    return {"ok": True}


@router.post("/dialogs/{ticket_id}/reply")
async def reply(request: Request, ticket_id: int) -> dict:
    body = await request.json()
    text = str(body.get("text", "")).strip()
    attachment = body.get("attachment") or None
    if not text and not attachment:
        raise HTTPException(status_code=400, detail="пустой ответ")

    pool = request.app.state.pool
    ticket = await q.get_ticket(pool, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="обращение не найдено")
    if not ticket["can_write"]:
        raise HTTPException(
            status_code=409, detail="пользователь запретил сообщения от сообщества"
        )

    await q.add_message(pool, ticket_id, "out", text)
    await q.mark_read(pool, ticket_id)
    await outbox.enqueue(pool, ticket["user_id"], text, attachment=attachment)
    return {"ok": True}


@router.post("/dialogs/{ticket_id}/close")
async def close(request: Request, ticket_id: int) -> dict:
    pool = request.app.state.pool
    ticket = await q.get_ticket(pool, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="обращение не найдено")
    if ticket["status"] == "closed":
        raise HTTPException(status_code=409, detail="обращение уже закрыто")

    await q.close_ticket(pool, ticket_id)
    if ticket["can_write"]:
        await outbox.enqueue(
            pool, ticket["user_id"],
            f"{texts.TICKET_CLOSED.format(id=ticket_id)}\n{texts.ASK_RATING}",
            keyboard=kb.rating(ticket_id),
        )
    return {"ok": True}


@router.get("/stats")
async def stats(request: Request) -> dict:
    row = await q.stats(request.app.state.pool)
    return {
        "day": row["day"],
        "week": row["week"],
        "open_now": row["open_now"],
        "avg_first_reply_seconds": round(float(row["avg_first_reply"]), 1)
        if row["avg_first_reply"] is not None else None,
        "avg_rating": round(float(row["avg_rating"]), 2)
        if row["avg_rating"] is not None else None,
    }


@router.post("/uploads")
async def upload(request: Request, peer_id: int, file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="пустой файл")
    if len(data) > vk_attachments.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="файл слишком большой")

    filename = file.filename or "файл"
    api = request.app.state.client.api_for_uploads()
    kind = vk_attachments.pick_uploader(file.content_type or "", filename)
    if kind == "photo":
        attachment = await vk_attachments.upload_photo(api, peer_id, data, filename)
    else:
        attachment = await vk_attachments.upload_doc(api, peer_id, data, filename)
    return {"attachment": attachment}


ATTACHMENT_TIMEOUT = 30.0

# Вложения присылают произвольные пользователи ВК, а документом можно загрузить
# .html или .svg. Отдать такое inline на домене дашборда — значит выполнить чужой
# скрипт с правами оператора: сессионная кука HttpOnly, но запросы к API она не
# остановит. Поэтому inline разрешён только тому, что заведомо не исполняется,
# всё остальное уходит на скачивание с обезличенным типом.
INLINE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/gif",
    "audio/ogg", "audio/mpeg", "audio/mp4", "audio/aac",
    "video/mp4", "video/webm",
})
NEUTRAL_TYPE = "application/octet-stream"
HARDENING_HEADERS = {
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'none'; sandbox",
    "referrer-policy": "no-referrer",
}


def _safe_disposition(content_type: str) -> tuple[str, str]:
    """Возвращает безопасный тип и способ показа для полученного содержимого."""
    bare = (content_type or "").split(";", 1)[0].strip().lower()
    if bare in INLINE_TYPES:
        return bare, "inline"
    # Сюда попадают text/html, image/svg+xml, application/pdf и всё незнакомое.
    return NEUTRAL_TYPE, "attachment"


async def _fetch_attachment(url: str) -> tuple[int, bytes, str]:
    """Возвращает статус, тело и тип содержимого. Вынесено ради подмены в тестах."""
    async with httpx.AsyncClient(timeout=ATTACHMENT_TIMEOUT, follow_redirects=True) as http:
        response = await http.get(url)
        return (
            response.status_code,
            response.content,
            response.headers.get("content-type", "application/octet-stream"),
        )


def _attachment_url(item: dict) -> str:
    return item.get("url") or item.get("link_ogg") or item.get("link_mp3") or ""


def _attachment_name(item: dict, index: int) -> str:
    title = item.get("title") or ""
    if title:
        return title
    kinds = {"photo": "фото.jpg", "audio_message": "голосовое.ogg", "sticker": "стикер.png"}
    return kinds.get(item.get("type", ""), f"вложение-{index}")


async def _refresh_attachments(request: Request, row) -> list[dict] | None:
    """Перезапрашивает вложения сообщения: подписанные ссылки ВК протухают."""
    client = getattr(request.app.state, "client", None)
    if client is None or not row["vk_message_id"]:
        return None
    try:
        payload = await client.call("messages.getById", message_ids=row["vk_message_id"])
    except Exception:
        logger.warning("не удалось обновить ссылки вложений сообщения %s", row["id"])
        return None

    items = (payload.get("items") or [{}])[0].get("attachments") or []
    fresh = parse_attachments(items)
    if not fresh:
        return None
    await request.app.state.pool.execute(
        "UPDATE ticket_messages SET attachments = $2 WHERE id = $1", row["id"], fresh
    )
    return fresh


@router.get("/attachments/{message_id}/{index}")
async def attachment(request: Request, message_id: int, index: int) -> RawResponse:
    pool = request.app.state.pool
    row = await pool.fetchrow("SELECT * FROM ticket_messages WHERE id = $1", message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="сообщение не найдено")

    items = row["attachments"] or []
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail="вложение не найдено")

    url = _attachment_url(items[index])
    if not url:
        raise HTTPException(status_code=404, detail="у вложения нет ссылки")
    if not url.startswith("https://"):
        # Схема приходит из данных ВК; выпускать прокси на file:// или http:// незачем.
        raise HTTPException(status_code=400, detail="недопустимая ссылка вложения")

    status, body, content_type = await _fetch_attachment(url)
    if status in (401, 403, 410):
        # Подписанная ссылка протухла — берём свежую и пробуем ещё раз.
        fresh = await _refresh_attachments(request, row)
        if fresh and index < len(fresh):
            url = _attachment_url(fresh[index])
            if url.startswith("https://"):
                status, body, content_type = await _fetch_attachment(url)
                items = fresh

    if status != 200:
        raise HTTPException(status_code=502, detail="вложение недоступно")

    name = _attachment_name(items[index], index)
    safe_type, disposition = _safe_disposition(content_type)
    return RawResponse(
        content=body,
        media_type=safe_type,
        headers={
            "content-disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
            **HARDENING_HEADERS,
        },
    )
