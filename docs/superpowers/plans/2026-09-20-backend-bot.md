# Бэкенд бота поддержки ВК — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Работающий бот поддержки ВК: принимает обращения, отвечает на FAQ, складывает диалоги и вложения в Postgres, надёжно отправляет ответы через очередь, выдерживает шторм повторов Callback API.

**Architecture:** Один процесс FastAPI принимает Callback API на `/vk/callback`, мгновенно отвечает `ok` и уводит обработку в фон. Все исходящие сообщения идут только через таблицу `outbox`, которую разгребает фоновый воркер с ограничением 20 rps и ретраями. Состояние диалогов — в Postgres, не в памяти: Railway перезапускает процесс в любой момент.

**Tech Stack:** Python 3.12 (через `uv`), FastAPI, uvicorn, vkbottle 4.11 (только как клиент VK API), asyncpg, pytest + pytest-asyncio, ruff, locust.

**Spec:** `docs/superpowers/specs/2026-09-20-vk-support-bot-design.md`

## Global Constraints

- Python 3.12. Локально ставится командой `uv venv --python 3.12`. Системный Python 3.14 не использовать: vkbottle 4.11 на нём не проверен.
- vkbottle используется **только** как клиент VK API (`API`, `Keyboard`, `Text`, `Callback`, `KeyboardButtonColor`, `VKAPIError`, аплоадеры, `BotPolling`). Её собственный `Bot`-рантайм и декораторы `@bot.on.message` не применять — события принимает FastAPI.
- Проверенные сигнатуры vkbottle 4.11, использовать именно их:
  - `Keyboard(one_time: bool = False, inline: bool = False)`, методы `.row()`, `.add(action, color=None)`, `.get_json()`
  - `Text(label: str, payload: str | dict | None = None)`
  - `Callback(label: str, payload: str | dict)` — **не** `Callback(Text(...), ...)`, в документации на сайте устаревший пример
  - `API.request(method: str, data: dict, version: str | None = None) -> dict`
  - `PhotoMessageUploader.upload(file_source, peer_id=None, **params) -> str`
  - `DocMessagesUploader.upload(file_source, group_id=None, peer_id=None, **params) -> str`
  - `KeyboardButtonColor` содержит ровно `PRIMARY`, `SECONDARY`, `NEGATIVE`, `POSITIVE`
  - `VKAPIError[code](error_msg="...")` — конструктор принимает **только** именованные
    аргументы; `VKAPIError[6]("текст")` падает с TypeError
- `VK_API_VERSION` по умолчанию `5.199`.
- Любая исходящая отправка — только через `outbox.enqueue(...)`. Прямой вызов `messages.send` из обработчика запрещён.
- `random_id` генерируется один раз при постановке в очередь и не меняется при ретраях.
- Маршрутизация кнопок только по `payload`, никогда по тексту кнопки.
- Токены, `VK_SECRET_KEY` и тексты сообщений пользователей не логировать. В логи ошибок VK API идут только код и метод.
- Каждая задача заканчивается коммитом. Сообщения коммитов на русском, в повелительном наклонении.
- Реальных запросов к VK API в тестах нет — только замоканный клиент.
- Postgres для тестов приносит пакет `pgserver`: ни brew, ни docker, ни системного сервиса.
- Колонки `jsonb` читаются и пишутся обычными `dict`/`list`. Кодеки регистрируются
  в `create_pool`; без них asyncpg отдаёт jsonb строкой. Ручной `json.dumps` и каст
  `::jsonb` в запросах не нужны и ломают кодек двойным кодированием.

---

### Task 1: Каркас проекта, конфиг и валидация окружения

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `.env.example`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: ничего, это первая задача.
- Produces: `app.config.Config` (frozen dataclass) и `app.config.load_config(env: Mapping[str, str]) -> Config`. Поля: `vk_group_token: str`, `vk_group_id: int`, `vk_confirmation_code: str`, `vk_secret_key: str`, `vk_api_version: str`, `admin_id: int`, `database_url: str`, `vk_mode: str`, `work_hours: tuple[int, int]`, `tz: str`, `session_secret: str`, `webauthn_rp_id: str`, `webauthn_origin: str`, `vapid_public_key: str`, `vapid_private_key: str`, `vapid_subject: str`. Исключение `app.config.ConfigError`.

- [ ] **Step 1: Создать окружение и pyproject**

```bash
cd /Users/maximiliannovikov/Desktop/VKbot
uv venv --python 3.12
```

`pyproject.toml`:

```toml
[project]
name = "vk-support-bot"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "vkbottle==4.11.0",
    "asyncpg>=0.30",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "locust>=2.32",
    "httpx>=0.28",
    "pgserver>=0.1.4",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC", "S"]
ignore = ["S101"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S105", "S106"]
```

```bash
uv sync
```

- [ ] **Step 2: Написать падающий тест**

`tests/test_config.py`:

```python
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
```

- [ ] **Step 3: Прогнать тест, убедиться что падает**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 4: Реализовать конфиг**

`app/__init__.py` — пустой файл.

`app/config.py`:

```python
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

    return Config(
        vk_group_token=_required(env, "VK_GROUP_TOKEN"),
        vk_group_id=_required_int(env, "VK_GROUP_ID"),
        vk_confirmation_code=_required(env, "VK_CONFIRMATION_CODE"),
        vk_secret_key=_required(env, "VK_SECRET_KEY"),
        vk_api_version=env.get("VK_API_VERSION", "").strip() or "5.199",
        admin_id=_required_int(env, "ADMIN_ID"),
        database_url=_required(env, "DATABASE_URL"),
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
```

`tests/__init__.py` — пустой файл.

`.env.example`:

```
# Значения заполняются в Railway Variables, не здесь
VK_GROUP_TOKEN=
VK_GROUP_ID=
VK_CONFIRMATION_CODE=
VK_SECRET_KEY=
VK_API_VERSION=5.199
ADMIN_ID=
DATABASE_URL=
VK_MODE=callback
WORK_HOURS=10-19
TZ=Europe/Moscow
SESSION_SECRET=
WEBAUTHN_RP_ID=
WEBAUTHN_ORIGIN=
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=
```

- [ ] **Step 5: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_config.py -v && uv run ruff check .`
Expected: 9 passed, ruff без ошибок

- [ ] **Step 6: Коммит**

```bash
git add pyproject.toml uv.lock app tests .env.example
git commit -m "Добавить каркас проекта и валидацию окружения"
```

---

### Task 2: Пул Postgres и миграции

**Files:**
- Create: `app/db/__init__.py`
- Create: `app/db/pool.py`
- Create: `app/db/migrations/001_init.sql`
- Create: `tests/conftest.py`
- Create: `tests/test_migrations.py`

**Interfaces:**
- Consumes: `app.config.Config` из Task 1.
- Produces: `app.db.pool.create_pool(dsn: str) -> asyncpg.Pool`, `app.db.pool.apply_migrations(pool: asyncpg.Pool) -> list[str]` (возвращает имена применённых файлов). Фикстура `pool` в `tests/conftest.py`, дающая чистую БД на каждый тест.

- [ ] **Step 1: Написать падающий тест**

`tests/test_migrations.py`:

```python
from app.db.pool import apply_migrations

EXPECTED_TABLES = {
    "users", "tickets", "ticket_messages", "faq", "processed_events",
    "outbox", "admin_credentials", "sessions", "push_subscriptions",
    "setup_tokens", "schema_migrations",
}


async def test_creates_all_tables(pool):
    rows = await pool.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    assert EXPECTED_TABLES <= {r["tablename"] for r in rows}


async def test_migrations_are_idempotent(pool):
    applied = await apply_migrations(pool)
    assert applied == []


async def test_records_applied_migration(pool):
    names = await pool.fetch("SELECT name FROM schema_migrations ORDER BY name")
    assert [r["name"] for r in names] == ["001_init.sql"]


async def test_ticket_status_is_constrained(pool):
    await pool.execute("INSERT INTO users (vk_id) VALUES (1)")
    import asyncpg
    import pytest
    with pytest.raises(asyncpg.IntegrityConstraintViolationError):
        await pool.execute(
            "INSERT INTO tickets (user_id, status) VALUES (1, 'нет такого статуса')"
        )
```

`tests/conftest.py`:

```python
"""Постгрес для тестов поднимается из пакета pgserver.

Системный Postgres не нужен: ни brew, ни docker, ни запущенного сервиса.
Это же делает набор тестов воспроизводимым в CI.
"""

import os
import pathlib
import tempfile

import pgserver
import pytest
import pytest_asyncio

from app.db.pool import apply_migrations, create_pool

TEST_DB = "vkbot_test"


@pytest.fixture(scope="session")
def dsn() -> str:
    """Один сервер на весь прогон: старт занимает пару секунд."""
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override

    data_dir = pathlib.Path(tempfile.gettempdir()) / "vkbot-pgserver"
    data_dir.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(data_dir))
    server.psql(f"DROP DATABASE IF EXISTS {TEST_DB};")
    server.psql(f"CREATE DATABASE {TEST_DB};")
    return server.get_uri(database=TEST_DB)


@pytest_asyncio.fixture
async def pool(dsn):
    """Чистая база на каждый тест: дропаем схему, накатываем миграции заново."""
    conn_pool = await create_pool(dsn)
    async with conn_pool.acquire() as conn:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await apply_migrations(conn_pool)
    try:
        yield conn_pool
    finally:
        await conn_pool.close()
```

- [ ] **Step 2: Прогнать тест**

Postgres ставить не нужно — `pgserver` приносит его с собой и поднимает на unix-сокете.

Run: `uv run pytest tests/test_migrations.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Написать миграцию**

`app/db/__init__.py` — пустой файл.

`app/db/migrations/001_init.sql`:

```sql
CREATE TABLE users (
    vk_id       BIGINT PRIMARY KEY,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    photo_url   TEXT NOT NULL DEFAULT '',
    can_write   BOOLEAN NOT NULL DEFAULT TRUE,
    state       TEXT NOT NULL DEFAULT 'idle',
    state_data  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tickets (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(vk_id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'closed')),
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    first_reply_at  TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    unread_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX tickets_queue_idx ON tickets (status, last_message_at DESC);
-- У пользователя не может быть двух незакрытых обращений одновременно.
CREATE UNIQUE INDEX tickets_one_open_per_user
    ON tickets (user_id) WHERE status <> 'closed';

CREATE TABLE ticket_messages (
    id             BIGSERIAL PRIMARY KEY,
    ticket_id      BIGINT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    direction      TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    text           TEXT NOT NULL DEFAULT '',
    attachments    JSONB NOT NULL DEFAULT '[]'::jsonb,
    vk_message_id  BIGINT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at        TIMESTAMPTZ
);
CREATE INDEX ticket_messages_feed_idx ON ticket_messages (ticket_id, created_at);

CREATE TABLE faq (
    id        BIGSERIAL PRIMARY KEY,
    title     TEXT NOT NULL,
    answer    TEXT NOT NULL,
    position  INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX faq_order_idx ON faq (is_active, position);

CREATE TABLE processed_events (
    event_id   TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX processed_events_cleanup_idx ON processed_events (created_at);

CREATE TABLE outbox (
    id              BIGSERIAL PRIMARY KEY,
    peer_id         BIGINT NOT NULL,
    payload         JSONB NOT NULL,
    random_id       INTEGER NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);
CREATE INDEX outbox_worker_idx ON outbox (status, next_attempt_at) WHERE status = 'pending';

CREATE TABLE admin_credentials (
    id            BIGSERIAL PRIMARY KEY,
    credential_id BYTEA NOT NULL UNIQUE,
    public_key    BYTEA NOT NULL,
    sign_count    BIGINT NOT NULL DEFAULT 0,
    transports    TEXT[] NOT NULL DEFAULT '{}',
    name          TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ
);

CREATE TABLE sessions (
    id         TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX sessions_expiry_idx ON sessions (expires_at);

CREATE TABLE push_subscriptions (
    id         BIGSERIAL PRIMARY KEY,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_ok_at TIMESTAMPTZ
);

CREATE TABLE setup_tokens (
    token_hash TEXT PRIMARY KEY,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at    TIMESTAMPTZ
);
```

- [ ] **Step 4: Реализовать пул и накатывание миграций**

`app/db/pool.py`:

```python
"""Пул соединений и накатывание SQL-миграций при старте."""

import json
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def _register_codecs(conn: asyncpg.Connection) -> None:
    """Без этого asyncpg отдаёт jsonb строкой, и весь код разбирает JSON руками.

    С кодеком в запросы передаются обычные dict и list, а обратно приходят они же.
    """
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def create_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn, min_size=2, max_size=10, command_timeout=30, init=_register_codecs
    )


async def apply_migrations(pool: asyncpg.Pool) -> list[str]:
    """Накатывает неприменённые .sql по возрастанию имени. Возвращает что применил."""
    async with pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name TEXT PRIMARY KEY,"
            " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}

        applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            # Миграция и отметка о ней — в одной транзакции, иначе половинчатое состояние.
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES ($1)", path.name
                )
            logger.info("применена миграция %s", path.name)
            applied.append(path.name)
        return applied
```

- [ ] **Step 5: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_migrations.py -v && uv run ruff check .`
Expected: 4 passed

- [ ] **Step 6: Коммит**

```bash
git add app/db tests/conftest.py tests/test_migrations.py
git commit -m "Добавить пул Postgres и начальную миграцию схемы"
```

---

### Task 3: Слой запросов к БД

**Files:**
- Create: `app/db/queries.py`
- Create: `tests/test_queries.py`

**Interfaces:**
- Consumes: фикстура `pool` из Task 2.
- Produces: модуль `app.db.queries` с функциями:
  - `upsert_user(pool, vk_id: int, first_name: str = "", last_name: str = "", photo_url: str = "") -> None`
  - `set_user_state(pool, vk_id: int, state: str, state_data: dict | None = None) -> None`
  - `get_user(pool, vk_id: int) -> asyncpg.Record | None`
  - `mark_cannot_write(pool, vk_id: int) -> None`
  - `get_open_ticket(pool, user_id: int) -> asyncpg.Record | None`
  - `create_ticket(pool, user_id: int) -> int`
  - `close_ticket(pool, ticket_id: int, rating: int | None = None) -> None`
  - `add_message(pool, ticket_id: int, direction: str, text: str, attachments: list[dict] | None = None, vk_message_id: int | None = None) -> int`
  - `list_active_faq(pool) -> list[asyncpg.Record]`
  - `get_faq(pool, faq_id: int) -> asyncpg.Record | None`
  - `remember_event(pool, event_id: str) -> bool` — `True` если событие новое
  - `cleanup_old_events(pool) -> int`

- [ ] **Step 1: Написать падающий тест**

`tests/test_queries.py`:

```python
from app.db import queries as q


async def test_upsert_user_creates_then_updates(pool):
    await q.upsert_user(pool, 1, "Максим", "Новиков")
    await q.upsert_user(pool, 1, "Максим", "Михайлов")
    user = await q.get_user(pool, 1)
    assert user["last_name"] == "Михайлов"
    count = await pool.fetchval("SELECT count(*) FROM users")
    assert count == 1


async def test_state_roundtrip(pool):
    await q.upsert_user(pool, 1)
    await q.set_user_state(pool, 1, "awaiting_problem", {"from": "menu"})
    user = await q.get_user(pool, 1)
    assert user["state"] == "awaiting_problem"
    assert user["state_data"] == {"from": "menu"}


async def test_mark_cannot_write(pool):
    await q.upsert_user(pool, 1)
    await q.mark_cannot_write(pool, 1)
    assert (await q.get_user(pool, 1))["can_write"] is False


async def test_open_ticket_lifecycle(pool):
    await q.upsert_user(pool, 1)
    assert await q.get_open_ticket(pool, 1) is None

    ticket_id = await q.create_ticket(pool, 1)
    assert (await q.get_open_ticket(pool, 1))["id"] == ticket_id

    await q.close_ticket(pool, ticket_id, rating=5)
    assert await q.get_open_ticket(pool, 1) is None
    row = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    assert row["status"] == "closed"
    assert row["rating"] == 5
    assert row["closed_at"] is not None


async def test_create_ticket_returns_existing_open_one(pool):
    await q.upsert_user(pool, 1)
    first = await q.create_ticket(pool, 1)
    second = await q.create_ticket(pool, 1)
    assert first == second


async def test_add_message_bumps_ticket(pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "in", "не работает", [{"type": "photo"}], 99)

    msg = await pool.fetchrow("SELECT * FROM ticket_messages WHERE ticket_id = $1", ticket_id)
    assert msg["text"] == "не работает"
    assert msg["attachments"] == [{"type": "photo"}]
    assert msg["vk_message_id"] == 99

    ticket = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    assert ticket["unread_count"] == 1


async def test_outgoing_message_does_not_bump_unread(pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "out", "сейчас посмотрю")
    ticket = await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    assert ticket["unread_count"] == 0
    assert ticket["first_reply_at"] is not None


async def test_first_reply_at_set_once(pool):
    await q.upsert_user(pool, 1)
    ticket_id = await q.create_ticket(pool, 1)
    await q.add_message(pool, ticket_id, "out", "раз")
    first = (await pool.fetchrow("SELECT first_reply_at FROM tickets WHERE id=$1", ticket_id))[0]
    await q.add_message(pool, ticket_id, "out", "два")
    second = (await pool.fetchrow("SELECT first_reply_at FROM tickets WHERE id=$1", ticket_id))[0]
    assert first == second


async def test_faq_listing_skips_inactive(pool):
    await pool.execute(
        "INSERT INTO faq (title, answer, position, is_active) VALUES"
        " ('Б', 'ответ Б', 2, TRUE), ('А', 'ответ А', 1, TRUE), ('С', 'ответ С', 3, FALSE)"
    )
    items = await q.list_active_faq(pool)
    assert [i["title"] for i in items] == ["А", "Б"]


async def test_remember_event_deduplicates(pool):
    assert await q.remember_event(pool, "evt-1") is True
    assert await q.remember_event(pool, "evt-1") is False


async def test_cleanup_removes_only_old_events(pool):
    await q.remember_event(pool, "свежее")
    await pool.execute(
        "INSERT INTO processed_events (event_id, created_at)"
        " VALUES ('старое', now() - interval '2 days')"
    )
    assert await q.cleanup_old_events(pool) == 1
    remaining = await pool.fetchval("SELECT event_id FROM processed_events")
    assert remaining == "свежее"
```

- [ ] **Step 2: Прогнать тест, убедиться что падает**

Run: `uv run pytest tests/test_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.queries'`

- [ ] **Step 3: Реализовать запросы**

`app/db/queries.py`:

```python
"""Все SQL-запросы приложения. Никакого SQL за пределами этого модуля.

jsonb передаётся и принимается обычными dict и list: кодеки зарегистрированы
в create_pool, поэтому json.dumps здесь не нужен.
"""

import asyncpg


async def upsert_user(
    pool: asyncpg.Pool,
    vk_id: int,
    first_name: str = "",
    last_name: str = "",
    photo_url: str = "",
) -> None:
    await pool.execute(
        """
        INSERT INTO users (vk_id, first_name, last_name, photo_url)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (vk_id) DO UPDATE SET
            first_name   = COALESCE(NULLIF(EXCLUDED.first_name, ''), users.first_name),
            last_name    = COALESCE(NULLIF(EXCLUDED.last_name, ''), users.last_name),
            photo_url    = COALESCE(NULLIF(EXCLUDED.photo_url, ''), users.photo_url),
            last_seen_at = now()
        """,
        vk_id, first_name, last_name, photo_url,
    )


async def get_user(pool: asyncpg.Pool, vk_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM users WHERE vk_id = $1", vk_id)


async def set_user_state(
    pool: asyncpg.Pool, vk_id: int, state: str, state_data: dict | None = None
) -> None:
    await pool.execute(
        "UPDATE users SET state = $2, state_data = $3 WHERE vk_id = $1",
        vk_id, state, state_data or {},
    )


async def mark_cannot_write(pool: asyncpg.Pool, vk_id: int) -> None:
    await pool.execute("UPDATE users SET can_write = FALSE WHERE vk_id = $1", vk_id)


async def get_open_ticket(pool: asyncpg.Pool, user_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT * FROM tickets WHERE user_id = $1 AND status <> 'closed'", user_id
    )


async def create_ticket(pool: asyncpg.Pool, user_id: int) -> int:
    """Возвращает id открытого обращения, создавая его при необходимости.

    Частичный уникальный индекс не даёт завести второе незакрытое обращение,
    поэтому ON CONFLICT молча возвращает существующее.
    """
    row = await pool.fetchrow(
        """
        INSERT INTO tickets (user_id, status) VALUES ($1, 'open')
        ON CONFLICT (user_id) WHERE status <> 'closed' DO NOTHING
        RETURNING id
        """,
        user_id,
    )
    if row is not None:
        return row["id"]
    existing = await get_open_ticket(pool, user_id)
    return existing["id"]


async def close_ticket(pool: asyncpg.Pool, ticket_id: int, rating: int | None = None) -> None:
    await pool.execute(
        "UPDATE tickets SET status = 'closed', closed_at = now(), rating = $2"
        " WHERE id = $1",
        ticket_id, rating,
    )


async def add_message(
    pool: asyncpg.Pool,
    ticket_id: int,
    direction: str,
    text: str,
    attachments: list[dict] | None = None,
    vk_message_id: int | None = None,
) -> int:
    async with pool.acquire() as conn, conn.transaction():
        message_id = await conn.fetchval(
            """
            INSERT INTO ticket_messages
                (ticket_id, direction, text, attachments, vk_message_id)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            ticket_id, direction, text, attachments or [], vk_message_id,
        )
        await conn.execute(
            """
            UPDATE tickets SET
                last_message_at = now(),
                unread_count = CASE WHEN $2 = 'in' THEN unread_count + 1 ELSE unread_count END,
                first_reply_at = CASE
                    WHEN $2 = 'out' AND first_reply_at IS NULL THEN now()
                    ELSE first_reply_at END,
                status = CASE
                    WHEN $2 = 'out' AND status = 'open' THEN 'in_progress'
                    ELSE status END
            WHERE id = $1
            """,
            ticket_id, direction,
        )
        return message_id


async def list_active_faq(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT * FROM faq WHERE is_active ORDER BY position, id"
    )


async def get_faq(pool: asyncpg.Pool, faq_id: int) -> asyncpg.Record | None:
    return await pool.fetchrow("SELECT * FROM faq WHERE id = $1 AND is_active", faq_id)


async def remember_event(pool: asyncpg.Pool, event_id: str) -> bool:
    """True — событие видим впервые. False — это повтор от Callback API."""
    row = await pool.fetchrow(
        "INSERT INTO processed_events (event_id) VALUES ($1)"
        " ON CONFLICT (event_id) DO NOTHING RETURNING event_id",
        event_id,
    )
    return row is not None


async def cleanup_old_events(pool: asyncpg.Pool) -> int:
    result = await pool.execute(
        "DELETE FROM processed_events WHERE created_at < now() - interval '1 day'"
    )
    return int(result.split()[-1])
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_queries.py -v && uv run ruff check .`
Expected: 11 passed

- [ ] **Step 5: Коммит**

```bash
git add app/db/queries.py tests/test_queries.py
git commit -m "Добавить слой запросов к базе"
```

---

### Task 4: Клиент VK API с ограничением скорости

**Files:**
- Create: `app/vk/__init__.py`
- Create: `app/vk/ratelimit.py`
- Create: `app/vk/client.py`
- Create: `tests/test_ratelimit.py`
- Create: `tests/test_vk_client.py`

**Interfaces:**
- Consumes: `app.config.Config` из Task 1.
- Produces:
  - `app.vk.ratelimit.RateLimiter(rate: float, capacity: float)` с `async def acquire(self) -> None`
  - `app.vk.client.VKClient(api, api_version: str, limiter: RateLimiter)` с `async def call(self, method: str, **params) -> dict`
  - `app.vk.client.build_client(cfg: Config) -> VKClient`
  - `app.vk.client.VKCallError(code: int, method: str)` — обёртка над ошибкой VK API, поля `code` и `method`

- [ ] **Step 1: Написать падающий тест на ограничитель**

`tests/test_ratelimit.py`:

```python
import asyncio
import time

from app.vk.ratelimit import RateLimiter


async def test_allows_burst_up_to_capacity():
    limiter = RateLimiter(rate=20, capacity=20)
    started = time.monotonic()
    for _ in range(20):
        await limiter.acquire()
    assert time.monotonic() - started < 0.1


async def test_throttles_beyond_capacity():
    limiter = RateLimiter(rate=20, capacity=5)
    started = time.monotonic()
    for _ in range(10):
        await limiter.acquire()
    # 5 сразу, оставшиеся 5 по 20 в секунду — минимум 0.25 с
    assert time.monotonic() - started >= 0.2


async def test_is_safe_under_concurrency():
    limiter = RateLimiter(rate=50, capacity=1)
    started = time.monotonic()
    await asyncio.gather(*(limiter.acquire() for _ in range(10)))
    elapsed = time.monotonic() - started
    assert 0.15 <= elapsed < 0.5
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_ratelimit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.vk'`

- [ ] **Step 3: Реализовать ограничитель**

`app/vk/__init__.py` — пустой файл.

`app/vk/ratelimit.py`:

```python
"""Токенное ведро. У токена сообщества лимит около 20 запросов в секунду."""

import asyncio
import time


class RateLimiter:
    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                # Спим ровно столько, сколько нужно на восстановление одного токена.
                await asyncio.sleep((1 - self._tokens) / self._rate)
```

- [ ] **Step 4: Написать падающий тест на клиент**

`tests/test_vk_client.py`:

```python
import pytest
from vkbottle import VKAPIError

from app.vk.client import VKCallError, VKClient
from app.vk.ratelimit import RateLimiter


class FakeAPI:
    def __init__(self, responses=None, raises=None):
        self.calls = []
        self._responses = responses or []
        self._raises = raises

    async def request(self, method, data, version=None):
        self.calls.append((method, data, version))
        if self._raises:
            raise self._raises
        return self._responses.pop(0) if self._responses else {"response": 1}


def make_client(api):
    return VKClient(api, api_version="5.199", limiter=RateLimiter(rate=1000, capacity=1000))


async def test_passes_method_params_and_version():
    api = FakeAPI()
    client = make_client(api)
    await client.call("messages.send", peer_id=1, message="привет")
    method, data, version = api.calls[0]
    assert method == "messages.send"
    assert data == {"peer_id": 1, "message": "привет"}
    assert version == "5.199"


async def test_unwraps_response_key():
    api = FakeAPI(responses=[{"response": {"id": 7}}])
    client = make_client(api)
    assert await client.call("messages.send") == {"id": 7}


async def test_drops_none_params():
    api = FakeAPI()
    client = make_client(api)
    await client.call("messages.send", peer_id=1, attachment=None)
    assert api.calls[0][1] == {"peer_id": 1}


async def test_wraps_vk_error_with_code_and_method():
    api = FakeAPI(raises=VKAPIError[6](error_msg="too many requests"))
    client = make_client(api)
    with pytest.raises(VKCallError) as exc:
        await client.call("messages.send", peer_id=1)
    assert exc.value.code == 6
    assert exc.value.method == "messages.send"


async def test_error_text_carries_no_message_body():
    api = FakeAPI(raises=VKAPIError[901](error_msg="нельзя писать"))
    client = make_client(api)
    with pytest.raises(VKCallError) as exc:
        await client.call("messages.send", peer_id=1, message="секретный текст клиента")
    assert "секретный текст клиента" not in str(exc.value)
```

- [ ] **Step 5: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_vk_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.vk.client'`

- [ ] **Step 6: Реализовать клиент**

`app/vk/client.py`:

```python
"""Обёртка над vkbottle.API: ограничение скорости и единый формат ошибок."""

import logging
from typing import Any

from vkbottle import API, VKAPIError

from app.config import Config
from app.vk.ratelimit import RateLimiter

logger = logging.getLogger(__name__)

# Лимит токена сообщества — около 20 запросов в секунду. Берём с запасом вниз.
VK_RATE = 18.0


class VKCallError(Exception):
    """Ошибка VK API. Несёт код и метод, но никогда — тело сообщения."""

    def __init__(self, code: int, method: str) -> None:
        self.code = code
        self.method = method
        super().__init__(f"VK API {method} вернул ошибку {code}")


class VKClient:
    def __init__(self, api: API, api_version: str, limiter: RateLimiter) -> None:
        self._api = api
        self._version = api_version
        self._limiter = limiter

    async def call(self, method: str, **params: Any) -> dict:
        data = {k: v for k, v in params.items() if v is not None}
        await self._limiter.acquire()
        try:
            raw = await self._api.request(method, data, version=self._version)
        except VKAPIError as exc:
            # Логируем код и метод. Параметры не логируем: там тексты пользователей.
            logger.warning("VK API %s вернул ошибку %s", method, exc.code)
            raise VKCallError(code=exc.code, method=method) from None
        return raw.get("response", raw)


def build_client(cfg: Config) -> VKClient:
    return VKClient(
        api=API(cfg.vk_group_token),
        api_version=cfg.vk_api_version,
        limiter=RateLimiter(rate=VK_RATE, capacity=VK_RATE),
    )
```

- [ ] **Step 7: Прогнать все тесты и линтер**

Run: `uv run pytest tests/test_ratelimit.py tests/test_vk_client.py -v && uv run ruff check .`
Expected: 8 passed

- [ ] **Step 8: Коммит**

```bash
git add app/vk tests/test_ratelimit.py tests/test_vk_client.py
git commit -m "Добавить клиент VK API с ограничением скорости"
```

---

### Task 5: Очередь исходящих сообщений

**Files:**
- Create: `app/vk/outbox.py`
- Create: `tests/test_outbox.py`

**Interfaces:**
- Consumes: `pool` (Task 2), `VKClient` и `VKCallError` (Task 4), `queries.mark_cannot_write` (Task 3).
- Produces:
  - `app.vk.outbox.enqueue(pool, peer_id: int, text: str = "", attachment: str | None = None, keyboard: str | None = None) -> int` — возвращает id строки
  - `app.vk.outbox.recover_stuck(pool) -> int` — переводит `sending` обратно в `pending` при старте
  - `app.vk.outbox.process_batch(pool, client, limit: int = 20) -> int` — обрабатывает пачку, возвращает количество обработанных
  - `app.vk.outbox.run_worker(pool, client, stop: asyncio.Event) -> None`
  - Константы `MAX_ATTEMPTS = 5`, `FLOOD_DELAY_SECONDS = 300`

- [ ] **Step 1: Написать падающий тест**

`tests/test_outbox.py`:

```python
import pytest

from app.db import queries as q
from app.vk import outbox
from app.vk.client import VKCallError


class FakeClient:
    """Считает вызовы и умеет падать заданными кодами по очереди."""

    def __init__(self, errors=None):
        self.calls = []
        self._errors = list(errors or [])

    async def call(self, method, **params):
        self.calls.append((method, params))
        if self._errors:
            code = self._errors.pop(0)
            if code is not None:
                raise VKCallError(code=code, method=method)
        return {"message_id": len(self.calls)}


async def test_enqueue_stores_pending_row_with_random_id(pool):
    row_id = await outbox.enqueue(pool, peer_id=1, text="привет")
    row = await pool.fetchrow("SELECT * FROM outbox WHERE id = $1", row_id)
    assert row["status"] == "pending"
    assert row["peer_id"] == 1
    assert row["payload"]["message"] == "привет"
    assert 0 < row["random_id"] <= 2**31 - 1


async def test_random_id_differs_between_messages(pool):
    a = await outbox.enqueue(pool, peer_id=1, text="раз")
    b = await outbox.enqueue(pool, peer_id=1, text="два")
    ids = await pool.fetch("SELECT random_id FROM outbox WHERE id = ANY($1::bigint[])", [a, b])
    assert ids[0]["random_id"] != ids[1]["random_id"]


async def test_process_batch_sends_and_marks_sent(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    client = FakeClient()
    assert await outbox.process_batch(pool, client) == 1

    method, params = client.calls[0]
    assert method == "messages.send"
    assert params["peer_id"] == 1
    assert params["message"] == "привет"
    assert "random_id" in params

    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "sent"
    assert row["sent_at"] is not None


async def test_retry_reuses_the_same_random_id(pool):
    """Это то, что не даёт клиенту получить дубль после ретрая."""
    await outbox.enqueue(pool, peer_id=1, text="привет")
    original = await pool.fetchval("SELECT random_id FROM outbox")

    failing = FakeClient(errors=[6])
    await outbox.process_batch(pool, failing)
    assert await pool.fetchval("SELECT random_id FROM outbox") == original

    await pool.execute("UPDATE outbox SET next_attempt_at = now()")
    ok = FakeClient()
    await outbox.process_batch(pool, ok)
    assert ok.calls[0][1]["random_id"] == original


async def test_error_6_backs_off_and_stays_pending(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await outbox.process_batch(pool, FakeClient(errors=[6]))
    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "pending"
    assert row["attempts"] == 1
    assert row["next_attempt_at"] > row["created_at"]


async def test_error_9_delays_long(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await outbox.process_batch(pool, FakeClient(errors=[9]))
    delay = await pool.fetchval(
        "SELECT extract(epoch FROM next_attempt_at - now()) FROM outbox"
    )
    assert delay > outbox.FLOOD_DELAY_SECONDS - 10


async def test_error_901_fails_permanently_and_blocks_user(pool):
    await q.upsert_user(pool, 1)
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await outbox.process_batch(pool, FakeClient(errors=[901]))

    row = await pool.fetchrow("SELECT * FROM outbox")
    assert row["status"] == "failed"
    assert (await q.get_user(pool, 1))["can_write"] is False


async def test_gives_up_after_max_attempts(pool):
    await outbox.enqueue(pool, peer_id=1, text="привет")
    for _ in range(outbox.MAX_ATTEMPTS):
        await pool.execute("UPDATE outbox SET next_attempt_at = now()")
        await outbox.process_batch(pool, FakeClient(errors=[10]))
    assert await pool.fetchval("SELECT status FROM outbox") == "failed"


async def test_skips_rows_scheduled_for_later(pool):
    await outbox.enqueue(pool, peer_id=1, text="потом")
    await pool.execute("UPDATE outbox SET next_attempt_at = now() + interval '1 hour'")
    client = FakeClient()
    assert await outbox.process_batch(pool, client) == 0
    assert client.calls == []


async def test_recover_stuck_returns_sending_rows_to_pending(pool):
    """Процесс убили посреди отправки — строка не должна зависнуть навсегда."""
    await outbox.enqueue(pool, peer_id=1, text="привет")
    await pool.execute("UPDATE outbox SET status = 'sending'")
    assert await outbox.recover_stuck(pool) == 1
    assert await pool.fetchval("SELECT status FROM outbox") == "pending"


async def test_preserves_order_within_one_peer(pool):
    for i in range(5):
        await outbox.enqueue(pool, peer_id=1, text=str(i))
    client = FakeClient()
    await outbox.process_batch(pool, client)
    assert [c[1]["message"] for c in client.calls] == ["0", "1", "2", "3", "4"]


async def test_attachment_and_keyboard_are_passed_through(pool):
    await outbox.enqueue(
        pool, peer_id=1, text="вот", attachment="photo1_2", keyboard='{"buttons":[]}'
    )
    client = FakeClient()
    await outbox.process_batch(pool, client)
    params = client.calls[0][1]
    assert params["attachment"] == "photo1_2"
    assert params["keyboard"] == '{"buttons":[]}'
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_outbox.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.vk.outbox'`

- [ ] **Step 3: Реализовать очередь**

`app/vk/outbox.py`:

```python
"""Надёжная отправка сообщений.

Railway перезапускает процесс в любой момент, поэтому прямой messages.send из
обработчика теряет ответ. Всё исходящее сначала ложится строкой в таблицу, а
воркер разгребает её с ретраями.
"""

import asyncio
import logging
import secrets

import asyncpg

from app.db import queries as q
from app.vk.client import VKCallError

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
FLOOD_DELAY_SECONDS = 300
MAX_BACKOFF_SECONDS = 60
IDLE_SLEEP_SECONDS = 0.5

ERROR_TOO_MANY_REQUESTS = 6
ERROR_FLOOD_CONTROL = 9
ERROR_CANNOT_WRITE = 901


async def enqueue(
    pool: asyncpg.Pool,
    peer_id: int,
    text: str = "",
    attachment: str | None = None,
    keyboard: str | None = None,
) -> int:
    """Ставит сообщение в очередь.

    random_id генерируется здесь и больше не меняется: ВК считает повтор с тем же
    random_id дублем и не доставляет его, поэтому ретрай безопасен.
    """
    payload: dict[str, str] = {"message": text}
    if attachment:
        payload["attachment"] = attachment
    if keyboard:
        payload["keyboard"] = keyboard

    return await pool.fetchval(
        "INSERT INTO outbox (peer_id, payload, random_id) VALUES ($1, $2, $3)"
        " RETURNING id",
        peer_id, payload, secrets.randbelow(2**31 - 1) + 1,
    )


async def recover_stuck(pool: asyncpg.Pool) -> int:
    """Возвращает в работу строки, застрявшие в 'sending' после падения процесса."""
    result = await pool.execute(
        "UPDATE outbox SET status = 'pending' WHERE status = 'sending'"
    )
    count = int(result.split()[-1])
    if count:
        logger.info("вернули в очередь %s зависших сообщений", count)
    return count


async def process_batch(pool: asyncpg.Pool, client, limit: int = 20) -> int:
    rows = await pool.fetch(
        """
        UPDATE outbox SET status = 'sending'
        WHERE id IN (
            SELECT id FROM outbox
            WHERE status = 'pending' AND next_attempt_at <= now()
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT $1
        )
        RETURNING *
        """,
        limit,
    )

    # RETURNING не гарантирует порядок строк, даже когда подзапрос с ORDER BY id.
    # Для переписки порядок важен, поэтому сортируем явно.
    for row in sorted(rows, key=lambda r: r["id"]):
        await _send_one(pool, client, row)
    return len(rows)


async def _send_one(pool: asyncpg.Pool, client, row: asyncpg.Record) -> None:
    payload = row["payload"]
    try:
        await client.call(
            "messages.send",
            peer_id=row["peer_id"],
            random_id=row["random_id"],
            **payload,
        )
    except VKCallError as exc:
        await _handle_error(pool, row, exc)
        return

    await pool.execute(
        "UPDATE outbox SET status = 'sent', sent_at = now() WHERE id = $1", row["id"]
    )


async def _handle_error(pool: asyncpg.Pool, row: asyncpg.Record, exc: VKCallError) -> None:
    attempts = row["attempts"] + 1
    error_text = f"код {exc.code}"

    if exc.code == ERROR_CANNOT_WRITE:
        # Пользователь запретил сообщения. Ретраи бессмысленны навсегда.
        await pool.execute(
            "UPDATE outbox SET status = 'failed', attempts = $2, last_error = $3"
            " WHERE id = $1",
            row["id"], attempts, error_text,
        )
        await q.mark_cannot_write(pool, row["peer_id"])
        return

    if attempts >= MAX_ATTEMPTS:
        await pool.execute(
            "UPDATE outbox SET status = 'failed', attempts = $2, last_error = $3"
            " WHERE id = $1",
            row["id"], attempts, error_text,
        )
        logger.warning("сообщение %s провалено после %s попыток", row["id"], attempts)
        return

    if exc.code == ERROR_FLOOD_CONTROL:
        delay = FLOOD_DELAY_SECONDS
    elif exc.code == ERROR_TOO_MANY_REQUESTS:
        delay = min(MAX_BACKOFF_SECONDS, 2**attempts)
    else:
        delay = min(MAX_BACKOFF_SECONDS, 2**attempts)

    await pool.execute(
        "UPDATE outbox SET status = 'pending', attempts = $2, last_error = $3,"
        " next_attempt_at = now() + make_interval(secs => $4) WHERE id = $1",
        row["id"], attempts, error_text, float(delay),
    )


async def run_worker(pool: asyncpg.Pool, client, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            handled = await process_batch(pool, client)
        except Exception:
            logger.exception("воркер очереди упал на пачке")
            handled = 0
        if handled == 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=IDLE_SLEEP_SECONDS)
            except TimeoutError:
                pass
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_outbox.py -v && uv run ruff check .`
Expected: 12 passed

- [ ] **Step 5: Коммит**

```bash
git add app/vk/outbox.py tests/test_outbox.py
git commit -m "Добавить очередь исходящих сообщений с ретраями"
```

---

### Task 6: Клавиатуры

**Files:**
- Create: `app/vk/keyboards.py`
- Create: `tests/test_keyboards.py`

**Interfaces:**
- Consumes: ничего из предыдущих задач, только vkbottle.
- Produces: модуль `app.vk.keyboards`, все функции возвращают JSON-строку для параметра `keyboard`:
  - `main_menu() -> str`
  - `faq_list(items: list[Mapping]) -> str` — `items` с ключами `id` и `title`
  - `ticket_actions(ticket_id: int) -> str`
  - `rating(ticket_id: int) -> str`
  - `empty() -> str` — пустая клавиатура, чтобы убрать предыдущую
  - Константы `MAX_INLINE_BUTTONS = 10`, `MAX_FAQ_ITEMS = 8`, `FAQ_PER_ROW = 2`, `MAX_PAYLOAD = 255`
  - Внутренний хелпер `_payload(**fields) -> str` — payload обязан быть строкой, а не вложенным объектом

- [ ] **Step 1: Написать падающий тест**

`tests/test_keyboards.py`:

```python
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
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_keyboards.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.vk.keyboards'`

- [ ] **Step 3: Реализовать клавиатуры**

`app/vk/keyboards.py`:

```python
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
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_keyboards.py -v && uv run ruff check .`
Expected: 11 passed

Если тест `test_faq_list_respects_vk_inline_limit` падает на числе рядов — проверь, что `MAX_FAQ_ITEMS` равен 9: девять тем по одной в ряду плюс кнопка оператора дают 10 рядов, что превышает лимит в 6. В этом случае группируй темы по две в ряд.

- [ ] **Step 5: Коммит**

```bash
git add app/vk/keyboards.py tests/test_keyboards.py
git commit -m "Добавить клавиатуры бота с маршрутизацией по payload"
```

---

### Task 7: Разбор входящих вложений

**Files:**
- Create: `app/vk/attachments.py`
- Create: `tests/test_attachments.py`

**Interfaces:**
- Consumes: ничего из предыдущих задач.
- Produces:
  - `app.vk.attachments.parse_attachments(raw: list[dict]) -> list[dict]`
  - `app.vk.attachments.parse_geo(geo: dict | None) -> dict | None`
  - `app.vk.attachments.describe(items: list[dict]) -> str` — краткое текстовое описание для уведомлений
  - Нормализованные типы: `photo`, `video`, `doc`, `audio_message`, `sticker`, `geo`, `unsupported`

- [ ] **Step 1: Написать падающий тест**

`tests/test_attachments.py`:

```python
from app.vk.attachments import describe, parse_attachments, parse_geo


def test_photo_picks_largest_size():
    raw = [{
        "type": "photo",
        "photo": {
            "id": 1, "owner_id": 2,
            "sizes": [
                {"type": "m", "url": "small.jpg", "width": 130, "height": 100},
                {"type": "w", "url": "big.jpg", "width": 2560, "height": 1920},
                {"type": "x", "url": "mid.jpg", "width": 604, "height": 453},
            ],
        },
    }]
    [item] = parse_attachments(raw)
    assert item["type"] == "photo"
    assert item["url"] == "big.jpg"
    assert item["width"] == 2560


def test_photo_without_sizes_is_tolerated():
    [item] = parse_attachments([{"type": "photo", "photo": {"id": 1, "owner_id": 2}}])
    assert item["type"] == "photo"
    assert item["url"] == ""


def test_video_yields_page_url_not_file():
    """VK API не отдаёт прямой файл видео — только страницу с плеером."""
    raw = [{
        "type": "video",
        "video": {
            "id": 456, "owner_id": -789, "title": "Экран", "duration": 42,
            "access_key": "abc",
            "image": [{"url": "prev.jpg", "width": 320, "height": 240}],
        },
    }]
    [item] = parse_attachments(raw)
    assert item["type"] == "video"
    assert item["url"] == "https://vk.com/video-789_456?access_key=abc"
    assert item["preview"] == "prev.jpg"
    assert item["duration"] == 42


def test_video_without_access_key():
    raw = [{"type": "video", "video": {"id": 1, "owner_id": 2, "title": "", "image": []}}]
    [item] = parse_attachments(raw)
    assert item["url"] == "https://vk.com/video2_1"


def test_doc_keeps_metadata():
    raw = [{
        "type": "doc",
        "doc": {"id": 5, "owner_id": 6, "title": "счёт.pdf", "ext": "pdf",
                "size": 10240, "url": "https://vk.com/doc.pdf"},
    }]
    [item] = parse_attachments(raw)
    assert item == {
        "type": "doc", "id": 5, "owner_id": 6, "title": "счёт.pdf",
        "ext": "pdf", "size": 10240, "url": "https://vk.com/doc.pdf",
    }


def test_audio_message_keeps_both_links_and_waveform():
    raw = [{
        "type": "audio_message",
        "audio_message": {
            "id": 9, "owner_id": 10, "duration": 7,
            "link_ogg": "voice.ogg", "link_mp3": "voice.mp3",
            "waveform": [1, 5, 3],
        },
    }]
    [item] = parse_attachments(raw)
    assert item["type"] == "audio_message"
    assert item["duration"] == 7
    assert item["link_ogg"] == "voice.ogg"
    assert item["link_mp3"] == "voice.mp3"
    assert item["waveform"] == [1, 5, 3]


def test_sticker_picks_largest_image():
    raw = [{
        "type": "sticker",
        "sticker": {"sticker_id": 3, "images": [
            {"url": "s64.png", "width": 64},
            {"url": "s512.png", "width": 512},
        ]},
    }]
    [item] = parse_attachments(raw)
    assert item == {"type": "sticker", "id": 3, "url": "s512.png"}


def test_unknown_type_is_marked_not_dropped():
    """Терять вложение молча нельзя — оператор должен видеть, что оно было."""
    [item] = parse_attachments([{"type": "market", "market": {"id": 1}}])
    assert item == {"type": "unsupported", "raw_type": "market"}


def test_malformed_attachment_does_not_crash():
    assert parse_attachments([{"type": "photo"}]) == [{"type": "photo", "url": "",
                                                       "id": 0, "owner_id": 0,
                                                       "width": 0, "height": 0}]


def test_empty_list():
    assert parse_attachments([]) == []


def test_parse_geo():
    geo = {"coordinates": {"latitude": 55.75, "longitude": 37.61},
           "place": {"title": "Москва"}}
    assert parse_geo(geo) == {"type": "geo", "lat": 55.75, "lon": 37.61, "title": "Москва"}


def test_parse_geo_none():
    assert parse_geo(None) is None


def test_describe_summarises_for_notification():
    items = [{"type": "photo"}, {"type": "photo"}, {"type": "audio_message"}]
    assert describe(items) == "2 фото, голосовое"


def test_describe_empty():
    assert describe([]) == ""
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_attachments.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.vk.attachments'`

- [ ] **Step 3: Реализовать разбор**

`app/vk/attachments.py`:

```python
"""Приведение вложений ВК к единому виду для хранения и показа в дашборде.

Неизвестные типы не выбрасываем: оператор должен видеть, что вложение было,
даже если мы не умеем его отрисовать.
"""

from typing import Any

RUSSIAN_NAMES = {
    "photo": ("фото", "фото", "фото"),
    "video": ("видео", "видео", "видео"),
    "doc": ("файл", "файла", "файлов"),
    "audio_message": ("голосовое", "голосовых", "голосовых"),
    "sticker": ("стикер", "стикера", "стикеров"),
    "geo": ("геопозиция", "геопозиции", "геопозиций"),
    "unsupported": ("вложение", "вложения", "вложений"),
}


def _largest(items: list[dict], key: str = "width") -> dict:
    return max(items, key=lambda i: i.get(key, 0)) if items else {}


def _photo(body: dict) -> dict:
    biggest = _largest(body.get("sizes") or [])
    return {
        "type": "photo",
        "id": body.get("id", 0),
        "owner_id": body.get("owner_id", 0),
        "url": biggest.get("url", ""),
        "width": biggest.get("width", 0),
        "height": biggest.get("height", 0),
    }


def _video(body: dict) -> dict:
    owner_id = body.get("owner_id", 0)
    video_id = body.get("id", 0)
    url = f"https://vk.com/video{owner_id}_{video_id}"
    if body.get("access_key"):
        url += f"?access_key={body['access_key']}"
    return {
        "type": "video",
        "id": video_id,
        "owner_id": owner_id,
        "title": body.get("title", ""),
        "duration": body.get("duration", 0),
        "preview": _largest(body.get("image") or []).get("url", ""),
        "url": url,
    }


def _doc(body: dict) -> dict:
    return {
        "type": "doc",
        "id": body.get("id", 0),
        "owner_id": body.get("owner_id", 0),
        "title": body.get("title", ""),
        "ext": body.get("ext", ""),
        "size": body.get("size", 0),
        "url": body.get("url", ""),
    }


def _audio_message(body: dict) -> dict:
    return {
        "type": "audio_message",
        "id": body.get("id", 0),
        "owner_id": body.get("owner_id", 0),
        "duration": body.get("duration", 0),
        "link_ogg": body.get("link_ogg", ""),
        "link_mp3": body.get("link_mp3", ""),
        "waveform": body.get("waveform", []),
    }


def _sticker(body: dict) -> dict:
    return {
        "type": "sticker",
        "id": body.get("sticker_id", 0),
        "url": _largest(body.get("images") or []).get("url", ""),
    }


PARSERS = {
    "photo": _photo,
    "video": _video,
    "doc": _doc,
    "audio_message": _audio_message,
    "sticker": _sticker,
}


def parse_attachments(raw: list[dict]) -> list[dict]:
    result: list[dict] = []
    for attachment in raw or []:
        kind = attachment.get("type", "")
        parser = PARSERS.get(kind)
        if parser is None:
            result.append({"type": "unsupported", "raw_type": kind})
            continue
        result.append(parser(attachment.get(kind) or {}))
    return result


def parse_geo(geo: dict[str, Any] | None) -> dict | None:
    if not geo:
        return None
    coordinates = geo.get("coordinates") or {}
    return {
        "type": "geo",
        "lat": coordinates.get("latitude", 0.0),
        "lon": coordinates.get("longitude", 0.0),
        "title": (geo.get("place") or {}).get("title", ""),
    }


def _plural(count: int, forms: tuple[str, str, str]) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return forms[0]
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return forms[1]
    return forms[2]


def describe(items: list[dict]) -> str:
    """Короткая сводка для текста уведомления: «2 фото, голосовое»."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1

    parts: list[str] = []
    for kind, count in counts.items():
        forms = RUSSIAN_NAMES.get(kind, RUSSIAN_NAMES["unsupported"])
        parts.append(forms[0] if count == 1 else f"{count} {_plural(count, forms)}")
    return ", ".join(parts)
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_attachments.py -v && uv run ruff check .`
Expected: 14 passed

- [ ] **Step 5: Коммит**

```bash
git add app/vk/attachments.py tests/test_attachments.py
git commit -m "Добавить разбор входящих вложений"
```

---

### Task 8: Обработчики пользовательских событий

**Files:**
- Create: `app/workhours.py`
- Create: `app/handlers/__init__.py`
- Create: `app/handlers/user.py`
- Create: `app/texts.py`
- Create: `tests/test_workhours.py`
- Create: `tests/test_handlers_user.py`

**Interfaces:**
- Consumes: `queries` (Task 3), `outbox.enqueue` (Task 5), `keyboards` (Task 6), `attachments` (Task 7), `Config` (Task 1).
- Produces:
  - `app.workhours.is_working_now(cfg: Config, now: datetime | None = None) -> bool`
  - `app.workhours.next_working_time(cfg: Config, now: datetime | None = None) -> str` — человекочитаемо, например «завтра с 10:00»
  - `app.handlers.user.handle_event(pool, cfg, event: dict) -> None` — единая точка входа для `message_new` и `message_event`
  - `app.texts` — все пользовательские строки константами: `GREETING`, `ASK_PROBLEM`, `TICKET_CREATED`, `OFF_HOURS`, `NO_TICKETS`, `TICKET_CLOSED`, `ASK_RATING`, `THANKS_FOR_RATING`, `FAQ_EMPTY`, `UNKNOWN`

- [ ] **Step 1: Написать падающий тест на рабочие часы**

`tests/test_workhours.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import load_config
from app.workhours import is_working_now, next_working_time

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "1", "VK_CONFIRMATION_CODE": "c",
    "VK_SECRET_KEY": "s", "ADMIN_ID": "2", "DATABASE_URL": "postgresql://x",
    "SESSION_SECRET": "s" * 32, "WORK_HOURS": "10-19", "TZ": "Europe/Moscow",
}
CFG = load_config(ENV)
MSK = ZoneInfo("Europe/Moscow")


def test_inside_working_hours():
    assert is_working_now(CFG, datetime(2026, 9, 21, 14, 0, tzinfo=MSK)) is True


def test_exactly_at_opening():
    assert is_working_now(CFG, datetime(2026, 9, 21, 10, 0, tzinfo=MSK)) is True


def test_exactly_at_closing_is_already_closed():
    assert is_working_now(CFG, datetime(2026, 9, 21, 19, 0, tzinfo=MSK)) is False


def test_before_opening():
    assert is_working_now(CFG, datetime(2026, 9, 21, 9, 59, tzinfo=MSK)) is False


def test_uses_configured_timezone_not_server_time():
    """Railway живёт в UTC. 08:00 UTC — это 11:00 МСК, то есть рабочее время."""
    utc_morning = datetime(2026, 9, 21, 8, 0, tzinfo=ZoneInfo("UTC"))
    assert is_working_now(CFG, utc_morning) is True


def test_next_working_time_today():
    assert next_working_time(CFG, datetime(2026, 9, 21, 7, 0, tzinfo=MSK)) == "сегодня с 10:00"


def test_next_working_time_tomorrow():
    assert next_working_time(CFG, datetime(2026, 9, 21, 22, 0, tzinfo=MSK)) == "завтра с 10:00"
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_workhours.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.workhours'`

- [ ] **Step 3: Реализовать рабочие часы**

`app/workhours.py`:

```python
"""Рабочие часы считаем в часовом поясе из конфига.

Railway запускает контейнер в UTC, поэтому опираться на локальное время сервера
нельзя: бот будет считать рабочим не тот промежуток.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Config


def _local(cfg: Config, now: datetime | None) -> datetime:
    tz = ZoneInfo(cfg.tz)
    if now is None:
        return datetime.now(tz)
    return now.astimezone(tz)


def is_working_now(cfg: Config, now: datetime | None = None) -> bool:
    start, end = cfg.work_hours
    return start <= _local(cfg, now).hour < end


def next_working_time(cfg: Config, now: datetime | None = None) -> str:
    start, _ = cfg.work_hours
    current = _local(cfg, now)
    when = "сегодня" if current.hour < start else "завтра"
    return f"{when} с {start:02d}:00"
```

- [ ] **Step 4: Написать падающий тест на обработчики**

`tests/test_handlers_user.py`:

```python
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
```

- [ ] **Step 5: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_handlers_user.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.handlers'`

- [ ] **Step 6: Реализовать тексты и обработчики**

`app/texts.py`:

```python
"""Все строки, которые видит пользователь. В одном месте, чтобы править без поиска по коду."""

GREETING = (
    "Здравствуйте! Это поддержка Atlas Secure.\n\n"
    "Посмотрите частые вопросы — возможно, ответ уже есть. "
    "Если нет, напишите оператору."
)
ASK_PROBLEM = "Опишите, что случилось. Можно приложить скриншот или файл."
TICKET_CREATED = "Обращение №{id} создано. Оператор ответит здесь же."
OFF_HOURS = "Сейчас нерабочее время. Ответим {when}."
NO_TICKETS = "У вас нет открытых обращений."
TICKET_LIST_HEADER = "Ваши обращения:"
TICKET_LINE = "№{id} — {status}, создано {created}"
TICKET_CLOSED = "Обращение №{id} закрыто."
ASK_RATING = "Оцените поддержку от 1 до 5."
THANKS_FOR_RATING = "Спасибо за оценку!"
FAQ_EMPTY = "Пока здесь пусто. Напишите оператору — поможем."
FAQ_NOT_FOUND = "Такой темы больше нет. Выберите другую или напишите оператору."
UNKNOWN = "Не понял. Выберите пункт меню."

STATUS_NAMES = {"open": "ждёт ответа", "in_progress": "в работе", "closed": "закрыто"}
```

`app/handlers/__init__.py` — пустой файл.

`app/handlers/user.py`:

```python
"""Обработка событий от пользователей.

Единственная точка входа — handle_event. Все ответы уходят только через outbox.
"""

import json
import logging

import asyncpg

from app import texts
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


async def _send_menu(pool: asyncpg.Pool, peer_id: int) -> None:
    await outbox.enqueue(pool, peer_id, texts.GREETING, keyboard=kb.main_menu())


async def _send_faq_list(pool: asyncpg.Pool, peer_id: int) -> None:
    items = await q.list_active_faq(pool)
    body = texts.FAQ_EMPTY if not items else "Выберите тему:"
    await outbox.enqueue(pool, peer_id, body, keyboard=kb.faq_list(items))


async def _send_faq_answer(pool: asyncpg.Pool, peer_id: int, faq_id) -> None:
    item = await q.get_faq(pool, faq_id) if isinstance(faq_id, int) else None
    if item is None:
        items = await q.list_active_faq(pool)
        await outbox.enqueue(pool, peer_id, texts.FAQ_NOT_FOUND, keyboard=kb.faq_list(items))
        return
    items = await q.list_active_faq(pool)
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
```

- [ ] **Step 7: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_workhours.py tests/test_handlers_user.py -v && uv run ruff check .`
Expected: 7 + 20 passed

- [ ] **Step 8: Коммит**

```bash
git add app/workhours.py app/texts.py app/handlers tests/test_workhours.py tests/test_handlers_user.py
git commit -m "Добавить обработчики пользовательских событий"
```

---

### Task 9: Эндпоинт Callback API

**Files:**
- Create: `app/web/__init__.py`
- Create: `app/vk/callback.py`
- Create: `tests/test_callback.py`

**Interfaces:**
- Consumes: `queries.remember_event` (Task 3), `Config` (Task 1), `handle_event` (Task 8).
- Produces:
  - `app.vk.callback.router` — APIRouter с `POST /vk/callback`
  - Читает из `request.app.state`: `cfg: Config`, `pool: asyncpg.Pool`, `handler: Callable[[dict], Awaitable[None]]`, `background: set[asyncio.Task]`
  - `app.vk.callback.spawn(app, event) -> asyncio.Task` — запуск фоновой обработки с удержанием ссылки

- [ ] **Step 1: Написать падающий тест**

`tests/test_callback.py`:

```python
import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.vk.callback import router

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код42",
    "VK_SECRET_KEY": "секрет", "ADMIN_ID": "777", "DATABASE_URL": "postgresql://x",
    "SESSION_SECRET": "s" * 32,
}
CFG = load_config(ENV)


@pytest.fixture
def seen():
    return []


@pytest.fixture
def client(pool, seen):
    app = FastAPI()
    app.include_router(router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.background = set()

    async def handler(event):
        seen.append(event)

    app.state.handler = handler
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), app


async def drain(app):
    """Дожидаемся фоновых задач, порождённых запросом."""
    if app.state.background:
        await asyncio.gather(*list(app.state.background))


def event(**extra):
    base = {
        "type": "message_new", "group_id": 111, "secret": "секрет",
        "event_id": "evt-1",
        "object": {"message": {"id": 1, "from_id": 5, "peer_id": 5, "text": "привет"}},
    }
    base.update(extra)
    return base


async def test_confirmation_returns_plain_code(client):
    http, _ = client
    response = await http.post("/vk/callback",
                               json={"type": "confirmation", "group_id": 111})
    assert response.status_code == 200
    assert response.text == "код42"
    assert response.headers["content-type"].startswith("text/plain")


async def test_confirmation_from_wrong_group_rejected(client):
    http, _ = client
    response = await http.post("/vk/callback",
                               json={"type": "confirmation", "group_id": 999})
    assert response.status_code == 403


async def test_event_returns_ok(client):
    http, app = client
    response = await http.post("/vk/callback", json=event())
    assert response.status_code == 200
    assert response.text == "ok"
    await drain(app)


async def test_event_reaches_handler(client, seen):
    http, app = client
    await http.post("/vk/callback", json=event())
    await drain(app)
    assert seen[0]["type"] == "message_new"


async def test_wrong_secret_is_rejected(client, seen):
    http, _ = client
    response = await http.post("/vk/callback", json=event(secret="чужой"))
    assert response.status_code == 403
    assert seen == []


async def test_missing_secret_is_rejected(client):
    http, _ = client
    payload = event()
    del payload["secret"]
    assert (await http.post("/vk/callback", json=payload)).status_code == 403


async def test_wrong_group_is_rejected(client):
    http, _ = client
    assert (await http.post("/vk/callback", json=event(group_id=222))).status_code == 403


async def test_duplicate_event_is_handled_once(client, seen):
    """ВК повторяет событие, если не получил ok вовремя. Обработать надо один раз."""
    http, app = client
    for _ in range(5):
        response = await http.post("/vk/callback", json=event())
        assert response.text == "ok"
        await drain(app)
    assert len(seen) == 1


async def test_distinct_events_all_handled(client, seen):
    http, app = client
    for i in range(3):
        await http.post("/vk/callback", json=event(event_id=f"evt-{i}"))
        await drain(app)
    assert len(seen) == 3


async def test_event_without_event_id_is_still_handled(client, seen):
    http, app = client
    payload = event()
    del payload["event_id"]
    await http.post("/vk/callback", json=payload)
    await drain(app)
    assert len(seen) == 1


async def test_handler_failure_does_not_break_response(client, pool):
    """Падение обработчика не должно приводить к повторам от ВК."""
    app = FastAPI()
    app.include_router(router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.background = set()

    async def broken(_event):
        raise RuntimeError("что-то сломалось")

    app.state.handler = broken
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    response = await http.post("/vk/callback", json=event())
    assert response.text == "ok"
    await drain(app)


async def test_malformed_json_returns_400(client):
    http, _ = client
    response = await http.post(
        "/vk/callback", content="{не json".encode(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 400


async def test_response_is_fast(client):
    """Обработка уходит в фон: ВК ждёт ok, а не завершения работы."""
    import time
    http, app = client

    async def slow(_event):
        await asyncio.sleep(0.5)

    app.state.handler = slow
    started = time.monotonic()
    await http.post("/vk/callback", json=event())
    assert time.monotonic() - started < 0.1
    await drain(app)
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_callback.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.vk.callback'`

- [ ] **Step 3: Реализовать эндпоинт**

`app/web/__init__.py` — пустой файл.

`app/vk/callback.py`:

```python
"""Приём событий Callback API.

Правила ВК: на confirmation отвечаем строкой с кодом, на всё остальное — 'ok', и
быстро. Если ok не пришёл вовремя, ВК повторит событие, поэтому обработка уходит
в фон, а дубли отсекаются по event_id.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.db import queries as q

logger = logging.getLogger(__name__)

router = APIRouter()


def spawn(app, event: dict) -> asyncio.Task:
    """Запускает обработку в фоне, удерживая ссылку на задачу.

    Без сохранения ссылки сборщик мусора может убить задачу на середине —
    это известная ловушка asyncio.create_task.
    """

    async def guarded() -> None:
        try:
            await app.state.handler(event)
        except Exception:
            # Падение обработчика не должно превращаться в повтор события от ВК.
            logger.exception("обработка события %s провалилась", event.get("type"))

    task = asyncio.create_task(guarded())
    app.state.background.add(task)
    task.add_done_callback(app.state.background.discard)
    return task


@router.post("/vk/callback", response_class=PlainTextResponse)
async def vk_callback(request: Request) -> str:
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="bad request") from None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="bad request")

    cfg = request.app.state.cfg
    if event.get("group_id") != cfg.vk_group_id:
        raise HTTPException(status_code=403, detail="forbidden")

    if event.get("type") == "confirmation":
        # Секрет здесь не проверяем: при первичном подтверждении в настройках
        # сообщества он может быть ещё не сохранён. Group_id уже сверен выше.
        return cfg.vk_confirmation_code

    if event.get("secret") != cfg.vk_secret_key:
        raise HTTPException(status_code=403, detail="forbidden")

    event_id = event.get("event_id")
    if event_id and not await q.remember_event(request.app.state.pool, str(event_id)):
        return "ok"

    spawn(request.app, event)
    return "ok"
```

- [ ] **Step 4: Прогнать тесты и линтер**

Run: `uv run pytest tests/test_callback.py -v && uv run ruff check .`
Expected: 13 passed

- [ ] **Step 5: Коммит**

```bash
git add app/web/__init__.py app/vk/callback.py tests/test_callback.py
git commit -m "Добавить приём событий Callback API с дедупликацией"
```

---

### Task 10: Одноразовая ссылка для регистрации passkey

**Files:**
- Create: `app/setup_tokens.py`
- Create: `tests/test_setup_tokens.py`
- Modify: `app/config.py` — добавить поле `public_url`
- Modify: `tests/test_config.py` — тест на `public_url`
- Modify: `app/handlers/user.py` — обработка `/link`
- Modify: `app/texts.py` — тексты ссылки
- Modify: `tests/test_handlers_user.py` — тесты `/link`
- Modify: `.env.example` — `PUBLIC_URL`

**Interfaces:**
- Consumes: `pool` (Task 2), `Config` (Task 1), `outbox.enqueue` (Task 5).
- Produces:
  - `app.setup_tokens.issue(pool, ttl_seconds: int = 600) -> str` — возвращает сырой токен, в БД кладёт только хеш
  - `app.setup_tokens.consume(pool, token: str) -> bool` — `True` если токен был валиден; повторный вызов даёт `False`
  - `app.setup_tokens.purge_expired(pool) -> int`
  - `Config.public_url: str` — базовый адрес сервиса, например `https://vkbot.up.railway.app`
  - Константа `app.setup_tokens.TTL_SECONDS = 600`

- [ ] **Step 1: Написать падающий тест на токены**

`tests/test_setup_tokens.py`:

```python
from app import setup_tokens


async def test_issued_token_is_accepted_once(pool):
    token = await setup_tokens.issue(pool)
    assert await setup_tokens.consume(pool, token) is True
    assert await setup_tokens.consume(pool, token) is False


async def test_raw_token_is_not_stored(pool):
    """В базе лежит только хеш: дамп БД не должен давать доступ к дашборду."""
    token = await setup_tokens.issue(pool)
    stored = await pool.fetchval("SELECT token_hash FROM setup_tokens")
    assert stored != token
    assert token not in stored


async def test_unknown_token_rejected(pool):
    assert await setup_tokens.consume(pool, "выдуманный") is False


async def test_expired_token_rejected(pool):
    token = await setup_tokens.issue(pool, ttl_seconds=-1)
    assert await setup_tokens.consume(pool, token) is False


async def test_tokens_are_unique(pool):
    tokens = {await setup_tokens.issue(pool) for _ in range(20)}
    assert len(tokens) == 20


async def test_token_is_long_enough_to_resist_guessing(pool):
    assert len(await setup_tokens.issue(pool)) >= 32


async def test_purge_removes_expired_only(pool):
    fresh = await setup_tokens.issue(pool)
    await setup_tokens.issue(pool, ttl_seconds=-1)
    assert await setup_tokens.purge_expired(pool) == 1
    assert await setup_tokens.consume(pool, fresh) is True
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_setup_tokens.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.setup_tokens'`

- [ ] **Step 3: Реализовать токены**

`app/setup_tokens.py`:

```python
"""Одноразовые ссылки для регистрации passkey.

Бот отправляет такую ссылку владельцу ADMIN_ID в личку ВК. В базе хранится только
хеш: утечка дампа не должна давать вход в дашборд.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import asyncpg

TTL_SECONDS = 600
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def issue(pool: asyncpg.Pool, ttl_seconds: int = TTL_SECONDS) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    await pool.execute(
        "INSERT INTO setup_tokens (token_hash, expires_at) VALUES ($1, $2)",
        _hash(token), expires_at,
    )
    return token


async def consume(pool: asyncpg.Pool, token: str) -> bool:
    """Помечает токен использованным. True только если он был валиден и свеж."""
    row = await pool.fetchrow(
        "UPDATE setup_tokens SET used_at = now()"
        " WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()"
        " RETURNING token_hash",
        _hash(token),
    )
    return row is not None


async def purge_expired(pool: asyncpg.Pool) -> int:
    result = await pool.execute(
        "DELETE FROM setup_tokens WHERE expires_at < now() AND used_at IS NULL"
    )
    return int(result.split()[-1])
```

- [ ] **Step 4: Добавить `public_url` в конфиг**

В `app/config.py` добавить поле в датакласс после `database_url`:

```python
    public_url: str
```

и в `load_config` в конструктор `Config`, после `database_url=...`:

```python
        public_url=(env.get("PUBLIC_URL", "").strip() or "").rstrip("/"),
```

В `.env.example` добавить строку после `DATABASE_URL=`:

```
PUBLIC_URL=
```

В `tests/test_config.py` добавить тесты:

```python
def test_public_url_defaults_to_empty():
    assert load_config(BASE_ENV).public_url == ""


def test_public_url_trailing_slash_removed():
    cfg = load_config({**BASE_ENV, "PUBLIC_URL": "https://bot.up.railway.app/"})
    assert cfg.public_url == "https://bot.up.railway.app"
```

- [ ] **Step 5: Написать падающий тест на `/link`**

В `tests/test_handlers_user.py` добавить в начало:

```python
ADMIN_CFG = load_config({**ENV, "PUBLIC_URL": "https://bot.example"})
```

и тесты в конец файла:

```python
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
```

- [ ] **Step 6: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_handlers_user.py -k link -v`
Expected: FAIL — ссылка не отправляется

- [ ] **Step 7: Реализовать `/link`**

В `app/texts.py` добавить:

```python
SETUP_LINK = (
    "Ссылка для входа в дашборд. Действует 10 минут и только один раз:\n{url}"
)
SETUP_LINK_NO_URL = "Не задана переменная PUBLIC_URL — ссылку сформировать не из чего."
```

В `app/handlers/user.py` добавить импорт:

```python
from app import setup_tokens
```

и в `_handle_message`, сразу после вычисления `text` и `payload`, до разбора команд:

```python
    if user_id == cfg.admin_id and text == "/link":
        await _send_setup_link(pool, cfg, peer_id)
        return
```

и новую функцию:

```python
async def _send_setup_link(pool: asyncpg.Pool, cfg: Config, peer_id: int) -> None:
    if not cfg.public_url:
        await outbox.enqueue(pool, peer_id, texts.SETUP_LINK_NO_URL)
        return
    token = await setup_tokens.issue(pool)
    url = f"{cfg.public_url}/setup?token={token}"
    await outbox.enqueue(pool, peer_id, texts.SETUP_LINK.format(url=url))
```

- [ ] **Step 8: Прогнать все тесты и линтер**

Run: `uv run pytest -v && uv run ruff check .`
Expected: все зелёные

- [ ] **Step 9: Коммит**

```bash
git add app tests .env.example
git commit -m "Добавить одноразовую ссылку для регистрации passkey"
```

---

### Task 11: Сборка приложения, режим long poll и фоновые задачи

**Files:**
- Create: `app/main.py`
- Create: `app/vk/longpoll.py`
- Create: `app/maintenance.py`
- Create: `tests/test_main.py`
- Create: `tests/test_longpoll.py`

**Interfaces:**
- Consumes: всё из задач 1–10.
- Produces:
  - `app.main.create_app(cfg: Config) -> FastAPI` — собранное приложение с lifespan
  - `app.main.build_from_env() -> FastAPI` — фабрика для uvicorn (`--factory`)
  - `app.vk.longpoll.build_polling(cfg: Config) -> BotPolling`
  - `app.vk.longpoll.run_longpoll(polling, handler, stop: asyncio.Event) -> None`
  - `app.maintenance.run_housekeeping(pool, stop: asyncio.Event) -> None` — чистит `processed_events` и `setup_tokens` раз в час
  - `GET /healthz` → `{"status": "ok"}`

- [ ] **Step 1: Написать падающий тест**

`tests/test_main.py`:

```python
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.main import create_app

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код",
    "VK_SECRET_KEY": "секрет", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
}


def test_create_app_registers_callback_route():
    app = create_app(load_config(ENV))
    paths = {r.path for r in app.routes}
    assert "/vk/callback" in paths
    assert "/healthz" in paths


def test_create_app_stores_config():
    cfg = load_config(ENV)
    assert create_app(cfg).state.cfg is cfg


async def test_healthz_responds_without_database(pool):
    """Проверка живости не должна зависеть от БД — иначе Railway убьёт контейнер."""
    app = create_app(load_config(ENV))
    app.state.pool = pool
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    response = await http.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

`tests/test_longpoll.py`:

```python
import asyncio

from app.config import load_config
from app.vk.longpoll import run_longpoll

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код",
    "VK_SECRET_KEY": "секрет", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
    "VK_MODE": "longpoll",
}
CFG = load_config(ENV)


class FakePolling:
    def __init__(self, batches):
        self._batches = batches

    async def listen(self):
        for batch in self._batches:
            yield batch
            await asyncio.sleep(0)


async def test_longpoll_feeds_events_to_handler(pool):
    seen = []

    async def handler(event):
        seen.append(event)

    stop = asyncio.Event()
    polling = FakePolling([{"updates": [
        {"type": "message_new", "object": {"message": {"from_id": 1}}},
        {"type": "message_new", "object": {"message": {"from_id": 2}}},
    ]}])

    await run_longpoll(polling, handler, stop)
    assert [e["object"]["message"]["from_id"] for e in seen] == [1, 2]


async def test_longpoll_survives_handler_error(pool):
    seen = []

    async def handler(event):
        if event["object"]["message"]["from_id"] == 1:
            raise RuntimeError("сломалось")
        seen.append(event)

    polling = FakePolling([{"updates": [
        {"type": "message_new", "object": {"message": {"from_id": 1}}},
        {"type": "message_new", "object": {"message": {"from_id": 2}}},
    ]}])

    await run_longpoll(polling, handler, asyncio.Event())
    assert len(seen) == 1


async def test_longpoll_stops_on_event(pool):
    stop = asyncio.Event()
    stop.set()
    seen = []

    async def handler(event):
        seen.append(event)

    polling = FakePolling([{"updates": [{"type": "message_new", "object": {}}]}])
    await asyncio.wait_for(run_longpoll(polling, handler, stop), timeout=1)
    assert seen == []
```

- [ ] **Step 2: Прогнать, убедиться что падает**

Run: `uv run pytest tests/test_main.py tests/test_longpoll.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Реализовать long poll и обслуживание**

`app/vk/longpoll.py`:

```python
"""Long Poll — режим локальной разработки.

На проде работает Callback API: у Railway есть публичный адрес, и повторные
доставки ВК обрабатываются дедупликацией. Long Poll нужен, чтобы поднять бота на
ноутбуке без туннеля.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from vkbottle import API
from vkbottle.polling import BotPolling

from app.config import Config

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]


def build_polling(cfg: Config) -> BotPolling:
    return BotPolling(api=API(cfg.vk_group_token), skip_old_events=True)


async def run_longpoll(polling, handler: Handler, stop: asyncio.Event) -> None:
    async for batch in polling.listen():
        if stop.is_set():
            return
        for event in batch.get("updates", []):
            if stop.is_set():
                return
            try:
                await handler(event)
            except Exception:
                # Одно сломанное событие не должно останавливать весь опрос.
                logger.exception("обработка события long poll провалилась")
```

`app/maintenance.py`:

```python
"""Периодическая уборка. Таблицы дедупликации и токенов растут без неё бесконечно."""

import asyncio
import logging

import asyncpg

from app import setup_tokens
from app.db import queries as q

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


async def run_housekeeping(pool: asyncpg.Pool, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            events = await q.cleanup_old_events(pool)
            tokens = await setup_tokens.purge_expired(pool)
            if events or tokens:
                logger.info("уборка: событий %s, токенов %s", events, tokens)
        except Exception:
            logger.exception("уборка упала")
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
        except TimeoutError:
            pass
```

- [ ] **Step 4: Реализовать сборку приложения**

`app/main.py`:

```python
"""Точка входа. Один процесс: вебхук ВК, фоновая отправка и уборка."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Config, load_config
from app.db.pool import apply_migrations, create_pool
from app.handlers.user import handle_event
from app.maintenance import run_housekeeping
from app.vk import outbox
from app.vk.callback import router as callback_router
from app.vk.client import build_client
from app.vk.longpoll import build_polling, run_longpoll

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)


def create_app(cfg: Config) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.pool = await create_pool(cfg.database_url)
        await apply_migrations(application.state.pool)
        # Строки, застрявшие в 'sending' после прошлого падения, возвращаем в работу.
        await outbox.recover_stuck(application.state.pool)

        client = build_client(cfg)
        application.state.client = client
        stop = asyncio.Event()
        application.state.stop = stop

        tasks = [
            asyncio.create_task(outbox.run_worker(application.state.pool, client, stop)),
            asyncio.create_task(run_housekeeping(application.state.pool, stop)),
        ]
        if cfg.vk_mode == "longpoll":
            tasks.append(asyncio.create_task(
                run_longpoll(build_polling(cfg), application.state.handler, stop)
            ))
        application.state.tasks = tasks
        logger.info("бот запущен в режиме %s", cfg.vk_mode)

        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await application.state.pool.close()

    application = FastAPI(title="VK Support Bot", lifespan=lifespan)
    application.state.cfg = cfg
    application.state.background = set()
    application.include_router(callback_router)

    @application.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    async def handler(event: dict) -> None:
        await handle_event(application.state.pool, cfg, event)

    application.state.handler = handler
    return application


def build_from_env() -> FastAPI:
    """Фабрика для uvicorn. Конфиг читается при запуске, а не при импорте,
    иначе модуль нельзя импортировать в тестах без полного окружения."""
    return create_app(load_config(os.environ))
```

- [ ] **Step 5: Прогнать все тесты и линтер**

Run: `uv run pytest -v && uv run ruff check .`
Expected: все зелёные

- [ ] **Step 6: Проверить реальный запуск в режиме long poll**

```bash
VK_GROUP_TOKEN="$(grep '^VK_GROUP_TOKEN=' .env | cut -d= -f2-)" \
VK_GROUP_ID=... VK_CONFIRMATION_CODE=x VK_SECRET_KEY=x ADMIN_ID=... \
DATABASE_URL=postgresql://localhost/vkbot_dev SESSION_SECRET=$(openssl rand -hex 32) \
VK_MODE=longpoll uv run uvicorn app.main:build_from_env --factory --port 8000
```

Expected: в логах `бот запущен в режиме longpoll`, применены миграции, `curl localhost:8000/healthz` отдаёт `{"status":"ok"}`

- [ ] **Step 7: Коммит**

```bash
git add app/main.py app/vk/longpoll.py app/maintenance.py tests/test_main.py tests/test_longpoll.py
git commit -m "Собрать приложение, добавить long poll и фоновую уборку"
```

---

### Task 12: Нагрузочные проверки

**Files:**
- Create: `loadtests/__init__.py`
- Create: `loadtests/locustfile.py`
- Create: `loadtests/test_load.py`
- Create: `loadtests/README.md`
- Modify: `pyproject.toml` — маркер `load`

**Interfaces:**
- Consumes: всё приложение.
- Produces: `uv run pytest loadtests -m load` и `uv run locust -f loadtests/locustfile.py`.

Критерии из спеки, каждый оформлен отдельным тестом:

| Сценарий | Критерий |
|---|---|
| Шторм входящих | p95 ответа вебхука < 100 мс, 0 потерь, 0 повторных обработок |
| Повторы Callback API | один `event_id` обработан ровно один раз |
| Пропускная способность outbox | темп не превышает 20 rps, очередь разгребается полностью |
| Рестарт под нагрузкой | ни одной потери, ни одного дубля |
| Порядок сообщений | внутри одного диалога порядок сохранён |
| Пул Postgres | нет ожиданий соединения дольше 1 с |

- [ ] **Step 1: Добавить маркер в pyproject.toml**

В секцию `[tool.pytest.ini_options]`:

```toml
markers = ["load: нагрузочные проверки, запускаются отдельно"]
addopts = "-m 'not load'"
```

- [ ] **Step 2: Написать нагрузочные тесты**

`loadtests/__init__.py` — пустой файл.

`loadtests/test_load.py`:

```python
"""Нагрузочные проверки. Запуск: uv run pytest loadtests -m load -v

Реальный профиль — 272 подписчика и один оператор, но Callback API умеет
устраивать шторм повторов, и ломаются такие системы именно там.
"""

import asyncio
import statistics
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.db import queries as q
from app.vk import outbox
from app.vk.callback import router

pytestmark = pytest.mark.load

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код",
    "VK_SECRET_KEY": "секрет", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
}
CFG = load_config(ENV)

STORM_EVENTS = 500
P95_LIMIT_SECONDS = 0.1


def build_app(pool, handler):
    app = FastAPI()
    app.include_router(router)
    app.state.cfg = CFG
    app.state.pool = pool
    app.state.background = set()
    app.state.handler = handler
    return app


def event(index: int) -> dict:
    return {
        "type": "message_new", "group_id": 111, "secret": "секрет",
        "event_id": f"evt-{index}",
        "object": {"message": {"id": index, "from_id": 1000 + index % 50,
                               "peer_id": 1000 + index % 50, "text": "нагрузка"}},
    }


async def test_webhook_survives_event_storm(pool):
    handled: list[str] = []

    async def handler(evt):
        handled.append(evt["event_id"])

    app = build_app(pool, handler)
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    latencies: list[float] = []

    async def fire(index: int):
        started = time.monotonic()
        response = await http.post("/vk/callback", json=event(index))
        latencies.append(time.monotonic() - started)
        assert response.text == "ok"

    await asyncio.gather(*(fire(i) for i in range(STORM_EVENTS)))
    if app.state.background:
        await asyncio.gather(*list(app.state.background))

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    assert p95 < P95_LIMIT_SECONDS, f"p95={p95:.3f}с превышает {P95_LIMIT_SECONDS}с"
    assert len(handled) == STORM_EVENTS, "часть событий потеряна"
    assert len(set(handled)) == STORM_EVENTS, "часть событий обработана дважды"


async def test_duplicate_storm_handled_once(pool):
    """ВК повторяет одно и то же событие, пока не получит ok."""
    handled: list[str] = []

    async def handler(evt):
        handled.append(evt["event_id"])

    app = build_app(pool, handler)
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    await asyncio.gather(*(http.post("/vk/callback", json=event(1)) for _ in range(200)))
    if app.state.background:
        await asyncio.gather(*list(app.state.background))

    assert len(handled) == 1


async def test_outbox_respects_rate_limit(pool):
    """Превышение 20 rps приводит к ошибке 6 от ВК, поэтому темп надо держать."""
    from app.vk.ratelimit import RateLimiter

    limiter = RateLimiter(rate=18.0, capacity=18.0)
    timestamps: list[float] = []

    class TimedClient:
        async def call(self, method, **params):
            await limiter.acquire()
            timestamps.append(time.monotonic())
            return {"message_id": 1}

    total = 200
    await q.upsert_user(pool, 1)
    for i in range(total):
        await outbox.enqueue(pool, peer_id=1, text=str(i))

    client = TimedClient()
    while await outbox.process_batch(pool, client, limit=50):
        pass

    elapsed = timestamps[-1] - timestamps[0]
    actual_rate = (total - 1) / elapsed
    assert actual_rate <= 20.0, f"темп {actual_rate:.1f} rps превышает лимит ВК"
    assert await pool.fetchval("SELECT count(*) FROM outbox WHERE status='sent'") == total


async def test_outbox_preserves_order_per_peer(pool):
    sent_order: list[str] = []

    class RecordingClient:
        async def call(self, method, **params):
            sent_order.append(params["message"])
            return {"message_id": 1}

    for i in range(100):
        await outbox.enqueue(pool, peer_id=1, text=f"{i:03d}")

    client = RecordingClient()
    while await outbox.process_batch(pool, client, limit=10):
        pass

    assert sent_order == sorted(sent_order)


async def test_restart_loses_nothing_and_duplicates_nothing(pool):
    """Убиваем процесс посреди отправки — ни потерь, ни дублей."""
    random_ids: list[int] = []

    class FlakyClient:
        def __init__(self, fail_after):
            self.count = 0
            self.fail_after = fail_after

        async def call(self, method, **params):
            self.count += 1
            if self.count > self.fail_after:
                raise asyncio.CancelledError("процесс убит")
            random_ids.append(params["random_id"])
            return {"message_id": self.count}

    total = 50
    for i in range(total):
        await outbox.enqueue(pool, peer_id=1, text=str(i))

    with pytest.raises(asyncio.CancelledError):
        while await outbox.process_batch(pool, FlakyClient(fail_after=20), limit=10):
            pass

    # Перезапуск: возвращаем зависшие строки и дорабатываем очередь.
    await outbox.recover_stuck(pool)

    class GoodClient:
        async def call(self, method, **params):
            random_ids.append(params["random_id"])
            return {"message_id": 1}

    while await outbox.process_batch(pool, GoodClient(), limit=10):
        pass

    sent = await pool.fetchval("SELECT count(*) FROM outbox WHERE status = 'sent'")
    assert sent == total, "часть сообщений потеряна при рестарте"

    # Повторная отправка одного и того же random_id безопасна: ВК отбросит дубль.
    all_random = await pool.fetch("SELECT random_id FROM outbox")
    assert len({r["random_id"] for r in all_random}) == total


async def test_connection_pool_does_not_starve(pool):
    """Пул на 10 соединений против 200 параллельных запросов."""
    async def one(i: int):
        started = time.monotonic()
        await q.upsert_user(pool, 5000 + i)
        return time.monotonic() - started

    waits = await asyncio.gather(*(one(i) for i in range(200)))
    assert max(waits) < 1.0, f"худшее ожидание соединения {max(waits):.2f}с"
    assert statistics.median(waits) < 0.1
```

`loadtests/locustfile.py`:

```python
"""Обстрел вебхука по HTTP против запущенного сервиса.

Запуск против локального сервера:
    uv run locust -f loadtests/locustfile.py --host http://localhost:8000

Критерий приёмки: p95 ниже 100 мс, ноль ответов кроме 'ok'.
"""

import itertools
import os

from locust import HttpUser, constant_pacing, task

GROUP_ID = int(os.environ.get("VK_GROUP_ID", "111"))
SECRET = os.environ.get("VK_SECRET_KEY", "секрет")

counter = itertools.count()


class CallbackUser(HttpUser):
    wait_time = constant_pacing(0.05)

    @task
    def send_event(self):
        index = next(counter)
        with self.client.post(
            "/vk/callback",
            json={
                "type": "message_new",
                "group_id": GROUP_ID,
                "secret": SECRET,
                "event_id": f"locust-{index}",
                "object": {"message": {"id": index, "from_id": 1000 + index % 50,
                                       "peer_id": 1000 + index % 50,
                                       "text": "нагрузочный тест"}},
            },
            catch_response=True,
        ) as response:
            if response.text != "ok":
                response.failure(f"ожидали 'ok', получили {response.text[:50]!r}")
```

`loadtests/README.md`:

```markdown
# Нагрузочные проверки

Обычный `pytest` их не запускает: в `pyproject.toml` стоит `addopts = "-m 'not load'"`.

## Запуск

    uv run pytest loadtests -m load -v

## Обстрел по HTTP

Поднять сервис, затем:

    uv run locust -f loadtests/locustfile.py --host http://localhost:8000

Открыть http://localhost:8089, задать 50 пользователей и разгон 10/с.

## Критерии приёмки

| Сценарий | Критерий |
|---|---|
| Шторм 500 событий | p95 < 100 мс, 0 потерь, 0 повторов |
| 200 дублей одного event_id | обработано ровно 1 раз |
| 200 сообщений в outbox | темп <= 20 rps, всё отправлено |
| Рестарт посреди отправки | 0 потерь, random_id не переиспользован между разными сообщениями |
| 200 параллельных запросов к БД | худшее ожидание < 1 с |
```

- [ ] **Step 3: Прогнать нагрузочные тесты**

Run: `uv run pytest loadtests -m load -v`
Expected: 6 passed. Если `test_webhook_survives_event_storm` не укладывается в p95 — проверь, что обработка действительно уходит в фон через `spawn`, а не выполняется до возврата `ok`.

- [ ] **Step 4: Убедиться, что обычный прогон их не подхватывает**

Run: `uv run pytest -v`
Expected: нагрузочные помечены как deselected

- [ ] **Step 5: Коммит**

```bash
git add loadtests pyproject.toml
git commit -m "Добавить нагрузочные проверки"
```

---

### Task 13: Деплой на Railway

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `railway.json`
- Create: `README.md`

**Interfaces:**
- Consumes: `app.main:build_from_env` (Task 11).
- Produces: образ, который Railway собирает и запускает; `README.md` со списком переменных окружения.

- [ ] **Step 1: Написать Dockerfile**

`Dockerfile`:

```dockerfile
FROM python:3.12-slim

# tzdata нужна для zoneinfo: без неё ZoneInfo("Europe/Moscow") падает,
# и рабочие часы считаются неверно.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Railway передаёт порт через $PORT, захардкоженный порт работать не будет.
CMD ["sh", "-c", "uvicorn app.main:build_from_env --factory --host 0.0.0.0 --port ${PORT:-8000}"]
```

`.dockerignore`:

```
.git
.venv
tests
loadtests
docs
node_modules
__pycache__
*.pyc
.env
.pytest_cache
.ruff_cache
```

`railway.json`:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "healthcheckPath": "/healthz",
    "healthcheckTimeout": 30,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "numReplicas": 1
  }
}
```

`numReplicas` обязан остаться равным 1: очередь отправки и рассылка событий живут в процессе, второй инстанс приведёт к двойной отправке.

- [ ] **Step 2: Написать README**

`README.md`:

```markdown
# VKSystemAuto

Бот поддержки сообщества ВКонтакте и дашборд оператора.

## Локальный запуск

    uv venv --python 3.12
    uv sync
    cp .env.example .env    # заполнить значения
    uv run uvicorn app.main:build_from_env --factory --reload --port 8000

С `VK_MODE=longpoll` публичный адрес не нужен.

## Тесты

    uv run pytest                    # обычные, Postgres поднимается сам
    uv run pytest loadtests -m load  # нагрузочные
    uv run ruff check .

## Переменные окружения

| Переменная | Обязательна | Описание |
|---|---|---|
| `VK_GROUP_TOKEN` | да | Токен сообщества с правами `messages` и `manage` |
| `VK_GROUP_ID` | да | Числовой id сообщества |
| `VK_CONFIRMATION_CODE` | да | Строка подтверждения из настроек Callback API |
| `VK_SECRET_KEY` | да | Секретный ключ Callback API |
| `VK_API_VERSION` | нет | По умолчанию `5.199` |
| `ADMIN_ID` | да | vk_id владельца дашборда |
| `DATABASE_URL` | да | Подставляется Railway из сервиса Postgres |
| `PUBLIC_URL` | да | Адрес сервиса, например `https://имя.up.railway.app` |
| `SESSION_SECRET` | да | Случайная строка от 32 символов |
| `VK_MODE` | нет | `callback` (по умолчанию) или `longpoll` |
| `WORK_HOURS` | нет | По умолчанию `10-19` |
| `TZ` | нет | По умолчанию `Europe/Moscow` |

Переменные дашборда (`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`, `VAPID_*`) добавляются
во втором этапе.

## Настройка Callback API

1. Сообщество → Управление → Работа с API → Callback API.
2. Адрес сервера: `https://<PUBLIC_URL>/vk/callback`.
3. Версия API: та же, что в `VK_API_VERSION`.
4. Скопировать строку подтверждения в `VK_CONFIRMATION_CODE`, задать секретный
   ключ и продублировать его в `VK_SECRET_KEY`.
5. Типы событий: включить `message_new`.
6. Нажать «Подтвердить».

Порядок важен: сначала переменные в Railway и передеплой, потом «Подтвердить».
```

- [ ] **Step 3: Проверить сборку образа**

Docker локально не установлен, поэтому сборка проверяется на Railway:

```bash
railway link    # выбрать проект
railway up --detach
railway logs
```

Expected: в логах `бот запущен в режиме callback` и применённые миграции

- [ ] **Step 4: Проверить живость**

```bash
curl -s https://<PUBLIC_URL>/healthz
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: Коммит**

```bash
git add Dockerfile .dockerignore railway.json README.md
git commit -m "Добавить сборку образа и конфигурацию Railway"
```

---

## Что дальше

После выполнения этого плана бот работает: принимает обращения, отвечает на FAQ,
складывает переписку и вложения в Postgres, надёжно шлёт ответы. Обращения видны
только в базе — интерфейса ещё нет.

Второй план, `2026-09-20-dashboard.md`, добавляет: passkey-вход, REST и WebSocket,
PWA с пушами, экраны диалогов, FAQ, статистики и настроек, отправку фото и файлов
от оператора.
