import json

from app.vk import keyboards as kb


def buttons(raw: str) -> list[dict]:
    """Все кнопки клавиатуры одним списком."""
    return [b for row in json.loads(raw)["buttons"] for b in row]


def payloads(raw: str) -> list[dict]:
    return [json.loads(b["action"]["payload"]) for b in buttons(raw)]


def test_main_menu_has_three_commands():
    assert [p["cmd"] for p in payloads(kb.main_menu())] == ["faq", "ticket_new", "ticket_list"]


def test_main_menu_is_not_inline():
    """Главное меню должно висеть под полем ввода, а не в сообщении."""
    assert json.loads(kb.main_menu())["inline"] is False


def test_faq_list_is_inline():
    assert json.loads(kb.faq_list([{"id": 1, "title": "Подписка"}]))["inline"] is True


def test_faq_list_carries_item_ids():
    raw = kb.faq_list([{"id": 4, "title": "Оплата"}, {"id": 7, "title": "Доступ"}])
    assert payloads(raw)[:2] == [
        {"cmd": "faq_item", "id": 4},
        {"cmd": "faq_item", "id": 7},
    ]


def test_faq_list_ends_with_operator_button():
    raw = kb.faq_list([{"id": 1, "title": "Подписка"}])
    assert payloads(raw)[-1] == {"cmd": "ticket_new"}


def test_faq_list_respects_vk_inline_limit():
    """ВК не принимает inline-клавиатуру больше 10 кнопок — обрезаем заранее."""
    many = [{"id": i, "title": f"Тема {i}"} for i in range(30)]
    raw = kb.faq_list(many)
    assert len(buttons(raw)) <= kb.MAX_INLINE_BUTTONS
    assert len(json.loads(raw)["buttons"]) <= 6


def test_faq_list_without_items_offers_operator_only():
    assert payloads(kb.faq_list([])) == [{"cmd": "ticket_new"}]


def test_ticket_actions_carries_ticket_id():
    assert payloads(kb.ticket_actions(42)) == [{"cmd": "ticket_close", "id": 42}]


def test_rating_has_five_options():
    values = [p["v"] for p in payloads(kb.rating(42))]
    assert values == [1, 2, 3, 4, 5]
    assert all(p["id"] == 42 for p in payloads(kb.rating(42)))


def test_payload_is_a_string_not_an_object():
    """ВК ожидает payload строкой. vkbottle из dict делает вложенный объект —
    поэтому сериализуем сами, иначе ломается и лимит 255, и разбор на входе."""
    for button in buttons(kb.main_menu()):
        assert isinstance(button["action"]["payload"], str)


def test_every_payload_fits_vk_limit():
    """ВК режет payload длиннее 255 символов."""
    samples = [
        kb.main_menu(),
        kb.faq_list([{"id": 999999, "title": "Очень длинное название темы" * 5}]),
        kb.ticket_actions(999999999),
        kb.rating(999999999),
    ]
    for raw in samples:
        for button in buttons(raw):
            assert len(button["action"]["payload"]) <= 255


def test_empty_keyboard_has_no_buttons():
    assert json.loads(kb.empty())["buttons"] == []
