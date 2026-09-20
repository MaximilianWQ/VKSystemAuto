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
