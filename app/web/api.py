"""REST дашборда. Всё закрыто сессией."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app import texts
from app.db import queries as q
from app.vk import keyboards as kb
from app.vk import outbox
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
