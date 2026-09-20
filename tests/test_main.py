from httpx import ASGITransport, AsyncClient

from app.config import load_config
from app.main import create_app

ENV = {
    "VK_GROUP_TOKEN": "t", "VK_GROUP_ID": "111", "VK_CONFIRMATION_CODE": "код",
    "VK_SECRET_KEY": "секрет", "ADMIN_ID": "777",
    "DATABASE_URL": "postgresql://x", "SESSION_SECRET": "s" * 32,
}


def test_create_app_registers_callback_route():
    """Роутер включается лениво, поэтому пути смотрим в схеме, а не в app.routes."""
    app = create_app(load_config(ENV))
    paths = set(app.openapi()["paths"])
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
