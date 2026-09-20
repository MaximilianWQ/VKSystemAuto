import random

import pytest

from app import personas


def test_two_tiers_exist():
    assert set(personas.TIERS) == {"operator", "lead"}


def test_seven_roles_total():
    """Семь должностей, как договаривались."""
    assert len(personas.OPERATOR_ROLES) + len(personas.LEAD_ROLES) == 7


def test_roles_do_not_overlap():
    assert not set(personas.OPERATOR_ROLES) & set(personas.LEAD_ROLES)


def test_lead_tier_reads_as_escalation():
    assert all("руководитель" in role for role in personas.LEAD_ROLES)


def test_pick_stays_within_tier():
    for _ in range(50):
        assert personas.pick("operator").role in personas.OPERATOR_ROLES
        assert personas.pick("lead").role in personas.LEAD_ROLES


def test_pick_uses_known_names():
    assert personas.pick("operator").name in personas.NAMES


def test_pick_is_deterministic_with_seed():
    """Нужно для тестов: без этого поведение нельзя проверить."""
    first = personas.pick("operator", random.Random(7))  # noqa: S311
    second = personas.pick("operator", random.Random(7))  # noqa: S311
    assert first == second


def test_pick_varies():
    seen = {personas.pick("operator").signature for _ in range(200)}
    assert len(seen) > 5


def test_unknown_tier_is_rejected():
    with pytest.raises(ValueError, match="неизвестный уровень"):
        personas.pick("директор")


def test_signature_reads_naturally():
    persona = personas.Persona(name="Иван", role="инженер технической поддержки",
                               tier="operator")
    assert persona.signature == "Иван, инженер технической поддержки"
