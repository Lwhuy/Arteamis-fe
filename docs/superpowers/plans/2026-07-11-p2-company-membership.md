# P2 — Company + Membership + Roles + Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the `company` (tenant boundary) and `membership` (user↔company + role) tables plus the flows that let a just-authenticated, zero-company user create their first company (becoming its `owner`), list their companies, and switch the active one — with company-scoped access tokens minted on create/switch, a `require_role` RBAC primitive for later phases, and a first-run onboarding wizard + company switcher on the frontend.

**Architecture:** Next.js 16 App Router frontend (port 3000) → FastAPI (port 5055) → SurrealDB (port 8000). Identity-plane tables (`user`, `auth_identity` from P1; `company`, `membership` here) are **never** company-scoped — login/onboarding must read a user's memberships before any company is active, so isolation is enforced by explicit `user`/`company` filters in the service layer (SurrealDB has no RLS). Two JWT shapes: P1's **identity token** (`sub` only) and P2's **company-scoped access token** (`sub`, `company_id`, `role`), minted on company create/switch and swapped into the persisted Zustand auth store.

**Tech Stack:** Next.js 16, TanStack Query, Zustand (persist), FastAPI, SurrealDB (custom async repository + hand-written SurrealQL migrations), `python-jose[cryptography]` (HS256 JWT, from P1), Pydantic v2, vitest, pytest + pytest-asyncio.

**Spec:** docs/superpowers/specs/2026-07-11-p2-company-membership-onboarding-design.md
**Depends on:** P1 (auth + users) · **Branch:** feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB call is awaited (no sync DB access).
- All frontend HTTP goes through the single axios `apiClient` (frontend/src/lib/api/client.ts) — never a 2nd instance. It auto-injects `Authorization: Bearer <state.token>` from localStorage `auth-storage`.
- i18n MANDATORY: every UI string via `t('section.key')`; add the key to ALL 14 locales in the `resources` map under frontend/src/lib/locales/. The locale test `src/lib/locales/index.test.ts` enforces both **parity** (EVERY locale in `resources` must carry the exact en-US key set — not just the enforced ones) AND **usage** (every en-US leaf key must appear literally in a source file) — so add keys only alongside the component that references them literally. There are 14 locales (`zh-CN, en-US, zh-TW, pt-BR, ja-JP, it-IT, fr-FR, ru-RU, bn-IN, ca-ES, es-ES, de-DE, pl-PL, tr-TR`): the 7 enforced (`en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN`) get real translations; the other 7 (`it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR`) get English fallback values (acceptable silent en-US fallback) so `npm run test` stays green.
- New SurrealDB schema = new migration pair `open_notebook/database/migrations/20.surrealql` + `20_down.surrealql`, registered in `AsyncMigrationManager.__init__` (migrations are hard-coded, not auto-discovered).
- Physical SurrealDB table stays `notebook` (P3 repurposes it as "project"); P2 does not touch it.
- Tokens: identity token (P1) vs company-scoped access token (this phase implements `create_access_token`).
- Backend errors: raise typed exceptions from `open_notebook.exceptions`; global handlers in `api/main.py` map them (`NotFoundError`→404, `InvalidInputError`→400, `AuthenticationError`→401, `DuplicateResourceError`→409 [added by P1], `OpenNotebookError`→500). Do NOT raise bare `HTTPException` for domain errors — the only two exceptions in this plan are the two **403** cases (`require_role`, `switch-company`) which the spec explicitly specifies as `HTTPException(status_code=403, ...)` because no typed 403 exception exists in this repo.
- Backend tests: `uv run pytest tests/`. Frontend (inside `frontend/`): `npm run lint`, `npm run test`, `npm run build`.

### P1 interfaces this plan consumes (exact — from docs/.../2026-07-11-p1-auth-users-design.md)
- `api/security.py` (P1 owns the file): `create_identity_token(user_id) -> str`; `decode_identity_token(token) -> str` (returns `sub`, accepts identity OR company-scoped access token, raises `AuthenticationError`); a `create_access_token(user_id, company_id, role, ...)` **stub that P2 implements in Task 3**; `decode_access_token(token) -> AuthContext`; the `AuthContext` dataclass (`user_id: str`, `company_id: str | None`, `role: str | None`). Module-level JWT config it exposes (from `api/auth_config.py`): `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`. **Assumption (stated per PLAN_FORMAT):** these three names are importable from `api.security` (P1 re-exports/imports them there); if P1 named them differently, adjust the two import lines in Task 3 accordingly.
- `api/main.py`: P1 registers a `@app.exception_handler(DuplicateResourceError)` → `409 {"detail": ...}` and swaps `PasswordAuthMiddleware` for `JWTAuthMiddleware` (sets `request.state.user_id`; passes through when `JWT_SECRET` unset). P2 relies on the 409 handler; it does not modify the middleware.
- `open_notebook/exceptions.py`: P1 adds `class DuplicateResourceError(OpenNotebookError)`. P2 raises it for slug collisions.
- Frontend `auth-store` (P1 rewrites `frontend/src/lib/stores/auth-store.ts`): persisted (`partialize`) `token`, `user`, `isAuthenticated`; actions `login`/`register`/`refresh`/`fetchMe`/`logout`; `hasHydrated`/`setHasHydrated`; `name: 'auth-storage'`. P1's `/auth/me` and session payload return `{ user, memberships, needs_onboarding, active_company_id }`. P2 adds the company slice (Task 9).

---

## Task 1: Migration 20 — `company` + `membership` tables

**Files:**
- Create: `open_notebook/database/migrations/20.surrealql`
- Create: `open_notebook/database/migrations/20_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (`AsyncMigrationManager.__init__` — append the 20 entries after the 19 entries P1 added)
- Test: `tests/test_p2_migration_20.py`

**Interfaces:**
- Consumes: the existing `AsyncMigration.from_file` loader (strips `--` comment lines, joins the rest with spaces — so keep every statement `;`-terminated and never put code after an inline `--`).
- Produces: `company` table (`name`, `slug` UNIQUE, `owner record<user>`, `created`/`updated`) and `membership` table (`user record<user>`, `company record<company>`, `role`, `status`, `created`/`updated`) with a UNIQUE `(user, company)` index. The `idx_company_slug` UNIQUE index drives the 409 contract.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_migration_20.py`:
```python
"""Migration 20 (company + membership) is well-formed and registered.

DB-free: mirrors the repo's migration-test style — assert the DDL statements
exist and that AsyncMigrationManager wires the 20th up/down migration. A live
SurrealDB up/down round-trip is out of scope for the unit suite.
"""

from pathlib import Path

from open_notebook.database.async_migrate import AsyncMigration, AsyncMigrationManager

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_20_files_exist():
    assert (MIGRATIONS / "20.surrealql").exists()
    assert (MIGRATIONS / "20_down.surrealql").exists()


def test_migration_20_defines_company_and_membership():
    sql = AsyncMigration.from_file(str(MIGRATIONS / "20.surrealql")).sql
    assert "DEFINE TABLE IF NOT EXISTS company SCHEMAFULL" in sql
    assert "DEFINE FIELD IF NOT EXISTS slug ON TABLE company TYPE string" in sql
    assert "DEFINE FIELD IF NOT EXISTS owner ON TABLE company TYPE record<user>" in sql
    assert "idx_company_slug ON TABLE company FIELDS slug UNIQUE" in sql
    assert "DEFINE TABLE IF NOT EXISTS membership SCHEMAFULL" in sql
    assert "role ON TABLE membership TYPE string" in sql
    assert "idx_membership_user_company ON TABLE membership FIELDS user, company UNIQUE" in sql


def test_migration_20_down_removes_tables():
    sql = AsyncMigration.from_file(str(MIGRATIONS / "20_down.surrealql")).sql
    assert "REMOVE TABLE IF EXISTS membership" in sql
    assert "REMOVE TABLE IF EXISTS company" in sql


def test_migration_20_is_registered():
    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 20
    assert len(manager.down_migrations) == 20
    assert "company" in manager.up_migrations[19].sql
    assert "membership" in manager.down_migrations[19].sql
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_migration_20.py -q` — Expected: FAIL (files don't exist yet: `test_migration_20_files_exist` asserts False; the registration test finds 19 migrations, not 20).

- [ ] **Step 3: Write minimal implementation** —

`open_notebook/database/migrations/20.surrealql`:
```surql
-- Migration 20: company + membership (multi-tenancy identity plane).
-- Identity-plane tables: NOT company-scoped. Login/onboarding must read a
-- user's memberships before any company is active, so these carry no tenant
-- filter; isolation is enforced by explicit user/company filters in the service.

DEFINE TABLE IF NOT EXISTS company SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON TABLE company TYPE string;
DEFINE FIELD IF NOT EXISTS slug ON TABLE company TYPE string;
DEFINE FIELD IF NOT EXISTS owner ON TABLE company TYPE record<user>;
DEFINE FIELD IF NOT EXISTS created ON company DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON company DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_company_slug ON TABLE company FIELDS slug UNIQUE;

DEFINE TABLE IF NOT EXISTS membership SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS user ON TABLE membership TYPE record<user>;
DEFINE FIELD IF NOT EXISTS company ON TABLE membership TYPE record<company>;
DEFINE FIELD IF NOT EXISTS role ON TABLE membership TYPE string ASSERT $value IN ['owner', 'admin', 'member'];
DEFINE FIELD IF NOT EXISTS status ON TABLE membership TYPE string ASSERT $value IN ['active', 'invited', 'revoked'] DEFAULT 'active';
DEFINE FIELD IF NOT EXISTS created ON membership DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON membership DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_membership_user_company ON TABLE membership FIELDS user, company UNIQUE;
```
> Note: each `DEFINE FIELD ... ASSERT ...` statement is kept on ONE line because `AsyncMigration.from_file` joins lines with spaces after stripping `--` comments — a statement split across lines still joins fine, but keeping ASSERT clauses on their own single line avoids any accidental `--` interaction.

`open_notebook/database/migrations/20_down.surrealql`:
```surql
-- Migration 20 rollback: drop membership first (references company), then company.
REMOVE TABLE IF EXISTS membership;
REMOVE TABLE IF EXISTS company;
```

`open_notebook/database/async_migrate.py` — in `AsyncMigrationManager.__init__`, append to `up_migrations` (immediately after the `19.surrealql` entry P1 added, before the closing `]`):
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20.surrealql"
            ),
```
and append to `down_migrations` (after the `19_down.surrealql` entry, before the closing `]`):
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20_down.surrealql"
            ),
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_migration_20.py -q` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/database/migrations/20.surrealql open_notebook/database/migrations/20_down.surrealql open_notebook/database/async_migrate.py tests/test_p2_migration_20.py && git commit -m "P2: migration 20 — company + membership tables"`

---

## Task 2: Domain models `Company` + `Membership`

**Files:**
- Create: `open_notebook/domain/company.py`
- Modify: `open_notebook/domain/__init__.py`
- Test: `tests/test_p2_domain_company.py`

**Interfaces:**
- Consumes: `ObjectModel` (from `open_notebook/domain/base.py`) — provides `save()`/`get()`/`get_all()`/`delete()` and `created`/`updated`; `ensure_record_id` (from `open_notebook/database/repository.py`).
- Produces: `Company(name, slug, owner)` and `Membership(user, company, role, status="active")`, both with `table_name` ClassVars so `ObjectModel.get()` polymorphic resolution finds them. Both override `_prepare_save_data` to persist record-link fields (`owner`, `user`, `company`) as `RecordID` (so SurrealDB `record<...>` fields type-check).

- [ ] **Step 1: Write the failing test** — `tests/test_p2_domain_company.py`:
```python
"""Unit tests for Company / Membership domain models (DB-free)."""

from surrealdb import RecordID

from open_notebook.domain.base import ObjectModel
from open_notebook.domain.company import Company, Membership


def test_company_fields_and_table_name():
    c = Company(name="Acme Inc", slug="acme-inc", owner="user:abc")
    assert c.table_name == "company"
    assert c.name == "Acme Inc"
    assert c.slug == "acme-inc"
    assert c.owner == "user:abc"


def test_membership_defaults_active():
    m = Membership(user="user:abc", company="company:xyz", role="owner")
    assert m.table_name == "membership"
    assert m.status == "active"
    assert m.role == "owner"


def test_company_prepare_save_converts_owner_to_record_id():
    data = Company(name="Acme", slug="acme", owner="user:abc")._prepare_save_data()
    assert isinstance(data["owner"], RecordID)
    assert str(data["owner"]) == "user:abc"


def test_membership_prepare_save_converts_links_to_record_id():
    data = Membership(
        user="user:abc", company="company:xyz", role="member"
    )._prepare_save_data()
    assert isinstance(data["user"], RecordID)
    assert isinstance(data["company"], RecordID)
    assert str(data["user"]) == "user:abc"
    assert str(data["company"]) == "company:xyz"


def test_polymorphic_resolution_registers_subclasses():
    # ObjectModel.get() resolves by table_name prefix; importing company.py must
    # register both subclasses so get("company:...") / get("membership:...") work.
    assert ObjectModel._get_class_by_table_name("company") is Company
    assert ObjectModel._get_class_by_table_name("membership") is Membership
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_domain_company.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'open_notebook.domain.company'`.

- [ ] **Step 3: Write minimal implementation** —

`open_notebook/domain/company.py`:
```python
from typing import Any, ClassVar, Dict

from open_notebook.database.repository import ensure_record_id
from open_notebook.domain.base import ObjectModel


class Company(ObjectModel):
    table_name: ClassVar[str] = "company"
    name: str
    slug: str
    owner: str  # "user:<id>" record link

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("owner") is not None:
            data["owner"] = ensure_record_id(data["owner"])
        return data


class Membership(ObjectModel):
    table_name: ClassVar[str] = "membership"
    user: str  # "user:<id>" record link
    company: str  # "company:<id>" record link
    role: str  # owner | admin | member
    status: str = "active"  # active | invited | revoked

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("user") is not None:
            data["user"] = ensure_record_id(data["user"])
        if data.get("company") is not None:
            data["company"] = ensure_record_id(data["company"])
        return data
```

`open_notebook/domain/__init__.py` — replace the body so the subclasses are imported at package import time (belt-and-suspenders for polymorphic `get()`):
```python
"""
Domain models for Open Notebook.

This module exports the core domain models used throughout the application.
"""

from open_notebook.domain.company import Company, Membership

__all__: list[str] = ["Company", "Membership"]
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_domain_company.py -q` — Expected: PASS (5 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/domain/company.py open_notebook/domain/__init__.py tests/test_p2_domain_company.py && git commit -m "P2: Company + Membership domain models"`

---

## Task 3: Implement `create_access_token` in `api/security.py`

**Files:**
- Modify: `api/security.py` (replace P1's `create_access_token` stub with a real implementation)
- Test: `tests/test_p2_access_token.py`

**Interfaces:**
- Consumes: `jwt` (`from jose import jwt`), `AuthenticationError`, and module-level `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` (already present in `api/security.py` after P1). `decode_access_token(token) -> AuthContext` (P1).
- Produces: `create_access_token(user_id, company_id, role, minutes=None) -> str` — a JWT with claims `sub`, `company_id`, `role`, `type="access"`, `exp`. Round-trips through `decode_access_token` into an `AuthContext` with populated `company_id`/`role`.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_access_token.py`:
```python
"""create_access_token mints a company-scoped token decode_access_token reads."""

import os

# Ensure a JWT secret exists before importing the security module (it reads
# config at import time). Mirrors tests/conftest.py's env-first pattern.
os.environ.setdefault("JWT_SECRET", "test-secret-p2-access-token")

import pytest

from api.security import create_access_token, decode_access_token
from open_notebook.exceptions import AuthenticationError


def test_access_token_round_trips_company_and_role():
    token = create_access_token(
        user_id="user:abc", company_id="company:xyz", role="owner"
    )
    ctx = decode_access_token(token)
    assert ctx.user_id == "user:abc"
    assert ctx.company_id == "company:xyz"
    assert ctx.role == "owner"


def test_access_token_rejects_non_user_subject():
    with pytest.raises(AuthenticationError):
        create_access_token(user_id="abc", company_id="company:xyz", role="owner")


def test_access_token_rejects_non_company_scope():
    with pytest.raises(AuthenticationError):
        create_access_token(user_id="user:abc", company_id="xyz", role="owner")
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_access_token.py -q` — Expected: FAIL — P1's stub raises `NotImplementedError`, so `test_access_token_round_trips_company_and_role` errors.

- [ ] **Step 3: Write minimal implementation** — In `api/security.py`, replace the `create_access_token` stub with:
```python
def create_access_token(
    user_id: str,
    company_id: str,
    role: str,
    minutes: int | None = None,
) -> str:
    """Company-scoped access token (claims: sub, company_id, role).

    SurrealDB record ids are strings like ``user:abc`` / ``company:xyz`` (not
    UUIDs), so validate the prefix instead of the arteamis-system UUID check.
    """
    if not isinstance(user_id, str) or not user_id.startswith("user:"):
        raise AuthenticationError("Access token subject must be a user record id")
    if not isinstance(company_id, str) or not company_id.startswith("company:"):
        raise AuthenticationError("Access token company must be a company record id")
    mins = ACCESS_TOKEN_EXPIRE_MINUTES if minutes is None else minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=mins)
    payload = {
        "sub": user_id,
        "company_id": company_id,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
```
> If P1's file does not already `from datetime import datetime, timedelta, timezone`, add it (the identity-token helper needs the same imports, so it is almost certainly present).

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_access_token.py -q` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add api/security.py tests/test_p2_access_token.py && git commit -m "P2: implement company-scoped create_access_token"`

---

## Task 4: `api/deps.py` — `get_identity`, `get_auth_context`, `require_role`

**Files:**
- Create: `api/deps.py`
- Test: `tests/test_p2_deps.py`

**Interfaces:**
- Consumes: `decode_identity_token`, `decode_access_token`, `AuthContext` (from `api.security`); `AuthenticationError`.
- Produces:
  - `get_identity(creds) -> str` — user_id from an identity OR access token (the pre-company dependency). 401 on missing/invalid token.
  - `get_auth_context(creds) -> AuthContext` — requires a **company-scoped** token; 401 if the token carries no `company_id`/`role` (i.e. an identity-only token).
  - `require_role(*roles)` — dependency factory returning a dep that 403s if `AuthContext.role` not in `roles`. Reused unchanged by P3+.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_deps.py`:
```python
"""Unit tests for the auth dependencies in api/deps.py."""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-p2-deps")

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.deps import get_auth_context, get_identity, require_role
from api.security import (
    AuthContext,
    create_access_token,
    create_identity_token,
)
from open_notebook.exceptions import AuthenticationError


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_get_identity_accepts_identity_token():
    token = create_identity_token("user:abc")
    assert await get_identity(_creds(token)) == "user:abc"


@pytest.mark.asyncio
async def test_get_identity_missing_header_401():
    with pytest.raises(AuthenticationError):
        await get_identity(None)


@pytest.mark.asyncio
async def test_get_auth_context_requires_company_scope():
    # An identity-only token has no company_id -> get_auth_context rejects it.
    token = create_identity_token("user:abc")
    with pytest.raises(AuthenticationError):
        await get_auth_context(_creds(token))


@pytest.mark.asyncio
async def test_get_auth_context_accepts_access_token():
    token = create_access_token("user:abc", "company:xyz", "owner")
    ctx = await get_auth_context(_creds(token))
    assert ctx.company_id == "company:xyz"
    assert ctx.role == "owner"


@pytest.mark.asyncio
async def test_require_role_allows_matching_role():
    dep = require_role("owner", "admin")
    ctx = AuthContext(user_id="user:abc", company_id="company:xyz", role="owner")
    assert await dep(ctx) is ctx


@pytest.mark.asyncio
async def test_require_role_forbids_other_role():
    dep = require_role("owner", "admin")
    ctx = AuthContext(user_id="user:abc", company_id="company:xyz", role="member")
    with pytest.raises(HTTPException) as exc:
        await dep(ctx)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_deps.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'api.deps'`.

- [ ] **Step 3: Write minimal implementation** — `api/deps.py`:
```python
"""Shared FastAPI auth dependencies for the multi-tenancy layer.

Introduced by P2; P6 later extends this module with require_company /
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
    """user_id from an identity OR company-scoped access token (pre-company dep)."""
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
    """Require a company-scoped access token; 401 for an identity-only token."""
    if creds is None:
        raise AuthenticationError("Missing authorization header")
    try:
        ctx = decode_access_token(creds.credentials)
    except AuthenticationError:
        raise
    except Exception as e:
        raise AuthenticationError(f"Invalid token: {e}")
    if ctx.company_id is None or ctx.role is None:
        raise AuthenticationError("A company-scoped access token is required")
    return ctx


def require_role(*roles: str):
    """Dependency factory: 403 unless the caller's token role is in `roles`.

    The role is baked into the access token at create/switch time and never
    read from a client-supplied value. Used by P3+ (e.g. project create).
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
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_deps.py -q` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add api/deps.py tests/test_p2_deps.py && git commit -m "P2: api/deps.py — get_identity, get_auth_context, require_role"`

---

## Task 5: `api/company_service.py` — slug + company/membership logic

**Files:**
- Create: `api/company_service.py`
- Test: `tests/test_p2_company_service.py`

**Interfaces:**
- Consumes: `Company`, `Membership` (Task 2); `repo_query`, `ensure_record_id` (repository); `DuplicateResourceError`, `DatabaseOperationError` (exceptions). `Company.save()`/`Membership.save()` internally call `repo_create` (from `open_notebook.database.base`… actually `open_notebook.domain.base.repo_create`).
- Produces:
  - `slugify(name) -> str` — lower-case, `[^a-z0-9]+ → "-"`, strip dashes, truncate to 40; empty → `"company"`.
  - `async create_company(user_id, name, slug=None) -> tuple[Company, Membership]` — saves company (409 on slug collision) + owner membership; best-effort deletes the company if membership save fails.
  - `async list_memberships(user_id) -> list[dict]` — active memberships joined to company: `{company_id, name, slug, role, created, updated}`.
  - `async get_membership(user_id, company_id) -> Optional[Membership]` — single-row lookup (status not filtered here; the caller checks `status`).

- [ ] **Step 1: Write the failing test** — `tests/test_p2_company_service.py`:
```python
"""Unit tests for api/company_service.py (repo layer mocked)."""

from unittest.mock import AsyncMock, patch

import pytest

from api.company_service import (
    create_company,
    get_membership,
    list_memberships,
    slugify,
)
from open_notebook.domain.company import Membership
from open_notebook.exceptions import DuplicateResourceError


def test_slugify_basic():
    assert slugify("Acme Inc.") == "acme-inc"
    assert slugify("  Hello   World!! ") == "hello-world"
    assert slugify("") == "company"
    assert slugify("!!!") == "company"
    assert len(slugify("x" * 100)) == 40


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_company_creates_owner_membership(mock_create):
    # First repo_create -> company row; second -> membership row.
    mock_create.side_effect = [
        [{
            "id": "company:acme",
            "name": "Acme",
            "slug": "acme",
            "owner": "user:1",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }],
        [{
            "id": "membership:1",
            "user": "user:1",
            "company": "company:acme",
            "role": "owner",
            "status": "active",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }],
    ]
    company, membership = await create_company("user:1", "Acme")
    assert company.id == "company:acme"
    assert company.slug == "acme"
    assert membership.role == "owner"
    assert membership.status == "active"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_company_slug_collision_raises_duplicate(mock_create):
    mock_create.side_effect = RuntimeError(
        "Database index `idx_company_slug` already contains 'acme'"
    )
    with pytest.raises(DuplicateResourceError):
        await create_company("user:1", "Acme")


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_delete", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_company_orphan_cleanup_on_membership_failure(
    mock_create, mock_delete
):
    mock_create.side_effect = [
        [{"id": "company:acme", "name": "Acme", "slug": "acme", "owner": "user:1"}],
        RuntimeError("boom"),
    ]
    with pytest.raises(RuntimeError):
        await create_company("user:1", "Acme")
    mock_delete.assert_awaited()  # company was cleaned up


@pytest.mark.asyncio
@patch("api.company_service.repo_query", new_callable=AsyncMock)
async def test_list_memberships_maps_rows(mock_query):
    mock_query.return_value = [
        {
            "role": "owner",
            "company": {
                "id": "company:acme",
                "name": "Acme",
                "slug": "acme",
                "created": "2026-07-11T00:00:00Z",
                "updated": "2026-07-11T00:00:00Z",
            },
        }
    ]
    rows = await list_memberships("user:1")
    assert rows == [{
        "company_id": "company:acme",
        "name": "Acme",
        "slug": "acme",
        "role": "owner",
        "created": "2026-07-11T00:00:00Z",
        "updated": "2026-07-11T00:00:00Z",
    }]
    # Isolation: the query filters by the caller's user id.
    assert "WHERE user = $user" in mock_query.await_args.args[0]


@pytest.mark.asyncio
@patch("api.company_service.repo_query", new_callable=AsyncMock)
async def test_get_membership_returns_none_when_absent(mock_query):
    mock_query.return_value = []
    assert await get_membership("user:1", "company:acme") is None


@pytest.mark.asyncio
@patch("api.company_service.repo_query", new_callable=AsyncMock)
async def test_get_membership_returns_membership(mock_query):
    mock_query.return_value = [{
        "id": "membership:1",
        "user": "user:1",
        "company": "company:acme",
        "role": "member",
        "status": "active",
    }]
    m = await get_membership("user:1", "company:acme")
    assert isinstance(m, Membership)
    assert m.role == "member"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_company_service.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'api.company_service'`.

- [ ] **Step 3: Write minimal implementation** — `api/company_service.py`:
```python
"""Company + membership business logic (routers stay thin, per api/AGENTS.md).

Identity-plane: every read filters explicitly by the caller's user id — there is
no SurrealDB RLS to fall back on. P2 only ever writes an `active` `owner`
membership; `invited`/`revoked` and other roles arrive with P4.
"""

import re
from typing import List, Optional, Tuple

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.company import Company, Membership
from open_notebook.exceptions import DuplicateResourceError

_SLUG_SUB = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Human-readable slug: lower-case, non-alphanumeric -> '-', trimmed, <=40.

    Lifted from arteamis-system companies._slugify but WITHOUT the random uuid
    suffix — we keep slugs clean and let the unique index reject collisions (409).
    """
    base = _SLUG_SUB.sub("-", name.strip().lower()).strip("-")
    base = base[:40].strip("-")
    return base or "company"


def _is_slug_conflict(error: Exception) -> bool:
    msg = str(error)
    return "idx_company_slug" in msg or "already contains" in msg


async def create_company(
    user_id: str, name: str, slug: Optional[str] = None
) -> Tuple[Company, Membership]:
    """Create a company + its owner membership. 409 on slug collision."""
    slug_value = slugify(slug) if slug else slugify(name)

    company = Company(name=name, slug=slug_value, owner=user_id)
    try:
        await company.save()
    except Exception as e:
        if _is_slug_conflict(e):
            raise DuplicateResourceError("Company slug already exists")
        raise

    try:
        membership = Membership(
            user=user_id, company=company.id or "", role="owner", status="active"
        )
        await membership.save()
    except Exception:
        # Best-effort: avoid an orphan company if the membership write fails.
        try:
            await company.delete()
        except Exception as ce:  # pragma: no cover - cleanup best effort
            logger.warning(f"Failed to clean up orphan company {company.id}: {ce}")
        raise

    return company, membership


async def list_memberships(user_id: str) -> List[dict]:
    """Active memberships for a user, each with its company's name/slug/role."""
    rows = await repo_query(
        "SELECT role, company FROM membership "
        "WHERE user = $user AND status = 'active' "
        "ORDER BY created ASC FETCH company",
        {"user": ensure_record_id(user_id)},
    )
    result: List[dict] = []
    for row in rows:
        company = row.get("company")
        if not isinstance(company, dict):
            continue
        result.append(
            {
                "company_id": str(company.get("id", "")),
                "name": company.get("name", ""),
                "slug": company.get("slug", ""),
                "role": row.get("role", "member"),
                "created": str(company.get("created", "")),
                "updated": str(company.get("updated", "")),
            }
        )
    return result


async def get_membership(user_id: str, company_id: str) -> Optional[Membership]:
    """Single-row membership lookup on the (user, company) unique index.

    Status is NOT filtered here — the caller (switch-company) inspects
    `membership.status` so it can distinguish 'not a member' from 'revoked'.
    """
    rows = await repo_query(
        "SELECT * FROM membership WHERE user = $user AND company = $company LIMIT 1",
        {
            "user": ensure_record_id(user_id),
            "company": ensure_record_id(company_id),
        },
    )
    if not rows:
        return None
    return Membership(**rows[0])
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_company_service.py -q` — Expected: PASS (8 passed).

- [ ] **Step 5: Commit** — `git add api/company_service.py tests/test_p2_company_service.py && git commit -m "P2: company_service (slugify, create/list/get)"`

---

## Task 6: Schemas + `POST /companies` + `GET /companies` router

**Files:**
- Modify: `api/models.py` (append `CompanyCreate`, `CompanyResponse`, `TokenResponse`)
- Create: `api/routers/companies.py`
- Modify: `api/main.py` (import + register the companies router)
- Test: `tests/test_p2_companies_router.py`

**Interfaces:**
- Consumes: `get_identity` (Task 4); `create_company`, `list_memberships` (Task 5); `create_access_token` (Task 3); the new schemas.
- Produces: `POST /api/companies` (201 → `TokenResponse` with a freshly minted owner access token) and `GET /api/companies` (→ `List[CompanyResponse]`, caller's active memberships only). Slug collisions raise `DuplicateResourceError` → 409 (P1 handler).

- [ ] **Step 1: Write the failing test** — `tests/test_p2_companies_router.py`:
```python
"""API tests for POST/GET /companies (service + token minting exercised)."""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-p2-router")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token, decode_access_token
from open_notebook.domain.company import Company, Membership
from open_notebook.exceptions import DuplicateResourceError


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _auth(user_id: str = "user:1") -> dict:
    return {"Authorization": f"Bearer {create_identity_token(user_id)}"}


@patch("api.routers.companies.create_company", new_callable=AsyncMock)
def test_create_company_returns_owner_token(mock_create, client):
    company = Company(id="company:acme", name="Acme", slug="acme", owner="user:1")
    membership = Membership(
        id="membership:1", user="user:1", company="company:acme", role="owner"
    )
    mock_create.return_value = (company, membership)

    resp = client.post("/api/companies", json={"name": "Acme"}, headers=_auth())

    assert resp.status_code == 201
    body = resp.json()
    assert body["active_company_id"] == "company:acme"
    assert body["role"] == "owner"
    ctx = decode_access_token(body["access_token"])
    assert ctx.user_id == "user:1"
    assert ctx.company_id == "company:acme"
    assert ctx.role == "owner"
    mock_create.assert_awaited_once_with("user:1", "Acme", None)


@patch("api.routers.companies.create_company", new_callable=AsyncMock)
def test_create_company_slug_conflict_returns_409(mock_create, client):
    mock_create.side_effect = DuplicateResourceError("Company slug already exists")
    resp = client.post("/api/companies", json={"name": "Acme"}, headers=_auth())
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Company slug already exists"


def test_create_company_requires_auth(client):
    assert client.post("/api/companies", json={"name": "Acme"}).status_code == 401


def test_create_company_empty_name_422(client):
    resp = client.post("/api/companies", json={"name": ""}, headers=_auth())
    assert resp.status_code == 422


@patch("api.routers.companies.list_memberships", new_callable=AsyncMock)
def test_list_companies_returns_only_callers_memberships(mock_list, client):
    mock_list.return_value = [
        {
            "company_id": "company:acme",
            "name": "Acme",
            "slug": "acme",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]
    resp = client.get("/api/companies", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "id": "company:acme",
            "name": "Acme",
            "slug": "acme",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]
    mock_list.assert_awaited_once_with("user:1")


@patch("api.routers.companies.list_memberships", new_callable=AsyncMock)
def test_list_companies_empty_when_none(mock_list, client):
    mock_list.return_value = []
    resp = client.get("/api/companies", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_companies_router.py -q` — Expected: FAIL — `api.routers.companies` does not exist yet (import error inside `api.main`), or 404 on the routes.

- [ ] **Step 3: Write minimal implementation** —

`api/models.py` — append (the file already imports `BaseModel`, `Field`, and `Optional`; if `Optional` is not imported there, add `from typing import Optional`):
```python
class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: Optional[str] = None  # optional explicit slug; else derived from name


class CompanyResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str  # caller's role in this company
    created: str
    updated: str


class TokenResponse(BaseModel):  # returned by company create + switch-company
    access_token: str
    token_type: str = "bearer"
    active_company_id: str
    role: str
```

`api/routers/companies.py`:
```python
from typing import List

from fastapi import APIRouter, Depends

from api.company_service import create_company, list_memberships
from api.deps import get_identity
from api.models import CompanyCreate, CompanyResponse, TokenResponse
from api.security import create_access_token

router = APIRouter()


@router.post("/companies", response_model=TokenResponse, status_code=201)
async def create_company_endpoint(
    body: CompanyCreate,
    user_id: str = Depends(get_identity),
) -> TokenResponse:
    """Create a company; the caller becomes its owner.

    Open to any authenticated user (incl. one with 0 companies — you cannot
    require a role you do not yet have). Re-mints a company-scoped `owner`
    access token so the very next request (P3 project create) is scoped.
    A slug collision raises DuplicateResourceError -> 409 (global handler).
    """
    company, membership = await create_company(user_id, body.name, body.slug)
    access_token = create_access_token(
        user_id=user_id,
        company_id=company.id or "",
        role=membership.role,
    )
    return TokenResponse(
        access_token=access_token,
        active_company_id=company.id or "",
        role=membership.role,
    )


@router.get("/companies", response_model=List[CompanyResponse])
async def list_companies_endpoint(
    user_id: str = Depends(get_identity),
) -> List[CompanyResponse]:
    """List the caller's active memberships (empty pre-company)."""
    rows = await list_memberships(user_id)
    return [
        CompanyResponse(
            id=row["company_id"],
            name=row["name"],
            slug=row["slug"],
            role=row["role"],
            created=row["created"],
            updated=row["updated"],
        )
        for row in rows
    ]
```

`api/main.py` — add `companies` to the routers import block (alphabetical, next to `commands`/`config`):
```python
from api.routers import (
    auth,
    chat,
    companies,
    config,
    context,
    credentials,
    embedding,
    embedding_rebuild,
    episode_profiles,
    insights,
    languages,
    models,
    notebooks,
    notes,
    podcasts,
    search,
    settings,
    source_chat,
    sources,
    speaker_profiles,
    transformations,
)
```
and register it alongside the other `app.include_router(...)` calls (e.g. right after the `auth` router):
```python
app.include_router(companies.router, prefix="/api", tags=["companies"])
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_companies_router.py -q` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add api/models.py api/routers/companies.py api/main.py tests/test_p2_companies_router.py && git commit -m "P2: /companies create + list endpoints"`

---

## Task 7: `POST /auth/switch-company/{company_id}` endpoint

**Files:**
- Modify: `api/routers/auth.py` (add the switch-company endpoint — P1 owns this file; P2 adds one route)
- Test: `tests/test_p2_switch_company.py`

**Interfaces:**
- Consumes: `get_identity` (Task 4); `get_membership` (Task 5); `create_access_token` (Task 3); `TokenResponse` (Task 6).
- Produces: `POST /api/auth/switch-company/{company_id}` — 403 if the caller has no membership in `{company_id}` or its `status != 'active'`; else 200 with a re-minted company-scoped `TokenResponse`.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_switch_company.py`:
```python
"""API tests for POST /auth/switch-company/{company_id}."""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-p2-switch")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token, decode_access_token
from open_notebook.domain.company import Membership


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _auth(user_id: str = "user:1") -> dict:
    return {"Authorization": f"Bearer {create_identity_token(user_id)}"}


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_company_member_gets_scoped_token(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:1",
        user="user:1",
        company="company:acme",
        role="member",
        status="active",
    )
    resp = client.post("/api/auth/switch-company/company:acme", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_company_id"] == "company:acme"
    assert body["role"] == "member"
    ctx = decode_access_token(body["access_token"])
    assert ctx.company_id == "company:acme"
    assert ctx.role == "member"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_company_non_member_403(mock_get, client):
    mock_get.return_value = None
    resp = client.post("/api/auth/switch-company/company:other", headers=_auth())
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a member of this company"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_company_revoked_membership_403(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:1",
        user="user:1",
        company="company:acme",
        role="member",
        status="revoked",
    )
    resp = client.post("/api/auth/switch-company/company:acme", headers=_auth())
    assert resp.status_code == 403


def test_switch_company_requires_auth(client):
    assert client.post("/api/auth/switch-company/company:acme").status_code == 401
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_switch_company.py -q` — Expected: FAIL — the route does not exist (404) so the 200/403 assertions fail.

- [ ] **Step 3: Write minimal implementation** — In `api/routers/auth.py`, add these imports (merge with P1's existing imports) and endpoint:
```python
from fastapi import Depends, HTTPException

from api.company_service import get_membership
from api.deps import get_identity
from api.models import TokenResponse
from api.security import create_access_token


@router.post("/switch-company/{company_id}", response_model=TokenResponse)
async def switch_company(
    company_id: str,
    user_id: str = Depends(get_identity),
) -> TokenResponse:
    """Re-mint a company-scoped token after re-verifying membership server-side.

    Never trusts a client-sent role: the role comes from the freshly-loaded
    membership. A non-member or a non-active (invited/revoked) membership -> 403.
    """
    membership = await get_membership(user_id, company_id)
    if membership is None or membership.status != "active":
        raise HTTPException(status_code=403, detail="Not a member of this company")
    access_token = create_access_token(
        user_id=user_id,
        company_id=company_id,
        role=membership.role,
    )
    return TokenResponse(
        access_token=access_token,
        active_company_id=company_id,
        role=membership.role,
    )
```
> The router is mounted at `prefix="/api"` with the router's own `prefix="/auth"`, so the full path is `/api/auth/switch-company/{company_id}`. It is NOT in P1's `JWTAuthMiddleware` excluded-paths list, so the middleware requires a valid token before the handler runs — consistent with `get_identity`.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_switch_company.py -q` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add api/routers/auth.py tests/test_p2_switch_company.py && git commit -m "P2: /auth/switch-company endpoint"`

- [ ] **Step 6: Run the full backend suite** — Run: `uv run pytest tests/ -q` — Expected: PASS (all P2 tests green, no regressions). Then `ruff check . --fix`.

---

## Task 8: Frontend API module + types + query key

**Files:**
- Modify: `frontend/src/lib/types/api.ts` (append company types)
- Create: `frontend/src/lib/api/companies.ts`
- Modify: `frontend/src/lib/api/query-client.ts` (add `companies` query key)
- Test: `frontend/src/lib/api/companies.test.ts`

**Interfaces:**
- Consumes: the shared `apiClient` (`frontend/src/lib/api/client.ts`).
- Produces: `companiesApi.list()` → `CompanyResponse[]`, `companiesApi.create(data)` → `TokenResponse`, `companiesApi.switch(companyId)` → `TokenResponse`; types `CompanyResponse`, `CreateCompanyRequest`, `TokenResponse`, `Membership`; `QUERY_KEYS.companies`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/api/companies.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { companiesApi } from './companies'
import apiClient from './client'

vi.mock('./client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

describe('companiesApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('list GETs /companies', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [{ id: 'company:1' }] })
    const res = await companiesApi.list()
    expect(apiClient.get).toHaveBeenCalledWith('/companies')
    expect(res).toEqual([{ id: 'company:1' }])
  })

  it('create POSTs /companies with the body', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { access_token: 't', token_type: 'bearer', active_company_id: 'company:1', role: 'owner' },
    })
    const res = await companiesApi.create({ name: 'Acme' })
    expect(apiClient.post).toHaveBeenCalledWith('/companies', { name: 'Acme' })
    expect(res.active_company_id).toBe('company:1')
  })

  it('switch POSTs the switch-company path', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { access_token: 't', token_type: 'bearer', active_company_id: 'company:1', role: 'member' },
    })
    await companiesApi.switch('company:1')
    expect(apiClient.post).toHaveBeenCalledWith('/auth/switch-company/company:1')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- companies` — Expected: FAIL — cannot resolve `./companies`.

- [ ] **Step 3: Write minimal implementation** —

`frontend/src/lib/types/api.ts` — append:
```ts
export interface CompanyResponse {
  id: string
  name: string
  slug: string
  role: string
  created: string
  updated: string
}

export interface CreateCompanyRequest {
  name: string
  slug?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  active_company_id: string
  role: string
}

// Shape of each row in the auth store's `memberships` (from GET /auth/me and
// company_service.list_memberships).
export interface Membership {
  company_id: string
  name: string
  slug: string
  role: string
}
```

`frontend/src/lib/api/companies.ts`:
```ts
import apiClient from './client'
import { CompanyResponse, CreateCompanyRequest, TokenResponse } from '@/lib/types/api'

export const companiesApi = {
  list: () => apiClient.get<CompanyResponse[]>('/companies').then((r) => r.data),
  create: (data: CreateCompanyRequest) =>
    apiClient.post<TokenResponse>('/companies', data).then((r) => r.data),
  switch: (companyId: string) =>
    apiClient.post<TokenResponse>(`/auth/switch-company/${companyId}`).then((r) => r.data),
}
```

`frontend/src/lib/api/query-client.ts` — add to `QUERY_KEYS` (before the closing `}`):
```ts
  companies: ['companies'] as const,
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- companies` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/types/api.ts frontend/src/lib/api/companies.ts frontend/src/lib/api/query-client.ts frontend/src/lib/api/companies.test.ts && git commit -m "P2: frontend companies api + types + query key"`

---

## Task 9: Auth-store company slice (`applyToken`, `setSession`, memberships)

**Files:**
- Modify: `frontend/src/lib/stores/auth-store.ts` (extend the P1-rewritten store)
- Test: `frontend/src/lib/stores/auth-store.company.test.ts`

**Interfaces:**
- Consumes: `Membership`, `TokenResponse` (Task 8). Assumes P1's store already holds `token`, `user`, `isAuthenticated`, `hasHydrated` and persists (`partialize`) `token`/`user`/`isAuthenticated` under `name: 'auth-storage'`.
- Produces (added to the store): state `memberships: Membership[]`, `activeCompanyId: string | null`, `role: string | null`; actions `applyToken(res)`, `setSession({ memberships })`, `setActiveCompany(companyId, role)`; extended `partialize` persisting `memberships`/`activeCompanyId`/`role`. A component computes `needsOnboarding = isAuthenticated && memberships.length === 0` from these.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/stores/auth-store.company.test.ts`:
```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from './auth-store'

describe('auth-store company slice', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      memberships: [],
      activeCompanyId: null,
      role: null,
    })
  })

  it('applyToken swaps token, activeCompanyId and role', () => {
    useAuthStore.getState().applyToken({
      access_token: 'scoped-token',
      token_type: 'bearer',
      active_company_id: 'company:acme',
      role: 'owner',
    })
    const s = useAuthStore.getState()
    expect(s.token).toBe('scoped-token')
    expect(s.activeCompanyId).toBe('company:acme')
    expect(s.role).toBe('owner')
  })

  it('setSession derives activeCompanyId + role from the first membership', () => {
    useAuthStore.getState().setSession({
      memberships: [
        { company_id: 'company:a', name: 'A', slug: 'a', role: 'owner' },
        { company_id: 'company:b', name: 'B', slug: 'b', role: 'member' },
      ],
    })
    const s = useAuthStore.getState()
    expect(s.memberships).toHaveLength(2)
    expect(s.activeCompanyId).toBe('company:a')
    expect(s.role).toBe('owner')
  })

  it('setSession with no memberships leaves activeCompanyId null', () => {
    useAuthStore.getState().setSession({ memberships: [] })
    const s = useAuthStore.getState()
    expect(s.activeCompanyId).toBeNull()
    expect(s.role).toBeNull()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- auth-store.company` — Expected: FAIL — `applyToken`/`setSession` are not functions.

- [ ] **Step 3: Write minimal implementation** — In `frontend/src/lib/stores/auth-store.ts` (the P1 version), merge in the company slice:

1. Import the types at the top:
```ts
import { Membership, TokenResponse } from '@/lib/types/api'
```
2. Add to the `AuthState` interface:
```ts
  memberships: Membership[]
  activeCompanyId: string | null
  role: string | null
  applyToken: (res: TokenResponse) => void
  setSession: (payload: { memberships: Membership[] }) => void
  setActiveCompany: (companyId: string, role: string) => void
```
3. Add to the store's initial state object:
```ts
      memberships: [],
      activeCompanyId: null,
      role: null,
```
4. Add the three actions inside the `(set, get) => ({ ... })` body:
```ts
      applyToken: (res: TokenResponse) => {
        // The single mutation shared by company create + switch: swap the stored
        // Bearer to the company-scoped access token (apiClient reads state.token).
        set({
          token: res.access_token,
          activeCompanyId: res.active_company_id,
          role: res.role,
        })
      },

      setSession: ({ memberships }: { memberships: Membership[] }) => {
        const first = memberships[0] ?? null
        set({
          memberships,
          activeCompanyId: first ? first.company_id : null,
          role: first ? first.role : null,
        })
      },

      setActiveCompany: (companyId: string, role: string) => {
        set({ activeCompanyId: companyId, role })
      },
```
5. Extend `partialize` to persist the company slice (a company change must survive reload):
```ts
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        memberships: state.memberships,
        activeCompanyId: state.activeCompanyId,
        role: state.role,
      }),
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- auth-store.company` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/stores/auth-store.ts frontend/src/lib/stores/auth-store.company.test.ts && git commit -m "P2: auth-store company slice (applyToken/setSession)"`

---

## Task 10: `useCompanies` / `useCreateCompany` / `useSwitchCompany` hooks

**Files:**
- Create: `frontend/src/lib/hooks/use-companies.ts`
- Test: `frontend/src/lib/hooks/use-companies.test.tsx`

**Interfaces:**
- Consumes: `companiesApi` (Task 8); `QUERY_KEYS.companies`; `useAuthStore.applyToken` (Task 9); `useToast`, `useTranslation`.
- Produces: `useCompanies()` (query), `useCreateCompany()` (mutation → `applyToken` + invalidate + toast; 409 → `company.slugTaken`), `useSwitchCompany()` (mutation → `applyToken` + `queryClient.clear()` + navigate).

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/hooks/use-companies.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useCreateCompany, useSwitchCompany } from './use-companies'
import { companiesApi } from '@/lib/api/companies'
import { useAuthStore } from '@/lib/stores/auth-store'

vi.mock('@/lib/api/companies', () => ({
  companiesApi: { list: vi.fn(), create: vi.fn(), switch: vi.fn() },
}))
vi.mock('@/lib/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))

const wrapper = (client: QueryClient) =>
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }

describe('use-companies', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({ token: null, activeCompanyId: null, role: null })
  })

  it('useCreateCompany success applies the token to the store', async () => {
    vi.mocked(companiesApi.create).mockResolvedValue({
      access_token: 'scoped', token_type: 'bearer', active_company_id: 'company:1', role: 'owner',
    })
    const client = new QueryClient()
    const { result } = renderHook(() => useCreateCompany(), { wrapper: wrapper(client) })
    result.current.mutate({ name: 'Acme' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(useAuthStore.getState().token).toBe('scoped')
    expect(useAuthStore.getState().activeCompanyId).toBe('company:1')
  })

  it('useSwitchCompany success applies the token and clears the cache', async () => {
    vi.mocked(companiesApi.switch).mockResolvedValue({
      access_token: 'scoped2', token_type: 'bearer', active_company_id: 'company:2', role: 'member',
    })
    const client = new QueryClient()
    const clearSpy = vi.spyOn(client, 'clear')
    const { result } = renderHook(() => useSwitchCompany(), { wrapper: wrapper(client) })
    result.current.mutate('company:2')
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(useAuthStore.getState().token).toBe('scoped2')
    expect(clearSpy).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- use-companies` — Expected: FAIL — cannot resolve `./use-companies`.

- [ ] **Step 3: Write minimal implementation** — `frontend/src/lib/hooks/use-companies.ts`:
```tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { AxiosError } from 'axios'
import { companiesApi } from '@/lib/api/companies'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateCompanyRequest } from '@/lib/types/api'

export function useCompanies() {
  return useQuery({
    queryKey: QUERY_KEYS.companies,
    queryFn: () => companiesApi.list(),
  })
}

export function useCreateCompany() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const applyToken = useAuthStore((s) => s.applyToken)

  return useMutation({
    mutationFn: (data: CreateCompanyRequest) => companiesApi.create(data),
    onSuccess: (res) => {
      applyToken(res)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.companies })
      toast({ title: t('common.success'), description: t('company.createSuccess') })
    },
    onError: (error: unknown) => {
      const status = (error as AxiosError)?.response?.status
      const description =
        status === 409 ? t('company.slugTaken') : t(getApiErrorKey(error, t('common.error')))
      toast({ title: t('common.error'), description, variant: 'destructive' })
    },
  })
}

export function useSwitchCompany() {
  const queryClient = useQueryClient()
  const router = useRouter()
  const { toast } = useToast()
  const { t } = useTranslation()
  const applyToken = useAuthStore((s) => s.applyToken)

  return useMutation({
    mutationFn: (companyId: string) => companiesApi.switch(companyId),
    onSuccess: (res) => {
      applyToken(res)
      // A company change invalidates ALL company-scoped caches.
      queryClient.clear()
      toast({ title: t('common.success'), description: t('company.switchSuccess') })
      router.push('/notebooks')
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}
```
> The global test setup (`src/test/setup.ts`) mocks `next/navigation` and `use-translation`, so `useRouter`/`t` resolve in the test without extra mocks.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- use-companies` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/hooks/use-companies.ts frontend/src/lib/hooks/use-companies.test.tsx && git commit -m "P2: use-companies hooks"`

---

## Task 11: Onboarding route + wizard + company step

**Files:**
- Create: `frontend/src/app/onboarding/page.tsx`
- Create: `frontend/src/components/onboarding/OnboardingWizard.tsx`
- Create: `frontend/src/components/onboarding/CompanyStep.tsx`
- Test: `frontend/src/components/onboarding/CompanyStep.test.tsx`

**Interfaces:**
- Consumes: `useCreateCompany` (Task 10); `useTranslation`; UI primitives `Button`, `Input` (from `@/components/ui/*`). References i18n keys `onboarding.title`, `onboarding.welcome`, `onboarding.companyStepTitle`, `onboarding.stepCompany`, `onboarding.stepProject`, `onboarding.createCompanyCta`, `company.nameLabel`, `company.namePlaceholder`, `company.slugLabel`, `company.slugHelp` (added to all locales in Task 14).
- Produces: a top-level `/onboarding` route (outside `(dashboard)` — the dashboard requires an active company). On successful create, `useCreateCompany` swaps the token; the wizard advances to a **P3 hand-off** step (step 2) which — until P3 exists — routes to `/notebooks`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/onboarding/CompanyStep.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CompanyStep } from './CompanyStep'

const mutate = vi.fn()
vi.mock('@/lib/hooks/use-companies', () => ({
  useCreateCompany: () => ({ mutate, isPending: false }),
}))

describe('CompanyStep', () => {
  it('renders the company name field (i18n keys via mocked t)', () => {
    render(<CompanyStep onCreated={vi.fn()} />)
    expect(screen.getByText('company.nameLabel')).toBeDefined()
    expect(screen.getByText('onboarding.createCompanyCta')).toBeDefined()
  })

  it('submits the trimmed name through useCreateCompany', () => {
    render(<CompanyStep onCreated={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('company.namePlaceholder'), {
      target: { value: '  Acme  ' },
    })
    fireEvent.submit(screen.getByTestId('company-step-form'))
    expect(mutate).toHaveBeenCalledWith(
      { name: 'Acme', slug: undefined },
      expect.anything(),
    )
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- CompanyStep` — Expected: FAIL — cannot resolve `./CompanyStep`.

- [ ] **Step 3: Write minimal implementation** —

`frontend/src/components/onboarding/CompanyStep.tsx`:
```tsx
'use client'

import { useState } from 'react'
import { useCreateCompany } from '@/lib/hooks/use-companies'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function CompanyStep({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation()
  const createCompany = useCreateCompany()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createCompany.mutate(
      { name: name.trim(), slug: slug.trim() || undefined },
      { onSuccess: () => onCreated() },
    )
  }

  return (
    <form data-testid="company-step-form" onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <label className="block text-sm font-medium" htmlFor="company-name">
          {t('company.nameLabel')}
        </label>
        <Input
          id="company-name"
          autoFocus
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('company.namePlaceholder')}
        />
      </div>
      <div className="space-y-1.5">
        <label className="block text-sm font-medium" htmlFor="company-slug">
          {t('company.slugLabel')}
        </label>
        <Input
          id="company-slug"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t('company.slugHelp')}</p>
      </div>
      <Button type="submit" className="w-full" disabled={createCompany.isPending || !name.trim()}>
        {t('onboarding.createCompanyCta')}
      </Button>
    </form>
  )
}
```
> If the UI primitives live at different paths, match the imports used by P1's `LoginForm` (e.g. `@/components/ui/button`, `@/components/ui/input`) — confirm the casing in `frontend/src/components/ui/`.

`frontend/src/components/onboarding/OnboardingWizard.tsx`:
```tsx
'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/hooks/use-translation'
import { CompanyStep } from './CompanyStep'

type Step = 'company' | 'project'

export function OnboardingWizard() {
  const { t } = useTranslation()
  const router = useRouter()
  const [step, setStep] = useState<Step>('company')

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-lg flex-col justify-center px-4 py-12">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold">{t('onboarding.title')}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t('onboarding.welcome')}</p>
      </div>

      <div className="mb-5 flex items-center justify-center gap-2 text-xs font-medium">
        <span aria-current={step === 'company'}>{t('onboarding.stepCompany')}</span>
        <span className="h-px w-8 bg-border" />
        <span aria-current={step === 'project'}>{t('onboarding.stepProject')}</span>
      </div>

      <div className="rounded-xl border p-6">
        {step === 'company' ? (
          <>
            <h2 className="mb-4 text-lg font-medium">{t('onboarding.companyStepTitle')}</h2>
            {/* On create, the token is already company-scoped (useCreateCompany
                applied it). Advance to the P3 project hand-off. */}
            <CompanyStep onCreated={() => setStep('project')} />
          </>
        ) : (
          // P3 fills in the first-project step here. Until then, hand off to the
          // dashboard now that the company + owner token exist.
          <ProjectHandoff onDone={() => router.push('/notebooks')} />
        )}
      </div>
    </div>
  )
}

function ProjectHandoff({ onDone }: { onDone: () => void }) {
  // Immediately hand off — P3 replaces this with a real project-create step.
  onDone()
  return null
}
```

`frontend/src/app/onboarding/page.tsx`:
```tsx
import { OnboardingWizard } from '@/components/onboarding/OnboardingWizard'

export default function OnboardingPage() {
  return <OnboardingWizard />
}
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- CompanyStep` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/app/onboarding frontend/src/components/onboarding && git commit -m "P2: onboarding route + wizard + company step"`

---

## Task 12: `CompanySwitcher` + mount in dashboard chrome

**Files:**
- Create: `frontend/src/components/company/CompanySwitcher.tsx`
- Modify: the dashboard chrome that renders the sidebar/header — mount `<CompanySwitcher />` (e.g. `frontend/src/components/layout/AppSidebar.tsx`; confirm the actual chrome component)
- Test: `frontend/src/components/company/CompanySwitcher.test.tsx`

**Interfaces:**
- Consumes: `useAuthStore` (`memberships`, `activeCompanyId`), `useSwitchCompany` (Task 10), `useTranslation`. References i18n keys `company.switchLabel`, `company.switcherEmpty`, `company.roleOwner`, `company.roleAdmin`, `company.roleMember` (added in Task 14).
- Produces: a dropdown listing `memberships` (name + role badge), a check/active marker on `activeCompanyId`; selecting a different company calls `useSwitchCompany().mutate(companyId)`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/company/CompanySwitcher.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CompanySwitcher } from './CompanySwitcher'
import { useAuthStore } from '@/lib/stores/auth-store'

const mutate = vi.fn()
vi.mock('@/lib/hooks/use-companies', () => ({
  useSwitchCompany: () => ({ mutate, isPending: false }),
}))

describe('CompanySwitcher', () => {
  beforeEach(() => {
    mutate.mockClear()
    useAuthStore.setState({
      memberships: [
        { company_id: 'company:a', name: 'Acme', slug: 'acme', role: 'owner' },
        { company_id: 'company:b', name: 'Beta', slug: 'beta', role: 'member' },
      ],
      activeCompanyId: 'company:a',
    })
  })

  it('lists memberships with names and role badges', () => {
    render(<CompanySwitcher />)
    expect(screen.getByText('Acme')).toBeDefined()
    expect(screen.getByText('Beta')).toBeDefined()
    // Role badge for the owner membership uses the roleOwner key (mocked t).
    expect(screen.getAllByText('company.roleOwner').length).toBeGreaterThan(0)
  })

  it('switches when a different company is selected', () => {
    render(<CompanySwitcher />)
    fireEvent.click(screen.getByTestId('company-option-company:b'))
    expect(mutate).toHaveBeenCalledWith('company:b')
  })

  it('does not switch when the active company is selected', () => {
    render(<CompanySwitcher />)
    fireEvent.click(screen.getByTestId('company-option-company:a'))
    expect(mutate).not.toHaveBeenCalled()
  })

  it('renders an empty state when there are no memberships', () => {
    useAuthStore.setState({ memberships: [], activeCompanyId: null })
    render(<CompanySwitcher />)
    expect(screen.getByText('company.switcherEmpty')).toBeDefined()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- CompanySwitcher` — Expected: FAIL — cannot resolve `./CompanySwitcher`.

- [ ] **Step 3: Write minimal implementation** — `frontend/src/components/company/CompanySwitcher.tsx`:
```tsx
'use client'

import { Check } from 'lucide-react'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useSwitchCompany } from '@/lib/hooks/use-companies'
import { useTranslation } from '@/lib/hooks/use-translation'

export function CompanySwitcher() {
  const { t } = useTranslation()
  const memberships = useAuthStore((s) => s.memberships)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const switchCompany = useSwitchCompany()

  // Literal keys (not template strings) so the i18n usage test can find them.
  const roleLabels: Record<string, string> = {
    owner: t('company.roleOwner'),
    admin: t('company.roleAdmin'),
    member: t('company.roleMember'),
  }

  if (memberships.length === 0) {
    return <div className="px-3 py-2 text-xs text-muted-foreground">{t('company.switcherEmpty')}</div>
  }

  return (
    <div role="listbox" aria-label={t('company.switchLabel')} className="flex flex-col gap-1">
      {memberships.map((m) => {
        const isActive = m.company_id === activeCompanyId
        return (
          <button
            key={m.company_id}
            type="button"
            role="option"
            aria-selected={isActive}
            data-testid={`company-option-${m.company_id}`}
            disabled={switchCompany.isPending}
            onClick={() => {
              if (!isActive) switchCompany.mutate(m.company_id)
            }}
            className="flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
          >
            <span className="truncate">{m.name}</span>
            <span className="flex items-center gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase">
                {roleLabels[m.role] ?? m.role}
              </span>
              {isActive && <Check className="h-4 w-4" aria-hidden />}
            </span>
          </button>
        )
      })}
    </div>
  )
}
```
Then mount it in the dashboard chrome. Confirm the chrome file (the sidebar rendered by `frontend/src/app/(dashboard)/layout.tsx` — likely `frontend/src/components/layout/AppSidebar.tsx`) and add near the top of its content:
```tsx
import { CompanySwitcher } from '@/components/company/CompanySwitcher'
// ...inside the sidebar body, above the nav links:
<CompanySwitcher />
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- CompanySwitcher` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/company frontend/src/components/layout/AppSidebar.tsx && git commit -m "P2: CompanySwitcher + mount in dashboard chrome"`

---

## Task 13: Dashboard-layout onboarding guard

**Files:**
- Modify: `frontend/src/app/(dashboard)/layout.tsx`
- Test: `frontend/src/app/(dashboard)/layout.guard.test.tsx`

**Interfaces:**
- Consumes: `useAuthStore` (`memberships`, `activeCompanyId`, `setActiveCompany`), `useAuth` (`isAuthenticated`, `isLoading`), `useRouter`.
- Produces: guard behavior — authenticated + `memberships.length === 0` → `router.push('/onboarding')`; authenticated + `!activeCompanyId` but has memberships → auto-select the first membership via `setActiveCompany` (avoids a dead dashboard when a persisted session has memberships but no active company). Unauthenticated → existing `/login` redirect (unchanged).

- [ ] **Step 1: Write the failing test** — `frontend/src/app/(dashboard)/layout.guard.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import DashboardLayout from './layout'
import { useAuth } from '@/lib/hooks/use-auth'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useRouter } from 'next/navigation'

vi.mock('next/navigation', () => ({ useRouter: vi.fn() }))
vi.mock('@/lib/hooks/use-auth', () => ({ useAuth: vi.fn() }))
vi.mock('@/lib/hooks/use-version-check', () => ({ useVersionCheck: vi.fn() }))

describe('DashboardLayout onboarding guard', () => {
  const push = vi.fn()
  beforeEach(() => {
    push.mockClear()
    vi.mocked(useRouter).mockReturnValue({ push } as any)
    useAuthStore.setState({ memberships: [], activeCompanyId: null })
  })

  it('redirects an authenticated user with no memberships to /onboarding', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, isLoading: false } as any)
    useAuthStore.setState({ memberships: [], activeCompanyId: null })
    render(<DashboardLayout>content</DashboardLayout>)
    expect(push).toHaveBeenCalledWith('/onboarding')
  })

  it('auto-selects the first membership when none is active', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, isLoading: false } as any)
    useAuthStore.setState({
      memberships: [{ company_id: 'company:a', name: 'A', slug: 'a', role: 'owner' }],
      activeCompanyId: null,
    })
    render(<DashboardLayout>content</DashboardLayout>)
    expect(useAuthStore.getState().activeCompanyId).toBe('company:a')
    expect(push).not.toHaveBeenCalledWith('/onboarding')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- layout.guard` — Expected: FAIL — the current layout has no `/onboarding` redirect nor auto-select.

- [ ] **Step 3: Write minimal implementation** — Update `frontend/src/app/(dashboard)/layout.tsx`'s effect. Add the store reads and extend the `useEffect`:
```tsx
'use client'

import { useAuth } from '@/lib/hooks/use-auth'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useVersionCheck } from '@/lib/hooks/use-version-check'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { ModalProvider } from '@/components/providers/ModalProvider'
import { CreateDialogsProvider } from '@/lib/hooks/use-create-dialogs'
import { CommandPalette } from '@/components/common/CommandPalette'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const memberships = useAuthStore((s) => s.memberships)
  const activeCompanyId = useAuthStore((s) => s.activeCompanyId)
  const setActiveCompany = useAuthStore((s) => s.setActiveCompany)
  const router = useRouter()
  const [hasCheckedAuth, setHasCheckedAuth] = useState(false)

  useVersionCheck()

  useEffect(() => {
    if (!isLoading) {
      setHasCheckedAuth(true)

      if (!isAuthenticated) {
        const currentPath = window.location.pathname + window.location.search
        sessionStorage.setItem('redirectAfterLogin', currentPath)
        router.push('/login')
        return
      }

      // Authenticated but no company yet -> first-run onboarding.
      if (memberships.length === 0) {
        router.push('/onboarding')
        return
      }

      // Has memberships but none active (e.g. a restored session) -> pick the
      // first active membership so the dashboard is company-scoped.
      if (!activeCompanyId && memberships.length > 0) {
        setActiveCompany(memberships[0].company_id, memberships[0].role)
      }
    }
  }, [isAuthenticated, isLoading, memberships, activeCompanyId, setActiveCompany, router])

  if (isLoading || !hasCheckedAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!isAuthenticated) {
    return null
  }

  return (
    <ErrorBoundary>
      <CreateDialogsProvider>
        {children}
        <ModalProvider />
        <CommandPalette />
      </CreateDialogsProvider>
    </ErrorBoundary>
  )
}
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- layout.guard` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add "frontend/src/app/(dashboard)/layout.tsx" "frontend/src/app/(dashboard)/layout.guard.test.tsx" && git commit -m "P2: dashboard onboarding guard + auto-select company"`

---

## Task 14: i18n keys in all 14 locales (7 enforced + 7 English-fallback)

**Files:**
- Modify (real translations): `frontend/src/lib/locales/en-US/index.ts`
- Modify (real translations): `frontend/src/lib/locales/pt-BR/index.ts`
- Modify (real translations): `frontend/src/lib/locales/zh-CN/index.ts`
- Modify (real translations): `frontend/src/lib/locales/zh-TW/index.ts`
- Modify (real translations): `frontend/src/lib/locales/ja-JP/index.ts`
- Modify (real translations): `frontend/src/lib/locales/ru-RU/index.ts`
- Modify (real translations): `frontend/src/lib/locales/bn-IN/index.ts`
- Modify (English fallback — same keys, English values): `frontend/src/lib/locales/{it-IT,fr-FR,ca-ES,es-ES,de-DE,pl-PL,tr-TR}/index.ts`
- Test (existing): `frontend/src/lib/locales/index.test.ts` (parity + usage; run it as the gate)

**Interfaces:**
- Consumes: nothing new. Every key added here is referenced literally by Tasks 10–13 (hooks + components), which the usage half of the locale test enforces.
- Produces: `onboarding.*` and `company.*` keys in all 14 locales (real translations in the 7 enforced, English fallback in the other 7).

Keys to add (13 `company.*` + 6 `onboarding.*`). Each locale file exports one nested object; add an `onboarding` section and a `company` section (or extend them if P1 already created a `company`/`onboarding` section — merge, don't duplicate).

- [ ] **Step 1: Write the failing test** — No new test file; the existing `frontend/src/lib/locales/index.test.ts` IS the gate. Run it first to confirm it currently fails (the keys are referenced by the components from Tasks 10–13 but not yet present in en-US, so the parity test also flags the other 6 locales once en-US has them). Run: `npm run test -- locales/index` — Expected: FAIL (usage test lists the new keys as missing once they exist in en-US; before adding, add to en-US first per Step 3, then the other locales).

- [ ] **Step 2: Confirm the failing signal** — After adding ONLY to `en-US` (do this to see the parity failure), Run: `npm run test -- locales/index` — Expected: FAIL — "Missing keys in pt-BR: onboarding.title, ..." (parity), proving the remaining 6 locales need the keys.

- [ ] **Step 3: Write minimal implementation** — Add to each locale. English (`en-US/index.ts`):
```ts
  onboarding: {
    title: "Welcome to Arteamis",
    welcome: "Let's set up your company to get started.",
    companyStepTitle: "Create your company",
    stepCompany: "Company",
    stepProject: "Project",
    createCompanyCta: "Create company",
  },
  company: {
    nameLabel: "Company name",
    namePlaceholder: "Acme Inc.",
    slugLabel: "Slug (optional)",
    slugHelp: "Used in URLs. Leave blank to generate one from the name.",
    createSuccess: "Company created",
    slugTaken: "That company slug is already taken. Try another name.",
    switchLabel: "Switch company",
    switchSuccess: "Switched company",
    roleOwner: "Owner",
    roleAdmin: "Admin",
    roleMember: "Member",
    switcherEmpty: "No companies yet",
  },
```

Portuguese (`pt-BR/index.ts`):
```ts
  onboarding: {
    title: "Bem-vindo ao Arteamis",
    welcome: "Vamos configurar sua empresa para começar.",
    companyStepTitle: "Crie sua empresa",
    stepCompany: "Empresa",
    stepProject: "Projeto",
    createCompanyCta: "Criar empresa",
  },
  company: {
    nameLabel: "Nome da empresa",
    namePlaceholder: "Acme Ltda.",
    slugLabel: "Slug (opcional)",
    slugHelp: "Usado nas URLs. Deixe em branco para gerar a partir do nome.",
    createSuccess: "Empresa criada",
    slugTaken: "Esse slug de empresa já está em uso. Tente outro nome.",
    switchLabel: "Trocar de empresa",
    switchSuccess: "Empresa trocada",
    roleOwner: "Proprietário",
    roleAdmin: "Administrador",
    roleMember: "Membro",
    switcherEmpty: "Nenhuma empresa ainda",
  },
```

Simplified Chinese (`zh-CN/index.ts`):
```ts
  onboarding: {
    title: "欢迎使用 Arteamis",
    welcome: "让我们先设置您的公司。",
    companyStepTitle: "创建您的公司",
    stepCompany: "公司",
    stepProject: "项目",
    createCompanyCta: "创建公司",
  },
  company: {
    nameLabel: "公司名称",
    namePlaceholder: "Acme 公司",
    slugLabel: "标识（可选）",
    slugHelp: "用于网址。留空则根据名称自动生成。",
    createSuccess: "公司已创建",
    slugTaken: "该公司标识已被占用，请换一个名称。",
    switchLabel: "切换公司",
    switchSuccess: "已切换公司",
    roleOwner: "所有者",
    roleAdmin: "管理员",
    roleMember: "成员",
    switcherEmpty: "暂无公司",
  },
```

Traditional Chinese (`zh-TW/index.ts`):
```ts
  onboarding: {
    title: "歡迎使用 Arteamis",
    welcome: "讓我們先設定您的公司。",
    companyStepTitle: "建立您的公司",
    stepCompany: "公司",
    stepProject: "專案",
    createCompanyCta: "建立公司",
  },
  company: {
    nameLabel: "公司名稱",
    namePlaceholder: "Acme 公司",
    slugLabel: "識別碼（選填）",
    slugHelp: "用於網址。留空則依名稱自動產生。",
    createSuccess: "公司已建立",
    slugTaken: "該公司識別碼已被使用，請換一個名稱。",
    switchLabel: "切換公司",
    switchSuccess: "已切換公司",
    roleOwner: "擁有者",
    roleAdmin: "管理員",
    roleMember: "成員",
    switcherEmpty: "尚無公司",
  },
```

Japanese (`ja-JP/index.ts`):
```ts
  onboarding: {
    title: "Arteamis へようこそ",
    welcome: "まずは会社を設定しましょう。",
    companyStepTitle: "会社を作成",
    stepCompany: "会社",
    stepProject: "プロジェクト",
    createCompanyCta: "会社を作成",
  },
  company: {
    nameLabel: "会社名",
    namePlaceholder: "Acme 株式会社",
    slugLabel: "スラッグ（任意）",
    slugHelp: "URL に使用されます。空欄の場合は名前から自動生成されます。",
    createSuccess: "会社を作成しました",
    slugTaken: "その会社スラッグは既に使用されています。別の名前をお試しください。",
    switchLabel: "会社を切り替え",
    switchSuccess: "会社を切り替えました",
    roleOwner: "オーナー",
    roleAdmin: "管理者",
    roleMember: "メンバー",
    switcherEmpty: "会社がまだありません",
  },
```

Russian (`ru-RU/index.ts`):
```ts
  onboarding: {
    title: "Добро пожаловать в Arteamis",
    welcome: "Давайте настроим вашу компанию, чтобы начать.",
    companyStepTitle: "Создайте компанию",
    stepCompany: "Компания",
    stepProject: "Проект",
    createCompanyCta: "Создать компанию",
  },
  company: {
    nameLabel: "Название компании",
    namePlaceholder: "ООО «Акме»",
    slugLabel: "Slug (необязательно)",
    slugHelp: "Используется в URL. Оставьте пустым, чтобы сгенерировать из названия.",
    createSuccess: "Компания создана",
    slugTaken: "Такой slug компании уже занят. Попробуйте другое название.",
    switchLabel: "Сменить компанию",
    switchSuccess: "Компания изменена",
    roleOwner: "Владелец",
    roleAdmin: "Администратор",
    roleMember: "Участник",
    switcherEmpty: "Пока нет компаний",
  },
```

Bengali (`bn-IN/index.ts`):
```ts
  onboarding: {
    title: "Arteamis-এ স্বাগতম",
    welcome: "শুরু করতে চলুন আপনার কোম্পানি সেট আপ করি।",
    companyStepTitle: "আপনার কোম্পানি তৈরি করুন",
    stepCompany: "কোম্পানি",
    stepProject: "প্রকল্প",
    createCompanyCta: "কোম্পানি তৈরি করুন",
  },
  company: {
    nameLabel: "কোম্পানির নাম",
    namePlaceholder: "Acme Inc.",
    slugLabel: "স্লাগ (ঐচ্ছিক)",
    slugHelp: "URL-এ ব্যবহৃত হয়। নাম থেকে তৈরি করতে ফাঁকা রাখুন।",
    createSuccess: "কোম্পানি তৈরি হয়েছে",
    slugTaken: "এই কোম্পানি স্লাগটি ইতিমধ্যে নেওয়া হয়েছে। অন্য নাম চেষ্টা করুন।",
    switchLabel: "কোম্পানি পরিবর্তন করুন",
    switchSuccess: "কোম্পানি পরিবর্তন করা হয়েছে",
    roleOwner: "মালিক",
    roleAdmin: "অ্যাডমিন",
    roleMember: "সদস্য",
    switcherEmpty: "এখনও কোনো কোম্পানি নেই",
  },
```

> Placement: insert each `onboarding`/`company` block as a top-level section inside the exported object (sibling of `common`, `auth`, etc.), respecting the file's trailing-comma/formatting style.

- [ ] **Step 3b: Add the same keys (English fallback) to the 7 non-enforced locales** — the parity test iterates EVERY locale in the `resources` map, so `ca-ES, de-DE, es-ES, fr-FR, it-IT, pl-PL, tr-TR` (7 files) MUST also carry the new `onboarding.*` + `company.*` keys or `npm run test` fails. Add the exact same key structure to each of these 7 files using the **en-US English values** (silent en-US fallback is acceptable for non-enforced locales; a native pass can follow). If P1 already created `onboarding`/`company` sections in these files, merge — don't duplicate.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- locales/index` — Expected: PASS (parity: all 14 locales carry every new key; usage: every new key is referenced in a component/hook from Tasks 10–13).

- [ ] **Step 5: Run the full frontend gate** — Run (inside `frontend/`): `npm run test && npm run lint && npm run build` — Expected: all PASS.

- [ ] **Step 6: Commit** — `git add frontend/src/lib/locales && git commit -m "P2: i18n onboarding + company keys in all 14 locales"`

---

## Self-review

### Spec coverage (every spec section → task)
- Migration 20 (`company` + `membership`, unique indexes, `_down`, manager registration) → **Task 1**.
- Domain models `Company`/`Membership` + `domain/__init__.py` import for polymorphic `get()` → **Task 2**.
- `create_access_token` (P1 stub → P2 impl) → **Task 3**.
- `api/deps.py` (`get_identity`, `get_auth_context`, `require_role`) → **Task 4**.
- `company_service.py` (`slugify` without uuid suffix, `create_company` + orphan cleanup, `list_memberships`, `get_membership`) → **Task 5**.
- Schemas (`CompanyCreate`/`CompanyResponse`/`TokenResponse`) + `POST /companies` (201, token re-mint) + `GET /companies` + main.py registration → **Task 6**.
- `POST /auth/switch-company/{id}` (membership re-verify, 403, token re-mint) → **Task 7**.
- Frontend `companies.ts` + types + `QUERY_KEYS.companies` → **Task 8**.
- auth-store company slice (`applyToken`/`setSession`/`setActiveCompany`, persisted) → **Task 9**.
- `useCompanies`/`useCreateCompany`/`useSwitchCompany` (409 → `slugTaken`, `queryClient.clear()`) → **Task 10**.
- Onboarding route + wizard + company step (P3 hand-off stub) → **Task 11**.
- `CompanySwitcher` + dashboard mount → **Task 12**.
- Dashboard-layout onboarding guard + auto-select → **Task 13**.
- i18n in all 14 locales (7 enforced + 7 English-fallback) → **Task 14**.
- Spec's RBAC table: create is open to any authenticated user (no role gate) — Task 6 uses `get_identity`, not `require_role`; `require_role` is delivered (Task 4) but consumed by P3+ (tested directly in Task 4). Covered.
- Spec's error contract: 401 (deps, Task 4/6/7), 403 (`require_role` Task 4, `switch-company` Task 7), 409 (slug, Tasks 5/6), 422 (empty name, Task 6). Covered.
- Spec testing checklist: backend cases 1–7 map to Tasks 1–7 tests (case 4 identity-plane isolation → Task 5 `list_memberships` `WHERE user = $user` assertion; case 7 migration up/down → Task 1 DB-free DDL assertions, with a note that a live round-trip is out of unit scope). Frontend cases 1–5 → Tasks 8–14 tests. Covered.

### Placeholder scan
No "TBD/implement later/add error handling/similar to Task N". The onboarding step-2 is an explicit, intentional P3 hand-off (spec-mandated), implemented concretely as an immediate route to `/notebooks` — not a placeholder. Every code step is complete and runnable.

### Type/signature consistency
- `create_access_token(user_id, company_id, role, minutes=None) -> str` (Task 3) — called by Task 6 and Task 7 with keyword args exactly matching.
- `AuthContext(user_id, company_id, role)` (P1) — constructed in Task 4 tests and consumed by `require_role`/`get_auth_context`.
- `create_company(user_id, name, slug=None) -> (Company, Membership)` (Task 5) — Task 6 unpacks `company, membership` and reads `company.id`, `membership.role`; test asserts `mock_create.assert_awaited_once_with("user:1", "Acme", None)`.
- `get_membership(user_id, company_id) -> Optional[Membership]` (Task 5) — Task 7 checks `membership.status != "active"`; `Membership.status` exists (Task 2, default `"active"`).
- `TokenResponse{access_token, token_type, active_company_id, role}` (Task 6 schema) — matches frontend `TokenResponse` (Task 8) and `applyToken(res)` reads `res.access_token`/`res.active_company_id`/`res.role` (Task 9).
- `Membership` (frontend, Task 8) `{company_id, name, slug, role}` — matches backend `list_memberships` row and `CompanyResponse` maps `company_id`→`id`.
- `applyToken`/`setSession`/`setActiveCompany` (Task 9) — consumed by Tasks 10/12/13 exactly as declared.
- i18n keys referenced in Tasks 10–13 (`company.createSuccess`, `company.slugTaken`, `company.switchSuccess`, `company.roleOwner/Admin/Member`, `company.switchLabel`, `company.switcherEmpty`, `onboarding.*`, `company.nameLabel/namePlaceholder/slugLabel/slugHelp`) all appear literally and are all added in Task 14 — satisfying both halves of the locale test.
