"""JWT token helpers (port of arteamis-system core/security.py).

Two-token seam:
  * identity token  — {sub, type:"identity", exp}. The P1 frontend Bearer.
  * access token     — workspace-scoped ({sub, workspace_id, role}); create_access_token
    is a P2 stub. decode_access_token already parses the full claim set so P2/P6
    share one decoder; in P1 workspace_id/role are always None. (Personal-workspace
    auto-provisioning happens in P2, not P1.)
  * refresh token    — {sub, type:"refresh", exp}; httpOnly cookie, mints new tokens.

SurrealDB record ids are strings like "user:abc" (not UUIDs), so sub is validated
as a non-empty string with a "user:" prefix rather than as a UUID.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from api.auth_config import get_auth_config
from open_notebook.exceptions import AuthenticationError


def _require_user_id(value: object, claim: str = "sub") -> str:
    if not isinstance(value, str) or not value.startswith("user:") or len(value) <= len("user:"):
        raise AuthenticationError(f"Claim '{claim}' is not a valid user id")
    return value


@dataclass
class AuthContext:
    user_id: str
    workspace_id: Optional[str]
    role: Optional[str]


def create_identity_token(user_id: str, minutes: Optional[int] = None) -> str:
    cfg = get_auth_config()
    mins = cfg.access_token_expire_minutes if minutes is None else minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=mins)
    payload = {"sub": _require_user_id(user_id), "type": "identity", "exp": expire}
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_identity_token(token: str) -> str:
    """Return sub from an identity OR a (future) workspace-scoped access token."""
    cfg = get_auth_config()
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
        if payload.get("type") == "refresh":
            raise AuthenticationError("refresh token cannot be used as a bearer token")
        return _require_user_id(payload["sub"])
    except (JWTError, KeyError) as e:
        raise AuthenticationError(f"Invalid token: {e}") from e


def create_refresh_token(user_id: str) -> str:
    cfg = get_auth_config()
    expire = datetime.now(timezone.utc) + timedelta(days=cfg.refresh_token_expire_days)
    payload = {"sub": _require_user_id(user_id), "type": "refresh", "exp": expire}
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_refresh_token(token: str) -> str:
    cfg = get_auth_config()
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
        if payload.get("type") != "refresh":
            raise AuthenticationError("Not a refresh token")
        return _require_user_id(payload["sub"])
    except (JWTError, KeyError) as e:
        raise AuthenticationError(f"Invalid refresh token: {e}") from e


def create_access_token(
    user_id: str, workspace_id: str, role: str, minutes: Optional[int] = None
) -> str:
    """Workspace-scoped access token (claims: sub, workspace_id, role, type="access").

    Used for BOTH kinds of workspace: kind="personal" (auto-provisioned, minted
    on every login) and kind="company" (minted on create/switch) — the claim
    shape and validation are identical either way.

    SurrealDB record ids are strings like ``user:abc`` / ``workspace:xyz`` (not
    UUIDs), so sub/workspace_id are validated by prefix rather than as UUIDs.
    """
    sub = _require_user_id(user_id)
    if not isinstance(workspace_id, str) or not workspace_id.startswith("workspace:"):
        raise AuthenticationError("Access token workspace must be a workspace record id")
    cfg = get_auth_config()
    mins = cfg.access_token_expire_minutes if minutes is None else minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=mins)
    payload = {
        "sub": sub,
        "workspace_id": workspace_id,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_access_token(token: str) -> AuthContext:
    """Decode the full workspace-scoped claim set into a typed context.

    In P1 no access token is minted, so workspace_id/role are always None; P2's
    create_access_token populates them.
    """
    cfg = get_auth_config()
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
        if payload.get("type") == "refresh":
            raise AuthenticationError("refresh token cannot be used as a bearer token")
        return AuthContext(
            user_id=_require_user_id(payload["sub"]),
            workspace_id=payload.get("workspace_id"),
            role=payload.get("role"),
        )
    except (JWTError, KeyError) as e:
        raise AuthenticationError(f"Invalid token: {e}") from e
