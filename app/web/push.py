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
