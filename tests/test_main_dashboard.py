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
