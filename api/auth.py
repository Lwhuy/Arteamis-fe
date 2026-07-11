from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from api.auth_config import auth_enabled
from api.security import decode_identity_token
from open_notebook.exceptions import AuthenticationError


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Authenticate every request from a JWT Bearer token.

    Behavior:
      * If no JWT_SECRET is configured, auth is disabled (dev parity with the
        old 'no password → open' behavior) — pass everything through.
      * Otherwise require `Authorization: Bearer <jwt>`; decode it via
        decode_identity_token (accepts identity OR future workspace-scoped access
        tokens); on success set request.state.user_id; on missing/invalid/expired
        token return 401 {"detail": ...} with WWW-Authenticate: Bearer.
      * Excluded paths and CORS preflight (OPTIONS) always pass through.
    """

    def __init__(self, app: ASGIApp, excluded_paths: Optional[list[str]] = None) -> None:
        super().__init__(app)
        self.excluded_paths: list[str] = excluded_paths or [
            "/",
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]

    @staticmethod
    def _unauthorized(detail: str) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": detail},
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Auth disabled (no secret configured) → open pass-through.
        if not auth_enabled():
            return await call_next(request)

        if request.url.path in self.excluded_paths:
            return await call_next(request)

        # OAuth provider callbacks arrive without a Bearer token; the CSRF state
        # (validated in connectors_service) is the protection here.
        if request.url.path.startswith("/api/connectors/") and request.url.path.endswith("/callback"):
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return self._unauthorized("Missing authorization header")

        try:
            scheme, credentials = auth_header.split(" ", 1)
            if scheme.lower() != "bearer":
                raise ValueError("Invalid authentication scheme")
        except ValueError:
            return self._unauthorized("Invalid authorization header format")

        try:
            user_id = decode_identity_token(credentials)
        except AuthenticationError:
            return self._unauthorized("Invalid or expired token")

        request.state.user_id = user_id
        return await call_next(request)
