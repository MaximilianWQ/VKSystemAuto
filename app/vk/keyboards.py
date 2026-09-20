"""Клавиатуры бота.

Маршрутизация идёт по payload, а не по тексту кнопки: тексты будут меняться,
и привязка к ним ломает бота при первой же правке копирайта.
"""

import json
from collections.abc import Mapping, Sequence

from vkbottle import Keyboard, KeyboardButtonColor, Text

# Ограничения ВК для inline-клавиатуры: до 6 рядов и не более 10 кнопок всего.
MAX_INLINE_BUTTONS = 10
# Темы кладём по две в ряд: восемь тем дают 4 ряда, плюс ряд с кнопкой
# оператора — укладываемся и в 6 рядов, и в 10 кнопок.
MAX_FAQ_ITEMS = 8
FAQ_PER_ROW = 2

# Длинные названия тем режем, иначе кнопка выглядит сломанной.
MAX_LABEL = 40

# ВК ограничивает payload 255 символами.
MAX_PAYLOAD = 255


def _clip(label: str) -> str:
    return label if len(label) <= MAX_LABEL else label[: MAX_LABEL - 1] + "…"


def _payload(**fields: object) -> str:
    """Сериализует payload строкой.

    Документация ВК требует здесь строку, но vkbottle, получив dict, кладёт в
    JSON вложенный объект. Поэтому сериализуем сами, компактно и без экранирования
    кириллицы — иначе быстрее упираемся в лимит 255 символов.
    """
    return json.dumps(fields, ensure_ascii=False, separators=(",", ":"))


def main_menu() -> str:
    keyboard = Keyboard(one_time=False, inline=False)
    keyboard.row().add(Text("Частые вопросы", payload=_payload(cmd="faq")),
                       color=KeyboardButtonColor.PRIMARY)
    keyboard.row().add(Text("Написать оператору", payload=_payload(cmd="ticket_new")),
                       color=KeyboardButtonColor.POSITIVE)
    keyboard.row().add(Text("Мои обращения", payload=_payload(cmd="ticket_list")),
                       color=KeyboardButtonColor.SECONDARY)
    return keyboard.get_json()


def faq_list(items: Sequence[Mapping]) -> str:
    keyboard = Keyboard(one_time=False, inline=True)
    for index, item in enumerate(items[:MAX_FAQ_ITEMS]):
        if index % FAQ_PER_ROW == 0:
            keyboard.row()
        keyboard.add(
            Text(_clip(item["title"]), payload=_payload(cmd="faq_item", id=item["id"])),
            color=KeyboardButtonColor.SECONDARY,
        )
    keyboard.row()
    keyboard.add(
        Text("Написать оператору", payload=_payload(cmd="ticket_new")),
        color=KeyboardButtonColor.POSITIVE,
    )
    return keyboard.get_json()


def ticket_actions(ticket_id: int) -> str:
    keyboard = Keyboard(one_time=False, inline=True)
    keyboard.row().add(
        Text("Закрыть обращение", payload=_payload(cmd="ticket_close", id=ticket_id)),
        color=KeyboardButtonColor.NEGATIVE,
    )
    return keyboard.get_json()


def rating(ticket_id: int) -> str:
    keyboard = Keyboard(one_time=False, inline=True)
    keyboard.row()
    for value in range(1, 6):
        keyboard.add(
            Text(str(value), payload=_payload(cmd="rate", id=ticket_id, v=value)),
            color=KeyboardButtonColor.SECONDARY,
        )
    return keyboard.get_json()


def empty() -> str:
    return Keyboard(one_time=False, inline=False).get_json()
