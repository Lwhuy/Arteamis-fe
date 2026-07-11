"""Authentication router: email/password + Google OAuth, JWT + refresh cookie.

Business logic lives in api/auth_service.py and open_notebook/auth/google.py;
this router only wires HTTP <-> those helpers, sets/reads the refresh cookie, and
maps outcomes to typed exceptions (global handlers in api/main.py map to status).
"""

import secrets

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from loguru import logger

from api import auth_service
from api.auth_config import get_auth_config
from api.models import LoginRequest, MeResponse, RegisterRequest, SessionPayload
from api.security import create_refresh_token, decode_refresh_token
from open_notebook.auth import google
from open_notebook.domain.user import User
from open_notebook.exceptions import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_STATE_COOKIE = "arteamis_oauth_state"


def _set_refresh_cookie(response: Response, user_id: str) -> None:
    cfg = get_auth_config()
    response.set_cookie(
        cfg.refresh_cookie_name,
        create_refresh_token(user_id),
        max_age=cfg.refresh_token_expire_days * 24 * 3600,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
        path="/",
    )


@router.get("/status")
async def get_auth_status():
    """Report whether JWT authentication is enabled (JWT_SECRET configured)."""
    enabled = bool(get_auth_config().jwt_secret)
    return {
        "auth_enabled": enabled,
        "message": "Authentication is required"
        if enabled
        else "Authentication is disabled",
    }


@router.post("/register", response_model=SessionPayload, status_code=201)
async def register(body: RegisterRequest, response: Response):
    user = await auth_service.register(
        body.email, body.password, body.display_name
    )
    _set_refresh_cookie(response, user.id or "")
    return auth_service.build_session_payload(user)


@router.post("/login", response_model=SessionPayload)
async def login(body: LoginRequest, response: Response):
    user = await auth_service.login(body.email, body.password)
    _set_refresh_cookie(response, user.id or "")
    return auth_service.build_session_payload(user)


@router.get("/google/start")
async def google_start():
    cfg = get_auth_config()
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(google.build_authorize_url(state))
    resp.set_cookie(
        _STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
        path="/",
    )
    return resp


@router.get("/google/callback")
async def google_callback(code: str, state: str, request: Request):
    cfg = get_auth_config()
    expected = request.cookies.get(_STATE_COOKIE)
    if not expected or not secrets.compare_digest(expected, state):
        raise InvalidInputError("Invalid OAuth state")

    info = await google.exchange_code_for_userinfo(code)
    email = info.get("email")
    subject = info.get("sub")
    if not email or not subject:
        raise InvalidInputError("Google profile missing email")
    # Only trust the email for account matching if Google verified it, else a
    # Google account with an unverified address matching a victim could link to
    # the victim's user (account takeover). Google returns bool True or "true".
    if info.get("email_verified") not in (True, "true"):
        raise InvalidInputError("Google email is not verified")

    user = await User.upsert_with_identity(
        provider="google",
        subject=subject,
        email=email,
        display_name=info.get("name"),
    )
    resp = RedirectResponse(f"{cfg.frontend_url}/notebooks")
    resp.delete_cookie(_STATE_COOKIE, path="/")
    _set_refresh_cookie(resp, user.id or "")
    return resp


@router.post("/refresh", response_model=SessionPayload)
async def refresh(request: Request, response: Response):
    cfg = get_auth_config()
    token = request.cookies.get(cfg.refresh_cookie_name)
    if not token:
        raise AuthenticationError("No refresh token")
    user_id = decode_refresh_token(token)  # raises AuthenticationError (401)
    try:
        user = await User.get(user_id)
    except NotFoundError:
        raise AuthenticationError("Unknown user")
    _set_refresh_cookie(response, user.id or "")
    return auth_service.build_session_payload(user)


@router.post("/logout")
async def logout(response: Response):
    cfg = get_auth_config()
    response.delete_cookie(cfg.refresh_cookie_name, path="/")
    return {"status": "logged_out"}


@router.get("/me", response_model=MeResponse)
async def me(request: Request):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise AuthenticationError("Not authenticated")
    try:
        user = await User.get(user_id)
    except NotFoundError:
        raise NotFoundError("User not found")
    return {
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "memberships": [],
    }
