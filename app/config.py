"""Чтение и валидация переменных окружения. Падаем на старте, а не в рантайме."""

from collections.abc import Mapping
from dataclasses import dataclass

VALID_MODES = ("callback", "longpoll")


class ConfigError(Exception):
    """Окружение задано неверно. Сообщение содержит имя переменной."""


@dataclass(frozen=True)
class Config:
    vk_group_token: str
    vk_group_id: int
    vk_confirmation_code: str
    vk_secret_key: str
    vk_api_version: str
    admin_id: int
    database_url: str
    public_url: str
    vk_mode: str
    work_hours: tuple[int, int]
    tz: str
    session_secret: str
    webauthn_rp_id: str
    webauthn_origin: str
    vapid_public_key: str
    vapid_private_key: str
    vapid_subject: str


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} не задана")
    return value


def _first(env: Mapping[str, str], *keys: str) -> str:
    """Первое непустое значение из перечисленных имён."""
    for key in keys:
        value = env.get(key, "").strip()
        if value:
            return value
    return ""


def _resolve_public_url(env: Mapping[str, str]) -> str:
    """Railway сам выставляет RAILWAY_PUBLIC_DOMAIN — не заставляем дублировать руками."""
    explicit = env.get("PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    domain = env.get("RAILWAY_PUBLIC_DOMAIN", "").strip().rstrip("/")
    if not domain:
        return ""
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def _required_int(env: Mapping[str, str], key: str) -> int:
    raw = _required(env, key)
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{key} должна быть числом") from None


def _parse_work_hours(raw: str) -> tuple[int, int]:
    parts = raw.split("-")
    if len(parts) != 2:
        raise ConfigError("WORK_HOURS должна быть в формате '10-19'")
    try:
        start, end = int(parts[0]), int(parts[1])
    except ValueError:
        raise ConfigError("WORK_HOURS должна быть в формате '10-19'") from None
    if not (0 <= start < end <= 24):
        raise ConfigError("WORK_HOURS: начало должно быть меньше конца, диапазон 0..24")
    return start, end


def load_config(env: Mapping[str, str]) -> Config:
    mode = env.get("VK_MODE", "callback").strip() or "callback"
    if mode not in VALID_MODES:
        raise ConfigError(f"VK_MODE должна быть одной из {VALID_MODES}")

    session_secret = _required(env, "SESSION_SECRET")
    if len(session_secret) < 32:
        raise ConfigError("SESSION_SECRET должна быть не короче 32 символов")

    # Историческое имя VK_TOKEN поддерживаем: в Railway переменная уже так называется.
    vk_group_token = _first(env, "VK_GROUP_TOKEN", "VK_TOKEN")
    if not vk_group_token:
        raise ConfigError("VK_GROUP_TOKEN не задана")

    return Config(
        vk_group_token=vk_group_token,
        vk_group_id=_required_int(env, "VK_GROUP_ID"),
        vk_confirmation_code=_required(env, "VK_CONFIRMATION_CODE"),
        vk_secret_key=_required(env, "VK_SECRET_KEY"),
        vk_api_version=env.get("VK_API_VERSION", "").strip() or "5.199",
        admin_id=_required_int(env, "ADMIN_ID"),
        database_url=_required(env, "DATABASE_URL"),
        public_url=_resolve_public_url(env),
        vk_mode=mode,
        work_hours=_parse_work_hours(env.get("WORK_HOURS", "").strip() or "10-19"),
        tz=env.get("TZ", "").strip() or "Europe/Moscow",
        session_secret=session_secret,
        webauthn_rp_id=env.get("WEBAUTHN_RP_ID", "").strip(),
        webauthn_origin=env.get("WEBAUTHN_ORIGIN", "").strip(),
        vapid_public_key=env.get("VAPID_PUBLIC_KEY", "").strip(),
        vapid_private_key=env.get("VAPID_PRIVATE_KEY", "").strip(),
        vapid_subject=env.get("VAPID_SUBJECT", "").strip(),
    )
