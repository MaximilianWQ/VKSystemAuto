import pytest

from app.config import ConfigError, load_config

BASE_ENV = {
    "VK_GROUP_TOKEN": "tok",
    "VK_GROUP_ID": "123",
    "VK_CONFIRMATION_CODE": "abc123",
    "VK_SECRET_KEY": "sec",
    "ADMIN_ID": "456",
    "DATABASE_URL": "postgresql://localhost/test",
    "SESSION_SECRET": "s" * 32,
}


def test_loads_required_values():
    cfg = load_config(BASE_ENV)
    assert cfg.vk_group_id == 123
    assert cfg.admin_id == 456
    assert cfg.vk_group_token == "tok"


def test_applies_defaults():
    cfg = load_config(BASE_ENV)
    assert cfg.vk_api_version == "5.199"
    assert cfg.vk_mode == "callback"
    assert cfg.work_hours == (10, 19)
    assert cfg.tz == "Europe/Moscow"


def test_parses_work_hours():
    cfg = load_config({**BASE_ENV, "WORK_HOURS": "9-21"})
    assert cfg.work_hours == (9, 21)


def test_rejects_missing_required():
    env = {k: v for k, v in BASE_ENV.items() if k != "VK_GROUP_TOKEN"}
    with pytest.raises(ConfigError, match="VK_GROUP_TOKEN"):
        load_config(env)


def test_rejects_non_numeric_group_id():
    with pytest.raises(ConfigError, match="VK_GROUP_ID"):
        load_config({**BASE_ENV, "VK_GROUP_ID": "не число"})


def test_rejects_bad_work_hours():
    with pytest.raises(ConfigError, match="WORK_HOURS"):
        load_config({**BASE_ENV, "WORK_HOURS": "21-9"})


def test_rejects_unknown_vk_mode():
    with pytest.raises(ConfigError, match="VK_MODE"):
        load_config({**BASE_ENV, "VK_MODE": "webhook"})


def test_rejects_short_session_secret():
    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        load_config({**BASE_ENV, "SESSION_SECRET": "short"})


def test_dashboard_values_optional_for_now():
    cfg = load_config(BASE_ENV)
    assert cfg.webauthn_rp_id == ""
    assert cfg.vapid_public_key == ""


def test_public_url_defaults_to_empty():
    assert load_config(BASE_ENV).public_url == ""


def test_public_url_trailing_slash_removed():
    cfg = load_config({**BASE_ENV, "PUBLIC_URL": "https://bot.up.railway.app/"})
    assert cfg.public_url == "https://bot.up.railway.app"


def test_accepts_legacy_vk_token_name():
    """В Railway переменная уже называется VK_TOKEN — не заставляем её переименовывать."""
    env = {k: v for k, v in BASE_ENV.items() if k != "VK_GROUP_TOKEN"}
    cfg = load_config({**env, "VK_TOKEN": "из-railway"})
    assert cfg.vk_group_token == "из-railway"


def test_group_token_wins_over_legacy_name():
    cfg = load_config({**BASE_ENV, "VK_TOKEN": "старый"})
    assert cfg.vk_group_token == "tok"


def test_missing_both_token_names_is_an_error():
    env = {k: v for k, v in BASE_ENV.items() if k != "VK_GROUP_TOKEN"}
    with pytest.raises(ConfigError, match="VK_GROUP_TOKEN"):
        load_config(env)


def test_public_url_derived_from_railway_domain():
    """Railway сам подставляет RAILWAY_PUBLIC_DOMAIN — PUBLIC_URL задавать не нужно."""
    cfg = load_config({**BASE_ENV, "RAILWAY_PUBLIC_DOMAIN": "vkbot.up.railway.app"})
    assert cfg.public_url == "https://vkbot.up.railway.app"


def test_explicit_public_url_wins_over_railway_domain():
    cfg = load_config({
        **BASE_ENV,
        "PUBLIC_URL": "https://support.example.ru",
        "RAILWAY_PUBLIC_DOMAIN": "vkbot.up.railway.app",
    })
    assert cfg.public_url == "https://support.example.ru"


def test_railway_domain_with_scheme_is_not_doubled():
    cfg = load_config({**BASE_ENV, "RAILWAY_PUBLIC_DOMAIN": "https://vkbot.up.railway.app"})
    assert cfg.public_url == "https://vkbot.up.railway.app"


from app.config import require_dashboard  # noqa: E402

DASHBOARD_ENV = {
    "WEBAUTHN_RP_ID": "bot.example",
    "WEBAUTHN_ORIGIN": "https://bot.example",
    "VAPID_PUBLIC_KEY": "B" * 87,
    "VAPID_PRIVATE_KEY": "p" * 43,
    "VAPID_SUBJECT": "mailto:admin@example.com",
}


def test_dashboard_not_ready_without_keys():
    assert load_config(BASE_ENV).dashboard_ready is False


def test_dashboard_ready_with_all_keys():
    assert load_config({**BASE_ENV, **DASHBOARD_ENV}).dashboard_ready is True


def test_require_dashboard_lists_every_missing_variable():
    with pytest.raises(ConfigError) as exc:
        require_dashboard(load_config(BASE_ENV))
    message = str(exc.value)
    for name in DASHBOARD_ENV:
        assert name in message


def test_require_dashboard_passes_when_configured():
    require_dashboard(load_config({**BASE_ENV, **DASHBOARD_ENV}))


def test_rp_id_derived_from_public_url():
    """RP ID — это голый домен без схемы и порта."""
    cfg = load_config({**BASE_ENV, "PUBLIC_URL": "https://worker-production-f298.up.railway.app"})
    assert cfg.webauthn_rp_id == "worker-production-f298.up.railway.app"


def test_explicit_rp_id_wins():
    cfg = load_config({
        **BASE_ENV,
        "PUBLIC_URL": "https://bot.up.railway.app",
        "WEBAUTHN_RP_ID": "support.example.ru",
    })
    assert cfg.webauthn_rp_id == "support.example.ru"


def test_origin_derived_from_public_url():
    cfg = load_config({**BASE_ENV, "PUBLIC_URL": "https://bot.up.railway.app"})
    assert cfg.webauthn_origin == "https://bot.up.railway.app"


def test_rp_id_empty_without_public_url():
    assert load_config(BASE_ENV).webauthn_rp_id == ""
