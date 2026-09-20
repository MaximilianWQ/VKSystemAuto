"""Персоны поддержки.

Оператор один, но клиенту представляется живой человек с именем и должностью.
Имя закрепляется за обращением при взятии в работу и больше не меняется:
клиент уже прочитал, кем ему представились.

Роли разделены на два уровня. «Взять как руководителя» — это эскалация, и
клиент прочитает её именно так, поэтому уровень выбирается осознанно, а не
случайно.
"""

import random
from dataclasses import dataclass

NAMES = (
    "Алексей", "Анна", "Дмитрий", "Екатерина", "Иван", "Мария", "Максим",
    "Наталья", "Ольга", "Павел", "Сергей", "Татьяна",
)

OPERATOR_ROLES = (
    "оператор техподдержки",
    "старший оператор поддержки",
    "инженер технической поддержки",
    "специалист по биллингу",
    "специалист службы безопасности",
)

LEAD_ROLES = (
    "руководитель службы поддержки",
    "руководитель отдела качества",
)

TIERS = {"operator": OPERATOR_ROLES, "lead": LEAD_ROLES}


@dataclass(frozen=True)
class Persona:
    name: str
    role: str
    tier: str

    @property
    def signature(self) -> str:
        return f"{self.name}, {self.role}"


def roles(tier: str) -> tuple[str, ...]:
    if tier not in TIERS:
        raise ValueError(f"неизвестный уровень: {tier}")
    return TIERS[tier]


def pick(tier: str, rng: random.Random | None = None) -> Persona:
    """Случайные имя и роль внутри выбранного уровня."""
    chooser = rng or random
    # S311: выбираем отображаемое имя, а не секрет. Предсказуемость здесь
    # ничем не грозит, а secrets ради подписи в чате — лишнее.
    return Persona(
        name=chooser.choice(NAMES),  # noqa: S311
        role=chooser.choice(roles(tier)),  # noqa: S311
        tier=tier,
    )


def all_roles() -> dict[str, tuple[str, ...]]:
    return {tier: value for tier, value in TIERS.items()}
