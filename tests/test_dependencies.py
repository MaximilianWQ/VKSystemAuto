"""Боевой код не должен зависеть от тестовых пакетов.

Образ ставится через `uv sync --no-dev`, поэтому импорт dev-зависимости из
app/ роняет контейнер на старте, а не на тестах — и узнаёшь об этом только
из логов упавшего деплоя.
"""

import ast
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app"

# Имя пакета не всегда совпадает с именем модуля.
MODULE_NAMES = {
    "pytest-asyncio": "pytest_asyncio",
    "python-multipart": "multipart",
}

# Ставятся транзитивно, но используются осознанно.
TRANSITIVE = {"py_vapid", "cryptography"}


def _names(requirements: list[str]) -> set[str]:
    """Из «uvicorn[standard]>=0.32» делает «uvicorn»."""
    return {
        MODULE_NAMES.get(raw, raw).replace("-", "_")
        for raw in (re.split(r"[><=!\[~ ]", item.strip())[0] for item in requirements)
        if raw
    }


def _sections() -> tuple[set[str], set[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    prod = _names(data["project"]["dependencies"])
    dev = _names(data["dependency-groups"]["dev"])
    return prod, dev


def _imports() -> set[str]:
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_sections_parsed_correctly():
    """Страховка от разбора, который молча съедает часть зависимостей."""
    prod, dev = _sections()
    assert {"fastapi", "uvicorn", "asyncpg", "vkbottle", "httpx"} <= prod
    assert "pytest" in dev


def test_app_does_not_import_dev_only_packages():
    prod, dev = _sections()
    leaked = sorted((dev - prod) & _imports())
    assert not leaked, (
        f"боевой код импортирует тестовые пакеты: {leaked}. "
        "Перенеси их в основные зависимости, иначе контейнер упадёт на старте."
    )


def test_every_third_party_import_is_declared():
    """Импорт, которого нет ни в одной секции, тоже упадёт в контейнере."""
    prod, dev = _sections()
    allowed = prod | dev | TRANSITIVE | {"app"}
    undeclared = sorted(_imports() - allowed - set(sys.stdlib_module_names))
    assert not undeclared, f"импорты без объявленной зависимости: {undeclared}"
