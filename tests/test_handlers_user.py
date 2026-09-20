import json
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import load_config
from app.db import queries as q
from app.handlers.user import handle_event

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "1", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "s", "ADMIN_ID": "777", "DATABASE_URL": "postgresql://x",
    "SESSION_SECRET": "s" * 32, "WORK_HOURS": "0-24",
}
CFG = load_config(ENV)

# Окно в один час, заведомо не совпадающее с текущим: иначе тест нерабочего
# времени зелёный или красный в зависимости от часа запуска.
_HOUR = datetime.now(ZoneInfo("Europe/Moscow")).hour
CLOSED_START = (_HOUR + 3) % 22
NIGHT_CFG = load_config({**ENV, "WORK_HOURS": f"{CLOSED_START}-{CLOSED_START + 1}"})


def message_new(from_id=1, text="", payload=None, attachments=None, message_id=100):
    return {
        "type": "message_new",
        "object": {
            "message": {
                "id": message_id,
                "from_id": from_id,
                "peer_id": from_id,
                "text": text,
                "payload": json.dumps(payload) if payload else None,
                "attachments": attachments or [],
            },
            "client_info": {"keyboard": True, "inline_keyboard": True},
        },
    }


async def sent(pool) -> list[dict]:
    rows = await pool.fetch("SELECT payload FROM outbox ORDER BY id")
    return [r["payload"] for r in rows]


async def test_greets_new_user(pool):
    await handle_event(pool, CFG, message_new(text="Начать"))
    messages = await sent(pool)
    assert len(messages) == 1
    assert "keyboard" in messages[0]
    assert json.loads(messages[0]["keyboard"])["inline"] is False


async def test_creates_user_record(pool):
    await handle_event(pool, CFG, message_new(from_id=55, text="привет"))
    assert await q.get_user(pool, 55) is not None


async def test_ignores_messages_from_communities(pool):
    await handle_event(pool, CFG, message_new(from_id=-123, text="спам"))
    assert await sent(pool) == []


async def test_faq_button_lists_topics(pool):
    await pool.execute("INSERT INTO faq (title, answer, position) VALUES ('Подписка','ответ',1)")
    await handle_event(pool, CFG, message_new(payload={"cmd": "faq"}))
    keyboard = json.loads((await sent(pool))[0]["keyboard"])
    assert keyboard["inline"] is True
    labels = [b["action"]["label"] for row in keyboard["buttons"] for b in row]
    assert "Подписка" in labels


async def test_faq_item_returns_answer(pool):
    faq_id = await pool.fetchval(
        "INSERT INTO faq (title, answer, position) VALUES ('Оплата','Платите картой',1)"
        " RETURNING id"
    )
    await handle_event(pool, CFG, message_new(payload={"cmd": "faq_item", "id": faq_id}))
    assert "Платите картой" in (await sent(pool))[0]["message"]


async def test_faq_item_missing_does_not_crash(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "faq_item", "id": 999}))
    assert len(await sent(pool)) == 1


async def test_ticket_new_asks_to_describe_problem(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    assert (await q.get_user(pool, 1))["state"] == "awaiting_problem"
    # Само обращение ещё не создано — ждём описание проблемы.
    assert await pool.fetchval("SELECT count(*) FROM tickets") == 0


async def test_next_message_creates_ticket(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    await handle_event(pool, CFG, message_new(text="подписка не работает"))

    ticket = await q.get_open_ticket(pool, 1)
    assert ticket is not None
    body = await pool.fetchval(
        "SELECT text FROM ticket_messages WHERE ticket_id = $1", ticket["id"]
    )
    assert body == "подписка не работает"
    assert (await q.get_user(pool, 1))["state"] == "idle"


async def test_further_messages_append_to_open_ticket(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    await handle_event(pool, CFG, message_new(text="раз"))
    await handle_event(pool, CFG, message_new(text="два"))
    await handle_event(pool, CFG, message_new(text="три"))

    ticket = await q.get_open_ticket(pool, 1)
    count = await pool.fetchval(
        "SELECT count(*) FROM ticket_messages WHERE ticket_id = $1", ticket["id"]
    )
    assert count == 3
    assert await pool.fetchval("SELECT count(*) FROM tickets") == 1


async def test_attachments_are_stored_with_message(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    photo = {"type": "photo", "photo": {"id": 1, "owner_id": 2,
                                        "sizes": [{"url": "big.jpg", "width": 1000}]}}
    await handle_event(pool, CFG, message_new(text="вот скрин", attachments=[photo]))

    ticket = await q.get_open_ticket(pool, 1)
    stored = await pool.fetchval(
        "SELECT attachments FROM ticket_messages WHERE ticket_id = $1", ticket["id"]
    )
    assert stored[0]["type"] == "photo"
    assert stored[0]["url"] == "big.jpg"


async def test_attachment_only_message_is_not_dropped(pool):
    """Сообщение без текста, но со скриншотом — самый частый случай в поддержке."""
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    photo = {"type": "photo", "photo": {"id": 1, "owner_id": 2, "sizes": []}}
    await handle_event(pool, CFG, message_new(text="", attachments=[photo]))

    ticket = await q.get_open_ticket(pool, 1)
    assert ticket is not None


async def test_off_hours_autoreply(pool):
    await handle_event(pool, NIGHT_CFG, message_new(payload={"cmd": "ticket_new"}))
    await handle_event(pool, NIGHT_CFG, message_new(text="проблема"))
    bodies = " ".join(m["message"] for m in await sent(pool))
    assert f"с {CLOSED_START:02d}:00" in bodies


async def test_ticket_list_when_empty(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_list"}))
    assert "нет" in (await sent(pool))[0]["message"].lower()


async def test_ticket_list_shows_open_ticket(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    await handle_event(pool, CFG, message_new(text="проблема"))
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_list"}))

    ticket = await q.get_open_ticket(pool, 1)
    assert f"№{ticket['id']}" in (await sent(pool))[-1]["message"]


async def test_close_ticket_asks_for_rating(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    await handle_event(pool, CFG, message_new(text="проблема"))
    ticket = await q.get_open_ticket(pool, 1)

    await handle_event(pool, CFG,
                       message_new(payload={"cmd": "ticket_close", "id": ticket["id"]}))
    assert await q.get_open_ticket(pool, 1) is None
    keyboard = json.loads((await sent(pool))[-1]["keyboard"])
    values = [json.loads(b["action"]["payload"])["v"]
              for row in keyboard["buttons"] for b in row]
    assert values == [1, 2, 3, 4, 5]


async def test_rating_is_saved(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    await handle_event(pool, CFG, message_new(text="проблема"))
    ticket = await q.get_open_ticket(pool, 1)
    await handle_event(pool, CFG,
                       message_new(payload={"cmd": "ticket_close", "id": ticket["id"]}))
    await handle_event(pool, CFG,
                       message_new(payload={"cmd": "rate", "id": ticket["id"], "v": 5}))

    assert await pool.fetchval("SELECT rating FROM tickets WHERE id=$1", ticket["id"]) == 5


async def test_cannot_close_someone_elses_ticket(pool):
    await handle_event(pool, CFG, message_new(from_id=1, payload={"cmd": "ticket_new"}))
    await handle_event(pool, CFG, message_new(from_id=1, text="проблема"))
    victim = await q.get_open_ticket(pool, 1)

    await handle_event(pool, CFG,
                       message_new(from_id=2, payload={"cmd": "ticket_close",
                                                       "id": victim["id"]}))
    assert await q.get_open_ticket(pool, 1) is not None


async def test_malformed_payload_falls_back_to_menu(pool):
    event = message_new(text="привет")
    event["object"]["message"]["payload"] = "{это не json"
    await handle_event(pool, CFG, event)
    assert len(await sent(pool)) == 1


async def test_text_commands_work_without_keyboard(pool):
    """У старых клиентов ВК клавиатуры нет — команды должны работать текстом."""
    await handle_event(pool, CFG, message_new(text="меню"))
    assert len(await sent(pool)) == 1


async def test_unknown_event_type_is_ignored(pool):
    await handle_event(pool, CFG, {"type": "group_join", "object": {}})
    assert await sent(pool) == []


ADMIN_CFG = load_config({**ENV, "PUBLIC_URL": "https://bot.example"})


async def test_link_command_sends_one_time_url_to_admin(pool):
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="/link"))
    body = (await sent(pool))[0]["message"]
    assert "https://bot.example/setup?token=" in body
    assert await pool.fetchval("SELECT count(*) FROM setup_tokens") == 1


async def test_link_command_ignored_from_non_admin(pool):
    """Чужой /link не должен ни выдавать токен, ни намекать на его существование."""
    await handle_event(pool, ADMIN_CFG, message_new(from_id=5, text="/link"))
    assert await pool.fetchval("SELECT count(*) FROM setup_tokens") == 0
    messages = await sent(pool)
    assert all("setup?token=" not in m["message"] for m in messages)


async def test_link_command_without_public_url_reports_problem(pool):
    await handle_event(pool, CFG, message_new(from_id=777, text="/link"))
    assert "PUBLIC_URL" in (await sent(pool))[0]["message"]


async def test_each_link_issues_a_new_token(pool):
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="/link"))
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="/link"))
    assert await pool.fetchval("SELECT count(*) FROM setup_tokens") == 2


async def test_admin_can_still_use_the_bot_normally(pool):
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="Начать"))
    assert "keyboard" in (await sent(pool))[0]


async def test_notify_called_for_message_in_open_ticket(pool):
    seen = []

    async def notify(event):
        seen.append(event)

    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}), notify=notify)
    await handle_event(pool, CFG, message_new(text="проблема"), notify=notify)
    await handle_event(pool, CFG, message_new(text="ещё деталь"), notify=notify)

    assert len(seen) == 2
    assert seen[-1]["type"] == "message"
    assert seen[-1]["text"] == "ещё деталь"
    assert seen[-1]["user_id"] == 1
    assert seen[-1]["ticket_id"] == (await q.get_open_ticket(pool, 1))["id"]


async def test_notify_carries_attachments(pool):
    seen = []

    async def notify(event):
        seen.append(event)

    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}), notify=notify)
    photo = {"type": "photo", "photo": {"id": 1, "owner_id": 2,
                                        "sizes": [{"url": "big.jpg", "width": 900}]}}
    await handle_event(pool, CFG, message_new(text="", attachments=[photo]), notify=notify)
    assert seen[-1]["attachments"][0]["type"] == "photo"


async def test_notify_not_called_for_menu_clicks(pool):
    """Нажатие кнопки меню — не обращение, дёргать оператора незачем."""
    seen = []

    async def notify(event):
        seen.append(event)

    await handle_event(pool, CFG, message_new(text="Начать"), notify=notify)
    await handle_event(pool, CFG, message_new(payload={"cmd": "faq"}), notify=notify)
    assert seen == []


async def test_handler_survives_broken_notify(pool):
    """Упавшее уведомление не должно терять сообщение клиента."""
    async def notify(event):
        raise RuntimeError("шина сломалась")

    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}), notify=notify)
    await handle_event(pool, CFG, message_new(text="проблема"), notify=notify)

    ticket = await q.get_open_ticket(pool, 1)
    assert ticket is not None
    assert await pool.fetchval(
        "SELECT count(*) FROM ticket_messages WHERE ticket_id = $1", ticket["id"]) == 1


async def test_works_without_notify(pool):
    await handle_event(pool, CFG, message_new(payload={"cmd": "ticket_new"}))
    await handle_event(pool, CFG, message_new(text="проблема"))
    assert await q.get_open_ticket(pool, 1) is not None


async def test_dashboard_word_sends_link(pool):
    """Команду должно быть легко набрать с телефона, без слешей и латиницы."""
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="дашборд"))
    assert "https://bot.example/setup?token=" in (await sent(pool))[0]["message"]


async def test_dashboard_word_is_case_insensitive(pool):
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="Дашборд"))
    assert "setup?token=" in (await sent(pool))[0]["message"]


async def test_dashboard_word_tolerates_spaces(pool):
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="  дашборд  "))
    assert "setup?token=" in (await sent(pool))[0]["message"]


async def test_slash_link_still_works(pool):
    await handle_event(pool, ADMIN_CFG, message_new(from_id=777, text="/link"))
    assert "setup?token=" in (await sent(pool))[0]["message"]


async def test_dashboard_word_ignored_from_non_admin(pool):
    """Обычный пользователь не должен ни получить ссылку, ни узнать о её существовании."""
    await handle_event(pool, ADMIN_CFG, message_new(from_id=5, text="дашборд"))
    assert await pool.fetchval("SELECT count(*) FROM setup_tokens") == 0
    assert all("setup?token=" not in m["message"] for m in await sent(pool))


async def test_dashboard_word_from_non_admin_falls_back_to_menu(pool):
    """Для чужого это просто непонятный текст — показываем меню, а не молчим."""
    await handle_event(pool, ADMIN_CFG, message_new(from_id=5, text="дашборд"))
    messages = await sent(pool)
    assert len(messages) == 1
    assert "keyboard" in messages[0]
