"""Shared FastAPI auth dependencies for the multi-tenancy layer.

Introduced by P2; P6 later extends this module with require_workspace /
get_request_context / ScopedRepository and reuses require_role unchanged.
"""

from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import (
    AuthContext,
    decode_access_token,
    decode_identity_token,
)
from open_notebook.exceptions import AuthenticationError

# auto_error=False so a missing header raises our AuthenticationError (-> 401 via
# the global handler) instead of HTTPBearer's default 403.
_bearer = HTTPBearer(auto_error=False)


async def get_identity(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """user_id from an identity OR workspace-scoped access token (pre-workspace dep)."""
    if creds is None:
        raise AuthenticationError("Missing authorization header")
    try:
        return decode_identity_token(creds.credentials)
    except AuthenticationError:
        raise
    except Exception as e:  # jose errors etc.
        raise AuthenticationError(f"Invalid token: {e}")


async def get_auth_context(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthContext:
    """Require a workspace-scoped access token; 401 for an identity-only token."""
    if creds is None:
        raise AuthenticationError("Missing authorization header")
    try:
        ctx = decode_access_token(creds.credentials)
    except AuthenticationError:
        raise
    except Exception as e:
        raise AuthenticationError(f"Invalid token: {e}")
    if ctx.workspace_id is None or ctx.role is None:
        raise AuthenticationError("A workspace-scoped access token is required")
    return ctx


def require_role(*roles: str):
    """Dependency factory: 403 unless the caller's token role is in `roles`.

    The role is baked into the access token at create/switch time and never
    read from a client-supplied value. Used by P3+ (e.g. project create).
    Applies uniformly to a personal or company workspace token — a personal
    workspace's sole member always carries role="owner".
    """
    allowed = set(roles)

    async def _dep(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Requires role: {', '.join(sorted(allowed))}",
            )
        return ctx

    return _dep
