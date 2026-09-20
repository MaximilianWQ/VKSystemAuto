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
