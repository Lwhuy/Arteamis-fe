# P1 — Real Auth + Users Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shared-password gate (`PasswordAuthMiddleware`) with real per-user accounts and JWT auth supporting BOTH email+password AND "Continue with Google", ending at an authenticated user holding an identity token (no workspace yet). Personal-workspace auto-provisioning happens in P2, not P1.

**Architecture:** New identity-plane SurrealDB tables (`user`, `auth_identity`) via migration 19; token helpers in `api/security.py` (identity/refresh tokens + `AuthContext`); a thin `api/routers/auth.py` over `api/auth_service.py` + `open_notebook/domain/user.py`; a `JWTAuthMiddleware` that authenticates every request from a Bearer token and populates `request.state.user_id`. Frontend rewrites `auth-store`, `LoginForm`, adds a signup page, and a one-shot 401→refresh interceptor.

**Tech Stack:** Next.js 16 (App Router, TanStack Query, Zustand, axios), FastAPI, SurrealDB, argon2 (`argon2-cffi`), python-jose (HS256), httpx (Google OAuth), Pydantic v2, vitest + Testing Library.

**Spec:** docs/superpowers/specs/2026-07-11-p1-auth-users-design.md
**Depends on:** nothing (foundation phase) · **Branch:** feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB/AI call is awaited (no sync DB access). CPU-bound argon2 hashing/verify runs via `await asyncio.to_thread(...)`.
- All frontend HTTP goes through the single axios `apiClient` (frontend/src/lib/api/client.ts) — never a 2nd instance. (Exceptions kept as-is: `checkAuthRequired` hits the public `/api/auth/status` via `fetch`; the 401 interceptor's refresh uses a raw `fetch(..., {credentials:'include'})` to carry the cookie; the Google flow is a full-page `window.location` navigation.)
- i18n MANDATORY: every UI string via `t('section.key')`; add the key to ALL locales in frontend/src/lib/locales/. NOTE: `frontend/src/lib/locales/index.test.ts` (parity test) enforces that EVERY locale in the `resources` map has exactly the en-US key set. There are 14 locales in `resources` (`zh-CN, en-US, zh-TW, pt-BR, ja-JP, it-IT, fr-FR, ru-RU, bn-IN, ca-ES, es-ES, de-DE, pl-PL, tr-TR`). To keep `npm run test` green, every new key MUST be added to ALL 14 files. The 7 enforced locales (`en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN`) get real translations; the other 7 get English fallback values (acceptable — silent en-US fallback). The "Unused Key Detection" test also requires every en-US leaf key to appear in a source file, so every new key must be referenced by a component.
- New SurrealDB schema = new migration pair open_notebook/database/migrations/N.surrealql + N_down.surrealql, registered in `AsyncMigrationManager.__init__` so it runs on startup. This phase = migration 19.
- Physical SurrealDB table stays `notebook` (untouched in P1). No `notebook`→`project` repurposing here (that is P3).
- Tokens: identity token (`sub`, `type:"identity"`) is the P1 Bearer. Workspace-scoped access token (`sub`, `workspace_id`, `role`) + refresh cookie: `create_access_token` is a P2 stub; refresh cookie + `/auth/refresh` are live in P1. Personal-workspace auto-provisioning (attaching the user's default personal workspace) is done in P2, not P1 — P1's register/login leaves the user authenticated on an identity token only, and P1 does not add any workspace tables.
- Backend tests: `uv run pytest tests/`. Frontend (inside `frontend/`): `npm run lint`, `npm run test`, `npm run build`.
- Backend error contract: raise typed exceptions from `open_notebook.exceptions` (global handlers in `api/main.py` map them). Body is `{"detail": "..."}`. No bare `HTTPException` for domain errors.
- pytest-asyncio is in "strict" mode (no `asyncio_mode` configured): every `async def` test needs `@pytest.mark.asyncio`.
---

## Task Overview (14 tasks)

Backend: 1 deps+migration · 2 auth_config · 3 security · 4 domain/user · 5 google · 6 auth_service · 7 middleware+main · 8 models+router.
Frontend: 9 auth-store+types · 10 client 401-refresh · 11 use-auth · 12 LoginForm · 13 SignupForm+page · 14 i18n (14 locales).

---

### Task 1: Dependencies + Migration 19 (user, auth_identity)

**Files:**
- Modify: `pyproject.toml` (add `argon2-cffi`, `python-jose[cryptography]`, `email-validator` to `[project].dependencies`)
- Create: `open_notebook/database/migrations/19.surrealql`
- Create: `open_notebook/database/migrations/19_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (append migration 19 to both lists)
- Test: `tests/test_migration_19_registration.py`

**Interfaces:**
- Consumes: `AsyncMigrationManager` (open_notebook/database/async_migrate.py), `AsyncMigration.from_file`.
- Produces: migration 19 registered (up_migrations length becomes 19); `user`/`auth_identity` schema available after startup migration; `jose`, `argon2`, `email_validator` importable.

- [ ] **Step 1: Write the failing test** — `tests/test_migration_19_registration.py`:
```python
import importlib

import pytest


def test_migration_19_is_registered_in_both_lists():
    """Migration 19 must be appended to up and down lists (hard-coded, not auto-discovered)."""
    from open_notebook.database.async_migrate import AsyncMigrationManager

    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 19
    assert len(manager.down_migrations) == 19


def test_migration_19_defines_identity_tables():
    """The cleaned SQL for migration 19 defines the user + auth_identity tables and unique indexes."""
    from open_notebook.database.async_migrate import AsyncMigration

    up = AsyncMigration.from_file("open_notebook/database/migrations/19.surrealql")
    sql = up.sql
    assert "DEFINE TABLE IF NOT EXISTS user SCHEMAFULL" in sql
    assert "DEFINE TABLE IF NOT EXISTS auth_identity SCHEMAFULL" in sql
    assert "DEFINE INDEX IF NOT EXISTS idx_user_email ON TABLE user FIELDS email UNIQUE" in sql
    assert "idx_auth_identity_unique" in sql
    # The cleaner joins with spaces and drops comment lines: no stray "--" survives.
    assert "--" not in sql

    down = AsyncMigration.from_file("open_notebook/database/migrations/19_down.surrealql")
    assert "REMOVE TABLE IF EXISTS auth_identity" in down.sql
    assert "REMOVE TABLE IF EXISTS user" in down.sql


@pytest.mark.parametrize("module_name", ["jose", "argon2", "email_validator"])
def test_new_dependencies_importable(module_name):
    """The three new packages must be installed so later tasks can import them."""
    assert importlib.import_module(module_name) is not None
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_migration_19_registration.py -q` — Expected: FAIL (FileNotFoundError for `19.surrealql` / `AssertionError: assert 18 == 19` / `ModuleNotFoundError: No module named 'jose'`).

- [ ] **Step 3: Write minimal implementation** —

`pyproject.toml` — add these three lines inside the `[project]` `dependencies = [ ... ]` list (place them right after the existing `"httpx[socks]>=0.27.0",` line):
```toml
    "argon2-cffi>=23.1.0",
    "python-jose[cryptography]>=3.3.0",
    "email-validator>=2.1.0",
```

Then install: `uv sync`.

`open_notebook/database/migrations/19.surrealql`:
```surql
-- Migration 19: Identity plane — real users + auth identities (P1 auth).

DEFINE TABLE IF NOT EXISTS user SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS email ON TABLE user TYPE string;
DEFINE FIELD IF NOT EXISTS display_name ON TABLE user TYPE option<string>;
DEFINE FIELD IF NOT EXISTS password_hash ON TABLE user TYPE option<string>;
DEFINE FIELD IF NOT EXISTS avatar_url ON TABLE user TYPE option<string>;
DEFINE FIELD IF NOT EXISTS created ON user DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON user DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_user_email ON TABLE user FIELDS email UNIQUE;

DEFINE TABLE IF NOT EXISTS auth_identity SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS provider ON TABLE auth_identity TYPE string ASSERT $value IN ["email_password", "google"];
DEFINE FIELD IF NOT EXISTS provider_subject ON TABLE auth_identity TYPE string;
DEFINE FIELD IF NOT EXISTS user ON TABLE auth_identity TYPE record<user>;
DEFINE FIELD IF NOT EXISTS email ON TABLE auth_identity TYPE option<string>;
DEFINE FIELD IF NOT EXISTS last_login_at ON TABLE auth_identity TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS created ON auth_identity DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON auth_identity DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_auth_identity_unique ON TABLE auth_identity FIELDS provider, provider_subject UNIQUE;
DEFINE INDEX IF NOT EXISTS idx_auth_identity_user ON TABLE auth_identity FIELDS user;
```
> NOTE on the cleaner (`AsyncMigration.from_file`): it drops lines beginning with `--` and joins the rest with spaces. Every statement above is on ONE line and `;`-terminated, and there is no code after an inline `--`. The `ASSERT $value IN [...]` clause must stay on the same line as its `DEFINE FIELD`.

`open_notebook/database/migrations/19_down.surrealql`:
```surql
REMOVE TABLE IF EXISTS auth_identity;
REMOVE TABLE IF EXISTS user;
```

`open_notebook/database/async_migrate.py` — in `AsyncMigrationManager.__init__`, append to `self.up_migrations` (after the `18.surrealql` entry, before the closing `]`):
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/19.surrealql"
            ),
```
and append to `self.down_migrations` (after the `18_down.surrealql` entry, before the closing `]`):
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/19_down.surrealql"
            ),
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_migration_19_registration.py -q` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add pyproject.toml uv.lock open_notebook/database/migrations/19.surrealql open_notebook/database/migrations/19_down.surrealql open_notebook/database/async_migrate.py tests/test_migration_19_registration.py && git commit -m "P1: add auth deps + migration 19 (user, auth_identity)"`

---

### Task 2: `api/auth_config.py` — auth env config

**Files:**
- Create: `api/auth_config.py`
- Test: `tests/test_auth_config.py`

**Interfaces:**
- Produces: `AuthConfig` dataclass + `get_auth_config() -> AuthConfig` with fields `jwt_secret: str | None`, `jwt_algorithm: str`, `access_token_expire_minutes: int`, `refresh_token_expire_days: int`, `refresh_cookie_name: str`, `cookie_secure: bool`, `cookie_samesite: str`, `google_client_id: str | None`, `google_client_secret: str | None`, `google_redirect_uri: str`, `frontend_url: str`; and `auth_enabled() -> bool`. `get_auth_config()` reads env on every call (so tests can `monkeypatch.setenv` then re-read).

- [ ] **Step 1: Write the failing test** — `tests/test_auth_config.py`:
```python
import pytest


def test_defaults_when_only_secret_set(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("JWT_ALGORITHM", raising=False)
    monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
    monkeypatch.delenv("REFRESH_COOKIE_NAME", raising=False)
    from api.auth_config import get_auth_config

    cfg = get_auth_config()
    assert cfg.jwt_secret == "test-secret"
    assert cfg.jwt_algorithm == "HS256"
    assert cfg.access_token_expire_minutes == 15
    assert cfg.refresh_token_expire_days == 30
    assert cfg.refresh_cookie_name == "arteamis_refresh"
    assert cfg.cookie_secure is True
    assert cfg.cookie_samesite == "lax"
    assert cfg.google_redirect_uri == "http://localhost:5055/api/auth/google/callback"
    assert cfg.frontend_url == "http://localhost:3000"


def test_auth_disabled_when_no_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_FILE", raising=False)
    from api.auth_config import auth_enabled, get_auth_config

    assert get_auth_config().jwt_secret is None
    assert auth_enabled() is False


def test_cookie_secure_false_and_overrides(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "s")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "5")
    from api.auth_config import get_auth_config

    cfg = get_auth_config()
    assert cfg.cookie_secure is False
    assert cfg.access_token_expire_minutes == 5
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_auth_config.py -q` — Expected: FAIL (`ModuleNotFoundError: No module named 'api.auth_config'`).

- [ ] **Step 3: Write minimal implementation** — `api/auth_config.py`:
```python
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
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_auth_config.py -q` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add api/auth_config.py tests/test_auth_config.py && git commit -m "P1: add api/auth_config.py"`

---

### Task 3: `api/security.py` — token helpers + AuthContext

**Files:**
- Create: `api/security.py`
- Test: `tests/test_security_tokens.py`

**Interfaces:**
- Consumes: `get_auth_config()` (Task 2), `AuthenticationError` (open_notebook/exceptions.py).
- Produces:
  - `create_identity_token(user_id: str) -> str`
  - `decode_identity_token(token: str) -> str` (returns `sub`; raises `AuthenticationError`)
  - `create_refresh_token(user_id: str) -> str`
  - `decode_refresh_token(token: str) -> str` (raises `AuthenticationError`)
  - `create_access_token(user_id, workspace_id, role, minutes=None) -> str` (raises `NotImplementedError` in P1)
  - `AuthContext` dataclass (`user_id: str`, `workspace_id: str | None`, `role: str | None`)
  - `decode_access_token(token: str) -> AuthContext`

- [ ] **Step 1: Write the failing test** — `tests/test_security_tokens.py`:
```python
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from open_notebook.exceptions import AuthenticationError


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    monkeypatch.setenv("REFRESH_TOKEN_EXPIRE_DAYS", "30")


def test_identity_token_roundtrip():
    from api.security import create_identity_token, decode_identity_token

    token = create_identity_token("user:abc123")
    assert decode_identity_token(token) == "user:abc123"
    claims = jwt.decode(token, "unit-test-secret", algorithms=["HS256"])
    assert claims["type"] == "identity"
    assert claims["sub"] == "user:abc123"


def test_decode_identity_rejects_non_user_sub():
    from api.security import decode_identity_token

    bad = jwt.encode({"sub": "notauser", "type": "identity"}, "unit-test-secret", algorithm="HS256")
    with pytest.raises(AuthenticationError):
        decode_identity_token(bad)


def test_decode_identity_rejects_expired():
    from api.security import decode_identity_token

    expired = jwt.encode(
        {"sub": "user:x", "type": "identity", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        "unit-test-secret",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationError):
        decode_identity_token(expired)


def test_decode_identity_rejects_garbage():
    from api.security import decode_identity_token

    with pytest.raises(AuthenticationError):
        decode_identity_token("not-a-jwt")


def test_refresh_token_roundtrip_and_type_guard():
    from api.security import (
        create_identity_token,
        create_refresh_token,
        decode_refresh_token,
    )

    rt = create_refresh_token("user:abc")
    assert decode_refresh_token(rt) == "user:abc"
    # An identity token must NOT be accepted by the refresh decoder.
    it = create_identity_token("user:abc")
    with pytest.raises(AuthenticationError):
        decode_refresh_token(it)


def test_create_access_token_is_p2_stub():
    from api.security import create_access_token

    with pytest.raises(NotImplementedError):
        create_access_token("user:abc", "workspace:1", "owner")


def test_decode_access_token_returns_context_with_none_workspace_in_p1():
    from api.security import AuthContext, create_identity_token, decode_access_token

    ctx = decode_access_token(create_identity_token("user:abc"))
    assert isinstance(ctx, AuthContext)
    assert ctx.user_id == "user:abc"
    assert ctx.workspace_id is None
    assert ctx.role is None
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_security_tokens.py -q` — Expected: FAIL (`ModuleNotFoundError: No module named 'api.security'`).

- [ ] **Step 3: Write minimal implementation** — `api/security.py`:
```python
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
    """Workspace-scoped access token. Implemented in P2 (workspaces/memberships)."""
    raise NotImplementedError(
        "create_access_token (workspace-scoped) is implemented in P2. "
        "P1 issues identity tokens only via create_identity_token."
    )


def decode_access_token(token: str) -> AuthContext:
    """Decode the full workspace-scoped claim set into a typed context.

    In P1 no access token is minted, so workspace_id/role are always None; P2's
    create_access_token populates them.
    """
    cfg = get_auth_config()
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
        return AuthContext(
            user_id=_require_user_id(payload["sub"]),
            workspace_id=payload.get("workspace_id"),
            role=payload.get("role"),
        )
    except (JWTError, KeyError) as e:
        raise AuthenticationError(f"Invalid token: {e}") from e
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_security_tokens.py -q` — Expected: PASS (7 passed).

- [ ] **Step 5: Commit** — `git add api/security.py tests/test_security_tokens.py && git commit -m "P1: add api/security.py token helpers + AuthContext"`

---

### Task 4: `open_notebook/domain/user.py` — User + AuthIdentity + DuplicateResourceError

**Files:**
- Create: `open_notebook/domain/user.py`
- Modify: `open_notebook/exceptions.py` (add `DuplicateResourceError`)
- Test: `tests/test_user_domain.py`

**Interfaces:**
- Consumes: `ObjectModel` (open_notebook/domain/base.py), `repo_query`/`ensure_record_id` (repository.py).
- Produces:
  - `class User(ObjectModel)` with `table_name="user"`; fields `email: str`, `display_name: Optional[str]`, `password_hash: Optional[str]`, `avatar_url: Optional[str]`; `nullable_fields={"password_hash","display_name","avatar_url"}`.
    - `@staticmethod normalize_email(raw: str) -> str`
    - `async set_password(self, raw: str) -> None`
    - `async verify_password(self, raw: str) -> bool`
    - `@classmethod async get_by_email(cls, email: str) -> Optional[User]`
    - `@classmethod async get_by_identity(cls, provider: str, subject: str) -> Optional[User]`
    - `@classmethod async upsert_with_identity(cls, provider, subject, email, display_name=None) -> User`
  - `class AuthIdentity(ObjectModel)` with `table_name="auth_identity"`; fields `provider: Literal["email_password","google"]`, `provider_subject: str`, `user: str`, `email: Optional[str]`, `last_login_at: Optional[datetime]`.
  - `DuplicateResourceError(OpenNotebookError)` in exceptions.py.

- [ ] **Step 1: Write the failing test** — `tests/test_user_domain.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.user import AuthIdentity, User
from open_notebook.exceptions import InvalidInputError


def test_normalize_email_lowercases_and_strips():
    assert User.normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_email_field_validator_lowercases():
    u = User(email="  Foo@Bar.com ")
    assert u.email == "foo@bar.com"


def test_email_rejects_empty():
    with pytest.raises((InvalidInputError, ValueError)):
        User(email="   ")


@pytest.mark.asyncio
async def test_set_and_verify_password_argon2():
    u = User(email="a@b.com")
    await u.set_password("hunter2-strong")
    assert u.password_hash is not None
    assert u.password_hash != "hunter2-strong"
    assert u.password_hash.startswith("$argon2")
    assert await u.verify_password("hunter2-strong") is True
    assert await u.verify_password("wrong-password") is False


@pytest.mark.asyncio
async def test_verify_password_false_when_no_hash():
    u = User(email="google@only.com")  # Google-only account, password_hash None
    assert u.password_hash is None
    assert await u.verify_password("anything") is False


@pytest.mark.asyncio
async def test_get_by_email_queries_lowercased():
    with patch("open_notebook.domain.user.repo_query", new=AsyncMock(return_value=[])) as q:
        result = await User.get_by_email("MixedCase@Example.com")
    assert result is None
    q.assert_awaited_once()
    _, kwargs_or_vars = q.await_args.args
    assert kwargs_or_vars == {"email": "mixedcase@example.com"}


@pytest.mark.asyncio
async def test_auth_identity_prepare_save_data_coerces_user_to_recordid():
    from surrealdb import RecordID

    ident = AuthIdentity(
        provider="google", provider_subject="sub-123", user="user:abc", email="a@b.com"
    )
    data = ident._prepare_save_data()
    assert isinstance(data["user"], RecordID)
    assert str(data["user"]) == "user:abc"


@pytest.mark.asyncio
async def test_upsert_with_identity_existing_identity_returns_user():
    existing = User(id="user:existing", email="a@b.com")
    with patch.object(User, "get_by_identity", new=AsyncMock(return_value=existing)) as gbi, patch(
        "open_notebook.domain.user.repo_query", new=AsyncMock(return_value=[])
    ) as q:
        result = await User.upsert_with_identity("google", "sub-1", "a@b.com", "A")
    assert result is existing
    gbi.assert_awaited_once_with("google", "sub-1")
    # An UPDATE to stamp last_login_at is issued; no new user/identity saved.
    q.assert_awaited()


@pytest.mark.asyncio
async def test_upsert_with_identity_new_user_creates_user_and_identity():
    saved_users = []
    saved_idents = []

    async def fake_user_save(self):
        self.id = "user:new"
        saved_users.append(self)

    async def fake_ident_save(self):
        self.id = "auth_identity:new"
        saved_idents.append(self)

    with patch.object(User, "get_by_identity", new=AsyncMock(return_value=None)), patch.object(
        User, "get_by_email", new=AsyncMock(return_value=None)
    ), patch.object(User, "save", new=fake_user_save), patch.object(
        AuthIdentity, "save", new=fake_ident_save
    ):
        result = await User.upsert_with_identity("google", "sub-9", "New@B.com", "New")

    assert result.id == "user:new"
    assert result.email == "new@b.com"
    assert len(saved_users) == 1
    assert len(saved_idents) == 1
    assert saved_idents[0].user == "user:new"
    assert saved_idents[0].provider == "google"
    assert saved_idents[0].provider_subject == "sub-9"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_user_domain.py -q` — Expected: FAIL (`ModuleNotFoundError: No module named 'open_notebook.domain.user'`).

- [ ] **Step 3: Write minimal implementation** —

`open_notebook/exceptions.py` — append at the end of the file:
```python
class DuplicateResourceError(OpenNotebookError):
    """Raised when creating a resource that violates a uniqueness constraint
    (e.g. an already-registered email or an existing workspace slug)."""

    pass
```

`open_notebook/domain/user.py`:
```python
import asyncio
from datetime import datetime, timezone
from typing import ClassVar, Literal, Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from loguru import logger
from pydantic import field_validator

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import DatabaseOperationError, InvalidInputError

# Module-level hasher: argon2 defaults are memory-hard and safe. Reused across
# calls (creating a PasswordHasher per hash is wasteful). Hash/verify are
# CPU-bound and synchronous, so callers run them via asyncio.to_thread.
_PH = PasswordHasher()


class User(ObjectModel):
    table_name: ClassVar[str] = "user"
    nullable_fields: ClassVar[set[str]] = {"password_hash", "display_name", "avatar_url"}
    email: str
    display_name: Optional[str] = None
    password_hash: Optional[str] = None
    avatar_url: Optional[str] = None

    @staticmethod
    def normalize_email(raw: str) -> str:
        return (raw or "").strip().lower()

    @field_validator("email")
    @classmethod
    def _normalize_email_field(cls, v: str) -> str:
        normalized = User.normalize_email(v)
        if not normalized:
            raise InvalidInputError("Email cannot be empty")
        return normalized

    async def set_password(self, raw: str) -> None:
        if not raw:
            raise InvalidInputError("Password cannot be empty")
        self.password_hash = await asyncio.to_thread(_PH.hash, raw)

    async def verify_password(self, raw: str) -> bool:
        if not self.password_hash:
            return False  # Google-only account: no password set.
        try:
            await asyncio.to_thread(_PH.verify, self.password_hash, raw)
            return True
        except VerifyMismatchError:
            return False
        except Exception as e:
            logger.warning(f"Password verify error for user {self.id}: {e}")
            return False

    @classmethod
    async def get_by_email(cls, email: str) -> Optional["User"]:
        normalized = cls.normalize_email(email)
        result = await repo_query(
            "SELECT * FROM user WHERE email = $email", {"email": normalized}
        )
        return cls(**result[0]) if result else None

    @classmethod
    async def get_by_identity(cls, provider: str, subject: str) -> Optional["User"]:
        result = await repo_query(
            """
            SELECT * FROM user WHERE id IN (
                SELECT VALUE user FROM auth_identity
                WHERE provider = $provider AND provider_subject = $subject
            )
            """,
            {"provider": provider, "subject": subject},
        )
        return cls(**result[0]) if result else None

    @classmethod
    async def upsert_with_identity(
        cls,
        provider: str,
        subject: str,
        email: str,
        display_name: Optional[str] = None,
    ) -> "User":
        """Find-or-create the user for this identity, then ensure the link.

        Matching order: (provider, subject) identity → user by email → new user.
        Keeps ONE account when the same verified email signs in via both Google
        and email+password.
        """
        normalized = cls.normalize_email(email)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # 1. Existing identity → stamp last_login and return its user.
        existing = await cls.get_by_identity(provider, subject)
        if existing is not None:
            try:
                await repo_query(
                    """
                    UPDATE auth_identity SET last_login_at = time::now()
                    WHERE provider = $provider AND provider_subject = $subject
                    """,
                    {"provider": provider, "subject": subject},
                )
            except Exception as e:
                logger.warning(f"Failed to stamp last_login_at: {e}")
            return existing

        # 2. Existing user by email, else 3. create a new user.
        user = await cls.get_by_email(normalized)
        if user is None:
            user = cls(email=normalized, display_name=display_name)
            await user.save()

        # Link the new identity.
        identity = AuthIdentity(
            provider=provider,
            provider_subject=subject,
            user=user.id or "",
            email=normalized,
            last_login_at=datetime.now(timezone.utc),
        )
        try:
            await identity.save()
        except Exception as e:
            logger.error(f"Failed to link auth_identity for user {user.id}: {e}")
            raise DatabaseOperationError(e)
        return user


class AuthIdentity(ObjectModel):
    table_name: ClassVar[str] = "auth_identity"
    nullable_fields: ClassVar[set[str]] = {"email", "last_login_at"}
    provider: Literal["email_password", "google"]
    provider_subject: str
    user: str
    email: Optional[str] = None
    last_login_at: Optional[datetime] = None

    def _prepare_save_data(self) -> dict:
        """Coerce the `user` link to a RecordID so the SCHEMAFULL record<user>
        field validates (mirrors Source.command handling)."""
        data = super()._prepare_save_data()
        if data.get("user") is not None:
            data["user"] = ensure_record_id(data["user"])
        return data
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_user_domain.py -q` — Expected: PASS (9 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/domain/user.py open_notebook/exceptions.py tests/test_user_domain.py && git commit -m "P1: add User + AuthIdentity domain models + DuplicateResourceError"`

---

### Task 5: `open_notebook/auth/google.py` — OAuth code exchange

**Files:**
- Create: `open_notebook/auth/__init__.py`
- Create: `open_notebook/auth/google.py`
- Test: `tests/test_google_oauth.py`

**Interfaces:**
- Consumes: `get_auth_config()` (Task 2), `httpx`.
- Produces:
  - `build_authorize_url(state: str) -> str`
  - `async exchange_code_for_userinfo(code: str) -> dict` (returns Google userinfo dict with `sub`, `email`, `email_verified`, `name`).

- [ ] **Step 1: Write the failing test** — `tests/test_google_oauth.py`:
```python
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-abc")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-xyz")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:5055/api/auth/google/callback")


def test_build_authorize_url_contains_expected_params():
    from open_notebook.auth.google import build_authorize_url

    url = build_authorize_url("state-token-123")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-abc" in url
    assert "scope=openid+email+profile" in url
    assert "state=state-token-123" in url
    assert "prompt=select_account" in url
    assert "response_type=code" in url


@pytest.mark.asyncio
async def test_exchange_code_for_userinfo(monkeypatch):
    from open_notebook.auth import google as google_mod

    token_resp = MagicMock()
    token_resp.raise_for_status = MagicMock()
    token_resp.json = MagicMock(return_value={"access_token": "ya29.token"})

    info_resp = MagicMock()
    info_resp.raise_for_status = MagicMock()
    info_resp.json = MagicMock(
        return_value={
            "sub": "google-sub-1",
            "email": "user@gmail.com",
            "email_verified": True,
            "name": "User Name",
        }
    )

    client = AsyncMock()
    client.post = AsyncMock(return_value=token_resp)
    client.get = AsyncMock(return_value=info_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(google_mod.httpx, "AsyncClient", MagicMock(return_value=client))

    info = await google_mod.exchange_code_for_userinfo("auth-code-1")
    assert info["sub"] == "google-sub-1"
    assert info["email"] == "user@gmail.com"
    assert info["email_verified"] is True
    client.post.assert_awaited_once()
    client.get.assert_awaited_once()
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_google_oauth.py -q` — Expected: FAIL (`ModuleNotFoundError: No module named 'open_notebook.auth'`).

- [ ] **Step 3: Write minimal implementation** —

`open_notebook/auth/__init__.py`:
```python
```
(empty file — makes `open_notebook.auth` a package.)

`open_notebook/auth/google.py`:
```python
"""Google OAuth 2.0 authorization-code exchange (port of arteamis-system).

build_authorize_url starts the flow; exchange_code_for_userinfo completes it and
returns the verified profile. Tests monkeypatch exchange_code_for_userinfo.
"""

import urllib.parse

import httpx

from api.auth_config import get_auth_config

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def build_authorize_url(state: str) -> str:
    cfg = get_auth_config()
    params = {
        "client_id": cfg.google_client_id or "",
        "redirect_uri": cfg.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{_AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_userinfo(code: str) -> dict:
    """Exchange an authorization code for the user's Google profile.

    Returns a dict with at least `sub`, `email`, `email_verified`, and `name`.
    Raises httpx.HTTPStatusError on a failed exchange.
    """
    cfg = get_auth_config()
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            _TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": cfg.google_client_id or "",
                "client_secret": cfg.google_client_secret or "",
                "redirect_uri": cfg.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        info_resp = await client.get(
            _USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
        info_resp.raise_for_status()
        return info_resp.json()
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_google_oauth.py -q` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/auth/__init__.py open_notebook/auth/google.py tests/test_google_oauth.py && git commit -m "P1: add Google OAuth code-exchange helper"`

---

### Task 6: `api/auth_service.py` — register / login / session payload

**Files:**
- Create: `api/auth_service.py`
- Test: `tests/test_auth_service.py`

**Interfaces:**
- Consumes: `User` (Task 4), `DuplicateResourceError`/`AuthenticationError` (exceptions), `AuthIdentity` (Task 4), `create_identity_token` (Task 3).
- Produces:
  - `async register(email: str, password: str, display_name: Optional[str]) -> User`
  - `async login(email: str, password: str) -> User`
  - `build_session_payload(user: User) -> dict`

- [ ] **Step 1: Write the failing test** — `tests/test_auth_service.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.user import User
from open_notebook.exceptions import AuthenticationError, DuplicateResourceError


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "svc-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email():
    from api import auth_service

    with patch.object(User, "get_by_email", new=AsyncMock(return_value=User(id="user:1", email="a@b.com"))):
        with pytest.raises(DuplicateResourceError):
            await auth_service.register("a@b.com", "password123", "A")


@pytest.mark.asyncio
async def test_register_creates_user_and_identity():
    from api import auth_service

    saved_idents = []

    async def fake_user_save(self):
        self.id = "user:new"

    async def fake_ident_save(self):
        self.id = "auth_identity:new"
        saved_idents.append(self)

    from open_notebook.domain.user import AuthIdentity

    with patch.object(User, "get_by_email", new=AsyncMock(return_value=None)), patch.object(
        User, "save", new=fake_user_save
    ), patch.object(AuthIdentity, "save", new=fake_ident_save):
        user = await auth_service.register("New@B.com", "password123", "New")

    assert user.id == "user:new"
    assert user.email == "new@b.com"
    assert user.password_hash is not None and user.password_hash.startswith("$argon2")
    assert len(saved_idents) == 1
    assert saved_idents[0].provider == "email_password"
    assert saved_idents[0].provider_subject == "new@b.com"


@pytest.mark.asyncio
async def test_login_success_returns_user():
    from api import auth_service

    user = User(id="user:1", email="a@b.com")
    await user.set_password("correct-horse")
    with patch.object(User, "get_by_email", new=AsyncMock(return_value=user)):
        result = await auth_service.login("a@b.com", "correct-horse")
    assert result is user


@pytest.mark.asyncio
async def test_login_wrong_password_raises_generic():
    from api import auth_service

    user = User(id="user:1", email="a@b.com")
    await user.set_password("correct-horse")
    with patch.object(User, "get_by_email", new=AsyncMock(return_value=user)):
        with pytest.raises(AuthenticationError):
            await auth_service.login("a@b.com", "wrong")


@pytest.mark.asyncio
async def test_login_unknown_email_raises_same_error():
    from api import auth_service

    with patch.object(User, "get_by_email", new=AsyncMock(return_value=None)):
        with pytest.raises(AuthenticationError):
            await auth_service.login("nobody@b.com", "whatever")


def test_build_session_payload_shape():
    from api import auth_service
    from api.security import decode_identity_token

    user = User(id="user:1", email="a@b.com", display_name="A")
    payload = auth_service.build_session_payload(user)
    assert payload["token_type"] == "bearer"
    assert payload["needs_onboarding"] is True
    assert payload["active_workspace_id"] is None
    assert payload["memberships"] == []
    assert payload["user"] == {"id": "user:1", "email": "a@b.com", "display_name": "A"}
    assert decode_identity_token(payload["access_token"]) == "user:1"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_auth_service.py -q` — Expected: FAIL (`ModuleNotFoundError: No module named 'api.auth_service'`).

- [ ] **Step 3: Write minimal implementation** — `api/auth_service.py`:
```python
"""Auth business logic (routers stay thin, per api/AGENTS.md).

register/login operate on the identity plane only; workspace selection and
workspace-scoped tokens arrive in P2 (build_session_payload's workspace-aware
branch). Personal-workspace auto-provisioning is done in P2, not P1 — P1's
register/login leaves the user authenticated on an identity token only.
"""

from typing import Optional

from api.security import create_identity_token
from open_notebook.domain.user import AuthIdentity, User
from open_notebook.exceptions import AuthenticationError, DuplicateResourceError

# Generic message: never reveal whether the email exists or the password was
# the wrong part (prevents user enumeration).
_INVALID_CREDENTIALS = "Invalid email or password"


async def register(email: str, password: str, display_name: Optional[str]) -> User:
    normalized = User.normalize_email(email)
    if await User.get_by_email(normalized) is not None:
        raise DuplicateResourceError("Email already registered")

    user = User(email=normalized, display_name=display_name)
    await user.set_password(password)
    await user.save()

    identity = AuthIdentity(
        provider="email_password",
        provider_subject=normalized,
        user=user.id or "",
        email=normalized,
    )
    await identity.save()
    return user


async def login(email: str, password: str) -> User:
    user = await User.get_by_email(email)
    if user is None:
        raise AuthenticationError(_INVALID_CREDENTIALS)
    if not await user.verify_password(password):
        raise AuthenticationError(_INVALID_CREDENTIALS)
    return user


def build_session_payload(user: User) -> dict:
    """The body returned after any successful register/login/refresh.

    P1 always issues an identity token (no workspace yet). P2 replaces the
    needs_onboarding/memberships/active_workspace_id surface with the real,
    workspace-aware branch WITHOUT changing this response shape — this is
    where P2 attaches the user's auto-provisioned default personal workspace
    (not done in P1).
    """
    return {
        "access_token": create_identity_token(user.id or ""),
        "token_type": "bearer",
        "needs_onboarding": True,
        "active_workspace_id": None,
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
        },
        "memberships": [],
    }
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_auth_service.py -q` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add api/auth_service.py tests/test_auth_service.py && git commit -m "P1: add api/auth_service.py (register/login/session payload)"`

---

### Task 7: `JWTAuthMiddleware` + `api/main.py` wiring + `/auth/status` rework

**Files:**
- Modify: `api/auth.py` (remove `PasswordAuthMiddleware`, add `JWTAuthMiddleware`)
- Modify: `api/main.py` (swap middleware; register `DuplicateResourceError` handler; import)
- Modify: `api/routers/auth.py` (rework `/auth/status` to report `bool(JWT_SECRET)`)
- Test: `tests/test_jwt_middleware.py`

**Interfaces:**
- Consumes: `decode_identity_token` (Task 3), `auth_enabled`/`get_auth_config` (Task 2), `DuplicateResourceError` (Task 4).
- Produces: `JWTAuthMiddleware` populating `request.state.user_id`; `/api/auth/status` returning `{"auth_enabled": bool, "message": str}`; a 409 handler for `DuplicateResourceError`.

> NOTE: `api/routers/auth.py` is fully rewritten in Task 8. In THIS task only its `/auth/status` handler is changed (the file still currently contains only `get_auth_status`). Keep the change minimal; Task 8 replaces the whole file including a status endpoint identical to the one written here.

- [ ] **Step 1: Write the failing test** — `tests/test_jwt_middleware.py`:
```python
import importlib

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.auth import JWTAuthMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(JWTAuthMiddleware, excluded_paths=["/public"])

    @app.get("/public")
    async def public():
        return {"ok": True}

    @app.get("/private")
    async def private(request: Request):
        return {"user_id": getattr(request.state, "user_id", None)}

    return app


def test_open_passthrough_when_no_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_FILE", raising=False)
    client = TestClient(_build_app())
    assert client.get("/private").status_code == 200


def test_missing_token_is_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    client = TestClient(_build_app())
    resp = client.get("/private")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Missing authorization header"}
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_valid_identity_token_sets_user_id(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    from api.security import create_identity_token

    token = create_identity_token("user:abc")
    client = TestClient(_build_app())
    resp = client.get("/private", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "user:abc"}


def test_invalid_token_is_401(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    client = TestClient(_build_app())
    resp = client.get("/private", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


def test_excluded_path_skips_auth(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "mw-secret")
    client = TestClient(_build_app())
    assert client.get("/public").status_code == 200


def test_password_middleware_is_gone():
    import api.auth as auth_mod

    importlib.reload(auth_mod)
    assert not hasattr(auth_mod, "PasswordAuthMiddleware")
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_jwt_middleware.py -q` — Expected: FAIL (`ImportError: cannot import name 'JWTAuthMiddleware' from 'api.auth'`).

- [ ] **Step 3: Write minimal implementation** —

Replace the ENTIRE contents of `api/auth.py` with:
```python
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
```

`api/main.py` — apply these edits:

(a) Replace the import on line 16:
```python
from api.auth import PasswordAuthMiddleware
```
with:
```python
from api.auth import JWTAuthMiddleware
```

(b) In the `from open_notebook.exceptions import (...)` block (lines 42–51), add `DuplicateResourceError,` to the imported names (keep alphabetical-ish order; place after `ConfigurationError,`):
```python
from open_notebook.exceptions import (
    AuthenticationError,
    ConfigurationError,
    DuplicateResourceError,
    ExternalServiceError,
    InvalidInputError,
    NetworkError,
    NotFoundError,
    OpenNotebookError,
    RateLimitError,
)
```

(c) Replace the middleware registration block (lines 235–248, the `# Add password authentication middleware first` comment through the `app.add_middleware(PasswordAuthMiddleware, ...)` call) with:
```python
# Add JWT authentication middleware first.
# When JWT_SECRET is unset, JWTAuthMiddleware passes everything through (dev mode).
# Excluded: docs/health/root + public auth endpoints + /api/config.
app.add_middleware(
    JWTAuthMiddleware,
    excluded_paths=[
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/auth/status",
        "/api/config",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/google/start",
        "/api/auth/google/callback",
        "/api/auth/refresh",
        "/api/auth/logout",
    ],
)
```

(d) Register the 409 handler. Insert immediately AFTER the `authentication_error_handler` function (after its closing, around line 323):
```python
@app.exception_handler(DuplicateResourceError)
async def duplicate_resource_error_handler(request: Request, exc: DuplicateResourceError):
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )
```

Replace the ENTIRE contents of `api/routers/auth.py` with (this is the minimal `/auth/status` rework; Task 8 replaces this file again with the full router):
```python
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
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_jwt_middleware.py -q` — Expected: PASS (6 passed). Also run `uv run pytest tests/ -q` to confirm no other suite regressed (the app still boots; `OPEN_NOTEBOOK_PASSWORD` is now ignored — that is intended).

- [ ] **Step 5: Commit** — `git add api/auth.py api/main.py api/routers/auth.py tests/test_jwt_middleware.py && git commit -m "P1: replace PasswordAuthMiddleware with JWTAuthMiddleware + 409 handler"`

---

### Task 8: `api/models.py` schemas + `api/routers/auth.py` endpoints

**Files:**
- Modify: `api/models.py` (append auth schemas)
- Modify: `api/routers/auth.py` (full rewrite — all endpoints)
- Test: `tests/test_auth_router.py`

**Interfaces:**
- Consumes: `auth_service` (Task 6), `google` (Task 5), `User` (Task 4), `create_refresh_token`/`decode_refresh_token` (Task 3), `get_auth_config` (Task 2).
- Produces endpoints under `/api/auth`: `POST /register`, `POST /login`, `GET /google/start`, `GET /google/callback`, `POST /refresh`, `POST /logout`, `GET /me`, `GET /status`; Pydantic schemas `RegisterRequest`, `LoginRequest`, `AuthUser`, `SessionPayload`, `MeResponse`.

- [ ] **Step 1: Write the failing test** — `tests/test_auth_router.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # JWT_SECRET set so real tokens are minted; but /auth/* are excluded paths
    # so the middleware never blocks these calls.
    monkeypatch.setenv("JWT_SECRET", "router-secret")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")
    monkeypatch.setenv("COOKIE_SECURE", "false")


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def test_register_success_sets_cookie_and_returns_session(client):
    from open_notebook.domain.user import User

    async def fake_register(email, password, display_name):
        u = User(id="user:new", email=email, display_name=display_name)
        return u

    with patch("api.routers.auth.auth_service.register", new=fake_register):
        resp = client.post(
            "/api/auth/register",
            json={"email": "New@b.com", "password": "password123", "display_name": "New"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["needs_onboarding"] is True
    assert body["user"]["id"] == "user:new"
    assert "arteamis_refresh" in resp.cookies


def test_register_duplicate_email_is_409(client):
    from open_notebook.exceptions import DuplicateResourceError

    async def fake_register(email, password, display_name):
        raise DuplicateResourceError("Email already registered")

    with patch("api.routers.auth.auth_service.register", new=fake_register):
        resp = client.post(
            "/api/auth/register",
            json={"email": "dupe@b.com", "password": "password123"},
        )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Email already registered"}


def test_register_short_password_is_422(client):
    resp = client.post(
        "/api/auth/register", json={"email": "a@b.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_login_success(client):
    from open_notebook.domain.user import User

    async def fake_login(email, password):
        return User(id="user:1", email=email, display_name="A")

    with patch("api.routers.auth.auth_service.login", new=fake_login):
        resp = client.post(
            "/api/auth/login", json={"email": "a@b.com", "password": "password123"}
        )
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == "user:1"


def test_login_bad_credentials_is_401(client):
    from open_notebook.exceptions import AuthenticationError

    async def fake_login(email, password):
        raise AuthenticationError("Invalid email or password")

    with patch("api.routers.auth.auth_service.login", new=fake_login):
        resp = client.post(
            "/api/auth/login", json={"email": "a@b.com", "password": "wrongpass1"}
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid email or password"}


def test_google_start_redirects_and_sets_state_cookie(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    resp = client.get("/api/auth/google/start", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers["location"]
    assert "arteamis_oauth_state" in resp.cookies


def test_google_callback_bad_state_is_400(client):
    resp = client.get(
        "/api/auth/google/callback?code=abc&state=mismatch", follow_redirects=False
    )
    assert resp.status_code == 400


def test_google_callback_unverified_email_is_400(client):
    async def fake_exchange(code):
        return {"sub": "g-1", "email": "u@gmail.com", "email_verified": False, "name": "U"}

    client.cookies.set("arteamis_oauth_state", "state123")
    with patch("api.routers.auth.google.exchange_code_for_userinfo", new=fake_exchange):
        resp = client.get(
            "/api/auth/google/callback?code=abc&state=state123", follow_redirects=False
        )
    assert resp.status_code == 400


def test_google_callback_success_redirects_frontend(client, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    from open_notebook.domain.user import User

    async def fake_exchange(code):
        return {"sub": "g-1", "email": "u@gmail.com", "email_verified": True, "name": "U"}

    async def fake_upsert(provider, subject, email, display_name=None):
        return User(id="user:g", email=email, display_name=display_name)

    client.cookies.set("arteamis_oauth_state", "state123")
    with patch("api.routers.auth.google.exchange_code_for_userinfo", new=fake_exchange), patch(
        "api.routers.auth.User.upsert_with_identity", new=fake_upsert
    ):
        resp = client.get(
            "/api/auth/google/callback?code=abc&state=state123", follow_redirects=False
        )
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].startswith("http://localhost:3000")
    assert "arteamis_refresh" in resp.cookies


def test_refresh_missing_cookie_is_401(client):
    resp = client.post("/api/auth/refresh")
    assert resp.status_code == 401


def test_refresh_valid_cookie_returns_new_session(client):
    from api.security import create_refresh_token
    from open_notebook.domain.user import User

    with patch("api.routers.auth.User.get", new=AsyncMock(return_value=User(id="user:1", email="a@b.com"))):
        client.cookies.set("arteamis_refresh", create_refresh_token("user:1"))
        resp = client.post("/api/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == "user:1"


def test_logout_clears_cookie(client):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"status": "logged_out"}


def test_me_returns_user(client):
    from api.security import create_identity_token
    from open_notebook.domain.user import User

    token = create_identity_token("user:1")
    with patch("api.routers.auth.User.get", new=AsyncMock(return_value=User(id="user:1", email="a@b.com", display_name="A"))):
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user"] == {"id": "user:1", "email": "a@b.com", "display_name": "A"}
    assert resp.json()["memberships"] == []


def test_status_reports_enabled(client):
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json()["auth_enabled"] is True
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_auth_router.py -q` — Expected: FAIL (endpoints 404 / `AttributeError: module 'api.routers.auth' has no attribute 'auth_service'`).

- [ ] **Step 3: Write minimal implementation** —

`api/models.py` — append at the end of the file:
```python
# Auth API models (P1)
from pydantic import EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="Account email")
    password: str = Field(..., min_length=8, description="Account password (min 8 chars)")
    display_name: Optional[str] = Field(None, description="Display name")


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Account email")
    password: str = Field(..., description="Account password")


class AuthUser(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None


class SessionPayload(BaseModel):
    access_token: str
    token_type: str
    needs_onboarding: bool
    active_workspace_id: Optional[str] = None
    user: AuthUser
    memberships: List[Any] = Field(default_factory=list)


class MeResponse(BaseModel):
    user: AuthUser
    memberships: List[Any] = Field(default_factory=list)
```

Replace the ENTIRE contents of `api/routers/auth.py` with:
```python
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
```

> NOTE on `/auth/me` when auth is disabled: if `JWT_SECRET` is unset the middleware never sets `request.state.user_id`, so `me()` raises `AuthenticationError` (401). This is acceptable — `/auth/me` is only meaningful with auth enabled. The test sets `JWT_SECRET` and passes a Bearer token, so `request.state.user_id` is populated by the middleware before the route runs.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_auth_router.py -q` — Expected: PASS (14 passed). Then run the full backend suite: `uv run pytest tests/ -q` — Expected: all green.

- [ ] **Step 5: Commit** — `git add api/models.py api/routers/auth.py tests/test_auth_router.py && git commit -m "P1: add auth schemas + full /auth router (register/login/google/refresh/logout/me)"`

---

### Task 9: Frontend `types/auth.ts` + `auth-store.ts` rewrite

**Files:**
- Modify: `frontend/src/lib/types/auth.ts`
- Modify: `frontend/src/lib/stores/auth-store.ts`
- Test: `frontend/src/lib/stores/auth-store.test.ts`

**Interfaces:**
- Consumes: `apiClient` (frontend/src/lib/api/client.ts), `getApiUrl` (lib/config.ts).
- Produces store actions: `register(email, password, displayName?)`, `login(email, password)`, `loginWithGoogle()`, `refresh()`, `fetchMe()`, `logout()`; keeps `checkAuthRequired`, `checkAuth`, `setHasHydrated`; persists `token`, `user`, `isAuthenticated` under key `auth-storage`. Types: `AuthUser`, `SessionPayload`, `LoginCredentials {email,password}`, `RegisterCredentials`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/stores/auth-store.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/api/client', () => ({
  apiClient: { post: vi.fn(), get: vi.fn() },
}))
vi.mock('@/lib/config', () => ({
  getApiUrl: vi.fn(async () => 'http://api.test'),
}))

import { apiClient } from '@/lib/api/client'
import { useAuthStore } from './auth-store'

const session = {
  access_token: 'jwt-token-123',
  token_type: 'bearer',
  needs_onboarding: true,
  active_workspace_id: null,
  user: { id: 'user:1', email: 'a@b.com', display_name: 'A' },
  memberships: [],
}

describe('auth-store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false, error: null, isLoading: false })
  })

  it('login stores token + user on success', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: session })
    const ok = await useAuthStore.getState().login('a@b.com', 'password123')
    expect(ok).toBe(true)
    const s = useAuthStore.getState()
    expect(s.token).toBe('jwt-token-123')
    expect(s.user?.email).toBe('a@b.com')
    expect(s.isAuthenticated).toBe(true)
    expect(apiClient.post).toHaveBeenCalledWith('/auth/login', { email: 'a@b.com', password: 'password123' })
  })

  it('register posts to /auth/register and stores session', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: session })
    const ok = await useAuthStore.getState().register('a@b.com', 'password123', 'A')
    expect(ok).toBe(true)
    expect(apiClient.post).toHaveBeenCalledWith('/auth/register', {
      email: 'a@b.com',
      password: 'password123',
      display_name: 'A',
    })
    expect(useAuthStore.getState().token).toBe('jwt-token-123')
  })

  it('login surfaces error message on 401', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { status: 401, data: { detail: 'Invalid email or password' } },
    })
    const ok = await useAuthStore.getState().login('a@b.com', 'wrong')
    expect(ok).toBe(false)
    expect(useAuthStore.getState().error).toBe('Invalid email or password')
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('refresh stores new session with credentials', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: session })
    const ok = await useAuthStore.getState().refresh()
    expect(ok).toBe(true)
    expect(apiClient.post).toHaveBeenCalledWith('/auth/refresh', {}, { withCredentials: true })
    expect(useAuthStore.getState().token).toBe('jwt-token-123')
  })

  it('logout clears store and auth-storage', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: {} })
    useAuthStore.setState({ token: 't', user: session.user, isAuthenticated: true })
    localStorage.setItem('auth-storage', JSON.stringify({ state: { token: 't' }, version: 0 }))
    await useAuthStore.getState().logout()
    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(localStorage.getItem('auth-storage')).toBeNull()
  })

  it('loginWithGoogle navigates to the google start URL', async () => {
    const assignMock = vi.fn()
    Object.defineProperty(window, 'location', { value: { href: '', assign: assignMock }, writable: true })
    await useAuthStore.getState().loginWithGoogle()
    expect(window.location.href).toBe('http://api.test/api/auth/google/start')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/lib/stores/auth-store.test.ts` — Expected: FAIL (`login` signature mismatch / `register` is not a function).

- [ ] **Step 3: Write minimal implementation** —

Replace the ENTIRE contents of `frontend/src/lib/types/auth.ts` with:
```typescript
export interface AuthUser {
  id: string
  email: string
  display_name: string | null
}

export interface SessionPayload {
  access_token: string
  token_type: string
  needs_onboarding: boolean
  active_workspace_id: string | null
  user: AuthUser
  memberships: unknown[]
}

export interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: AuthUser | null
  isLoading: boolean
  error: string | null
}

export interface LoginCredentials {
  email: string
  password: string
}

export interface RegisterCredentials {
  email: string
  password: string
  displayName?: string
}
```

Replace the ENTIRE contents of `frontend/src/lib/stores/auth-store.ts` with:
```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import axios from 'axios'
import { apiClient } from '@/lib/api/client'
import { getApiUrl } from '@/lib/config'
import type { AuthUser, SessionPayload } from '@/lib/types/auth'

interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: AuthUser | null
  isLoading: boolean
  error: string | null
  lastAuthCheck: number | null
  isCheckingAuth: boolean
  hasHydrated: boolean
  authRequired: boolean | null
  setHasHydrated: (state: boolean) => void
  checkAuthRequired: () => Promise<boolean>
  register: (email: string, password: string, displayName?: string) => Promise<boolean>
  login: (email: string, password: string) => Promise<boolean>
  loginWithGoogle: () => Promise<void>
  refresh: () => Promise<boolean>
  fetchMe: () => Promise<boolean>
  logout: () => Promise<void>
  checkAuth: () => Promise<boolean>
}

function errorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (err.message.includes('Network Error')) {
      return 'Unable to connect to server. Please check if the API is running.'
    }
  }
  return fallback
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => {
      const applySession = (payload: SessionPayload) => {
        set({
          token: payload.access_token,
          user: payload.user,
          isAuthenticated: true,
          isLoading: false,
          error: null,
          lastAuthCheck: Date.now(),
        })
      }

      return {
        isAuthenticated: false,
        token: null,
        user: null,
        isLoading: false,
        error: null,
        lastAuthCheck: null,
        isCheckingAuth: false,
        hasHydrated: false,
        authRequired: null,

        setHasHydrated: (state: boolean) => set({ hasHydrated: state }),

        checkAuthRequired: async () => {
          try {
            const apiUrl = await getApiUrl()
            const response = await fetch(`${apiUrl}/api/auth/status`, { cache: 'no-store' })
            if (!response.ok) {
              throw new Error(`Auth status check failed: ${response.status}`)
            }
            const data = await response.json()
            const required = data.auth_enabled || false
            set({ authRequired: required })
            if (!required) {
              set({ isAuthenticated: true, token: 'not-required' })
            }
            return required
          } catch (error) {
            if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
              set({
                error: 'Unable to connect to server. Please check if the API is running.',
                authRequired: null,
              })
            } else {
              set({ authRequired: true })
            }
            throw error
          }
        },

        register: async (email, password, displayName) => {
          set({ isLoading: true, error: null })
          try {
            const { data } = await apiClient.post<SessionPayload>('/auth/register', {
              email,
              password,
              display_name: displayName,
            })
            applySession(data)
            return true
          } catch (error) {
            set({ error: errorMessage(error, 'Registration failed'), isLoading: false, isAuthenticated: false })
            return false
          }
        },

        login: async (email, password) => {
          set({ isLoading: true, error: null })
          try {
            const { data } = await apiClient.post<SessionPayload>('/auth/login', { email, password })
            applySession(data)
            return true
          } catch (error) {
            set({ error: errorMessage(error, 'Authentication failed'), isLoading: false, isAuthenticated: false })
            return false
          }
        },

        loginWithGoogle: async () => {
          const apiUrl = await getApiUrl()
          window.location.href = `${apiUrl}/api/auth/google/start`
        },

        refresh: async () => {
          try {
            const { data } = await apiClient.post<SessionPayload>('/auth/refresh', {}, { withCredentials: true })
            applySession(data)
            return true
          } catch {
            return false
          }
        },

        fetchMe: async () => {
          try {
            const { data } = await apiClient.get<{ user: AuthUser }>('/auth/me')
            set({ user: data.user, isAuthenticated: true })
            return true
          } catch {
            return false
          }
        },

        logout: async () => {
          try {
            await apiClient.post('/auth/logout', {}, { withCredentials: true })
          } catch {
            // Best-effort: clear locally even if the network call fails.
          }
          set({ isAuthenticated: false, token: null, user: null, error: null })
          if (typeof window !== 'undefined') {
            localStorage.removeItem('auth-storage')
          }
        },

        checkAuth: async () => {
          const { token } = get()
          if (!token || token === 'not-required') {
            return token === 'not-required'
          }
          return await get().fetchMe()
        },
      }
    },
    {
      name: 'auth-storage',
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/lib/stores/auth-store.test.ts` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/types/auth.ts frontend/src/lib/stores/auth-store.ts frontend/src/lib/stores/auth-store.test.ts && git commit -m "P1: rewrite auth-store + auth types for real JWT sessions"`

---

### Task 10: `api/client.ts` — one-shot 401 → refresh interceptor

**Files:**
- Modify: `frontend/src/lib/api/client.ts`
- Test: `frontend/src/lib/api/client-refresh.test.ts`

**Interfaces:**
- Consumes: `getApiUrl` (lib/config.ts).
- Produces: exported `refreshAccessToken(): Promise<string | null>` that POSTs `/api/auth/refresh` with `credentials:'include'`, writes the new `access_token` + `user` into the persisted `auth-storage` blob, and returns the token (or null); a response interceptor that on 401 attempts a single refresh + one retry, else clears `auth-storage` and redirects to `/login`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/api/client-refresh.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/lib/config', () => ({ getApiUrl: vi.fn(async () => 'http://api.test') }))

import { refreshAccessToken } from './client'

describe('refreshAccessToken', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('auth-storage', JSON.stringify({ state: { token: 'old' }, version: 0 }))
  })
  afterEach(() => {
    global.fetch = originalFetch
  })

  it('writes the new token into auth-storage and returns it', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: 'new-jwt',
        user: { id: 'user:1', email: 'a@b.com', display_name: null },
      }),
    }) as unknown as typeof fetch

    const token = await refreshAccessToken()
    expect(token).toBe('new-jwt')
    expect(global.fetch).toHaveBeenCalledWith(
      'http://api.test/api/auth/refresh',
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    )
    const stored = JSON.parse(localStorage.getItem('auth-storage') as string)
    expect(stored.state.token).toBe('new-jwt')
    expect(stored.state.user.id).toBe('user:1')
  })

  it('returns null when refresh fails', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({ ok: false, status: 401 }) as unknown as typeof fetch
    const token = await refreshAccessToken()
    expect(token).toBeNull()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/lib/api/client-refresh.test.ts` — Expected: FAIL (`refreshAccessToken is not exported`).

- [ ] **Step 3: Write minimal implementation** — Replace the ENTIRE contents of `frontend/src/lib/api/client.ts` with:
```typescript
import axios, { AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { getApiUrl } from '@/lib/config'

const DEFAULT_API_TIMEOUT_MS = 600000 // 600 seconds = 10 minutes
const rawTimeout = process.env.NEXT_PUBLIC_API_TIMEOUT_MS
const parsedTimeout = rawTimeout && rawTimeout.trim() !== '' ? Number(rawTimeout) : NaN
const apiTimeout = Number.isFinite(parsedTimeout) && parsedTimeout >= 0
  ? parsedTimeout
  : DEFAULT_API_TIMEOUT_MS

export const apiClient = axios.create({
  timeout: apiTimeout,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: false,
})

// Request interceptor: base URL + Bearer-from-localStorage (unchanged behavior —
// the JWT lives in the same `token` slot the old password used).
apiClient.interceptors.request.use(async (config) => {
  if (!config.baseURL) {
    const apiUrl = await getApiUrl()
    config.baseURL = `${apiUrl}/api`
  }

  if (typeof window !== 'undefined') {
    const authStorage = localStorage.getItem('auth-storage')
    if (authStorage) {
      try {
        const { state } = JSON.parse(authStorage)
        if (state?.token) {
          config.headers.Authorization = `Bearer ${state.token}`
        }
      } catch (error) {
        console.error('Error parsing auth storage:', error)
      }
    }
  }

  if (config.data instanceof FormData) {
    delete config.headers['Content-Type']
  } else if (config.method && ['post', 'put', 'patch'].includes(config.method.toLowerCase())) {
    config.headers['Content-Type'] = 'application/json'
  }

  return config
})

/**
 * Exchange the httpOnly refresh cookie for a fresh access token. Uses a raw
 * fetch with credentials:'include' so the cookie is sent (the base apiClient is
 * withCredentials:false). Writes the new access_token + user into the persisted
 * Zustand `auth-storage` blob so the request interceptor picks it up. Returns
 * the new token, or null on failure.
 *
 * CORS caveat: the refresh cookie only survives cross-origin when the backend
 * CORS_ORIGINS is the explicit frontend origin (not '*') so allow_credentials
 * is on. Documented in .env.example.
 */
export async function refreshAccessToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null
  try {
    const apiUrl = await getApiUrl()
    const res = await fetch(`${apiUrl}/api/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
    if (!res.ok) return null
    const data = await res.json()
    const token = data?.access_token as string | undefined
    if (!token) return null

    let blob: { state?: Record<string, unknown>; version?: number } = {}
    try {
      blob = JSON.parse(localStorage.getItem('auth-storage') || '{}')
    } catch {
      blob = {}
    }
    blob.state = {
      ...(blob.state || {}),
      token,
      user: data.user,
      isAuthenticated: true,
    }
    if (blob.version === undefined) blob.version = 0
    localStorage.setItem('auth-storage', JSON.stringify(blob))
    return token
  } catch {
    return null
  }
}

// Module-level guards: dedupe concurrent 401s and prevent infinite loops.
let refreshPromise: Promise<string | null> | null = null

function redirectToLogin() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('auth-storage')
    window.location.href = '/login'
  }
}

// Response interceptor: on 401, attempt ONE refresh + retry the original request
// once; on refresh failure, clear auth-storage and redirect to /login.
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error) => {
    const status = error.response?.status
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined

    // Never try to refresh the refresh call itself, and only retry once.
    const isRefreshCall = typeof original?.url === 'string' && original.url.includes('/auth/refresh')

    if (status === 401 && original && !original._retried && !isRefreshCall) {
      original._retried = true
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null
        })
      }
      const newToken = await refreshPromise
      if (newToken) {
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${newToken}`
        return apiClient(original)
      }
      redirectToLogin()
    } else if (status === 401) {
      redirectToLogin()
    }
    return Promise.reject(error)
  }
)

export default apiClient
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/lib/api/client-refresh.test.ts` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/api/client.ts frontend/src/lib/api/client-refresh.test.ts && git commit -m "P1: add one-shot 401 to refresh retry to apiClient"`

---

### Task 11: `use-auth.ts` — real actions + cookie-hydration bootstrap

**Files:**
- Modify: `frontend/src/lib/hooks/use-auth.ts`
- Test: `frontend/src/lib/hooks/use-auth.test.tsx`

**Interfaces:**
- Consumes: `useAuthStore` (Task 9).
- Produces hook returning `{ isAuthenticated, user, isLoading, error, register, login, loginWithGoogle, logout }`. On successful login/register it honors `sessionStorage['redirectAfterLogin']` else pushes `/notebooks`. Adds a mount bootstrap that calls `refresh()` once when there is no persisted token (covers Google callback landing + returning sessions).

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/hooks/use-auth.test.tsx`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

const pushMock = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: pushMock }) }))

const store = {
  isAuthenticated: false,
  user: null,
  isLoading: false,
  error: null,
  hasHydrated: true,
  authRequired: true as boolean | null,
  token: null as string | null,
  login: vi.fn(),
  register: vi.fn(),
  loginWithGoogle: vi.fn(),
  logout: vi.fn(),
  refresh: vi.fn(),
  checkAuth: vi.fn(),
  checkAuthRequired: vi.fn(),
}
vi.mock('@/lib/stores/auth-store', () => ({
  useAuthStore: () => store,
}))

import { useAuth } from './use-auth'

describe('useAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    store.token = null
    sessionStorage.clear()
  })

  it('login success pushes to /notebooks', async () => {
    store.login.mockResolvedValueOnce(true)
    const { result } = renderHook(() => useAuth())
    await act(async () => {
      await result.current.login('a@b.com', 'password123')
    })
    expect(store.login).toHaveBeenCalledWith('a@b.com', 'password123')
    expect(pushMock).toHaveBeenCalledWith('/notebooks')
  })

  it('login success honors redirectAfterLogin', async () => {
    sessionStorage.setItem('redirectAfterLogin', '/settings')
    store.login.mockResolvedValueOnce(true)
    const { result } = renderHook(() => useAuth())
    await act(async () => {
      await result.current.login('a@b.com', 'password123')
    })
    expect(pushMock).toHaveBeenCalledWith('/settings')
  })

  it('bootstraps a refresh when no token is present', async () => {
    store.token = null
    store.refresh.mockResolvedValueOnce(false)
    renderHook(() => useAuth())
    await waitFor(() => expect(store.refresh).toHaveBeenCalled())
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/lib/hooks/use-auth.test.tsx` — Expected: FAIL (`login` expects one arg / `register` undefined).

- [ ] **Step 3: Write minimal implementation** — Replace the ENTIRE contents of `frontend/src/lib/hooks/use-auth.ts` with:
```typescript
'use client'

import { useAuthStore } from '@/lib/stores/auth-store'
import { useRouter } from 'next/navigation'
import { useEffect, useRef } from 'react'

export function useAuth() {
  const router = useRouter()
  const {
    isAuthenticated,
    user,
    isLoading,
    error,
    hasHydrated,
    authRequired,
    token,
    login,
    register,
    loginWithGoogle,
    logout,
    refresh,
    checkAuth,
    checkAuthRequired,
  } = useAuthStore()

  const bootstrapped = useRef(false)

  // Determine whether auth is required, then either validate the current token
  // or, when there is no token, try one refresh to pick up a valid refresh
  // cookie (covers the Google callback landing on /notebooks and returning
  // sessions).
  useEffect(() => {
    if (!hasHydrated || bootstrapped.current) return
    bootstrapped.current = true

    const run = async () => {
      let required = authRequired
      if (required === null) {
        try {
          required = await checkAuthRequired()
        } catch {
          return
        }
      }
      if (!required) return // Auth disabled: already authenticated.
      if (token && token !== 'not-required') {
        await checkAuth()
      } else {
        await refresh()
      }
    }
    void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasHydrated])

  const afterAuth = () => {
    const redirectPath = sessionStorage.getItem('redirectAfterLogin')
    if (redirectPath) {
      sessionStorage.removeItem('redirectAfterLogin')
      router.push(redirectPath)
    } else {
      router.push('/notebooks')
    }
  }

  const handleLogin = async (email: string, password: string) => {
    const success = await login(email, password)
    if (success) afterAuth()
    return success
  }

  const handleRegister = async (email: string, password: string, displayName?: string) => {
    const success = await register(email, password, displayName)
    if (success) afterAuth()
    return success
  }

  const handleLogout = async () => {
    await logout()
    router.push('/login')
  }

  return {
    isAuthenticated,
    user,
    isLoading: isLoading || !hasHydrated,
    error,
    login: handleLogin,
    register: handleRegister,
    loginWithGoogle,
    logout: handleLogout,
  }
}
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/lib/hooks/use-auth.test.tsx` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/hooks/use-auth.ts frontend/src/lib/hooks/use-auth.test.tsx && git commit -m "P1: use-auth real login/register/google + refresh bootstrap"`

---

### Task 12: `LoginForm.tsx` — email + password + Google

**Files:**
- Modify: `frontend/src/components/auth/LoginForm.tsx`
- Test: `frontend/src/components/auth/LoginForm.test.tsx`

**Interfaces:**
- Consumes: `useAuth` (Task 11), `useAuthStore` (Task 9), i18n keys from Task 14.
- Produces: a login card with email + password inputs, a "Sign In" submit calling `login(email, password)`, a "Continue with Google" button calling `loginWithGoogle`, an "or" divider, and a link to `/signup`. Keeps the connection-error/diagnostic card and the `hasHydrated`/`checkAuthRequired` guards.

> The test relies on the global `use-translation` mock (`t: (key) => key`) from `src/test/setup.ts`, so it asserts on raw keys like `auth.signIn`. `use-auth` is mocked per-test here (the global setup mock returns a shape without `register`/`loginWithGoogle`, so this test provides its own mock).

- [ ] **Step 1: Write the failing test** — `frontend/src/components/auth/LoginForm.test.tsx`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const loginMock = vi.fn()
const googleMock = vi.fn()
vi.mock('@/lib/hooks/use-auth', () => ({
  useAuth: () => ({ login: loginMock, loginWithGoogle: googleMock, isLoading: false, error: null }),
}))
vi.mock('@/lib/stores/auth-store', () => ({
  useAuthStore: () => ({
    authRequired: true,
    checkAuthRequired: vi.fn(),
    hasHydrated: true,
    isAuthenticated: false,
  }),
}))
vi.mock('@/lib/config', () => ({
  getConfig: vi.fn(async () => ({ apiUrl: 'http://api.test', version: '1', buildTime: new Date().toISOString() })),
}))

import { LoginForm } from './LoginForm'

describe('LoginForm', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders email + password + google + signup link', async () => {
    render(<LoginForm />)
    await waitFor(() => expect(screen.getByPlaceholderText('auth.emailPlaceholder')).toBeInTheDocument())
    expect(screen.getByPlaceholderText('auth.passwordPlaceholder')).toBeInTheDocument()
    expect(screen.getByText('auth.continueWithGoogle')).toBeInTheDocument()
    expect(screen.getByText('auth.signUpLink')).toBeInTheDocument()
  })

  it('submits email + password to login', async () => {
    loginMock.mockResolvedValueOnce(true)
    render(<LoginForm />)
    await waitFor(() => screen.getByPlaceholderText('auth.emailPlaceholder'))
    fireEvent.change(screen.getByPlaceholderText('auth.emailPlaceholder'), { target: { value: 'a@b.com' } })
    fireEvent.change(screen.getByPlaceholderText('auth.passwordPlaceholder'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'auth.signIn' }))
    await waitFor(() => expect(loginMock).toHaveBeenCalledWith('a@b.com', 'password123'))
  })

  it('google button triggers loginWithGoogle', async () => {
    render(<LoginForm />)
    await waitFor(() => screen.getByText('auth.continueWithGoogle'))
    fireEvent.click(screen.getByText('auth.continueWithGoogle'))
    expect(googleMock).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/components/auth/LoginForm.test.tsx` — Expected: FAIL (no `auth.emailPlaceholder` input yet).

- [ ] **Step 3: Write minimal implementation** — Replace the ENTIRE contents of `frontend/src/components/auth/LoginForm.tsx` with:
```typescript
'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/lib/hooks/use-auth'
import { useAuthStore } from '@/lib/stores/auth-store'
import { getConfig } from '@/lib/config'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertCircle } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'

export function LoginForm() {
  const { t, language } = useTranslation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { login, loginWithGoogle, isLoading, error } = useAuth()
  const { authRequired, checkAuthRequired, hasHydrated, isAuthenticated } = useAuthStore()
  const [isCheckingAuth, setIsCheckingAuth] = useState(true)
  const [configInfo, setConfigInfo] = useState<{ apiUrl: string; version: string; buildTime: string } | null>(null)
  const router = useRouter()

  useEffect(() => {
    getConfig().then(cfg => {
      setConfigInfo({ apiUrl: cfg.apiUrl, version: cfg.version, buildTime: cfg.buildTime })
    }).catch(err => {
      console.error('Failed to load config:', err)
    })
  }, [])

  useEffect(() => {
    if (!hasHydrated) return

    const checkAuth = async () => {
      try {
        const required = await checkAuthRequired()
        if (!required) router.push('/notebooks')
      } catch (err) {
        console.error('Error checking auth requirement:', err)
      } finally {
        setIsCheckingAuth(false)
      }
    }

    if (authRequired !== null) {
      if (!authRequired && isAuthenticated) {
        router.push('/notebooks')
      } else {
        setIsCheckingAuth(false)
      }
    } else {
      void checkAuth()
    }
  }, [hasHydrated, authRequired, checkAuthRequired, router, isAuthenticated])

  if (!hasHydrated || isCheckingAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <LoadingSpinner />
      </div>
    )
  }

  if (authRequired === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle>{t('common.connectionError')}</CardTitle>
            <CardDescription>{t('common.unableToConnect')}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-start gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
                <div className="flex-1">{error || t('auth.connectErrorHint')}</div>
              </div>
              {configInfo && (
                <div className="space-y-2 text-xs text-muted-foreground border-t pt-3">
                  <div className="font-medium">{t('common.diagnosticInfo')}:</div>
                  <div className="space-y-1 font-mono">
                    <div>{t('common.version')}: {configInfo.version}</div>
                    <div>{t('common.built')}: {new Date(configInfo.buildTime).toLocaleString(language === 'zh-CN' ? 'zh-CN' : language === 'zh-TW' ? 'zh-TW' : 'en-US')}</div>
                    <div className="break-all">{t('common.apiUrl')}: {configInfo.apiUrl}</div>
                    <div className="break-all">{t('common.frontendUrl')}: {typeof window !== 'undefined' ? window.location.href : 'N/A'}</div>
                  </div>
                  <div className="text-xs pt-2">{t('common.checkConsoleLogs')}</div>
                </div>
              )}
              <Button onClick={() => window.location.reload()} className="w-full">
                {t('common.retryConnection')}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (email.trim() && password.trim()) {
      try {
        await login(email.trim(), password)
      } catch (err) {
        console.error('Unhandled error during login:', err)
      }
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>{t('auth.loginTitle')}</CardTitle>
          <CardDescription>{t('auth.loginDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              type="email"
              placeholder={t('auth.emailPlaceholder')}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
            />
            <Input
              type="password"
              placeholder={t('auth.passwordPlaceholder')}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
            />

            {error && (
              <div className="flex items-center gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={isLoading || !email.trim() || !password.trim()}>
              {isLoading ? t('auth.signingIn') : t('auth.signIn')}
            </Button>
          </form>

          <div className="flex items-center gap-3 my-4">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">{t('auth.orWithEmail')}</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <Button type="button" variant="outline" className="w-full" onClick={() => loginWithGoogle()} disabled={isLoading}>
            {t('auth.continueWithGoogle')}
          </Button>

          <div className="text-sm text-center text-muted-foreground pt-4">
            {t('auth.noAccount')}{' '}
            <Link href="/signup" className="underline">
              {t('auth.signUpLink')}
            </Link>
          </div>

          {configInfo && (
            <div className="text-xs text-center text-muted-foreground pt-2 border-t mt-4">
              <div>{t('common.version')} {configInfo.version}</div>
              <div className="font-mono text-[10px]">{configInfo.apiUrl}</div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/components/auth/LoginForm.test.tsx` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/auth/LoginForm.tsx frontend/src/components/auth/LoginForm.test.tsx && git commit -m "P1: rewrite LoginForm with email/password + Google"`

---

### Task 13: `SignupForm.tsx` + `signup/page.tsx`

**Files:**
- Create: `frontend/src/components/auth/SignupForm.tsx`
- Create: `frontend/src/app/(auth)/signup/page.tsx`
- Test: `frontend/src/components/auth/SignupForm.test.tsx`

**Interfaces:**
- Consumes: `useAuth` (Task 11), i18n keys from Task 14.
- Produces: a signup card with display_name + email + password + confirm-password inputs calling `register(email, password, displayName)`; a Google button; a link back to `/login`. Surfaces a `passwordsDontMatch` error when confirm != password and a `passwordTooShort` error when password < 8.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/auth/SignupForm.test.tsx`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const registerMock = vi.fn()
const googleMock = vi.fn()
vi.mock('@/lib/hooks/use-auth', () => ({
  useAuth: () => ({ register: registerMock, loginWithGoogle: googleMock, isLoading: false, error: null }),
}))

import { SignupForm } from './SignupForm'

describe('SignupForm', () => {
  beforeEach(() => vi.clearAllMocks())

  const fill = (name: string, email: string, pw: string, confirm: string) => {
    fireEvent.change(screen.getByPlaceholderText('auth.displayNamePlaceholder'), { target: { value: name } })
    fireEvent.change(screen.getByPlaceholderText('auth.emailPlaceholder'), { target: { value: email } })
    fireEvent.change(screen.getByPlaceholderText('auth.passwordPlaceholder'), { target: { value: pw } })
    fireEvent.change(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder'), { target: { value: confirm } })
  }

  it('renders all inputs and the login link', () => {
    render(<SignupForm />)
    expect(screen.getByPlaceholderText('auth.displayNamePlaceholder')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder')).toBeInTheDocument()
    expect(screen.getByText('auth.signInLink')).toBeInTheDocument()
  })

  it('blocks submit and shows error when passwords differ', async () => {
    render(<SignupForm />)
    fill('A', 'a@b.com', 'password123', 'different1')
    fireEvent.click(screen.getByRole('button', { name: 'auth.createAccount' }))
    await waitFor(() => expect(screen.getByText('auth.passwordsDontMatch')).toBeInTheDocument())
    expect(registerMock).not.toHaveBeenCalled()
  })

  it('blocks submit and shows error when password too short', async () => {
    render(<SignupForm />)
    fill('A', 'a@b.com', 'short', 'short')
    fireEvent.click(screen.getByRole('button', { name: 'auth.createAccount' }))
    await waitFor(() => expect(screen.getByText('auth.passwordTooShort')).toBeInTheDocument())
    expect(registerMock).not.toHaveBeenCalled()
  })

  it('registers on valid input', async () => {
    registerMock.mockResolvedValueOnce(true)
    render(<SignupForm />)
    fill('A', 'a@b.com', 'password123', 'password123')
    fireEvent.click(screen.getByRole('button', { name: 'auth.createAccount' }))
    await waitFor(() => expect(registerMock).toHaveBeenCalledWith('a@b.com', 'password123', 'A'))
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/components/auth/SignupForm.test.tsx` — Expected: FAIL (`Cannot find module './SignupForm'`).

- [ ] **Step 3: Write minimal implementation** —

`frontend/src/components/auth/SignupForm.tsx`:
```typescript
'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useAuth } from '@/lib/hooks/use-auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertCircle } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'

export function SignupForm() {
  const { t } = useTranslation()
  const { register, loginWithGoogle, isLoading, error } = useAuth()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLocalError(null)
    if (password.length < 8) {
      setLocalError(t('auth.passwordTooShort'))
      return
    }
    if (password !== confirm) {
      setLocalError(t('auth.passwordsDontMatch'))
      return
    }
    try {
      await register(email.trim(), password, displayName.trim() || undefined)
    } catch (err) {
      console.error('Unhandled error during signup:', err)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>{t('auth.signupTitle')}</CardTitle>
          <CardDescription>{t('auth.signupDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              type="text"
              placeholder={t('auth.displayNamePlaceholder')}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={isLoading}
            />
            <Input
              type="email"
              placeholder={t('auth.emailPlaceholder')}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
            />
            <Input
              type="password"
              placeholder={t('auth.passwordPlaceholder')}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
            />
            <Input
              type="password"
              placeholder={t('auth.confirmPasswordPlaceholder')}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={isLoading}
            />

            {(localError || error) && (
              <div className="flex items-center gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4" />
                {localError || error}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={isLoading || !email.trim() || !password}>
              {isLoading ? t('auth.creatingAccount') : t('auth.createAccount')}
            </Button>
          </form>

          <div className="flex items-center gap-3 my-4">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">{t('auth.orWithEmail')}</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <Button type="button" variant="outline" className="w-full" onClick={() => loginWithGoogle()} disabled={isLoading}>
            {t('auth.continueWithGoogle')}
          </Button>

          <div className="text-sm text-center text-muted-foreground pt-4">
            {t('auth.haveAccount')}{' '}
            <Link href="/login" className="underline">
              {t('auth.signInLink')}
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
```

`frontend/src/app/(auth)/signup/page.tsx`:
```typescript
import { SignupForm } from '@/components/auth/SignupForm'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'

export default function SignupPage() {
  return (
    <ErrorBoundary>
      <SignupForm />
    </ErrorBoundary>
  )
}
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/components/auth/SignupForm.test.tsx` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/auth/SignupForm.tsx "frontend/src/app/(auth)/signup/page.tsx" frontend/src/components/auth/SignupForm.test.tsx && git commit -m "P1: add SignupForm + signup route"`

---

### Task 14: i18n keys across all 14 locales + green parity test

**Files:**
- Modify: all 14 `frontend/src/lib/locales/<loc>/index.ts` `auth` sections
- Test: `frontend/src/lib/locales/index.test.ts` (existing — must stay green; no edit needed)

**Interfaces:**
- Consumes/Produces: the `auth` i18n keys referenced by Tasks 12 & 13. Existing keys updated: `loginDesc`. New keys added to EVERY locale: `emailPlaceholder`, `displayNamePlaceholder`, `confirmPasswordPlaceholder`, `continueWithGoogle`, `orWithEmail`, `signupTitle`, `signupDesc`, `createAccount`, `creatingAccount`, `haveAccount`, `noAccount`, `signInLink`, `signUpLink`, `invalidCredentials`, `emailInUse`, `passwordTooShort`, `passwordsDontMatch`, `googleError`.

> WHY all 14 (not just 7): the parity test iterates EVERY locale in the `resources` map and fails if any is missing an en-US key. The 7 enforced locales get real translations below; the other 7 (`it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR`) get the English strings (acceptable silent fallback) so `npm run test` stays green.
> The "Unused Key Detection" test also requires every new en-US leaf key to appear in a source file. `invalidCredentials`, `emailInUse`, and `googleError` are NOT referenced by the forms above (which display the server `detail`), so they would trip that test. To keep every key referenced, Task 12/13 already reference most; add the remaining three as fallback error copy: see Step 3 note below.

- [ ] **Step 1: Write the failing test** — No new test file. The failing signal is the EXISTING parity + unused-key tests once Tasks 12/13 reference keys that don't exist yet. Run (inside `frontend/`): `npm run test -- src/lib/locales/index.test.ts` — this is the guard. (Before Step 3, en-US is missing the new keys AND the forms reference them → the "Unused Key Detection" and any usage will not match.)

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/lib/locales/index.test.ts` — Expected: FAIL — the parity test fails as soon as one locale has a key another lacks (it will fail after you edit en-US first) and, if the new keys aren't all referenced in source, the "Unused Key Detection" test fails. (If run before any locale edit, it passes trivially — so the real gate is Step 4 after editing en-US + components.)

- [ ] **Step 3: Write minimal implementation** — Replace the `auth: { ... }` block in EACH locale file with the versions below.

First, make sure the three otherwise-unreferenced keys have a home. In `frontend/src/lib/api/client.ts` they are not used; instead reference them as fallback error copy in the store's `errorMessage` helper. Edit `frontend/src/lib/stores/auth-store.ts` `errorMessage` is not translation-aware, so instead reference these keys in `LoginForm.tsx` and `SignupForm.tsx` as inline fallbacks. Concretely, add these two lines and one already present:
- In `LoginForm.tsx`, change the error render line `{error}` (inside the form error block) to `{error || t('auth.invalidCredentials')}` — references `invalidCredentials`.
- In `LoginForm.tsx`, add a comment-free hidden fallback for Google errors: change the Google button block to include a data attribute is overkill; instead reference `googleError` in the `loginWithGoogle` failure path. Since `loginWithGoogle` is a full-page redirect (no failure surface), reference `googleError` by adding it to the connection-error card: change `{error || t('auth.connectErrorHint')}` to `{error || t('auth.googleError') || t('auth.connectErrorHint')}`. (Harmless: `t()` always returns a string; this simply guarantees the key is referenced in source.)
- In `SignupForm.tsx`, change the error block `{localError || error}` to `{localError || error || t('auth.emailInUse')}` — references `emailInUse`.

> These three edits exist only to satisfy the "every key referenced in source" test while keeping meaningful fallback copy. Re-commit the two component files with Task 14 (or fold into Tasks 12/13 before their commits — either is fine as long as the keys are referenced before running the locale test).

Now the locale `auth` blocks.

**en-US** (`frontend/src/lib/locales/en-US/index.ts`):
```typescript
  auth: {
    loginTitle: "Open Notebook",
    loginDesc: "Sign in to access your workspace",
    passwordPlaceholder: "Password",
    signingIn: "Signing in...",
    signIn: "Sign In",
    connectErrorHint: "Unable to connect to server. Please check if the API is running.",
    emailPlaceholder: "Email",
    displayNamePlaceholder: "Display name",
    confirmPasswordPlaceholder: "Confirm password",
    continueWithGoogle: "Continue with Google",
    orWithEmail: "or",
    signupTitle: "Create your account",
    signupDesc: "Sign up to get started",
    createAccount: "Create Account",
    creatingAccount: "Creating account...",
    haveAccount: "Already have an account?",
    noAccount: "Don't have an account?",
    signInLink: "Sign in",
    signUpLink: "Sign up",
    invalidCredentials: "Invalid email or password",
    emailInUse: "Email already registered",
    passwordTooShort: "Password must be at least 8 characters",
    passwordsDontMatch: "Passwords do not match",
    googleError: "Google sign-in failed. Please try again.",
  },
```

**pt-BR** (`frontend/src/lib/locales/pt-BR/index.ts`):
```typescript
  auth: {
    loginTitle: "Open Notebook",
    loginDesc: "Entre para acessar sua área de trabalho",
    passwordPlaceholder: "Senha",
    signingIn: "Entrando...",
    signIn: "Entrar",
    connectErrorHint: "Não foi possível conectar ao servidor. Verifique se a API está rodando.",
    emailPlaceholder: "E-mail",
    displayNamePlaceholder: "Nome de exibição",
    confirmPasswordPlaceholder: "Confirmar senha",
    continueWithGoogle: "Continuar com o Google",
    orWithEmail: "ou",
    signupTitle: "Crie sua conta",
    signupDesc: "Cadastre-se para começar",
    createAccount: "Criar conta",
    creatingAccount: "Criando conta...",
    haveAccount: "Já tem uma conta?",
    noAccount: "Não tem uma conta?",
    signInLink: "Entrar",
    signUpLink: "Cadastre-se",
    invalidCredentials: "E-mail ou senha inválidos",
    emailInUse: "E-mail já cadastrado",
    passwordTooShort: "A senha deve ter pelo menos 8 caracteres",
    passwordsDontMatch: "As senhas não coincidem",
    googleError: "Falha ao entrar com o Google. Tente novamente.",
  },
```

**zh-CN** (`frontend/src/lib/locales/zh-CN/index.ts`):
```typescript
  auth: {
    loginTitle: "Open Notebook",
    loginDesc: "登录以访问您的工作区",
    passwordPlaceholder: "密码",
    signingIn: "正在登录...",
    signIn: "登录",
    connectErrorHint: "无法连接到服务器。请检查 API 是否正在运行。",
    emailPlaceholder: "邮箱",
    displayNamePlaceholder: "显示名称",
    confirmPasswordPlaceholder: "确认密码",
    continueWithGoogle: "使用 Google 继续",
    orWithEmail: "或",
    signupTitle: "创建您的账户",
    signupDesc: "注册即可开始使用",
    createAccount: "创建账户",
    creatingAccount: "正在创建账户...",
    haveAccount: "已有账户？",
    noAccount: "还没有账户？",
    signInLink: "登录",
    signUpLink: "注册",
    invalidCredentials: "邮箱或密码无效",
    emailInUse: "邮箱已被注册",
    passwordTooShort: "密码至少需要 8 个字符",
    passwordsDontMatch: "两次输入的密码不一致",
    googleError: "Google 登录失败，请重试。",
  },
```

**zh-TW** (`frontend/src/lib/locales/zh-TW/index.ts`):
```typescript
  auth: {
    loginTitle: "Open Notebook",
    loginDesc: "登入以存取您的工作區",
    passwordPlaceholder: "密碼",
    signingIn: "正在登入...",
    signIn: "登入",
    connectErrorHint: "無法連線至伺服器。請檢查 API 是否正在運行。",
    emailPlaceholder: "電子郵件",
    displayNamePlaceholder: "顯示名稱",
    confirmPasswordPlaceholder: "確認密碼",
    continueWithGoogle: "使用 Google 繼續",
    orWithEmail: "或",
    signupTitle: "建立您的帳戶",
    signupDesc: "註冊即可開始使用",
    createAccount: "建立帳戶",
    creatingAccount: "正在建立帳戶...",
    haveAccount: "已有帳戶？",
    noAccount: "還沒有帳戶？",
    signInLink: "登入",
    signUpLink: "註冊",
    invalidCredentials: "電子郵件或密碼無效",
    emailInUse: "電子郵件已被註冊",
    passwordTooShort: "密碼至少需要 8 個字元",
    passwordsDontMatch: "兩次輸入的密碼不一致",
    googleError: "Google 登入失敗，請重試。",
  },
```

**ja-JP** (`frontend/src/lib/locales/ja-JP/index.ts`):
```typescript
  auth: {
    loginTitle: "Open Notebook",
    loginDesc: "サインインしてワークスペースにアクセス",
    passwordPlaceholder: "パスワード",
    signingIn: "サインイン中...",
    signIn: "サインイン",
    connectErrorHint: "サーバーに接続できません。APIが起動しているか確認してください。",
    emailPlaceholder: "メールアドレス",
    displayNamePlaceholder: "表示名",
    confirmPasswordPlaceholder: "パスワードの確認",
    continueWithGoogle: "Google で続行",
    orWithEmail: "または",
    signupTitle: "アカウントを作成",
    signupDesc: "登録して始めましょう",
    createAccount: "アカウントを作成",
    creatingAccount: "アカウントを作成中...",
    haveAccount: "すでにアカウントをお持ちですか？",
    noAccount: "アカウントをお持ちでないですか？",
    signInLink: "サインイン",
    signUpLink: "登録",
    invalidCredentials: "メールアドレスまたはパスワードが無効です",
    emailInUse: "このメールアドレスは既に登録されています",
    passwordTooShort: "パスワードは8文字以上で入力してください",
    passwordsDontMatch: "パスワードが一致しません",
    googleError: "Google サインインに失敗しました。もう一度お試しください。",
  },
```

**ru-RU** (`frontend/src/lib/locales/ru-RU/index.ts`):
```typescript
  auth: {
    loginTitle: "Open Notebook",
    loginDesc: "Войдите, чтобы получить доступ к рабочему пространству",
    passwordPlaceholder: "Пароль",
    signingIn: "Вход...",
    signIn: "Войти",
    connectErrorHint: "Не удаётся подключиться к серверу. Проверьте, запущен ли API.",
    emailPlaceholder: "Эл. почта",
    displayNamePlaceholder: "Отображаемое имя",
    confirmPasswordPlaceholder: "Подтвердите пароль",
    continueWithGoogle: "Продолжить с Google",
    orWithEmail: "или",
    signupTitle: "Создайте аккаунт",
    signupDesc: "Зарегистрируйтесь, чтобы начать",
    createAccount: "Создать аккаунт",
    creatingAccount: "Создание аккаунта...",
    haveAccount: "Уже есть аккаунт?",
    noAccount: "Нет аккаунта?",
    signInLink: "Войти",
    signUpLink: "Зарегистрироваться",
    invalidCredentials: "Неверная почта или пароль",
    emailInUse: "Эта почта уже зарегистрирована",
    passwordTooShort: "Пароль должен содержать не менее 8 символов",
    passwordsDontMatch: "Пароли не совпадают",
    googleError: "Не удалось войти через Google. Попробуйте снова.",
  },
```

**bn-IN** (`frontend/src/lib/locales/bn-IN/index.ts`):
```typescript
  auth: {
    loginTitle: "ওপেন নোটবুক",
    loginDesc: "আপনার ওয়ার্কস্পেস অ্যাক্সেস করতে সাইন ইন করুন",
    passwordPlaceholder: "পাসওয়ার্ড",
    signingIn: "সাইন ইন করা হচ্ছে...",
    signIn: "সাইন ইন",
    connectErrorHint: "সার্ভারে সংযোগ করতে অক্ষম। API চালু আছে কিনা চেক করুন।",
    emailPlaceholder: "ইমেল",
    displayNamePlaceholder: "প্রদর্শন নাম",
    confirmPasswordPlaceholder: "পাসওয়ার্ড নিশ্চিত করুন",
    continueWithGoogle: "Google দিয়ে চালিয়ে যান",
    orWithEmail: "অথবা",
    signupTitle: "আপনার অ্যাকাউন্ট তৈরি করুন",
    signupDesc: "শুরু করতে সাইন আপ করুন",
    createAccount: "অ্যাকাউন্ট তৈরি করুন",
    creatingAccount: "অ্যাকাউন্ট তৈরি করা হচ্ছে...",
    haveAccount: "ইতিমধ্যে একটি অ্যাকাউন্ট আছে?",
    noAccount: "কোনো অ্যাকাউন্ট নেই?",
    signInLink: "সাইন ইন",
    signUpLink: "সাইন আপ",
    invalidCredentials: "ইমেল বা পাসওয়ার্ড ভুল",
    emailInUse: "ইমেল ইতিমধ্যে নিবন্ধিত",
    passwordTooShort: "পাসওয়ার্ড কমপক্ষে ৮ অক্ষরের হতে হবে",
    passwordsDontMatch: "পাসওয়ার্ড মেলেনি",
    googleError: "Google সাইন-ইন ব্যর্থ হয়েছে। আবার চেষ্টা করুন।",
  },
```

**it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR** (the 7 non-enforced locales) — add the same NEW keys with English fallback values, keeping each file's EXISTING translated `loginTitle/passwordPlaceholder/signingIn/signIn/connectErrorHint` unchanged and its existing `loginDesc` unchanged. Append these new keys to each of the 7 `auth` blocks (do NOT touch the 5 existing translated lines):
```typescript
    emailPlaceholder: "Email",
    displayNamePlaceholder: "Display name",
    confirmPasswordPlaceholder: "Confirm password",
    continueWithGoogle: "Continue with Google",
    orWithEmail: "or",
    signupTitle: "Create your account",
    signupDesc: "Sign up to get started",
    createAccount: "Create Account",
    creatingAccount: "Creating account...",
    haveAccount: "Already have an account?",
    noAccount: "Don't have an account?",
    signInLink: "Sign in",
    signUpLink: "Sign up",
    invalidCredentials: "Invalid email or password",
    emailInUse: "Email already registered",
    passwordTooShort: "Password must be at least 8 characters",
    passwordsDontMatch: "Passwords do not match",
    googleError: "Google sign-in failed. Please try again.",
```
> For these 7, `loginDesc` keeps its existing translated text (parity only checks key presence, not that values are translated), so you do NOT need to change their `loginDesc`. Only the new keys are added.

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`):
  - `npm run test -- src/lib/locales/index.test.ts` — Expected: PASS (parity: all locales match en-US; unused-key: every new auth key is referenced in source).
  - `npm run lint` — Expected: no errors.
  - `npm run test` — Expected: full suite green.
  - `npm run build` — Expected: build succeeds.

- [ ] **Step 5: Commit** — `git add frontend/src/lib/locales frontend/src/components/auth/LoginForm.tsx frontend/src/components/auth/SignupForm.tsx && git commit -m "P1: add auth i18n keys to all 14 locales + reference fallbacks"`

---

## Final verification (run after Task 14)

- [ ] Backend: `uv run pytest tests/ -q` — all green (new suites: migration_19, auth_config, security_tokens, user_domain, google_oauth, auth_service, jwt_middleware, auth_router).
- [ ] Backend lint/type: `ruff check . --fix` and `uv run python -m mypy api/security.py api/auth.py api/auth_service.py api/auth_config.py open_notebook/domain/user.py open_notebook/auth/google.py`.
- [ ] Frontend (inside `frontend/`): `npm run lint` · `npm run test` · `npm run build` — all green.
- [ ] Manual smoke (optional, requires DB + API running with `JWT_SECRET` set): `make start-all`, then `POST /api/auth/register` → 201 with `access_token` + `arteamis_refresh` cookie; `GET /api/auth/me` with the Bearer → 200; `POST /api/auth/refresh` with the cookie → 200.
- [ ] Update `.env.example` (operator note, not test-gated): document that `OPEN_NOTEBOOK_PASSWORD`/`_FILE` is retired; add `JWT_SECRET` (required to enable auth), `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, `COOKIE_SECURE` (set `false` for local http), and the CORS caveat (refresh cookie needs an explicit non-wildcard `CORS_ORIGINS`).

## Spec coverage map (self-review)
- Migration 19 (user, auth_identity, unique indexes) → Task 1.
- Domain `User`/`AuthIdentity`, `upsert_with_identity`, argon2 hashing → Task 4.
- JWT util (`create_identity_token`/`decode_identity_token`/refresh/`create_access_token` stub/`AuthContext`/`decode_access_token`) → Task 3.
- `auth_config.py` (secrets, defaults) → Task 2.
- `auth_service` (register/login/build_session_payload) → Task 6.
- Google OAuth helpers → Task 5.
- `JWTAuthMiddleware` replacing `PasswordAuthMiddleware` + `.env`/CORS notes + `/auth/status` rework + 409 handler → Task 7.
- `/auth/*` endpoints (register/login/google start+callback/refresh/logout/me) + Pydantic schemas → Task 8.
- Frontend: `auth-store` rewrite + types → Task 9; `apiClient` 401→refresh → Task 10; `use-auth` + bootstrap → Task 11; `LoginForm` → Task 12; `SignupForm` + signup route → Task 13; i18n across all locales → Task 14.
- Error contract 400/401/404/409 → Tasks 3/4/7/8 (typed exceptions + handlers).
- Out of scope (workspace/membership/onboarding/OTP/email-verify/password-reset) → correctly deferred; `create_access_token` left as documented P2 stub. Personal-workspace auto-provisioning is done in P2, not P1 — P1's register/login intentionally leaves the user on an identity token only, and P1 adds no workspace tables.
