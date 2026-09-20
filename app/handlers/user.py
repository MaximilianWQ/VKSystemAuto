"""Обработка событий от пользователей.

Единственная точка входа — handle_event. Все ответы уходят только через outbox.
"""

import json
import logging

import asyncpg

from app import setup_tokens, texts
from app.config import Config
from app.db import queries as q
from app.vk import keyboards as kb
from app.vk import outbox
from app.vk.attachments import parse_attachments, parse_geo
from app.workhours import is_working_now, next_working_time

logger = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_AWAITING_PROBLEM = "awaiting_problem"

MENU_WORDS = {"начать", "меню", "start", "старт", "привет"}


def _parse_payload(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        # Битый payload — не повод падать, откатываемся на меню.
        return {}
    return value if isinstance(value, dict) else {}


async def handle_event(pool: asyncpg.Pool, cfg: Config, event: dict) -> None:
    if event.get("type") != "message_new":
        return
    message = (event.get("object") or {}).get("message") or {}
    await _handle_message(pool, cfg, message)


async def _handle_message(pool: asyncpg.Pool, cfg: Config, message: dict) -> None:
    user_id = message.get("from_id", 0)
    if user_id <= 0:
        # Отрицательный from_id — сообщение от сообщества, не от человека.
        return

    peer_id = message.get("peer_id", user_id)
    await q.upsert_user(pool, user_id)

    text = (message.get("text") or "").strip()
    payload = _parse_payload(message.get("payload"))
    command = payload.get("cmd", "")

    if user_id == cfg.admin_id and text == "/link":
        await _send_setup_link(pool, cfg, peer_id)
        return

    if command == "faq":
        await _send_faq_list(pool, peer_id)
    elif command == "faq_item":
        await _send_faq_answer(pool, peer_id, payload.get("id"))
    elif command == "ticket_new":
        await _start_ticket(pool, user_id, peer_id)
    elif command == "ticket_list":
        await _send_ticket_list(pool, user_id, peer_id)
    elif command == "ticket_close":
        await _close_ticket(pool, user_id, peer_id, payload.get("id"))
    elif command == "rate":
        await _save_rating(pool, user_id, peer_id, payload.get("id"), payload.get("v"))
    elif command == "menu" or text.lower() in MENU_WORDS:
        await _send_menu(pool, peer_id)
    else:
        await _handle_free_text(pool, cfg, user_id, peer_id, message, text)


async def _send_setup_link(pool: asyncpg.Pool, cfg: Config, peer_id: int) -> None:
    if not cfg.public_url:
        await outbox.enqueue(pool, peer_id, texts.SETUP_LINK_NO_URL)
        return
    token = await setup_tokens.issue(pool)
    url = f"{cfg.public_url}/setup?token={token}"
    await outbox.enqueue(pool, peer_id, texts.SETUP_LINK.format(url=url))


async def _send_menu(pool: asyncpg.Pool, peer_id: int) -> None:
    await outbox.enqueue(pool, peer_id, texts.GREETING, keyboard=kb.main_menu())


async def _send_faq_list(pool: asyncpg.Pool, peer_id: int) -> None:
    items = await q.list_active_faq(pool)
    body = texts.FAQ_EMPTY if not items else "Выберите тему:"
    await outbox.enqueue(pool, peer_id, body, keyboard=kb.faq_list(items))


async def _send_faq_answer(pool: asyncpg.Pool, peer_id: int, faq_id) -> None:
    item = await q.get_faq(pool, faq_id) if isinstance(faq_id, int) else None
    items = await q.list_active_faq(pool)
    if item is None:
        await outbox.enqueue(pool, peer_id, texts.FAQ_NOT_FOUND, keyboard=kb.faq_list(items))
        return
    await outbox.enqueue(pool, peer_id, item["answer"], keyboard=kb.faq_list(items))


async def _start_ticket(pool: asyncpg.Pool, user_id: int, peer_id: int) -> None:
    existing = await q.get_open_ticket(pool, user_id)
    if existing is not None:
        await outbox.enqueue(
            pool, peer_id,
            texts.TICKET_CREATED.format(id=existing["id"]),
            keyboard=kb.ticket_actions(existing["id"]),
        )
        return
    await q.set_user_state(pool, user_id, STATE_AWAITING_PROBLEM)
    await outbox.enqueue(pool, peer_id, texts.ASK_PROBLEM)


async def _send_ticket_list(pool: asyncpg.Pool, user_id: int, peer_id: int) -> None:
    ticket = await q.get_open_ticket(pool, user_id)
    if ticket is None:
        await outbox.enqueue(pool, peer_id, texts.NO_TICKETS, keyboard=kb.main_menu())
        return
    line = texts.TICKET_LINE.format(
        id=ticket["id"],
        status=texts.STATUS_NAMES.get(ticket["status"], ticket["status"]),
        created=ticket["created_at"].strftime("%d.%m %H:%M"),
    )
    await outbox.enqueue(
        pool, peer_id, f"{texts.TICKET_LIST_HEADER}\n{line}",
        keyboard=kb.ticket_actions(ticket["id"]),
    )


async def _close_ticket(pool: asyncpg.Pool, user_id: int, peer_id: int, ticket_id) -> None:
    ticket = await q.get_open_ticket(pool, user_id)
    # Закрыть можно только своё обращение: id из payload подделывается тривиально.
    if ticket is None or ticket["id"] != ticket_id:
        await outbox.enqueue(pool, peer_id, texts.NO_TICKETS, keyboard=kb.main_menu())
        return
    await q.close_ticket(pool, ticket["id"])
    await outbox.enqueue(
        pool, peer_id,
        f"{texts.TICKET_CLOSED.format(id=ticket['id'])}\n{texts.ASK_RATING}",
        keyboard=kb.rating(ticket["id"]),
    )


async def _save_rating(
    pool: asyncpg.Pool, user_id: int, peer_id: int, ticket_id, value
) -> None:
    if not isinstance(ticket_id, int) or value not in (1, 2, 3, 4, 5):
        return
    owner = await pool.fetchval("SELECT user_id FROM tickets WHERE id = $1", ticket_id)
    if owner != user_id:
        return
    await pool.execute("UPDATE tickets SET rating = $2 WHERE id = $1", ticket_id, value)
    await outbox.enqueue(pool, peer_id, texts.THANKS_FOR_RATING, keyboard=kb.main_menu())


async def _handle_free_text(
    pool: asyncpg.Pool, cfg: Config, user_id: int, peer_id: int,
    message: dict, text: str,
) -> None:
    items = parse_attachments(message.get("attachments") or [])
    geo = parse_geo(message.get("geo"))
    if geo:
        items.append(geo)

    ticket = await q.get_open_ticket(pool, user_id)
    if ticket is not None:
        await q.add_message(pool, ticket["id"], "in", text, items, message.get("id"))
        return

    user = await q.get_user(pool, user_id)
    if user is None or user["state"] != STATE_AWAITING_PROBLEM:
        await _send_menu(pool, peer_id)
        return

    ticket_id = await q.create_ticket(pool, user_id)
    await q.add_message(pool, ticket_id, "in", text, items, message.get("id"))
    await q.set_user_state(pool, user_id, STATE_IDLE)

    await outbox.enqueue(
        pool, peer_id, texts.TICKET_CREATED.format(id=ticket_id),
        keyboard=kb.ticket_actions(ticket_id),
    )
    if not is_working_now(cfg):
        await outbox.enqueue(
            pool, peer_id, texts.OFF_HOURS.format(when=next_working_time(cfg))
        )
