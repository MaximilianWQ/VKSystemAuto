# Дашборд оператора, серверная часть — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** API дашборда: вход по passkey, список диалогов и лента переписки, ответ оператора с вложениями, реалтайм по WebSocket, веб-пуши. Интерфейса ещё нет — всё проверяется тестами и curl.

**Architecture:** Те же FastAPI и Postgres, что у бота, в том же процессе. Сессии серверные, идентификатор в HttpOnly-куке. Реалтайм — внутрипроцессная шина, потому что инстанс один. Пуши уходят через `pywebpush`, которая синхронная и поэтому вызывается в отдельном потоке.

**Tech Stack:** webauthn 3.0.0, pywebpush 2.5.0, FastAPI WebSocket, asyncpg.

**Spec:** `docs/superpowers/specs/2026-09-20-vk-support-bot-design.md`

**Предыдущий план:** `docs/superpowers/plans/2026-09-20-backend-bot.md` — выполнен, бот работает в проде.

## Global Constraints

- Всё, что уже зафиксировано в плане бота (Python 3.12, `uv`, только именованные аргументы `VKAPIError`, outbox для отправки, кодеки jsonb, `pgserver` в тестах), продолжает действовать.
- **Проверенные сигнатуры webauthn 3.0.0**, использовать именно их — все аргументы только именованные:
  - `generate_registration_options(*, rp_id, rp_name, user_name, user_id: bytes, authenticator_selection=None, exclude_credentials=None)` → объект, у него `.challenge` типа `bytes`
  - `options_to_json(options) -> str`
  - `verify_registration_response(*, credential, expected_challenge: bytes, expected_rp_id, expected_origin)` → `VerifiedRegistration` с полями `credential_id`, `credential_public_key`, `sign_count`
  - `generate_authentication_options(*, rp_id, allow_credentials: list[PublicKeyCredentialDescriptor] | None = None)`
  - `verify_authentication_response(*, credential, expected_challenge, expected_rp_id, expected_origin, credential_public_key, credential_current_sign_count)` → `VerifiedAuthentication` с полем `new_sign_count`
  - `PublicKeyCredentialDescriptor(id: bytes, type=..., transports=None)`
  - `base64url_to_bytes(value: str) -> bytes`
- **pywebpush 2.5.0 синхронная**: `webpush(subscription_info, data=None, vapid_private_key=None, vapid_claims=None, ttl=0)`. Вызывать только через `asyncio.to_thread` — иначе она заблокирует event loop вместе с приёмом вебхука ВК.
- Каждый эндпоинт дашборда закрыт зависимостью `require_session`. Единственные открытые — `/vk/callback`, `/healthz`, `/setup`, `/api/auth/*`.
- Кука сессии: имя `vkbot_session`, `HttpOnly`, `Secure`, `SameSite=Lax`.
- В базе хранятся только хеши токенов сессий, как и для setup-токенов.
- Ответы оператора отправляются **только через `outbox.enqueue`**, как и всё остальное.
- Тексты сообщений пользователей и содержимое вложений в логи не попадают.

---

### Task 1: Переменные дашборда и генерация ключей VAPID

**Files:**
- Modify: `app/config.py` — метод проверки переменных дашборда
- Create: `scripts/gen_vapid.py`
- Modify: `tests/test_config.py`
- Modify: `pyproject.toml` — зависимости `webauthn`, `pywebpush`
- Modify: `README.md`

**Interfaces:**
- Consumes: `Config` из плана бота.
- Produces:
  - `Config.dashboard_ready` — свойство, `True` когда заданы `webauthn_rp_id`, `webauthn_origin`, `vapid_public_key`, `vapid_private_key`, `vapid_subject`
  - `app.config.require_dashboard(cfg) -> None` — бросает `ConfigError` с перечислением недостающих переменных
  - `Config.webauthn_rp_id` выводится из `public_url`, если не задан явно
  - `scripts/gen_vapid.py` печатает готовые значения для Railway

- [ ] **Step 1: Добавить зависимости**

```bash
uv add webauthn pywebpush python-multipart
```

Ожидаемые версии: `webauthn==3.0.0`, `pywebpush==2.5.0`. `python-multipart` —
боевая зависимость: без неё FastAPI не разбирает multipart и падает на первом
же запросе загрузки файла.

- [ ] **Step 2: Написать падающий тест**

Добавить в `tests/test_config.py`:

```python
from app.config import require_dashboard

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
```

- [ ] **Step 3: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL — `ImportError: cannot import name 'require_dashboard'`

- [ ] **Step 4: Реализовать**

В `app/config.py` добавить импорт наверх файла:

```python
from urllib.parse import urlparse
```

Добавить в датакласс `Config` свойство (после определения полей):

```python
    @property
    def dashboard_ready(self) -> bool:
        return all((
            self.webauthn_rp_id,
            self.webauthn_origin,
            self.vapid_public_key,
            self.vapid_private_key,
            self.vapid_subject,
        ))
```

Добавить функции в конец файла:

```python
DASHBOARD_VARIABLES = (
    "WEBAUTHN_RP_ID",
    "WEBAUTHN_ORIGIN",
    "VAPID_PUBLIC_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_SUBJECT",
)


def require_dashboard(cfg: Config) -> None:
    """Проверяет, что дашборд настроен. Перечисляет всё недостающее разом."""
    values = {
        "WEBAUTHN_RP_ID": cfg.webauthn_rp_id,
        "WEBAUTHN_ORIGIN": cfg.webauthn_origin,
        "VAPID_PUBLIC_KEY": cfg.vapid_public_key,
        "VAPID_PRIVATE_KEY": cfg.vapid_private_key,
        "VAPID_SUBJECT": cfg.vapid_subject,
    }
    missing = [name for name in DASHBOARD_VARIABLES if not values[name]]
    if missing:
        raise ConfigError("не заданы переменные дашборда: " + ", ".join(missing))
```

Заменить вычисление `webauthn_rp_id` и `webauthn_origin` в `load_config`. Сейчас там:

```python
        webauthn_rp_id=env.get("WEBAUTHN_RP_ID", "").strip(),
        webauthn_origin=env.get("WEBAUTHN_ORIGIN", "").strip(),
```

Заменить на:

```python
        webauthn_rp_id=_resolve_rp_id(env, public_url),
        webauthn_origin=env.get("WEBAUTHN_ORIGIN", "").strip() or public_url,
```

Для этого `public_url` надо вычислить до конструктора `Config`. В начале `load_config`, рядом с `mode`, добавить:

```python
    public_url = _resolve_public_url(env)
```

и заменить в конструкторе `public_url=_resolve_public_url(env),` на `public_url=public_url,`.

Добавить функцию рядом с `_resolve_public_url`:

```python
def _resolve_rp_id(env: Mapping[str, str], public_url: str) -> str:
    """RP ID для passkey — голый домен: без схемы, порта и пути.

    Ключ привязан к этому значению намертво: смена домена требует
    перерегистрации passkey, это ограничение стандарта WebAuthn.
    """
    explicit = env.get("WEBAUTHN_RP_ID", "").strip()
    if explicit:
        return explicit
    if not public_url:
        return ""
    return urlparse(public_url).hostname or ""
```

- [ ] **Step 5: Написать генератор ключей**

`scripts/gen_vapid.py`:

```python
"""Печатает пару ключей VAPID для веб-пушей.

Запуск: uv run python scripts/gen_vapid.py
Значения вставляются в переменные Railway, в репозиторий не попадают.
"""

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01


def main() -> None:
    vapid = Vapid01()
    vapid.generate_keys()

    raw_public = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    public_key = base64.urlsafe_b64encode(raw_public).decode().rstrip("=")

    private_value = vapid.private_key.private_numbers().private_value
    private_key = base64.urlsafe_b64encode(
        private_value.to_bytes(32, "big")
    ).decode().rstrip("=")

    print("VAPID_PUBLIC_KEY =", public_key)
    print("VAPID_PRIVATE_KEY =", private_key)
    print("VAPID_SUBJECT = mailto:укажите@свою.почту")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Проверить генератор**

Run: `uv run python scripts/gen_vapid.py`
Expected: три строки; публичный ключ длиной 87 символов, приватный — 43

- [ ] **Step 7: Прогнать тесты и линтер**

Run: `uv run pytest -q && uv run ruff check .`
Expected: всё зелёное

- [ ] **Step 8: Коммит**

```bash
git add pyproject.toml uv.lock app/config.py scripts tests/test_config.py README.md
git commit -m "Добавить переменные дашборда и генератор ключей VAPID"
```

---

### Task 2: Миграция под задачи WebAuthn

**Files:**
- Create: `app/db/migrations/002_dashboard.sql`
- Create: `tests/test_migrations_002.py`

**Interfaces:**
- Consumes: механизм миграций из плана бота.
- Produces: таблица `webauthn_challenges(id TEXT PK, challenge BYTEA, purpose TEXT, expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ)`.

Зачем отдельная таблица: между выдачей challenge и его проверкой проходит один сетевой круг, а процесс на Railway может перезапуститься в любой момент. Хранить challenge в памяти нельзя.

- [ ] **Step 1: Написать падающий тест**

`tests/test_migrations_002.py`:

```python
async def test_challenges_table_exists(pool):
    columns = await pool.fetch(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_name = 'webauthn_challenges'"
    )
    found = {c["column_name"]: c["data_type"] for c in columns}
    assert found["id"] == "text"
    assert found["challenge"] == "bytea"
    assert found["purpose"] == "text"
    assert "used_at" in found


async def test_both_migrations_recorded(pool):
    names = [r["name"] for r in await pool.fetch(
        "SELECT name FROM schema_migrations ORDER BY name")]
    assert names == ["001_init.sql", "002_dashboard.sql"]


async def test_purpose_is_constrained(pool):
    import asyncpg
    import pytest
    with pytest.raises(asyncpg.IntegrityConstraintViolationError):
        await pool.execute(
            "INSERT INTO webauthn_challenges (id, challenge, purpose, expires_at)"
            " VALUES ('x', '\\x00'::bytea, 'нечто', now() + interval '5 min')"
        )
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_migrations_002.py -q`
Expected: FAIL — таблицы нет

- [ ] **Step 3: Написать миграцию**

`app/db/migrations/002_dashboard.sql`:

```sql
-- Challenge живёт между выдачей опций и проверкой ответа браузера.
-- В памяти держать нельзя: процесс на Railway перезапускается в любой момент.
CREATE TABLE webauthn_challenges (
    id         TEXT PRIMARY KEY,
    challenge  BYTEA NOT NULL,
    purpose    TEXT NOT NULL CHECK (purpose IN ('register', 'login')),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ
);
CREATE INDEX webauthn_challenges_cleanup_idx ON webauthn_challenges (expires_at);
```

- [ ] **Step 4: Прогнать тесты**

Run: `uv run pytest tests/test_migrations_002.py tests/test_migrations.py -q`
Expected: 3 + 4 passed. Тест `test_records_applied_migration` из первого плана проверяет список миграций — если он упал, значит его надо обновить: теперь ожидается два файла.

- [ ] **Step 5: Обновить тест первого плана**

В `tests/test_migrations.py` заменить:

```python
    assert [r["name"] for r in names] == ["001_init.sql"]
```

на:

```python
    assert [r["name"] for r in names] == ["001_init.sql", "002_dashboard.sql"]
```

- [ ] **Step 6: Прогнать всё**

Run: `uv run pytest -q && uv run ruff check .`

- [ ] **Step 7: Коммит**

```bash
git add app/db/migrations/002_dashboard.sql tests/test_migrations_002.py tests/test_migrations.py
git commit -m "Добавить таблицу challenge для WebAuthn"
```

---

### Task 3: Сессии и защита эндпоинтов

**Files:**
- Create: `app/web/sessions.py`
- Create: `tests/test_sessions.py`

**Interfaces:**
- Consumes: `pool`, таблица `sessions`.
- Produces:
  - `app.web.sessions.issue(pool, user_agent: str = "", ttl_days: int = 30) -> str` — возвращает сырой токен
  - `app.web.sessions.verify(pool, token: str) -> asyncpg.Record | None`
  - `app.web.sessions.revoke(pool, token: str) -> None`
  - `app.web.sessions.purge_expired(pool) -> int`
  - `app.web.sessions.require_session(request: Request) -> asyncpg.Record` — зависимость FastAPI, 401 без валидной куки
  - `app.web.sessions.set_cookie(response, token, ttl_days)` и `clear_cookie(response)`
  - Константы `COOKIE_NAME = "vkbot_session"`, `TTL_DAYS = 30`

- [ ] **Step 1: Написать падающий тест**

`tests/test_sessions.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.web import sessions


async def test_issued_session_verifies(pool):
    token = await sessions.issue(pool, user_agent="Safari")
    row = await sessions.verify(pool, token)
    assert row is not None
    assert row["user_agent"] == "Safari"


async def test_raw_token_is_not_stored(pool):
    """Дамп базы не должен давать вход в дашборд."""
    token = await sessions.issue(pool)
    stored = await pool.fetchval("SELECT id FROM sessions")
    assert stored != token
    assert token not in stored


async def test_unknown_token_rejected(pool):
    assert await sessions.verify(pool, "выдуманный") is None


async def test_expired_session_rejected(pool):
    token = await sessions.issue(pool, ttl_days=-1)
    assert await sessions.verify(pool, token) is None


async def test_revoked_session_rejected(pool):
    token = await sessions.issue(pool)
    await sessions.revoke(pool, token)
    assert await sessions.verify(pool, token) is None


async def test_tokens_are_unique(pool):
    assert len({await sessions.issue(pool) for _ in range(20)}) == 20


async def test_purge_removes_expired_only(pool):
    fresh = await sessions.issue(pool)
    await sessions.issue(pool, ttl_days=-1)
    assert await sessions.purge_expired(pool) == 1
    assert await sessions.verify(pool, fresh) is not None


def build_guarded_app(pool):
    app = FastAPI()
    app.state.pool = pool

    @app.get("/api/secret")
    async def secret(session=Depends(sessions.require_session)):
        return {"ok": True}

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_guard_rejects_without_cookie(pool):
    http = build_guarded_app(pool)
    assert (await http.get("/api/secret")).status_code == 401


async def test_guard_rejects_bad_cookie(pool):
    http = build_guarded_app(pool)
    http.cookies.set(sessions.COOKIE_NAME, "garbage")
    assert (await http.get("/api/secret")).status_code == 401


async def test_guard_accepts_valid_cookie(pool):
    token = await sessions.issue(pool)
    http = build_guarded_app(pool)
    http.cookies.set(sessions.COOKIE_NAME, token)
    response = await http.get("/api/secret")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_cookie_flags_are_safe():
    from fastapi.responses import JSONResponse
    response = JSONResponse({})
    sessions.set_cookie(response, "token-value", ttl_days=30)
    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "samesite=lax" in header.lower()


async def test_clear_cookie_expires_it():
    from fastapi.responses import JSONResponse
    response = JSONResponse({})
    sessions.clear_cookie(response)
    assert sessions.COOKIE_NAME in response.headers["set-cookie"]
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_sessions.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.web.sessions'`

- [ ] **Step 3: Реализовать**

`app/web/sessions.py`:

```python
"""Серверные сессии дашборда.

В базе лежит только хеш токена: утечка дампа не должна давать вход.
Сессия отзывается удалением строки, поэтому JWT здесь не подходит.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import asyncpg
from fastapi import HTTPException, Request
from fastapi.responses import Response

COOKIE_NAME = "vkbot_session"
TTL_DAYS = 30
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue(pool: asyncpg.Pool, user_agent: str = "", ttl_days: int = TTL_DAYS) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
    await pool.execute(
        "INSERT INTO sessions (id, expires_at, user_agent) VALUES ($1, $2, $3)",
        _hash(token), expires_at, user_agent[:500],
    )
    return token


async def verify(pool: asyncpg.Pool, token: str) -> asyncpg.Record | None:
    if not token:
        return None
    return await pool.fetchrow(
        "SELECT * FROM sessions WHERE id = $1 AND expires_at > now()", _hash(token)
    )


async def revoke(pool: asyncpg.Pool, token: str) -> None:
    await pool.execute("DELETE FROM sessions WHERE id = $1", _hash(token))


async def purge_expired(pool: asyncpg.Pool) -> int:
    result = await pool.execute("DELETE FROM sessions WHERE expires_at < now()")
    return int(result.split()[-1])


async def require_session(request: Request) -> asyncpg.Record:
    """Зависимость FastAPI. Всё в дашборде закрыто ею."""
    token = request.cookies.get(COOKIE_NAME, "")
    session = await verify(request.app.state.pool, token)
    if session is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return session


def set_cookie(response: Response, token: str, ttl_days: int = TTL_DAYS) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=ttl_days * 24 * 3600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_sessions.py -q && uv run ruff check .`
Expected: 12 passed

- [ ] **Step 5: Коммит**

```bash
git add app/web/sessions.py tests/test_sessions.py
git commit -m "Добавить серверные сессии дашборда"
```

---

### Task 4: Хранилище challenge и регистрация passkey

**Files:**
- Create: `app/web/challenges.py`
- Create: `app/web/auth.py`
- Create: `tests/test_challenges.py`
- Create: `tests/test_auth_register.py`

**Interfaces:**
- Consumes: `setup_tokens` (план бота), `sessions` (Task 3), таблица `webauthn_challenges` (Task 2).
- Produces:
  - `app.web.challenges.issue(pool, challenge: bytes, purpose: str, ttl_seconds: int = 300) -> str`
  - `app.web.challenges.consume(pool, challenge_id: str, purpose: str) -> bytes | None`
  - `app.web.challenges.purge_expired(pool) -> int`
  - `app.web.challenges.COOKIE_NAME = "vkbot_challenge"`
  - `app.web.auth.router` с `POST /api/auth/register/options` и `POST /api/auth/register/verify`
  - `app.web.auth.list_credentials(pool) -> list[asyncpg.Record]`

- [ ] **Step 1: Написать падающий тест хранилища**

`tests/test_challenges.py`:

```python
from app.web import challenges


async def test_issued_challenge_is_returned_once(pool):
    challenge_id = await challenges.issue(pool, b"\x01\x02\x03", "register")
    assert await challenges.consume(pool, challenge_id, "register") == b"\x01\x02\x03"
    assert await challenges.consume(pool, challenge_id, "register") is None


async def test_purpose_must_match(pool):
    """Challenge для входа нельзя подсунуть в регистрацию."""
    challenge_id = await challenges.issue(pool, b"\x01", "login")
    assert await challenges.consume(pool, challenge_id, "register") is None


async def test_expired_challenge_rejected(pool):
    challenge_id = await challenges.issue(pool, b"\x01", "register", ttl_seconds=-1)
    assert await challenges.consume(pool, challenge_id, "register") is None


async def test_unknown_id_rejected(pool):
    assert await challenges.consume(pool, "выдуманный", "register") is None


async def test_purge_removes_expired_only(pool):
    fresh = await challenges.issue(pool, b"\x01", "register")
    await challenges.issue(pool, b"\x02", "register", ttl_seconds=-1)
    assert await challenges.purge_expired(pool) == 1
    assert await challenges.consume(pool, fresh, "register") == b"\x01"
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_challenges.py -q`
Expected: FAIL — модуля нет

- [ ] **Step 3: Реализовать хранилище**

`app/web/challenges.py`:

```python
"""Хранилище одноразовых challenge для WebAuthn.

Между выдачей опций и проверкой ответа браузера проходит сетевой круг, а
процесс на Railway может перезапуститься. Поэтому challenge живёт в базе,
а не в памяти.
"""

import secrets
from datetime import UTC, datetime, timedelta

import asyncpg

COOKIE_NAME = "vkbot_challenge"
TTL_SECONDS = 300


async def issue(
    pool: asyncpg.Pool, challenge: bytes, purpose: str, ttl_seconds: int = TTL_SECONDS
) -> str:
    challenge_id = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    await pool.execute(
        "INSERT INTO webauthn_challenges (id, challenge, purpose, expires_at)"
        " VALUES ($1, $2, $3, $4)",
        challenge_id, challenge, purpose, expires_at,
    )
    return challenge_id


async def consume(pool: asyncpg.Pool, challenge_id: str, purpose: str) -> bytes | None:
    """Возвращает challenge и сразу гасит его. Назначение обязано совпасть."""
    if not challenge_id:
        return None
    row = await pool.fetchrow(
        "UPDATE webauthn_challenges SET used_at = now()"
        " WHERE id = $1 AND purpose = $2 AND used_at IS NULL AND expires_at > now()"
        " RETURNING challenge",
        challenge_id, purpose,
    )
    return bytes(row["challenge"]) if row is not None else None


async def purge_expired(pool: asyncpg.Pool) -> int:
    result = await pool.execute(
        "DELETE FROM webauthn_challenges WHERE expires_at < now() AND used_at IS NULL"
    )
    return int(result.split()[-1])
```

- [ ] **Step 4: Написать падающий тест регистрации**

`tests/test_auth_register.py`:

```python
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import setup_tokens
from app.config import load_config
from app.web import auth, challenges, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
    "VAPID_PUBLIC_KEY": "B" * 87, "VAPID_PRIVATE_KEY": "p" * 43,
    "VAPID_SUBJECT": "mailto:a@b.c",
}
CFG = load_config(ENV)


@pytest.fixture
def client(pool):
    app = FastAPI()
    app.include_router(auth.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


class FakeVerified:
    credential_id = b"cred-1"
    credential_public_key = b"pubkey-1"
    sign_count = 0


async def test_options_require_valid_setup_token(client, pool):
    response = await client.post("/api/auth/register/options", json={"token": "левый"})
    assert response.status_code == 403


async def test_options_return_webauthn_payload(client, pool):
    token = await setup_tokens.issue(pool)
    response = await client.post("/api/auth/register/options", json={"token": token})
    assert response.status_code == 200
    body = response.json()
    assert body["rp"]["id"] == "bot.example"
    assert "challenge" in body
    assert body["user"]["name"]


async def test_options_set_challenge_cookie(client, pool):
    token = await setup_tokens.issue(pool)
    response = await client.post("/api/auth/register/options", json={"token": token})
    assert challenges.COOKIE_NAME in response.cookies


async def test_options_do_not_burn_the_setup_token(client, pool):
    """Прерванный create() в браузере не должен сжигать ссылку."""
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    assert await pool.fetchval("SELECT used_at FROM setup_tokens") is None


async def test_verify_stores_credential_and_opens_session(client, pool, monkeypatch):
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})

    response = await client.post(
        "/api/auth/register/verify",
        json={"token": token, "credential": {"id": "x"}, "name": "iPhone"},
    )
    assert response.status_code == 200

    stored = await pool.fetchrow("SELECT * FROM admin_credentials")
    assert bytes(stored["credential_id"]) == b"cred-1"
    assert bytes(stored["public_key"]) == b"pubkey-1"
    assert stored["name"] == "iPhone"

    assert sessions.COOKIE_NAME in response.cookies
    assert await pool.fetchval("SELECT count(*) FROM sessions") == 1


async def test_verify_burns_the_setup_token(client, pool, monkeypatch):
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}})

    assert await pool.fetchval("SELECT used_at FROM setup_tokens") is not None


async def test_reused_setup_link_is_rejected_at_the_first_step(client, pool, monkeypatch):
    """Повторный заход по ссылке отсекается уже на выдаче опций."""
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}})

    again = await client.post("/api/auth/register/options", json={"token": token})
    assert again.status_code == 403
    assert await pool.fetchval("SELECT count(*) FROM admin_credentials") == 1


async def test_verify_with_spent_token_adds_no_credential(client, pool, monkeypatch):
    """Даже если дойти до verify в обход, второй ключ не появится."""
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}})

    second = await client.post("/api/auth/register/verify",
                               json={"token": token, "credential": {"id": "x"}})
    assert second.status_code >= 400
    assert await pool.fetchval("SELECT count(*) FROM admin_credentials") == 1


async def test_verify_without_challenge_cookie_fails(client, pool, monkeypatch):
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    token = await setup_tokens.issue(pool)
    response = await client.post("/api/auth/register/verify",
                                 json={"token": token, "credential": {"id": "x"}})
    assert response.status_code == 400


async def test_verify_propagates_webauthn_failure(client, pool, monkeypatch):
    def boom(**kwargs):
        raise ValueError("подпись не сошлась")

    monkeypatch.setattr(auth, "verify_registration_response", boom)
    token = await setup_tokens.issue(pool)
    await client.post("/api/auth/register/options", json={"token": token})
    response = await client.post("/api/auth/register/verify",
                                 json={"token": token, "credential": {"id": "x"}})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM admin_credentials") == 0


async def test_second_key_can_be_added(client, pool, monkeypatch):
    """Телефон и ноутбук — два ключа, оба валидны."""
    class Second(FakeVerified):
        credential_id = b"cred-2"

    token = await setup_tokens.issue(pool)
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: FakeVerified())
    await client.post("/api/auth/register/options", json={"token": token})
    await client.post("/api/auth/register/verify",
                      json={"token": token, "credential": {"id": "x"}, "name": "iPhone"})

    token2 = await setup_tokens.issue(pool)
    monkeypatch.setattr(auth, "verify_registration_response",
                        lambda **kwargs: Second())
    await client.post("/api/auth/register/options", json={"token": token2})
    await client.post("/api/auth/register/verify",
                      json={"token": token2, "credential": {"id": "y"}, "name": "MacBook"})

    names = [r["name"] for r in await auth.list_credentials(pool)]
    assert sorted(names) == ["MacBook", "iPhone"]
```

- [ ] **Step 5: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_auth_register.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.web.auth'`

- [ ] **Step 6: Реализовать регистрацию**

`app/web/auth.py`:

```python
"""Вход в дашборд по passkey.

Паролей нет вообще. Первый ключ регистрируется по одноразовой ссылке, которую
бот присылает владельцу ADMIN_ID в личку ВК. Ключей можно завести несколько —
телефон и ноутбук.
"""

import json
import logging

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from webauthn import (
    generate_registration_options,
    options_to_json,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import setup_tokens
from app.config import Config
from app.web import challenges, sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

RP_NAME = "Поддержка Atlas Secure"
ADMIN_USER_NAME = "operator"
ADMIN_USER_ID = b"atlas-operator"


async def list_credentials(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT * FROM admin_credentials ORDER BY created_at")


def _require_rp(cfg: Config) -> tuple[str, str]:
    if not cfg.webauthn_rp_id or not cfg.webauthn_origin:
        raise HTTPException(status_code=503, detail="webauthn не настроен")
    return cfg.webauthn_rp_id, cfg.webauthn_origin


@router.post("/register/options")
async def register_options(request: Request) -> JSONResponse:
    body = await request.json()
    pool = request.app.state.pool
    cfg = request.app.state.cfg
    rp_id, _ = _require_rp(cfg)

    token = str(body.get("token", ""))
    # Проверяем, но НЕ гасим: прерванный create() в браузере не должен
    # сжигать ссылку. Гасим на шаге verify.
    valid = await pool.fetchval(
        "SELECT 1 FROM setup_tokens WHERE token_hash = $1"
        " AND used_at IS NULL AND expires_at > now()",
        setup_tokens._hash(token),
    )
    if not valid:
        raise HTTPException(status_code=403, detail="ссылка недействительна")

    existing = await list_credentials(pool)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_name=ADMIN_USER_NAME,
        user_id=ADMIN_USER_ID,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(row["credential_id"]))
            for row in existing
        ],
    )
    challenge_id = await challenges.issue(pool, options.challenge, "register")

    response = JSONResponse(json.loads(options_to_json(options)))
    response.set_cookie(
        challenges.COOKIE_NAME, challenge_id,
        max_age=challenges.TTL_SECONDS, httponly=True, secure=True,
        samesite="lax", path="/",
    )
    return response


@router.post("/register/verify")
async def register_verify(request: Request) -> JSONResponse:
    body = await request.json()
    pool = request.app.state.pool
    cfg = request.app.state.cfg
    rp_id, origin = _require_rp(cfg)

    challenge_id = request.cookies.get(challenges.COOKIE_NAME, "")
    expected = await challenges.consume(pool, challenge_id, "register")
    if expected is None:
        raise HTTPException(status_code=400, detail="challenge истёк, начните заново")

    # Гасим ссылку только здесь и до проверки подписи: повторный заход по той
    # же ссылке не должен давать вторую попытку.
    if not await setup_tokens.consume(pool, str(body.get("token", ""))):
        raise HTTPException(status_code=403, detail="ссылка уже использована")

    try:
        verified = verify_registration_response(
            credential=body.get("credential"),
            expected_challenge=expected,
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except Exception:
        logger.warning("регистрация passkey отклонена: проверка не прошла")
        raise HTTPException(status_code=400, detail="ключ не принят") from None

    await pool.execute(
        "INSERT INTO admin_credentials (credential_id, public_key, sign_count, name)"
        " VALUES ($1, $2, $3, $4)"
        " ON CONFLICT (credential_id) DO UPDATE SET"
        " public_key = EXCLUDED.public_key, sign_count = EXCLUDED.sign_count",
        verified.credential_id, verified.credential_public_key,
        verified.sign_count, str(body.get("name", ""))[:100],
    )

    token = await sessions.issue(pool, request.headers.get("user-agent", ""))
    response = JSONResponse({"ok": True})
    sessions.set_cookie(response, token)
    response.delete_cookie(challenges.COOKIE_NAME, path="/")
    return response
```

- [ ] **Step 7: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_challenges.py tests/test_auth_register.py -q && uv run ruff check .`
Expected: 5 + 10 passed

Если ruff ругается на обращение к `setup_tokens._hash` из другого модуля — вынеси хеширование в публичную функцию `setup_tokens.hash_token` и используй её в обоих местах.

- [ ] **Step 8: Коммит**

```bash
git add app/web/challenges.py app/web/auth.py tests/test_challenges.py tests/test_auth_register.py
git commit -m "Добавить регистрацию passkey по одноразовой ссылке"
```

---

### Task 5: Вход по passkey и выход

**Files:**
- Modify: `app/web/auth.py`
- Create: `tests/test_auth_login.py`

**Interfaces:**
- Consumes: всё из Task 4.
- Produces: `POST /api/auth/login/options`, `POST /api/auth/login/verify`, `POST /api/auth/logout`, `GET /api/auth/me`.

- [ ] **Step 1: Написать падающий тест**

`tests/test_auth_login.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.web import auth, challenges, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


@pytest.fixture
def client(pool):
    app = FastAPI()
    app.include_router(auth.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


async def add_credential(pool, credential_id=b"cred-1", sign_count=5):
    await pool.execute(
        "INSERT INTO admin_credentials (credential_id, public_key, sign_count, name)"
        " VALUES ($1, $2, $3, 'iPhone')",
        credential_id, b"pubkey", sign_count,
    )


class FakeAuth:
    credential_id = b"cred-1"
    new_sign_count = 6


async def test_login_options_without_any_key_is_refused(client, pool):
    """Пока ключ не зарегистрирован, входить нечем — и это надо сказать прямо."""
    response = await client.post("/api/auth/login/options")
    assert response.status_code == 409


async def test_login_options_list_registered_keys(client, pool):
    await add_credential(pool)
    response = await client.post("/api/auth/login/options")
    assert response.status_code == 200
    body = response.json()
    assert body["rpId"] == "bot.example"
    assert len(body["allowCredentials"]) == 1
    assert challenges.COOKIE_NAME in response.cookies


async def test_login_verify_opens_session(client, pool, monkeypatch):
    await add_credential(pool)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    response = await client.post("/api/auth/login/verify",
                                 json={"credential": {"id": "x"}})
    assert response.status_code == 200
    assert sessions.COOKIE_NAME in response.cookies


async def test_login_updates_sign_count(client, pool, monkeypatch):
    """Счётчик защищает от клонированного ключа, поэтому его надо сохранять."""
    await add_credential(pool, sign_count=5)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert await pool.fetchval("SELECT sign_count FROM admin_credentials") == 6


async def test_login_records_last_used(client, pool, monkeypatch):
    await add_credential(pool)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert await pool.fetchval("SELECT last_used_at FROM admin_credentials") is not None


async def test_login_with_unknown_credential_rejected(client, pool, monkeypatch):
    await add_credential(pool, credential_id=b"cred-1")

    class Unknown:
        credential_id = b"чужой"
        new_sign_count = 1

    monkeypatch.setattr(auth, "verify_authentication_response", lambda **kwargs: Unknown())
    await client.post("/api/auth/login/options")
    response = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM sessions") == 0


async def test_login_without_challenge_cookie_fails(client, pool):
    await add_credential(pool)
    response = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert response.status_code == 400


async def test_login_signature_failure_opens_no_session(client, pool, monkeypatch):
    await add_credential(pool)

    def boom(**kwargs):
        raise ValueError("подпись не сошлась")

    monkeypatch.setattr(auth, "verify_authentication_response", boom)
    await client.post("/api/auth/login/options")
    response = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM sessions") == 0


async def test_me_requires_session(client, pool):
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_me_returns_key_list(client, pool):
    await add_credential(pool)
    token = await sessions.issue(pool)
    client.cookies.set(sessions.COOKIE_NAME, token)
    response = await client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["keys"][0]["name"] == "iPhone"


async def test_logout_revokes_session(client, pool):
    token = await sessions.issue(pool)
    client.cookies.set(sessions.COOKIE_NAME, token)
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert await sessions.verify(pool, token) is None


async def test_challenge_is_single_use(client, pool, monkeypatch):
    await add_credential(pool)
    monkeypatch.setattr(auth, "verify_authentication_response",
                        lambda **kwargs: FakeAuth())
    await client.post("/api/auth/login/options")
    first = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert first.status_code == 200
    second = await client.post("/api/auth/login/verify", json={"credential": {"id": "x"}})
    assert second.status_code == 400
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_auth_login.py -q`
Expected: FAIL — маршрутов входа нет

- [ ] **Step 3: Реализовать вход и выход**

В `app/web/auth.py` расширить импорт webauthn:

```python
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
```

добавить импорт зависимости:

```python
from fastapi import Depends
```

и дописать в конец файла:

```python
@router.post("/login/options")
async def login_options(request: Request) -> JSONResponse:
    pool = request.app.state.pool
    rp_id, _ = _require_rp(request.app.state.cfg)

    registered = await list_credentials(pool)
    if not registered:
        raise HTTPException(
            status_code=409,
            detail="ключей нет, получите ссылку командой /link в сообществе",
        )

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(row["credential_id"]))
            for row in registered
        ],
    )
    challenge_id = await challenges.issue(pool, options.challenge, "login")

    response = JSONResponse(json.loads(options_to_json(options)))
    response.set_cookie(
        challenges.COOKIE_NAME, challenge_id,
        max_age=challenges.TTL_SECONDS, httponly=True, secure=True,
        samesite="lax", path="/",
    )
    return response


@router.post("/login/verify")
async def login_verify(request: Request) -> JSONResponse:
    body = await request.json()
    pool = request.app.state.pool
    rp_id, origin = _require_rp(request.app.state.cfg)

    challenge_id = request.cookies.get(challenges.COOKIE_NAME, "")
    expected = await challenges.consume(pool, challenge_id, "login")
    if expected is None:
        raise HTTPException(status_code=400, detail="challenge истёк, начните заново")

    credential = body.get("credential") or {}
    raw_id = credential.get("rawId") or credential.get("id") or ""
    stored = await _find_credential(pool, raw_id)
    if stored is None:
        raise HTTPException(status_code=400, detail="ключ не найден")

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=expected,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"],
        )
    except Exception:
        logger.warning("вход по passkey отклонён: проверка не прошла")
        raise HTTPException(status_code=400, detail="ключ не принят") from None

    if bytes(verified.credential_id) != bytes(stored["credential_id"]):
        logger.warning("вход по passkey отклонён: идентификатор ключа не совпал")
        raise HTTPException(status_code=400, detail="ключ не принят")

    # Счётчик подписей растёт монотонно; его сохранение — защита от клона ключа.
    await pool.execute(
        "UPDATE admin_credentials SET sign_count = $2, last_used_at = now()"
        " WHERE credential_id = $1",
        stored["credential_id"], verified.new_sign_count,
    )

    token = await sessions.issue(pool, request.headers.get("user-agent", ""))
    response = JSONResponse({"ok": True})
    sessions.set_cookie(response, token)
    response.delete_cookie(challenges.COOKIE_NAME, path="/")
    return response


async def _find_credential(pool: asyncpg.Pool, raw_id: str) -> asyncpg.Record | None:
    """Ищет ключ по идентификатору из ответа браузера.

    Единственный оператор, ключей единицы — перебор дешевле и надёжнее,
    чем угадывать точную кодировку rawId.
    """
    from webauthn.helpers import base64url_to_bytes

    try:
        wanted = base64url_to_bytes(raw_id)
    except Exception:
        wanted = b""

    rows = await list_credentials(pool)
    for row in rows:
        if wanted and bytes(row["credential_id"]) == wanted:
            return row
    return rows[0] if len(rows) == 1 else None


@router.get("/me")
async def me(request: Request, session=Depends(sessions.require_session)) -> dict:
    rows = await list_credentials(request.app.state.pool)
    return {
        "keys": [
            {
                "id": row["id"],
                "name": row["name"] or "Без названия",
                "created_at": row["created_at"].isoformat(),
                "last_used_at": row["last_used_at"].isoformat()
                if row["last_used_at"] else None,
            }
            for row in rows
        ]
    }


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(sessions.COOKIE_NAME, "")
    if token:
        await sessions.revoke(request.app.state.pool, token)
    response = JSONResponse({"ok": True})
    sessions.clear_cookie(response)
    return response
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_auth_login.py -q && uv run ruff check .`
Expected: 12 passed

- [ ] **Step 5: Коммит**

```bash
git add app/web/auth.py tests/test_auth_login.py
git commit -m "Добавить вход по passkey и выход"
```

---

### Task 6: Шина событий и уведомление из обработчика

**Files:**
- Create: `app/web/bus.py`
- Modify: `app/handlers/user.py` — необязательный параметр `notify`
- Create: `tests/test_bus.py`
- Modify: `tests/test_handlers_user.py`

**Interfaces:**
- Produces:
  - `app.web.bus.Bus` с `subscribe() -> asyncio.Queue`, `unsubscribe(queue)`, `await publish(event: dict) -> int`, свойство `subscribers: int`
  - `app.handlers.user.handle_event(pool, cfg, event, notify=None)` — `notify: Callable[[dict], Awaitable[None]] | None`
- Событие уведомления: `{"type": "message", "ticket_id": int, "user_id": int, "text": str, "attachments": list[dict]}`

Почему внутрипроцессная шина, а не Redis: инстанс один и останется одним (`numReplicas: 1`), оператор тоже один. Внешний брокер здесь — лишний сервис, лишние деньги и лишняя точка отказа.

- [ ] **Step 1: Написать падающий тест шины**

`tests/test_bus.py`:

```python
import asyncio

from app.web.bus import Bus


async def test_subscriber_receives_event():
    bus = Bus()
    queue = bus.subscribe()
    await bus.publish({"type": "message", "ticket_id": 1})
    assert (await asyncio.wait_for(queue.get(), timeout=1))["ticket_id"] == 1


async def test_every_subscriber_receives_event():
    bus = Bus()
    first, second = bus.subscribe(), bus.subscribe()
    delivered = await bus.publish({"type": "message"})
    assert delivered == 2
    assert first.qsize() == 1
    assert second.qsize() == 1


async def test_publish_without_subscribers_is_harmless():
    assert await Bus().publish({"type": "message"}) == 0


async def test_unsubscribe_stops_delivery():
    bus = Bus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    assert await bus.publish({"type": "message"}) == 0
    assert queue.empty()


async def test_subscriber_count():
    bus = Bus()
    assert bus.subscribers == 0
    queue = bus.subscribe()
    assert bus.subscribers == 1
    bus.unsubscribe(queue)
    assert bus.subscribers == 0


async def test_slow_subscriber_does_not_block_others():
    """Забитая очередь одного клиента не должна ломать доставку остальным."""
    bus = Bus(max_queue=2)
    slow, fast = bus.subscribe(), bus.subscribe()
    for i in range(5):
        await bus.publish({"type": "message", "n": i})
    assert slow.qsize() == 2
    assert fast.qsize() == 2


async def test_unsubscribe_twice_is_safe():
    bus = Bus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    bus.unsubscribe(queue)
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_bus.py -q`
Expected: FAIL — модуля нет

- [ ] **Step 3: Реализовать шину**

`app/web/bus.py`:

```python
"""Внутрипроцессная шина событий для WebSocket.

Инстанс один и останется одним (numReplicas: 1), оператор тоже один, поэтому
внешний брокер здесь — лишний сервис и лишняя точка отказа.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

MAX_QUEUE = 100


class Bus:
    def __init__(self, max_queue: int = MAX_QUEUE) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._max_queue = max_queue

    @property
    def subscribers(self) -> int:
        return len(self._queues)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._queues.discard(queue)

    async def publish(self, event: dict) -> int:
        delivered = 0
        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Отставший клиент не должен тормозить остальных и копить память.
                logger.warning("очередь подписчика переполнена, событие отброшено")
        return delivered
```

- [ ] **Step 4: Написать падающий тест уведомления**

Добавить в `tests/test_handlers_user.py`:

```python
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
```

- [ ] **Step 5: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_handlers_user.py -q -k notify`
Expected: FAIL — `handle_event() got an unexpected keyword argument 'notify'`

- [ ] **Step 6: Провести notify через обработчик**

В `app/handlers/user.py` добавить в импорты:

```python
from collections.abc import Awaitable, Callable
```

Заменить сигнатуры. Было:

```python
async def handle_event(pool: asyncpg.Pool, cfg: Config, event: dict) -> None:
    if event.get("type") != "message_new":
        return
    message = (event.get("object") or {}).get("message") or {}
    await _handle_message(pool, cfg, message)
```

Стало:

```python
Notify = Callable[[dict], Awaitable[None]]


async def handle_event(
    pool: asyncpg.Pool, cfg: Config, event: dict, notify: Notify | None = None
) -> None:
    if event.get("type") != "message_new":
        return
    message = (event.get("object") or {}).get("message") or {}
    await _handle_message(pool, cfg, message, notify)


async def _safe_notify(notify: Notify | None, event: dict) -> None:
    """Сломанная шина не должна стоить нам сообщения клиента."""
    if notify is None:
        return
    try:
        await notify(event)
    except Exception:
        logger.exception("уведомление дашборда не доставлено")
```

В `_handle_message` заменить заголовок на:

```python
async def _handle_message(
    pool: asyncpg.Pool, cfg: Config, message: dict, notify: Notify | None = None
) -> None:
```

и в конце этой функции заменить вызов:

```python
        await _handle_free_text(pool, cfg, user_id, peer_id, message, text)
```

на:

```python
        await _handle_free_text(pool, cfg, user_id, peer_id, message, text, notify)
```

В `_handle_free_text` заменить заголовок на:

```python
async def _handle_free_text(
    pool: asyncpg.Pool, cfg: Config, user_id: int, peer_id: int,
    message: dict, text: str, notify: Notify | None = None,
) -> None:
```

и добавить уведомления после сохранения сообщения. Первая точка — сообщение в уже открытое обращение, было:

```python
    ticket = await q.get_open_ticket(pool, user_id)
    if ticket is not None:
        await q.add_message(pool, ticket["id"], "in", text, items, message.get("id"))
        return
```

стало:

```python
    ticket = await q.get_open_ticket(pool, user_id)
    if ticket is not None:
        await q.add_message(pool, ticket["id"], "in", text, items, message.get("id"))
        await _safe_notify(notify, {
            "type": "message", "ticket_id": ticket["id"], "user_id": user_id,
            "text": text, "attachments": items,
        })
        return
```

Вторая точка — создание обращения, после `await q.set_user_state(pool, user_id, STATE_IDLE)` добавить:

```python
    await _safe_notify(notify, {
        "type": "message", "ticket_id": ticket_id, "user_id": user_id,
        "text": text, "attachments": items,
    })
```

- [ ] **Step 7: Прогнать всё и линтер**

Run: `uv run pytest -q && uv run ruff check .`
Expected: всё зелёное

- [ ] **Step 8: Коммит**

```bash
git add app/web/bus.py app/handlers/user.py tests/test_bus.py tests/test_handlers_user.py
git commit -m "Добавить шину событий и уведомление дашборда"
```

---

### Task 7: Список диалогов и лента переписки

**Files:**
- Modify: `app/db/queries.py`
- Create: `app/web/api.py`
- Create: `tests/test_api_dialogs.py`

**Interfaces:**
- Produces:
  - `queries.list_dialogs(pool, status: str = "all", limit: int = 100) -> list[Record]`
  - `queries.list_messages(pool, ticket_id: int, limit: int = 200) -> list[Record]`
  - `queries.mark_read(pool, ticket_id: int) -> None`
  - `app.web.api.router` с `GET /api/dialogs`, `GET /api/dialogs/{ticket_id}/messages`, `POST /api/dialogs/{ticket_id}/read`
  - Все маршруты закрыты `Depends(sessions.require_session)`

- [ ] **Step 1: Написать падающий тест**

`tests/test_api_dialogs.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


@pytest.fixture
async def client(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


@pytest.fixture
def anonymous(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


async def make_dialog(pool, vk_id=1, name="Максим", text="не работает"):
    await q.upsert_user(pool, vk_id, name, "Новиков")
    ticket_id = await q.create_ticket(pool, vk_id)
    await q.add_message(pool, ticket_id, "in", text)
    return ticket_id


async def test_dialogs_require_session(anonymous):
    assert (await anonymous.get("/api/dialogs")).status_code == 401


async def test_messages_require_session(anonymous):
    assert (await anonymous.get("/api/dialogs/1/messages")).status_code == 401


async def test_empty_list(client):
    assert (await client.get("/api/dialogs")).json() == []


async def test_dialog_carries_user_and_preview(client, pool):
    await make_dialog(pool)
    [dialog] = (await client.get("/api/dialogs")).json()
    assert dialog["user"]["vk_id"] == 1
    assert dialog["user"]["name"] == "Максим Новиков"
    assert dialog["preview"] == "не работает"
    assert dialog["unread"] == 1
    assert dialog["status"] == "open"
    assert dialog["waiting_seconds"] >= 0


async def test_dialogs_sorted_by_recency(client, pool):
    first = await make_dialog(pool, vk_id=1, text="раньше")
    second = await make_dialog(pool, vk_id=2, text="позже")
    ids = [d["id"] for d in (await client.get("/api/dialogs")).json()]
    assert ids == [second, first]


async def test_closed_dialogs_hidden_by_default(client, pool):
    ticket_id = await make_dialog(pool)
    await q.close_ticket(pool, ticket_id)
    assert (await client.get("/api/dialogs")).json() == []


async def test_closed_dialogs_visible_on_request(client, pool):
    ticket_id = await make_dialog(pool)
    await q.close_ticket(pool, ticket_id)
    dialogs = (await client.get("/api/dialogs?status=closed")).json()
    assert [d["id"] for d in dialogs] == [ticket_id]


async def test_messages_in_chronological_order(client, pool):
    ticket_id = await make_dialog(pool, text="раз")
    await q.add_message(pool, ticket_id, "out", "два")
    await q.add_message(pool, ticket_id, "in", "три")
    body = (await client.get(f"/api/dialogs/{ticket_id}/messages")).json()
    assert [m["text"] for m in body["messages"]] == ["раз", "два", "три"]
    assert [m["direction"] for m in body["messages"]] == ["in", "out", "in"]


async def test_messages_include_attachments(client, pool):
    ticket_id = await make_dialog(pool)
    await q.add_message(pool, ticket_id, "in", "", [{"type": "photo", "url": "p.jpg"}])
    body = (await client.get(f"/api/dialogs/{ticket_id}/messages")).json()
    assert body["messages"][-1]["attachments"][0]["type"] == "photo"


async def test_messages_of_unknown_dialog_is_404(client):
    assert (await client.get("/api/dialogs/999/messages")).status_code == 404


async def test_read_resets_unread_counter(client, pool):
    ticket_id = await make_dialog(pool)
    await q.add_message(pool, ticket_id, "in", "ещё")
    assert (await client.post(f"/api/dialogs/{ticket_id}/read")).status_code == 200
    assert await pool.fetchval(
        "SELECT unread_count FROM tickets WHERE id = $1", ticket_id) == 0


async def test_read_marks_incoming_messages(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/read")
    unread = await pool.fetchval(
        "SELECT count(*) FROM ticket_messages"
        " WHERE ticket_id = $1 AND direction = 'in' AND read_at IS NULL", ticket_id)
    assert unread == 0
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_api_dialogs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.web.api'`

- [ ] **Step 3: Добавить запросы**

Дописать в `app/db/queries.py`:

```python
async def list_dialogs(
    pool: asyncpg.Pool, status: str = "all", limit: int = 100
) -> list[asyncpg.Record]:
    """Очередь оператора: свежие сверху, с превью и временем ожидания."""
    condition = {
        "open": "t.status <> 'closed'",
        "closed": "t.status = 'closed'",
    }.get(status, "TRUE")

    return await pool.fetch(
        f"""
        SELECT
            t.id, t.status, t.unread_count, t.created_at, t.last_message_at,
            t.first_reply_at, t.rating,
            u.vk_id, u.first_name, u.last_name, u.photo_url, u.can_write,
            (SELECT m.text FROM ticket_messages m
              WHERE m.ticket_id = t.id ORDER BY m.created_at DESC LIMIT 1) AS preview,
            (SELECT m.attachments FROM ticket_messages m
              WHERE m.ticket_id = t.id ORDER BY m.created_at DESC LIMIT 1)
              AS preview_attachments,
            EXTRACT(EPOCH FROM (now() - t.last_message_at))::bigint AS waiting_seconds
        FROM tickets t
        JOIN users u ON u.vk_id = t.user_id
        WHERE {condition}
        ORDER BY t.last_message_at DESC
        LIMIT $1
        """,  # noqa: S608 — condition берётся из замкнутого словаря, не из ввода
        limit,
    )


async def get_ticket(pool: asyncpg.Pool, ticket_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT t.*, u.first_name, u.last_name, u.photo_url, u.can_write"
        " FROM tickets t JOIN users u ON u.vk_id = t.user_id WHERE t.id = $1",
        ticket_id,
    )


async def list_messages(
    pool: asyncpg.Pool, ticket_id: int, limit: int = 200
) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM ticket_messages WHERE ticket_id = $1"
        " ORDER BY created_at, id LIMIT $2",
        ticket_id, limit,
    )


async def mark_read(pool: asyncpg.Pool, ticket_id: int) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "UPDATE ticket_messages SET read_at = now()"
            " WHERE ticket_id = $1 AND direction = 'in' AND read_at IS NULL",
            ticket_id,
        )
        await conn.execute(
            "UPDATE tickets SET unread_count = 0 WHERE id = $1", ticket_id
        )
```

- [ ] **Step 4: Реализовать маршруты**

`app/web/api.py`:

```python
"""REST дашборда. Всё закрыто сессией."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.db import queries as q
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
```

- [ ] **Step 5: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_api_dialogs.py -q && uv run ruff check .`
Expected: 13 passed

- [ ] **Step 6: Коммит**

```bash
git add app/db/queries.py app/web/api.py tests/test_api_dialogs.py
git commit -m "Добавить список диалогов и ленту переписки"
```

---

### Task 8: Ответ оператора и закрытие обращения

**Files:**
- Modify: `app/web/api.py`
- Modify: `app/texts.py`
- Create: `tests/test_api_reply.py`

**Interfaces:**
- Produces: `POST /api/dialogs/{ticket_id}/reply` (тело `{"text": str, "attachment": str | None}`), `POST /api/dialogs/{ticket_id}/close`.

Ответ кладётся в `ticket_messages` как `direction='out'` и одновременно в `outbox`. Прямой отправки нет: процесс перезапускается, ответ должен пережить рестарт.

- [ ] **Step 1: Написать падающий тест**

`tests/test_api_reply.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


@pytest.fixture
async def client(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


async def make_dialog(pool, vk_id=1):
    await q.upsert_user(pool, vk_id, "Максим", "Новиков")
    ticket_id = await q.create_ticket(pool, vk_id)
    await q.add_message(pool, ticket_id, "in", "не работает")
    return ticket_id


async def test_reply_is_queued_not_sent_directly(client, pool):
    """Прямая отправка теряется при рестарте, поэтому только через outbox."""
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply",
                                 json={"text": "сейчас посмотрю"})
    assert response.status_code == 200

    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["peer_id"] == 1
    assert row["payload"]["message"] == "сейчас посмотрю"
    assert row["status"] == "pending"


async def test_reply_is_stored_in_history(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "сейчас посмотрю"})
    row = await pool.fetchrow(
        "SELECT * FROM ticket_messages WHERE direction = 'out'")
    assert row["text"] == "сейчас посмотрю"


async def test_reply_moves_ticket_to_in_progress(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert await pool.fetchval(
        "SELECT status FROM tickets WHERE id = $1", ticket_id) == "in_progress"


async def test_reply_records_first_reply_time(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert await pool.fetchval(
        "SELECT first_reply_at FROM tickets WHERE id = $1", ticket_id) is not None


async def test_reply_marks_dialog_read(client, pool):
    """Оператор ответил — значит прочитал."""
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert await pool.fetchval(
        "SELECT unread_count FROM tickets WHERE id = $1", ticket_id) == 0


async def test_reply_with_attachment(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/reply",
                      json={"text": "вот инструкция", "attachment": "photo1_2"})
    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["payload"]["attachment"] == "photo1_2"


async def test_attachment_only_reply_allowed(client, pool):
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply",
                                 json={"text": "", "attachment": "photo1_2"})
    assert response.status_code == 200


async def test_empty_reply_rejected(client, pool):
    ticket_id = await make_dialog(pool)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "   "})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM outbox") == 0


async def test_reply_to_unknown_dialog_is_404(client):
    assert (await client.post("/api/dialogs/999/reply",
                              json={"text": "привет"})).status_code == 404


async def test_reply_to_blocked_user_is_refused(client, pool):
    """Пользователь запретил сообщения — отправлять некуда, и надо сказать об этом."""
    ticket_id = await make_dialog(pool)
    await q.mark_cannot_write(pool, 1)
    response = await client.post(f"/api/dialogs/{ticket_id}/reply", json={"text": "привет"})
    assert response.status_code == 409
    assert await pool.fetchval("SELECT count(*) FROM outbox") == 0


async def test_close_marks_ticket_closed(client, pool):
    ticket_id = await make_dialog(pool)
    assert (await client.post(f"/api/dialogs/{ticket_id}/close")).status_code == 200
    assert await pool.fetchval(
        "SELECT status FROM tickets WHERE id = $1", ticket_id) == "closed"


async def test_close_asks_user_for_rating(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/close")
    payload = await pool.fetchval("SELECT payload FROM outbox ORDER BY id DESC LIMIT 1")
    assert "keyboard" in payload
    assert "Оцените" in payload["message"]


async def test_close_unknown_dialog_is_404(client):
    assert (await client.post("/api/dialogs/999/close")).status_code == 404


async def test_close_twice_is_refused(client, pool):
    ticket_id = await make_dialog(pool)
    await client.post(f"/api/dialogs/{ticket_id}/close")
    assert (await client.post(f"/api/dialogs/{ticket_id}/close")).status_code == 409
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_api_reply.py -q`
Expected: FAIL — маршрутов нет

- [ ] **Step 3: Реализовать**

В `app/web/api.py` добавить импорты:

```python
from app import texts
from app.vk import keyboards as kb
from app.vk import outbox
```

и дописать маршруты:

```python
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
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_api_reply.py -q && uv run ruff check .`
Expected: 14 passed

- [ ] **Step 5: Коммит**

```bash
git add app/web/api.py tests/test_api_reply.py
git commit -m "Добавить ответ оператора и закрытие обращения"
```

---

### Task 9: Загрузка фото и файлов оператором

**Files:**
- Modify: `app/vk/attachments.py`
- Modify: `app/web/api.py`
- Create: `tests/test_uploads.py`

**Interfaces:**
- Produces:
  - `app.vk.attachments.upload_photo(client_api, peer_id: int, data: bytes, filename: str) -> str`
  - `app.vk.attachments.upload_doc(client_api, peer_id: int, data: bytes, filename: str) -> str`
  - `app.vk.attachments.pick_uploader(content_type: str, filename: str) -> str` — `"photo"` или `"doc"`
  - `POST /api/uploads` (multipart, поле `file`, query `peer_id`) → `{"attachment": "photo1_2"}`
  - Константа `MAX_UPLOAD_BYTES = 50 * 1024 * 1024`

Голосовые и видео от оператора в объём не входят — решено на этапе дизайна.

- [ ] **Step 1: Написать падающий тест**

`tests/test_uploads.py`:

```python
import io

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.vk import attachments
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


class FakeUploader:
    """Подменяет аплоадеры vkbottle: в тестах в ВК не ходим."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def upload(self, file_source, peer_id=None, **params):
        self.calls.append((file_source, peer_id, params))
        return self.result


@pytest.fixture
async def client(pool, monkeypatch):
    photo = FakeUploader("photo1_2")
    doc = FakeUploader("doc3_4")
    monkeypatch.setattr(attachments, "_photo_uploader", lambda api: photo)
    monkeypatch.setattr(attachments, "_doc_uploader", lambda api: doc)

    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.client = object()
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http, photo, doc


def test_picks_photo_uploader_for_images():
    assert attachments.pick_uploader("image/png", "скрин.png") == "photo"
    assert attachments.pick_uploader("image/jpeg", "фото.jpg") == "photo"


def test_picks_doc_uploader_for_everything_else():
    assert attachments.pick_uploader("application/pdf", "счёт.pdf") == "doc"
    assert attachments.pick_uploader("", "архив.zip") == "doc"


def test_gif_goes_as_document():
    """ВК показывает гифку как документ, а не как фото."""
    assert attachments.pick_uploader("image/gif", "анимация.gif") == "doc"


def test_falls_back_to_extension_when_type_missing():
    assert attachments.pick_uploader("", "скрин.PNG") == "photo"


async def test_upload_image_returns_photo_attachment(client):
    http, photo, _ = client
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("скрин.png", io.BytesIO(b"\x89PNG data"), "image/png")},
    )
    assert response.status_code == 200
    assert response.json() == {"attachment": "photo1_2"}
    assert photo.calls[0][1] == 1


async def test_upload_pdf_returns_doc_attachment(client):
    http, _, doc = client
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("счёт.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.json() == {"attachment": "doc3_4"}
    assert doc.calls[0][1] == 1


async def test_upload_requires_session(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("a.png", io.BytesIO(b"x"), "image/png")},
    )
    assert response.status_code == 401


async def test_empty_file_rejected(client):
    http, _, _ = client
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("пусто.png", io.BytesIO(b""), "image/png")},
    )
    assert response.status_code == 400


async def test_oversized_file_rejected(client, monkeypatch):
    http, _, _ = client
    monkeypatch.setattr(attachments, "MAX_UPLOAD_BYTES", 10)
    response = await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("большой.png", io.BytesIO(b"x" * 100), "image/png")},
    )
    assert response.status_code == 413


async def test_uploaded_attachment_can_be_sent(client, pool):
    """Полный круг: загрузили файл, приложили к ответу, ответ встал в очередь."""
    http, _, _ = client
    await q.upsert_user(pool, 1, "Максим", "Новиков")
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "in", "вопрос")

    uploaded = (await http.post(
        "/api/uploads?peer_id=1",
        files={"file": ("скрин.png", io.BytesIO(b"\x89PNG"), "image/png")},
    )).json()["attachment"]

    await http.post(f"/api/dialogs/{ticket_id}/reply",
                    json={"text": "вот так", "attachment": uploaded})
    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["payload"]["attachment"] == "photo1_2"
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_uploads.py -q`
Expected: FAIL — `pick_uploader` не существует

- [ ] **Step 3: Реализовать загрузку**

Дописать в `app/vk/attachments.py`:

```python
from vkbottle import DocMessagesUploader, PhotoMessageUploader

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Гифку ВК показывает документом, а не фото, поэтому она сюда не входит.
PHOTO_TYPES = ("image/png", "image/jpeg", "image/jpg", "image/webp")
PHOTO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def pick_uploader(content_type: str, filename: str) -> str:
    """Фото или документ. Ошибка в выборе даёт нечитаемое вложение у клиента."""
    if (content_type or "").lower() in PHOTO_TYPES:
        return "photo"
    if filename.lower().endswith(PHOTO_EXTENSIONS):
        return "photo"
    return "doc"


def _photo_uploader(api) -> PhotoMessageUploader:
    return PhotoMessageUploader(api)


def _doc_uploader(api) -> DocMessagesUploader:
    return DocMessagesUploader(api)


async def upload_photo(api, peer_id: int, data: bytes, filename: str) -> str:
    return await _photo_uploader(api).upload(
        file_source=data, peer_id=peer_id
    )


async def upload_doc(api, peer_id: int, data: bytes, filename: str) -> str:
    return await _doc_uploader(api).upload(
        file_source=data, peer_id=peer_id, title=filename
    )
```

- [ ] **Step 4: Добавить маршрут**

В `app/web/api.py` добавить импорты:

```python
from fastapi import File, UploadFile

from app.vk import attachments as vk_attachments
```

и маршрут:

```python
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
```

- [ ] **Step 5: Открыть доступ к API из клиента**

Аплоадерам vkbottle нужен сам объект `API`, а `VKClient` его прячет. Добавить в `app/vk/client.py` в класс `VKClient`:

```python
    def api_for_uploads(self):
        """Аплоадеры vkbottle работают с объектом API напрямую.

        Ограничение скорости на них не распространяется: загрузок единицы,
        и делает их живой человек.
        """
        return self._api
```

В тестах `app.state.client` подменяется объектом-заглушкой, поэтому добавь в `tests/test_uploads.py` в фикстуру вместо `app.state.client = object()`:

```python
    class FakeClient:
        def api_for_uploads(self):
            return None

    app.state.client = FakeClient()
```

- [ ] **Step 6: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_uploads.py -q && uv run ruff check .`
Expected: 11 passed

- [ ] **Step 7: Коммит**

```bash
git add app/vk/attachments.py app/vk/client.py app/web/api.py tests/test_uploads.py
git commit -m "Добавить загрузку фото и файлов от оператора"
```

---

### Task 10: Прокси входящих вложений

**Files:**
- Modify: `app/web/api.py`
- Create: `tests/test_attachment_proxy.py`

**Interfaces:**
- Produces: `GET /api/attachments/{message_id}/{index}` — стримит содержимое вложения.

Зачем прокси: ссылки ВК на документы и голосовые подписаны и протухают. Если отдать их браузеру напрямую, через несколько часов вложения в истории перестанут открываться. Прокси при 403 перезапрашивает свежий URL через `messages.getById`.

- [ ] **Step 1: Написать падающий тест**

`tests/test_attachment_proxy.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


class FakeFetcher:
    """Подменяет поход в интернет за содержимым вложения."""

    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    async def __call__(self, url: str):
        self.urls.append(url)
        return self.responses.pop(0)


@pytest.fixture
async def setup(pool, monkeypatch):
    await q.upsert_user(pool, 1, "Максим", "Новиков")
    ticket_id = await q.create_ticket(pool, 1)
    message_id = await q.add_message(
        pool, ticket_id, "in", "вот файл",
        [{"type": "doc", "title": "счёт.pdf", "url": "https://vk.com/doc.pdf",
          "ext": "pdf", "size": 10}],
        vk_message_id=555,
    )

    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http, app, message_id


async def test_proxy_requires_session(pool, setup):
    _, app, message_id = setup
    anonymous = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    assert (await anonymous.get(f"/api/attachments/{message_id}/0")).status_code == 401


async def test_proxy_streams_content(setup, monkeypatch):
    http, _, message_id = setup
    fetch = FakeFetcher([(200, b"%PDF payload", "application/pdf")])
    monkeypatch.setattr(api, "_fetch_attachment", fetch)

    response = await http.get(f"/api/attachments/{message_id}/0")
    assert response.status_code == 200
    assert response.content == b"%PDF payload"
    assert fetch.urls == ["https://vk.com/doc.pdf"]


async def test_proxy_sets_filename(setup, monkeypatch):
    http, _, message_id = setup
    monkeypatch.setattr(api, "_fetch_attachment",
                        FakeFetcher([(200, b"x", "application/pdf")]))
    response = await http.get(f"/api/attachments/{message_id}/0")
    assert "счёт.pdf" in response.headers.get("content-disposition", "")


async def test_expired_url_is_refreshed(setup, monkeypatch, pool):
    """Подписанная ссылка протухла — берём свежую через messages.getById."""
    http, app, message_id = setup
    fetch = FakeFetcher([(403, b"", ""), (200, b"свежий файл", "application/pdf")])
    monkeypatch.setattr(api, "_fetch_attachment", fetch)

    class FakeVK:
        async def call(self, method, **params):
            assert method == "messages.getById"
            return {"items": [{"attachments": [
                {"type": "doc", "doc": {"id": 1, "owner_id": 2, "title": "счёт.pdf",
                                        "ext": "pdf", "size": 10,
                                        "url": "https://vk.com/fresh.pdf"}}
            ]}]}

    app.state.client = FakeVK()
    response = await http.get(f"/api/attachments/{message_id}/0")
    assert response.status_code == 200
    assert response.content == b"свежий файл"
    assert fetch.urls == ["https://vk.com/doc.pdf", "https://vk.com/fresh.pdf"]


async def test_refreshed_url_is_saved(setup, monkeypatch, pool):
    """Обновлённую ссылку сохраняем, чтобы не ходить в ВК на каждый показ."""
    http, app, message_id = setup
    monkeypatch.setattr(api, "_fetch_attachment",
                        FakeFetcher([(403, b"", ""), (200, b"x", "application/pdf")]))

    class FakeVK:
        async def call(self, method, **params):
            return {"items": [{"attachments": [
                {"type": "doc", "doc": {"id": 1, "owner_id": 2, "title": "счёт.pdf",
                                        "ext": "pdf", "size": 10,
                                        "url": "https://vk.com/fresh.pdf"}}
            ]}]}

    app.state.client = FakeVK()
    await http.get(f"/api/attachments/{message_id}/0")
    stored = await pool.fetchval(
        "SELECT attachments FROM ticket_messages WHERE id = $1", message_id)
    assert stored[0]["url"] == "https://vk.com/fresh.pdf"


async def test_unknown_message_is_404(setup):
    http, _, _ = setup
    assert (await http.get("/api/attachments/99999/0")).status_code == 404


async def test_index_out_of_range_is_404(setup):
    http, _, message_id = setup
    assert (await http.get(f"/api/attachments/{message_id}/7")).status_code == 404
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_attachment_proxy.py -q`
Expected: FAIL — маршрута нет

- [ ] **Step 3: Реализовать прокси**

В `app/web/api.py` добавить импорты:

```python
import httpx
from fastapi.responses import Response as RawResponse
from urllib.parse import quote

from app.vk.attachments import parse_attachments
```

и дописать:

```python
ATTACHMENT_TIMEOUT = 30.0


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
        payload = await client.call("messages.getById",
                                    message_ids=row["vk_message_id"])
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

    status, body, content_type = await _fetch_attachment(url)
    if status in (401, 403, 410):
        # Подписанная ссылка протухла — берём свежую и пробуем ещё раз.
        fresh = await _refresh_attachments(request, row)
        if fresh and index < len(fresh):
            url = _attachment_url(fresh[index])
            if url:
                status, body, content_type = await _fetch_attachment(url)
                items = fresh

    if status != 200:
        raise HTTPException(status_code=502, detail="вложение недоступно")

    name = _attachment_name(items[index], index)
    return RawResponse(
        content=body,
        media_type=content_type,
        headers={"content-disposition": f"inline; filename*=UTF-8''{quote(name)}"},
    )
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_attachment_proxy.py -q && uv run ruff check .`
Expected: 7 passed

- [ ] **Step 5: Коммит**

```bash
git add app/web/api.py tests/test_attachment_proxy.py
git commit -m "Добавить прокси входящих вложений с обновлением ссылок"
```

---

### Task 11: WebSocket для реалтайма

**Files:**
- Create: `app/web/ws.py`
- Create: `tests/test_ws.py`

**Interfaces:**
- Consumes: `Bus` (Task 6), `sessions` (Task 3).
- Produces: `app.web.ws.router` с `WebSocket /ws`; авторизация той же сессионной кукой; ping каждые 25 секунд.

- [ ] **Step 1: Написать падающий тест**

`tests/test_ws.py`:

```python
"""Тесты WebSocket.

TestClient крутит приложение в своём потоке и своём цикле событий, а пул
asyncpg привязан к циклу pytest — работать с настоящей базой отсюда нельзя.
Поэтому проверку сессии подменяем заглушкой: предмет этих тестов — авторизация
сокета, учёт подписчиков и ping/pong, а не драйвер БД. Доставка события
подписчику покрыта тестами шины в Task 6.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from websockets.exceptions import WebSocketException

from app.web import sessions, ws
from app.web.bus import Bus

VALID = "valid-token"


@pytest.fixture
def app_with_ws(monkeypatch):
    async def fake_verify(pool, token):
        return {"id": "session"} if token == VALID else None

    monkeypatch.setattr(sessions, "verify", fake_verify)

    app = FastAPI()
    app.include_router(ws.router)
    app.state.pool = None
    app.state.bus = Bus()
    return app


def test_rejects_without_cookie(app_with_ws):
    with TestClient(app_with_ws) as http:
        with pytest.raises((WebSocketException, Exception)):  # noqa: B017
            with http.websocket_connect("/ws"):
                pass
    assert app_with_ws.state.bus.subscribers == 0


def test_rejects_bad_cookie(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, "garbage")
        with pytest.raises((WebSocketException, Exception)):  # noqa: B017
            with http.websocket_connect("/ws"):
                pass
    assert app_with_ws.state.bus.subscribers == 0


def test_accepts_valid_cookie_and_greets(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, VALID)
        with http.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "ready"


def test_subscriber_registered_and_released(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, VALID)
        with http.websocket_connect("/ws") as socket:
            socket.receive_json()
            assert app_with_ws.state.bus.subscribers == 1
    assert app_with_ws.state.bus.subscribers == 0


def test_ping_pong(app_with_ws):
    with TestClient(app_with_ws) as http:
        http.cookies.set(sessions.COOKIE_NAME, VALID)
        with http.websocket_connect("/ws") as socket:
            socket.receive_json()
            socket.send_json({"type": "ping"})
            assert socket.receive_json()["type"] == "pong"
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_ws.py -q`
Expected: FAIL — модуля нет

- [ ] **Step 3: Реализовать**

`app/web/ws.py`:

```python
"""WebSocket для дашборда.

Авторизация той же сессионной кукой, что и REST: отдельный токен в адресе
светил бы сессию в логах прокси.
"""

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.web import sessions

logger = logging.getLogger(__name__)

router = APIRouter()

PING_INTERVAL = 25.0


@router.websocket("/ws")
async def dashboard_socket(socket: WebSocket) -> None:
    token = socket.cookies.get(sessions.COOKIE_NAME, "")
    if await sessions.verify(socket.app.state.pool, token) is None:
        await socket.close(code=4401)
        return

    await socket.accept()
    bus = socket.app.state.bus
    queue = bus.subscribe()
    await socket.send_json({"type": "ready"})

    async def pump() -> None:
        while True:
            event = await queue.get()
            await socket.send_json(event)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    socket.receive_json(), timeout=PING_INTERVAL
                )
            except TimeoutError:
                # Тишина в обе стороны убивает соединение на прокси Railway.
                await socket.send_json({"type": "ping"})
                continue
            if message.get("type") == "ping":
                await socket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("websocket оборвался с ошибкой")
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        bus.unsubscribe(queue)
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_ws.py -q && uv run ruff check .`
Expected: 5 passed

- [ ] **Step 5: Коммит**

```bash
git add app/web/ws.py tests/test_ws.py
git commit -m "Добавить WebSocket для реалтайма дашборда"
```

---

### Task 12: Веб-пуши

**Files:**
- Create: `app/web/push.py`
- Create: `tests/test_push.py`

**Interfaces:**
- Produces:
  - `app.web.push.save_subscription(pool, subscription: dict) -> None`
  - `app.web.push.drop_subscription(pool, endpoint: str) -> None`
  - `app.web.push.send_to_all(pool, cfg, payload: dict) -> int` — возвращает количество доставленных
  - `app.web.push.router` с `GET /api/push/key`, `POST /api/push/subscribe`, `POST /api/push/unsubscribe`

`pywebpush` синхронная и внутри использует `requests`. Вызов напрямую заблокировал бы event loop вместе с приёмом вебхука ВК, поэтому она уходит в `asyncio.to_thread`.

Подписки с ответом 404 или 410 удаляются: браузер их отозвал, повторять бессмысленно. iOS периодически сбрасывает подписку сам, поэтому фронт переподписывается при каждом запуске.

- [ ] **Step 1: Написать падающий тест**

`tests/test_push.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.web import push, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
    "VAPID_PUBLIC_KEY": "B" * 87, "VAPID_PRIVATE_KEY": "p" * 43,
    "VAPID_SUBJECT": "mailto:a@b.c",
}
CFG = load_config(ENV)

SUBSCRIPTION = {
    "endpoint": "https://push.apple.com/abc",
    "keys": {"p256dh": "ключ", "auth": "секрет"},
}


@pytest.fixture
async def client(pool):
    app = FastAPI()
    app.include_router(push.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


async def test_key_endpoint_returns_public_key(client):
    response = await client.get("/api/push/key")
    assert response.json() == {"key": "B" * 87}


async def test_subscribe_stores_subscription(client, pool):
    assert (await client.post("/api/push/subscribe", json=SUBSCRIPTION)).status_code == 200
    row = await pool.fetchrow("SELECT * FROM push_subscriptions")
    assert row["endpoint"] == SUBSCRIPTION["endpoint"]
    assert row["p256dh"] == "ключ"


async def test_subscribe_is_idempotent(client, pool):
    """iOS переподписывается при каждом запуске — дублей быть не должно."""
    await client.post("/api/push/subscribe", json=SUBSCRIPTION)
    await client.post("/api/push/subscribe", json=SUBSCRIPTION)
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 1


async def test_subscribe_rejects_malformed_body(client, pool):
    response = await client.post("/api/push/subscribe", json={"endpoint": ""})
    assert response.status_code == 400
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 0


async def test_unsubscribe_removes_it(client, pool):
    await client.post("/api/push/subscribe", json=SUBSCRIPTION)
    await client.post("/api/push/unsubscribe", json={"endpoint": SUBSCRIPTION["endpoint"]})
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 0


async def test_subscribe_requires_session(pool):
    app = FastAPI()
    app.include_router(push.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    assert (await http.post("/api/push/subscribe", json=SUBSCRIPTION)).status_code == 401


async def test_send_delivers_to_every_subscription(pool, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "_deliver", lambda sub, data, cfg: sent.append(sub["endpoint"]))

    await push.save_subscription(pool, SUBSCRIPTION)
    await push.save_subscription(pool, {**SUBSCRIPTION, "endpoint": "https://push/2"})

    delivered = await push.send_to_all(pool, CFG, {"title": "Новое обращение"})
    assert delivered == 2
    assert sorted(sent) == ["https://push.apple.com/abc", "https://push/2"]


async def test_gone_subscription_is_removed(pool, monkeypatch):
    """410 означает, что браузер отозвал подписку навсегда."""
    class Gone(Exception):
        def __init__(self):
            self.response = type("R", (), {"status_code": 410})()

    monkeypatch.setattr(push, "WebPushException", Gone)

    def deliver(sub, data, cfg):
        raise Gone()

    monkeypatch.setattr(push, "_deliver", deliver)
    await push.save_subscription(pool, SUBSCRIPTION)

    assert await push.send_to_all(pool, CFG, {"title": "тест"}) == 0
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 0


async def test_temporary_failure_keeps_subscription(pool, monkeypatch):
    class Failed(Exception):
        def __init__(self):
            self.response = type("R", (), {"status_code": 500})()

    monkeypatch.setattr(push, "WebPushException", Failed)

    def deliver(sub, data, cfg):
        raise Failed()

    monkeypatch.setattr(push, "_deliver", deliver)
    await push.save_subscription(pool, SUBSCRIPTION)

    assert await push.send_to_all(pool, CFG, {"title": "тест"}) == 0
    assert await pool.fetchval("SELECT count(*) FROM push_subscriptions") == 1


async def test_send_without_subscriptions_is_harmless(pool):
    assert await push.send_to_all(pool, CFG, {"title": "тест"}) == 0
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_push.py -q`
Expected: FAIL — модуля нет

- [ ] **Step 3: Реализовать**

`app/web/push.py`:

```python
"""Веб-пуши оператору.

pywebpush синхронная и внутри ходит через requests. Прямой вызов заблокировал
бы event loop вместе с приёмом вебхука ВК, поэтому она уходит в поток.

Ограничения iOS, которые видны в поведении: пуши приходят только если PWA
добавлена на экран «Домой», и iOS периодически сбрасывает подписку — фронт
переподписывается при каждом запуске, поэтому запись подписки идемпотентна.
"""

import asyncio
import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from pywebpush import WebPushException, webpush

from app.config import Config
from app.web import sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/push", dependencies=[Depends(sessions.require_session)])

TTL_SECONDS = 3600
DEAD_STATUSES = (404, 410)


async def save_subscription(pool: asyncpg.Pool, subscription: dict) -> None:
    keys = subscription.get("keys") or {}
    await pool.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth) VALUES ($1, $2, $3)"
        " ON CONFLICT (endpoint) DO UPDATE SET"
        " p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth",
        subscription["endpoint"], keys.get("p256dh", ""), keys.get("auth", ""),
    )


async def drop_subscription(pool: asyncpg.Pool, endpoint: str) -> None:
    await pool.execute("DELETE FROM push_subscriptions WHERE endpoint = $1", endpoint)


def _deliver(subscription: dict, data: str, cfg: Config) -> None:
    """Синхронная отправка. Вызывается только внутри потока."""
    webpush(
        subscription_info=subscription,
        data=data,
        vapid_private_key=cfg.vapid_private_key,
        vapid_claims={"sub": cfg.vapid_subject},
        ttl=TTL_SECONDS,
    )


async def send_to_all(pool: asyncpg.Pool, cfg: Config, payload: dict) -> int:
    rows = await pool.fetch("SELECT * FROM push_subscriptions")
    if not rows:
        return 0

    data = json.dumps(payload, ensure_ascii=False)
    delivered = 0
    for row in rows:
        subscription = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        try:
            await asyncio.to_thread(_deliver, subscription, data, cfg)
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in DEAD_STATUSES:
                # Браузер отозвал подписку навсегда — держать её незачем.
                await drop_subscription(pool, row["endpoint"])
                logger.info("подписка на пуши удалена, ответ %s", status)
            else:
                logger.warning("пуш не доставлен, ответ %s", status)
            continue
        except Exception:
            logger.exception("пуш не доставлен")
            continue

        delivered += 1
        await pool.execute(
            "UPDATE push_subscriptions SET last_ok_at = now() WHERE endpoint = $1",
            row["endpoint"],
        )
    return delivered


@router.get("/key")
async def public_key(request: Request) -> dict:
    return {"key": request.app.state.cfg.vapid_public_key}


@router.post("/subscribe")
async def subscribe(request: Request) -> dict:
    body = await request.json()
    keys = body.get("keys") or {}
    if not body.get("endpoint") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail="подписка неполная")
    await save_subscription(request.app.state.pool, body)
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(request: Request) -> dict:
    body = await request.json()
    await drop_subscription(request.app.state.pool, str(body.get("endpoint", "")))
    return {"ok": True}
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_push.py -q && uv run ruff check .`
Expected: 10 passed

- [ ] **Step 5: Коммит**

```bash
git add app/web/push.py tests/test_push.py
git commit -m "Добавить веб-пуши оператору"
```

---

### Task 13: Статистика

**Files:**
- Modify: `app/db/queries.py`
- Modify: `app/web/api.py`
- Create: `tests/test_api_stats.py`

**Interfaces:**
- Produces: `queries.stats(pool) -> Record`, `GET /api/stats` → `{"day": {...}, "week": {...}, "open_now": int, "avg_first_reply_seconds": float | None, "avg_rating": float | None}`

- [ ] **Step 1: Написать падающий тест**

`tests/test_api_stats.py`:

```python
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.web import api, sessions

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
}
CFG = load_config(ENV)


@pytest.fixture
async def client(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    http.cookies.set(sessions.COOKIE_NAME, await sessions.issue(pool))
    return http


async def test_stats_require_session(pool):
    app = FastAPI()
    app.include_router(api.router)
    app.state.cfg = CFG
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="https://test")
    assert (await http.get("/api/stats")).status_code == 401


async def test_empty_stats(client):
    body = (await client.get("/api/stats")).json()
    assert body["day"] == 0
    assert body["week"] == 0
    assert body["open_now"] == 0
    assert body["avg_first_reply_seconds"] is None
    assert body["avg_rating"] is None


async def test_counts_today_and_week(client, pool):
    await q.upsert_user(pool, 1)
    await q.create_ticket(pool, 1)
    await pool.execute(
        "INSERT INTO users (vk_id) VALUES (2);"
        " INSERT INTO tickets (user_id, status, created_at)"
        " VALUES (2, 'closed', now() - interval '3 days')"
    )
    body = (await client.get("/api/stats")).json()
    assert body["day"] == 1
    assert body["week"] == 2


async def test_counts_open_now(client, pool):
    await q.upsert_user(pool, 1)
    await q.create_ticket(pool, 1)
    assert (await client.get("/api/stats")).json()["open_now"] == 1


async def test_average_first_reply(client, pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await pool.execute(
        "UPDATE tickets SET created_at = now() - interval '120 seconds',"
        " first_reply_at = now() WHERE id = $1", ticket_id)
    value = (await client.get("/api/stats")).json()["avg_first_reply_seconds"]
    assert 110 <= value <= 130


async def test_average_rating(client, pool):
    await q.upsert_user(pool, 1)
    first = await q.create_ticket(pool, 1)
    await q.close_ticket(pool, first, rating=5)
    await q.upsert_user(pool, 2)
    second = await q.create_ticket(pool, 2)
    await q.close_ticket(pool, second, rating=3)
    assert (await client.get("/api/stats")).json()["avg_rating"] == 4.0


async def test_old_tickets_excluded_from_week(client, pool):
    await pool.execute(
        "INSERT INTO users (vk_id) VALUES (9);"
        " INSERT INTO tickets (user_id, status, created_at)"
        " VALUES (9, 'closed', now() - interval '30 days')"
    )
    assert (await client.get("/api/stats")).json()["week"] == 0
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_api_stats.py -q`
Expected: FAIL — маршрута нет

- [ ] **Step 3: Реализовать**

Дописать в `app/db/queries.py`:

```python
async def stats(pool: asyncpg.Pool) -> asyncpg.Record:
    return await pool.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE created_at > now() - interval '1 day')  AS day,
            count(*) FILTER (WHERE created_at > now() - interval '7 days') AS week,
            count(*) FILTER (WHERE status <> 'closed')                     AS open_now,
            avg(EXTRACT(EPOCH FROM (first_reply_at - created_at)))
                FILTER (WHERE first_reply_at IS NOT NULL)      AS avg_first_reply,
            avg(rating) FILTER (WHERE rating IS NOT NULL)      AS avg_rating
        FROM tickets
        """
    )
```

Дописать в `app/web/api.py`:

```python
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
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_api_stats.py -q && uv run ruff check .`
Expected: 7 passed

- [ ] **Step 5: Коммит**

```bash
git add app/db/queries.py app/web/api.py tests/test_api_stats.py
git commit -m "Добавить статистику обращений"
```

---

### Task 14: Сборка: подключить дашборд к приложению

**Files:**
- Modify: `app/main.py`
- Modify: `app/maintenance.py`
- Create: `tests/test_main_dashboard.py`

**Interfaces:**
- Produces: приложение с подключёнными роутерами `auth`, `api`, `push`, `ws`; `app.state.bus`; уведомление из обработчика идёт в шину, а при отсутствии подключённых клиентов — в пуш.

- [ ] **Step 1: Написать падающий тест**

`tests/test_main_dashboard.py`:

```python
from app.config import load_config
from app.main import build_notifier, create_app
from app.web.bus import Bus

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код",
    "VK_SECRET_KEY": "Zx9KpQm2LtVn", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "PUBLIC_URL": "https://bot.example",
    "VAPID_PUBLIC_KEY": "B" * 87, "VAPID_PRIVATE_KEY": "p" * 43,
    "VAPID_SUBJECT": "mailto:a@b.c",
}
CFG = load_config(ENV)


def test_all_dashboard_routes_registered():
    paths = set(create_app(CFG).openapi()["paths"])
    for path in (
        "/vk/callback", "/healthz",
        "/api/auth/login/options", "/api/auth/logout",
        "/api/dialogs", "/api/stats", "/api/push/key",
    ):
        assert path in paths, path


def test_bus_is_created():
    assert isinstance(create_app(CFG).state.bus, Bus)


async def test_notifier_publishes_to_bus(pool):
    bus = Bus()
    queue = bus.subscribe()
    notify = build_notifier(pool, CFG, bus, send_push=None)
    await notify({"type": "message", "ticket_id": 1})
    assert queue.get_nowait()["ticket_id"] == 1


async def test_push_sent_when_nobody_is_connected(pool):
    """Дашборд закрыт — единственный способ дозваться оператора это пуш."""
    pushed = []

    async def send_push(payload):
        pushed.append(payload)

    notify = build_notifier(pool, CFG, Bus(), send_push=send_push)
    await notify({"type": "message", "ticket_id": 1, "text": "проблема"})
    assert len(pushed) == 1
    assert "проблема" in pushed[0]["body"]


async def test_push_skipped_when_dashboard_open(pool):
    """Оператор смотрит в экран — дублировать пушем незачем."""
    pushed = []

    async def send_push(payload):
        pushed.append(payload)

    bus = Bus()
    bus.subscribe()
    notify = build_notifier(pool, CFG, bus, send_push=send_push)
    await notify({"type": "message", "ticket_id": 1, "text": "проблема"})
    assert pushed == []


async def test_push_body_describes_attachments(pool):
    pushed = []

    async def send_push(payload):
        pushed.append(payload)

    notify = build_notifier(pool, CFG, Bus(), send_push=send_push)
    await notify({
        "type": "message", "ticket_id": 1, "text": "",
        "attachments": [{"type": "photo"}, {"type": "photo"}],
    })
    assert "2 фото" in pushed[0]["body"]
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_main_dashboard.py -q`
Expected: FAIL — `build_notifier` не существует

- [ ] **Step 3: Реализовать**

В `app/main.py` добавить импорты:

```python
from collections.abc import Awaitable, Callable

from app.vk.attachments import describe
from app.web import push as web_push
from app.web.api import router as api_router
from app.web.auth import router as auth_router
from app.web.bus import Bus
from app.web.push import router as push_router
from app.web.ws import router as ws_router
```

Добавить функцию до `create_app`:

```python
PUSH_PREVIEW_LIMIT = 120


def build_notifier(
    pool, cfg: Config, bus: Bus,
    send_push: Callable[[dict], Awaitable[None]] | None,
):
    """Событие уходит в открытый дашборд, а если его никто не смотрит — в пуш."""

    async def notify(event: dict) -> None:
        delivered = await bus.publish(event)
        if delivered or send_push is None:
            return

        text = (event.get("text") or "").strip()
        summary = describe(event.get("attachments") or [])
        body = ", ".join(part for part in (text[:PUSH_PREVIEW_LIMIT], summary) if part)
        await send_push({
            "title": "Новое сообщение",
            "body": body or "Вложение",
            "ticket_id": event.get("ticket_id"),
        })

    return notify
```

В `create_app` после `application.state.background = set()` добавить:

```python
    application.state.bus = Bus()
```

Заменить подключение роутеров:

```python
    application.include_router(callback_router)
```

на:

```python
    application.include_router(callback_router)
    application.include_router(auth_router)
    application.include_router(api_router)
    application.include_router(push_router)
    application.include_router(ws_router)
```

Заменить обработчик:

```python
    async def handler(event: dict) -> None:
        await handle_event(application.state.pool, cfg, event)
```

на:

```python
    async def handler(event: dict) -> None:
        async def send_push(payload: dict) -> None:
            await web_push.send_to_all(application.state.pool, cfg, payload)

        notify = build_notifier(
            application.state.pool, cfg, application.state.bus,
            send_push if cfg.dashboard_ready else None,
        )
        await handle_event(application.state.pool, cfg, event, notify=notify)
```

- [ ] **Step 4: Расширить уборку**

В `app/maintenance.py` добавить импорты:

```python
from app.web import challenges, sessions
```

и в `run_housekeeping` заменить тело `try`:

```python
            events = await q.cleanup_old_events(pool)
            tokens = await setup_tokens.purge_expired(pool)
            if events or tokens:
                logger.info("уборка: событий %s, токенов %s", events, tokens)
```

на:

```python
            events = await q.cleanup_old_events(pool)
            tokens = await setup_tokens.purge_expired(pool)
            stale_sessions = await sessions.purge_expired(pool)
            stale_challenges = await challenges.purge_expired(pool)
            if events or tokens or stale_sessions or stale_challenges:
                logger.info(
                    "уборка: событий %s, токенов %s, сессий %s, challenge %s",
                    events, tokens, stale_sessions, stale_challenges,
                )
```

- [ ] **Step 5: Прогнать всё и линтер**

Run: `uv run pytest -q && uv run ruff check .`
Expected: всё зелёное

- [ ] **Step 6: Проверить сквозной сценарий вживую**

Поднять приложение локально против `pgserver`, затем:

```bash
# 1. Диалоги без сессии — 401
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/api/dialogs

# 2. Вход без ключей — 409 с внятным текстом
curl -s -X POST localhost:8000/api/auth/login/options

# 3. Живость
curl -s localhost:8000/healthz
```

Expected: `401`, затем `409` с сообщением про `/link`, затем `{"status":"ok"}`

- [ ] **Step 7: Коммит**

```bash
git add app/main.py app/maintenance.py tests/test_main_dashboard.py
git commit -m "Подключить дашборд к приложению"
```

---

## Сознательно вне объёма

Редактирование FAQ (`GET/POST/DELETE /api/faq`) в этот план не входит — отложено
по решению заказчика. Бот на пустую таблицу отвечает корректной заглушкой, так
что отсутствие раздела ничего не ломает. Когда понадобится, это отдельная
небольшая задача: четыре маршрута поверх уже готовых `list_active_faq` и `get_faq`.

Голосовые и видео от оператора тоже вне объёма — решено на этапе дизайна.

## Что дальше

После этого плана API дашборда готов и покрыт тестами, но интерфейса нет —
пользоваться можно только через curl. Следующий план,
`2026-09-20-dashboard-frontend.md`, добавляет PWA: экраны диалогов, FAQ,
статистики и настроек, визуальный язык по референсам, service worker,
онбординг «Поделиться → На экран Домой» и подписку на пуши.

Перед выкладкой дашборда в прод надо будет добавить в Railway переменные
`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`
(`WEBAUTHN_RP_ID` и `WEBAUTHN_ORIGIN` выведутся из домена сами).
