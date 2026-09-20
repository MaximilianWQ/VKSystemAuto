# VKSystemAuto — бот поддержки ВК + веб-дашборд

Бот поддержки сообщества ВКонтакте и PWA-дашборд оператора.
Python 3.12 / FastAPI / vkbottle / Postgres / React, деплой на Railway.

## Главный скилл проекта

`.claude/skills/vk-support-bot/SKILL.md` — договорённости проекта, особенности VK API,
схема БД, принятые архитектурные решения. **Читать перед любой задачей по этому репозиторию.**

## Какие скиллы на каком этапе

| Этап | Скилл |
|---|---|
| Новая фича, изменение поведения | `superpowers:brainstorming` — до написания кода |
| Многошаговая задача с готовой спекой | `superpowers:writing-plans`, затем `superpowers:executing-plans` |
| Любой код | `superpowers:test-driven-development` — тест до реализации |
| Баг, упавший тест, странное поведение | `superpowers:systematic-debugging` — до предложения фикса |
| Перед «готово», коммитом, PR | `superpowers:verification-before-completion` — сначала прогон, потом утверждение |
| Ревью | `superpowers:requesting-code-review`, `superpowers:receiving-code-review` |
| Дисциплина правок | `andrej-karpathy-skills:karpathy-guidelines` — хирургические изменения, без переусложнения |

## Скиллы для дашборда

| Работа | Скилл |
|---|---|
| Визуальный язык, типографика, композиция | `frontend-design:frontend-design`, `awwwards` |
| Анимации и микровзаимодействия | `design-motion-principles` |
| Быстрая чистка вёрстки | `baseline-ui` |
| Доступность | `accessibility`, `fixing-accessibility` |
| Скорость PWA | `core-web-vitals`, `performance`, `fixing-motion-performance` |
| Безопасность и современные практики | `best-practices` |
| Графики в статистике | `dataviz` |

## Обязательное правило по библиотекам

Перед использованием любого метода **vkbottle, FastAPI, py_webauthn, pywebpush, asyncpg**
сверяться с актуальной документацией через **Context7**. По памяти не писать: у vkbottle
API заметно менялся между версиями, у py_webauthn — тоже.

## Секреты

Реальные значения только в Railway Variables. В репозитории — `.env.example` без значений.
`.env` в `.gitignore`. Токены и `VK_SECRET_KEY` не логировать, не выводить в ответах,
не коммитить.

## Definition of done

1. `pytest` зелёный
2. `ruff check` без ошибок
3. Бот стартует локально с `VK_MODE=longpoll`
4. Дашборд собирается (`npm run build`) без ошибок и предупреждений TypeScript
