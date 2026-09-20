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
