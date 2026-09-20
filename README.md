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

Задать вручную нужно четыре штуки — остальное подставляется само.

| Переменная | Откуда взять |
|---|---|
| `VK_GROUP_ID` | номер сообщества, для Atlas Secure это `237579772` |
| `VK_CONFIRMATION_CODE` | строка подтверждения из настроек Callback API |
| `VK_SECRET_KEY` | любая случайная строка, её же вписать в настройки Callback API |
| `SESSION_SECRET` | `openssl rand -hex 32`, минимум 32 символа |

Подставляются автоматически:

| Переменная | Кем |
|---|---|
| `VK_GROUP_TOKEN` | принимается и под старым именем `VK_TOKEN` |
| `ADMIN_ID` | уже задана в Railway |
| `DATABASE_URL` | сервисом Postgres |
| `PUBLIC_URL` | выводится из `RAILWAY_PUBLIC_DOMAIN` |

Необязательные, со значениями по умолчанию: `VK_API_VERSION` (`5.199`),
`VK_MODE` (`callback`), `WORK_HOURS` (`10-19`), `TZ` (`Europe/Moscow`).

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
