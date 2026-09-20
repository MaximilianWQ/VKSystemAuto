"""Вход в дашборд по passkey.

Паролей нет вообще. Первый ключ регистрируется по одноразовой ссылке, которую
бот присылает владельцу ADMIN_ID в личку ВК. Ключей можно завести несколько —
телефон и ноутбук.
"""

import json
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import setup_tokens
from app.config import Config
from app.web import challenges, sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

RP_NAME = "Поддержка Atlas Secure"
ADMIN_USER_NAME = "operator"
ADMIN_USER_ID = b"atlas-operator"


async def list_credentials(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    return await pool.fetch("SELECT * FROM admin_credentials ORDER BY created_at")


def _require_rp(cfg: Config) -> tuple[str, str]:
    if not cfg.webauthn_rp_id or not cfg.webauthn_origin:
        raise HTTPException(status_code=503, detail="webauthn не настроен")
    return cfg.webauthn_rp_id, cfg.webauthn_origin


def _challenge_cookie(response: JSONResponse, challenge_id: str) -> None:
    response.set_cookie(
        challenges.COOKIE_NAME, challenge_id,
        max_age=challenges.TTL_SECONDS, httponly=True, secure=True,
        samesite="lax", path="/",
    )


@router.post("/register/options")
async def register_options(request: Request) -> JSONResponse:
    body = await request.json()
    pool = request.app.state.pool
    rp_id, _ = _require_rp(request.app.state.cfg)

    # Проверяем, но НЕ гасим: прерванный create() в браузере не должен
    # сжигать ссылку. Гасим на шаге verify.
    valid = await pool.fetchval(
        "SELECT 1 FROM setup_tokens WHERE token_hash = $1"
        " AND used_at IS NULL AND expires_at > now()",
        setup_tokens.hash_token(str(body.get("token", ""))),
    )
    if not valid:
        raise HTTPException(status_code=403, detail="ссылка недействительна")

    existing = await list_credentials(pool)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_name=ADMIN_USER_NAME,
        user_id=ADMIN_USER_ID,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(row["credential_id"]))
            for row in existing
        ],
    )
    challenge_id = await challenges.issue(pool, options.challenge, "register")

    response = JSONResponse(json.loads(options_to_json(options)))
    _challenge_cookie(response, challenge_id)
    return response


@router.post("/register/verify")
async def register_verify(request: Request) -> JSONResponse:
    body = await request.json()
    pool = request.app.state.pool
    rp_id, origin = _require_rp(request.app.state.cfg)

    challenge_id = request.cookies.get(challenges.COOKIE_NAME, "")
    expected = await challenges.consume(pool, challenge_id, "register")
    if expected is None:
        raise HTTPException(status_code=400, detail="challenge истёк, начните заново")

    # Гасим ссылку здесь: повторный заход по той же ссылке не даёт второй попытки.
    if not await setup_tokens.consume(pool, str(body.get("token", ""))):
        raise HTTPException(status_code=403, detail="ссылка уже использована")

    try:
        verified = verify_registration_response(
            credential=body.get("credential"),
            expected_challenge=expected,
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except Exception:
        logger.warning("регистрация passkey отклонена: проверка не прошла")
        raise HTTPException(status_code=400, detail="ключ не принят") from None

    await pool.execute(
        "INSERT INTO admin_credentials (credential_id, public_key, sign_count, name)"
        " VALUES ($1, $2, $3, $4)"
        " ON CONFLICT (credential_id) DO UPDATE SET"
        " public_key = EXCLUDED.public_key, sign_count = EXCLUDED.sign_count",
        verified.credential_id, verified.credential_public_key,
        verified.sign_count, str(body.get("name", ""))[:100],
    )

    token = await sessions.issue(pool, request.headers.get("user-agent", ""))
    response = JSONResponse({"ok": True})
    sessions.set_cookie(response, token)
    response.delete_cookie(challenges.COOKIE_NAME, path="/")
    return response


@router.post("/login/options")
async def login_options(request: Request) -> JSONResponse:
    pool = request.app.state.pool
    rp_id, _ = _require_rp(request.app.state.cfg)

    registered = await list_credentials(pool)
    if not registered:
        raise HTTPException(
            status_code=409,
            detail="ключей нет, напишите боту сообщества слово «дашборд» — он пришлёт ссылку",
        )

    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(row["credential_id"]))
            for row in registered
        ],
    )
    challenge_id = await challenges.issue(pool, options.challenge, "login")

    response = JSONResponse(json.loads(options_to_json(options)))
    _challenge_cookie(response, challenge_id)
    return response


async def _find_credential(pool: asyncpg.Pool, raw_id: str) -> asyncpg.Record | None:
    """Ищет ключ по идентификатору из ответа браузера.

    Оператор один, ключей единицы — перебор дешевле и надёжнее, чем угадывать
    точную кодировку rawId.
    """
    try:
        wanted = base64url_to_bytes(raw_id)
    except Exception:
        wanted = b""

    rows = await list_credentials(pool)
    for row in rows:
        if wanted and bytes(row["credential_id"]) == wanted:
            return row
    return rows[0] if len(rows) == 1 else None


@router.post("/login/verify")
async def login_verify(request: Request) -> JSONResponse:
    body = await request.json()
    pool = request.app.state.pool
    rp_id, origin = _require_rp(request.app.state.cfg)

    challenge_id = request.cookies.get(challenges.COOKIE_NAME, "")
    expected = await challenges.consume(pool, challenge_id, "login")
    if expected is None:
        raise HTTPException(status_code=400, detail="challenge истёк, начните заново")

    credential = body.get("credential") or {}
    raw_id = credential.get("rawId") or credential.get("id") or ""
    stored = await _find_credential(pool, raw_id)
    if stored is None:
        raise HTTPException(status_code=400, detail="ключ не найден")

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=expected,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=bytes(stored["public_key"]),
            credential_current_sign_count=stored["sign_count"],
        )
    except Exception:
        logger.warning("вход по passkey отклонён: проверка не прошла")
        raise HTTPException(status_code=400, detail="ключ не принят") from None

    if bytes(verified.credential_id) != bytes(stored["credential_id"]):
        logger.warning("вход по passkey отклонён: идентификатор ключа не совпал")
        raise HTTPException(status_code=400, detail="ключ не принят")

    # Счётчик подписей растёт монотонно; его сохранение — защита от клона ключа.
    await pool.execute(
        "UPDATE admin_credentials SET sign_count = $2, last_used_at = now()"
        " WHERE credential_id = $1",
        stored["credential_id"], verified.new_sign_count,
    )

    token = await sessions.issue(pool, request.headers.get("user-agent", ""))
    response = JSONResponse({"ok": True})
    sessions.set_cookie(response, token)
    response.delete_cookie(challenges.COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def me(request: Request, session=Depends(sessions.require_session)) -> dict:
    rows = await list_credentials(request.app.state.pool)
    return {
        "keys": [
            {
                "id": row["id"],
                "name": row["name"] or "Без названия",
                "created_at": row["created_at"].isoformat(),
                "last_used_at": row["last_used_at"].isoformat()
                if row["last_used_at"] else None,
            }
            for row in rows
        ]
    }


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(sessions.COOKIE_NAME, "")
    if token:
        await sessions.revoke(request.app.state.pool, token)
    response = JSONResponse({"ok": True})
    sessions.clear_cookie(response)
    return response
