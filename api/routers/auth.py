"""Authentication router for Open Notebook API (status endpoint).

Task 8 replaces this file with the full auth surface (register/login/google/
refresh/logout/me). Until then this only reports whether JWT auth is enabled.
"""

from fastapi import APIRouter

from api.auth_config import auth_enabled

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
async def get_auth_status():
    """Report whether JWT authentication is enabled (JWT_SECRET configured)."""
    enabled = auth_enabled()
    return {
        "auth_enabled": enabled,
        "message": "Authentication is required"
        if enabled
        else "Authentication is disabled",
    }
