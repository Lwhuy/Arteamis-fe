"""Auth/JWT/OAuth configuration read from environment.

Secrets (JWT_SECRET, GOOGLE_CLIENT_SECRET) go through get_secret_from_env so the
Docker *_FILE pattern works; non-secrets through os.getenv. Read fresh on every
get_auth_config() call so operators (and tests) can change env without a reload.
"""

import os
from dataclasses import dataclass
from typing import Optional

from open_notebook.utils.encryption import get_secret_from_env


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AuthConfig:
    jwt_secret: Optional[str]
    jwt_algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_days: int
    refresh_cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    google_client_id: Optional[str]
    google_client_secret: Optional[str]
    google_redirect_uri: str
    frontend_url: str


def get_auth_config() -> AuthConfig:
    return AuthConfig(
        jwt_secret=get_secret_from_env("JWT_SECRET"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM") or "HS256",
        access_token_expire_minutes=_env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 15),
        refresh_token_expire_days=_env_int("REFRESH_TOKEN_EXPIRE_DAYS", 30),
        refresh_cookie_name=os.getenv("REFRESH_COOKIE_NAME") or "arteamis_refresh",
        cookie_secure=_env_bool("COOKIE_SECURE", True),
        cookie_samesite=os.getenv("COOKIE_SAMESITE") or "lax",
        google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
        google_client_secret=get_secret_from_env("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=os.getenv("GOOGLE_REDIRECT_URI")
        or "http://localhost:5055/api/auth/google/callback",
        frontend_url=os.getenv("FRONTEND_URL") or "http://localhost:3000",
    )


def auth_enabled() -> bool:
    """Auth is enforced only when a JWT secret is configured (dev parity with
    today's 'no password → open' behavior)."""
    return bool(get_auth_config().jwt_secret)
