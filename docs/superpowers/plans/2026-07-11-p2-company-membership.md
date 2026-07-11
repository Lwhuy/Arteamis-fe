# P2 — Workspace + Membership + Roles + Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **v2 REWRITE NOTICE:** This plan supersedes the earlier "company-only" P2 plan. The tenant
> entity is now **`workspace`** (`kind = "personal" | "company"`), not `company`. Every user gets
> exactly one auto-provisioned `kind="personal"` workspace at signup/first-login — onboarding
> (creating a company) is now **optional**, never a forced gate. See the rewritten spec
> (`docs/superpowers/specs/2026-07-11-p2-company-membership-onboarding-design.md`) and the shared
> `ARCHITECTURE_BRIEF.md` "v2 DESIGN REVISION" for the full rationale.

**Goal:** Introduce the `workspace` (tenant boundary, `kind` personal|company) and `membership`
(user↔workspace + role) tables; **auto-provision exactly one personal workspace per user at
signup/first-login** via an idempotent `ensure_personal_workspace` helper, so every logged-in
user always holds a workspace-scoped access token with zero forced setup; and ship the optional
company path — create (becoming its `owner`), list, and switch the active workspace — with
workspace-scoped access tokens minted on login/create/switch, a `require_role` RBAC primitive for
later phases, and a non-blocking onboarding surface + workspace switcher on the frontend.

**Architecture:** Next.js 16 App Router frontend (port 3000) → FastAPI (port 5055) → SurrealDB
(port 8000). Identity-plane tables (`user`, `auth_identity` from P1; `workspace`, `membership`
here) are **never** workspace-scoped — login/onboarding must read a user's memberships before any
workspace is active, so isolation is enforced by explicit `user`/`workspace` filters in the
service layer (SurrealDB has no RLS). Two JWT shapes: P1's **identity token** (`sub` only) and
P2's **workspace-scoped access token** (`sub`, `workspace_id`, `role`), minted on
login/register/refresh (always for the personal workspace — see the default decision in the
spec), on workspace create, and on switch, then swapped into the persisted Zustand auth store.

**Tech Stack:** Next.js 16, TanStack Query, Zustand (persist), FastAPI, SurrealDB (custom async
repository + hand-written SurrealQL migrations), `python-jose[cryptography]` (HS256 JWT, from
P1), Pydantic v2, vitest, pytest + pytest-asyncio.

**Spec:** docs/superpowers/specs/2026-07-11-p2-company-membership-onboarding-design.md
**Depends on:** P1 (auth + users) · **Branch:** feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB call is awaited (no sync DB access).
- All frontend HTTP goes through the single axios `apiClient` (frontend/src/lib/api/client.ts) — never a 2nd instance. It auto-injects `Authorization: Bearer <state.token>` from localStorage `auth-storage`.
- i18n MANDATORY: every UI string via `t('section.key')`; add the key to ALL 14 locales in the `resources` map under frontend/src/lib/locales/. The locale test `src/lib/locales/index.test.ts` enforces both **parity** (EVERY locale in `resources` must carry the exact en-US key set — not just the enforced ones) AND **usage** (every en-US leaf key must appear literally in a source file) — so add keys only alongside the component that references them literally. There are 14 locales (`zh-CN, en-US, zh-TW, pt-BR, ja-JP, it-IT, fr-FR, ru-RU, bn-IN, ca-ES, es-ES, de-DE, pl-PL, tr-TR`): the 7 enforced (`en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN`) get real translations; the other 7 (`it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR`) get English fallback values (acceptable silent en-US fallback) so `npm run test` stays green.
- New SurrealDB schema = new migration pair `open_notebook/database/migrations/20.surrealql` + `20_down.surrealql`, registered in `AsyncMigrationManager.__init__` (migrations are hard-coded, not auto-discovered). **Migration 19 (`user`, `auth_identity`) is already merged** (commit `fa53c83`, branch `feat/auth-multitenancy`) — `open_notebook/database/async_migrate.py` currently registers 19 up/down migrations; Task 1 appends the 20th pair.
- Physical SurrealDB table stays `notebook` (P3 repurposes it as "project"); P2 does not touch it.
- Tokens: identity token (P1) vs workspace-scoped access token (this phase implements `create_access_token`).
- **Naming (v2, non-negotiable):** the tenant entity is `workspace`, never `company`, in every table name, field name, class name, file name, route path, query key, and i18n namespace this plan introduces. "Company" appears ONLY as UI copy for a `kind="company"` workspace.
- Backend errors: raise typed exceptions from `open_notebook.exceptions`; global handlers in `api/main.py` map them (`NotFoundError`→404, `InvalidInputError`→400, `AuthenticationError`→401, `DuplicateResourceError`→409 [added by P1], `OpenNotebookError`→500). Do NOT raise bare `HTTPException` for domain errors — the only two exceptions in this plan are the two **403** cases (`require_role`, `switch-workspace`) which the spec explicitly specifies as `HTTPException(status_code=403, ...)` because no typed 403 exception exists in this repo.
- Backend tests: `uv run pytest tests/`. Frontend (inside `frontend/`): `npm run lint`, `npm run test`, `npm run build`.

### P1 interfaces this plan consumes (exact — from docs/.../2026-07-11-p1-auth-users-design.md)
- `api/security.py` (P1 owns the file, not yet created as of this plan's authoring — only
  migration 19 has landed so far): `create_identity_token(user_id) -> str`;
  `decode_identity_token(token) -> str` (returns `sub`, accepts identity OR workspace-scoped
  access tokens, raises `AuthenticationError`); a `create_access_token(user_id, workspace_id,
  role, ...)` **stub that P2 implements in Task 4**; `decode_access_token(token) -> AuthContext`;
  the `AuthContext` dataclass (`user_id: str`, `workspace_id: str | None`, `role: str | None`).
  **Naming assumption (stated per PLAN_FORMAT and the brief's v2 terminology patch):** this
  plan assumes P1's stub and `AuthContext` name the claim `workspace_id`, not `company_id` — the
  brief mandates the workspace rename project-wide, including in P1. If P1 lands with
  `company_id` instead, rename that one field in `api/security.py` before starting Task 4; no
  other line in this plan changes. Module-level JWT config it exposes (from
  `api/auth_config.py`): `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`.
- `api/auth_service.py` (P1 owns the file): `build_session_payload(user) -> dict` returning
  `{ access_token: create_identity_token(user.id), token_type: "bearer", needs_onboarding: True,
  active_workspace_id: None, user: {...}, memberships: [] }` — an **identity-only** placeholder
  P1 ships since no workspace exists yet at that phase. **P2 rewrites this function in Task 6**
  so every login/register/refresh call auto-provisions and returns a workspace-scoped session.
- `api/main.py`: P1 registers a `@app.exception_handler(DuplicateResourceError)` → `409 {"detail": ...}` and swaps `PasswordAuthMiddleware` for `JWTAuthMiddleware` (sets `request.state.user_id`; passes through when `JWT_SECRET` unset). P2 relies on the 409 handler; it does not modify the middleware.
- `open_notebook/exceptions.py`: P1 adds `class DuplicateResourceError(OpenNotebookError)`. P2 raises it for slug collisions. (Confirmed present today: `open_notebook/exceptions.py` currently has no `DuplicateResourceError` — it is added by P1's own plan before P2's Task 3 needs it.)
- Frontend `auth-store` (P1 rewrites `frontend/src/lib/stores/auth-store.ts` — **not yet done**; the file in the repo today is still the old shared-password version): persisted (`partialize`) `token`, `user`, `isAuthenticated`; actions `login`/`register`/`refresh`/`fetchMe`/`logout`; `hasHydrated`/`setHasHydrated`; `name: 'auth-storage'`. P1's `/auth/me` and session payload return `{ user, memberships, needs_onboarding, active_workspace_id }`. P2 adds the workspace slice (Task 10).

---

## Task 1: Migration 20 — `workspace` (+`kind`) + `membership` tables

**Files:**
- Create: `open_notebook/database/migrations/20.surrealql`
- Create: `open_notebook/database/migrations/20_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (`AsyncMigrationManager.__init__` — append the 20 entries after the 19 entries P1 already merged)
- Test: `tests/test_p2_migration_20.py`

**Interfaces:**
- Consumes: the existing `AsyncMigration.from_file` loader (strips `--` comment lines, joins the rest with spaces — so keep every statement `;`-terminated and never put code after an inline `--`).
- Produces: `workspace` table (`name`, `slug` UNIQUE, `kind` ASSERT IN [personal, company], `owner record<user>`, `created`/`updated`) and `membership` table (`user record<user>`, `workspace record<workspace>`, `role`, `status`, `created`/`updated`) with a UNIQUE `(user, workspace)` index. The `idx_workspace_slug` UNIQUE index drives the 409 contract for company creation.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_migration_20.py`:
```python
"""Migration 20 (workspace + membership) is well-formed and registered.

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


def test_migration_20_defines_workspace_and_membership():
    sql = AsyncMigration.from_file(str(MIGRATIONS / "20.surrealql")).sql
    assert "DEFINE TABLE IF NOT EXISTS workspace SCHEMAFULL" in sql
    assert "DEFINE FIELD IF NOT EXISTS slug ON TABLE workspace TYPE string" in sql
    assert "DEFINE FIELD IF NOT EXISTS kind  ON TABLE workspace TYPE string" in sql or "DEFINE FIELD IF NOT EXISTS kind ON TABLE workspace TYPE string" in sql
    assert "'personal'" in sql and "'company'" in sql
    assert "DEFINE FIELD IF NOT EXISTS owner ON TABLE workspace TYPE record<user>" in sql
    assert "idx_workspace_slug ON TABLE workspace FIELDS slug UNIQUE" in sql
    assert "DEFINE TABLE IF NOT EXISTS membership SCHEMAFULL" in sql
    assert "role      ON TABLE membership TYPE string" in sql or "role ON TABLE membership TYPE string" in sql
    assert "idx_membership_user_workspace ON TABLE membership FIELDS user, workspace UNIQUE" in sql


def test_migration_20_down_removes_tables():
    sql = AsyncMigration.from_file(str(MIGRATIONS / "20_down.surrealql")).sql
    assert "REMOVE TABLE IF EXISTS membership" in sql
    assert "REMOVE TABLE IF EXISTS workspace" in sql


def test_migration_20_is_registered():
    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 20
    assert len(manager.down_migrations) == 20
    assert "workspace" in manager.up_migrations[19].sql
    assert "membership" in manager.down_migrations[19].sql
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_migration_20.py -q` — Expected: FAIL (files don't exist yet: `test_migration_20_files_exist` asserts False; the registration test finds 19 migrations, not 20).

- [ ] **Step 3: Write minimal implementation** —

`open_notebook/database/migrations/20.surrealql`:
```surql
-- Migration 20: workspace + membership (multi-tenancy identity plane).
-- Identity-plane tables: NOT workspace-scoped. Login/onboarding must read a
-- user's memberships before any workspace is active, so these carry no tenant
-- filter; isolation is enforced by explicit user/workspace filters in the
-- service. workspace.kind distinguishes a solo "personal" tenant
-- (auto-provisioned at signup, exactly one member: its owner) from an
-- explicitly-created "company" tenant that supports invites + RBAC (P4+).

DEFINE TABLE IF NOT EXISTS workspace SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON TABLE workspace TYPE string;
DEFINE FIELD IF NOT EXISTS slug ON TABLE workspace TYPE string;
DEFINE FIELD IF NOT EXISTS kind ON TABLE workspace TYPE string ASSERT $value IN ['personal', 'company'];
DEFINE FIELD IF NOT EXISTS owner ON TABLE workspace TYPE record<user>;
DEFINE FIELD IF NOT EXISTS created ON workspace DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON workspace DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_workspace_slug ON TABLE workspace FIELDS slug UNIQUE;

DEFINE TABLE IF NOT EXISTS membership SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS user ON TABLE membership TYPE record<user>;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE membership TYPE record<workspace>;
DEFINE FIELD IF NOT EXISTS role ON TABLE membership TYPE string ASSERT $value IN ['owner', 'admin', 'member'];
DEFINE FIELD IF NOT EXISTS status ON TABLE membership TYPE string ASSERT $value IN ['active', 'invited', 'revoked'] DEFAULT 'active';
DEFINE FIELD IF NOT EXISTS created ON membership DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON membership DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_membership_user_workspace ON TABLE membership FIELDS user, workspace UNIQUE;
```
> Note: each `DEFINE FIELD ... ASSERT ...` statement is kept on ONE line because `AsyncMigration.from_file` joins lines with spaces after stripping `--` comments — a statement split across lines still joins fine, but keeping ASSERT clauses on their own single line avoids any accidental `--` interaction. The test above tolerates either one-or-two-space alignment around `kind`/`role` so the DDL author is free to align columns for readability without breaking the assertion; write it as shown (single space) to match the rest of the file's style.

`open_notebook/database/migrations/20_down.surrealql`:
```surql
-- Migration 20 rollback: drop membership first (references workspace), then workspace.
REMOVE TABLE IF EXISTS membership;
REMOVE TABLE IF EXISTS workspace;
```

`open_notebook/database/async_migrate.py` — in `AsyncMigrationManager.__init__`, append to `up_migrations` (immediately after the `19.surrealql` entry, before the closing `]`):
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

- [ ] **Step 5: Commit** — `git add open_notebook/database/migrations/20.surrealql open_notebook/database/migrations/20_down.surrealql open_notebook/database/async_migrate.py tests/test_p2_migration_20.py && git commit -m "P2: migration 20 — workspace + membership tables"`

---

## Task 2: Domain models `Workspace` + `Membership`

**Files:**
- Create: `open_notebook/domain/workspace.py`
- Modify: `open_notebook/domain/__init__.py`
- Test: `tests/test_p2_domain_workspace.py`

**Interfaces:**
- Consumes: `ObjectModel` (from `open_notebook/domain/base.py`) — provides `save()`/`get()`/`get_all()`/`delete()` and `created`/`updated`; `ensure_record_id` (from `open_notebook/database/repository.py`).
- Produces: `Workspace(name, slug, kind, owner)` and `Membership(user, workspace, role, status="active")`, both with `table_name` ClassVars so `ObjectModel.get()` polymorphic resolution finds them. Both override `_prepare_save_data` to persist record-link fields (`owner`, `user`, `workspace`) as `RecordID` (so SurrealDB `record<...>` fields type-check).

- [ ] **Step 1: Write the failing test** — `tests/test_p2_domain_workspace.py`:
```python
"""Unit tests for Workspace / Membership domain models (DB-free)."""

from surrealdb import RecordID

from open_notebook.domain.base import ObjectModel
from open_notebook.domain.workspace import Membership, Workspace


def test_workspace_fields_and_table_name():
    w = Workspace(name="Acme Inc", slug="acme-inc", kind="company", owner="user:abc")
    assert w.table_name == "workspace"
    assert w.name == "Acme Inc"
    assert w.slug == "acme-inc"
    assert w.kind == "company"
    assert w.owner == "user:abc"


def test_personal_workspace_kind():
    w = Workspace(name="Personal", slug="personal-abc", kind="personal", owner="user:abc")
    assert w.kind == "personal"


def test_membership_defaults_active():
    m = Membership(user="user:abc", workspace="workspace:xyz", role="owner")
    assert m.table_name == "membership"
    assert m.status == "active"
    assert m.role == "owner"


def test_workspace_prepare_save_converts_owner_to_record_id():
    data = Workspace(
        name="Acme", slug="acme", kind="company", owner="user:abc"
    )._prepare_save_data()
    assert isinstance(data["owner"], RecordID)
    assert str(data["owner"]) == "user:abc"


def test_membership_prepare_save_converts_links_to_record_id():
    data = Membership(
        user="user:abc", workspace="workspace:xyz", role="member"
    )._prepare_save_data()
    assert isinstance(data["user"], RecordID)
    assert isinstance(data["workspace"], RecordID)
    assert str(data["user"]) == "user:abc"
    assert str(data["workspace"]) == "workspace:xyz"


def test_polymorphic_resolution_registers_subclasses():
    # ObjectModel.get() resolves by table_name prefix; importing workspace.py must
    # register both subclasses so get("workspace:...") / get("membership:...") work.
    assert ObjectModel._get_class_by_table_name("workspace") is Workspace
    assert ObjectModel._get_class_by_table_name("membership") is Membership
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_domain_workspace.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'open_notebook.domain.workspace'`.

- [ ] **Step 3: Write minimal implementation** —

`open_notebook/domain/workspace.py`:
```python
from typing import Any, ClassVar, Dict

from open_notebook.database.repository import ensure_record_id
from open_notebook.domain.base import ObjectModel


class Workspace(ObjectModel):
    table_name: ClassVar[str] = "workspace"
    name: str
    slug: str
    kind: str  # "personal" | "company"
    owner: str  # "user:<id>" record link

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("owner") is not None:
            data["owner"] = ensure_record_id(data["owner"])
        return data


class Membership(ObjectModel):
    table_name: ClassVar[str] = "membership"
    user: str  # "user:<id>" record link
    workspace: str  # "workspace:<id>" record link
    role: str  # owner | admin | member
    status: str = "active"  # active | invited | revoked

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("user") is not None:
            data["user"] = ensure_record_id(data["user"])
        if data.get("workspace") is not None:
            data["workspace"] = ensure_record_id(data["workspace"])
        return data
```

`open_notebook/domain/__init__.py` — replace the body so the subclasses are imported at package import time (belt-and-suspenders for polymorphic `get()`):
```python
"""
Domain models for Open Notebook.

This module exports the core domain models used throughout the application.
"""

from open_notebook.domain.workspace import Membership, Workspace

__all__: list[str] = ["Workspace", "Membership"]
```
> If P1's `open_notebook/domain/user.py` has already been merged and also patches `domain/__init__.py` (to export `User`/`AuthIdentity`), MERGE the import lines rather than overwriting P1's — both modules' subclasses must be imported for polymorphic `get()` to resolve every table.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_domain_workspace.py -q` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/domain/workspace.py open_notebook/domain/__init__.py tests/test_p2_domain_workspace.py && git commit -m "P2: Workspace + Membership domain models"`

---

## Task 3: `api/workspace_service.py` — slug + personal auto-provision + company create logic

**Files:**
- Create: `api/workspace_service.py`
- Test: `tests/test_p2_workspace_service.py`

**Interfaces:**
- Consumes: `Workspace`, `Membership` (Task 2); `repo_query`, `ensure_record_id` (repository); `DuplicateResourceError` (exceptions). `Workspace.save()`/`Membership.save()` internally call `repo_create` (via `open_notebook.domain.base` → `open_notebook.database.repository`).
- Produces:
  - `slugify(name) -> str` — lower-case, `[^a-z0-9]+ → "-"`, strip dashes, truncate to 40; empty → `"workspace"`.
  - `async ensure_personal_workspace(user_id) -> Workspace` — **idempotent get-or-create** of the caller's single `kind="personal"` workspace + owner membership. THE ONLY place a personal workspace is ever created via application code. Lookup is by `(owner, kind='personal')`, never by a hardcoded record id. **Cross-phase note (P2 ↔ P3):** P3's migration 21 self-seeds a fixed-id `workspace:personal_default` for the first pre-existing user only if that user has no personal workspace yet (see P3's plan/spec); because this function's lookup keys on `(owner, kind='personal')` and not on that id, the next time that user logs in, `ensure_personal_workspace` finds and reuses migration 21's seeded row instead of creating a duplicate.
  - `async create_workspace(user_id, name, slug=None) -> tuple[Workspace, Membership]` — saves a `kind="company"` workspace (409 on slug collision) + owner membership; best-effort deletes the workspace if membership save fails.
  - `async list_memberships(user_id) -> list[dict]` — active memberships joined to workspace: `{workspace_id, name, slug, kind, role, created, updated}`, ordered `created ASC` (personal is always first, since `ensure_personal_workspace` always runs before any company can exist for that user).
  - `async get_membership(user_id, workspace_id) -> Optional[Membership]` — single-row lookup (status not filtered here; the caller checks `status`). Works identically for personal or company workspace ids.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_workspace_service.py`:
```python
"""Unit tests for api/workspace_service.py (repo layer mocked)."""

from unittest.mock import AsyncMock, patch

import pytest

from api.workspace_service import (
    create_workspace,
    ensure_personal_workspace,
    get_membership,
    list_memberships,
    slugify,
)
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import DuplicateResourceError


def test_slugify_basic():
    assert slugify("Acme Inc.") == "acme-inc"
    assert slugify("  Hello   World!! ") == "hello-world"
    assert slugify("") == "workspace"
    assert slugify("!!!") == "workspace"
    assert len(slugify("x" * 100)) == 40


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_ensure_personal_workspace_creates_when_absent(mock_query):
    # 1st call: no existing personal workspace found. 2nd call (post-create,
    # membership existence check): no existing membership found either.
    mock_query.side_effect = [[], []]
    with patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = [
            [{
                "id": "workspace:p1",
                "name": "Personal",
                "slug": "personal-1",
                "kind": "personal",
                "owner": "user:1",
                "created": "2026-07-11T00:00:00Z",
                "updated": "2026-07-11T00:00:00Z",
            }],
            [{
                "id": "membership:1",
                "user": "user:1",
                "workspace": "workspace:p1",
                "role": "owner",
                "status": "active",
            }],
        ]
        workspace = await ensure_personal_workspace("user:1")
    assert workspace.id == "workspace:p1"
    assert workspace.kind == "personal"


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_ensure_personal_workspace_idempotent_when_present(mock_query):
    mock_query.return_value = [{
        "id": "workspace:p1",
        "name": "Personal",
        "slug": "personal-1",
        "kind": "personal",
        "owner": "user:1",
    }]
    with patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock) as mock_create:
        workspace = await ensure_personal_workspace("user:1")
        mock_create.assert_not_awaited()  # no-op: nothing created on the 2nd call
    assert workspace.id == "workspace:p1"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_workspace_creates_owner_membership(mock_create):
    # First repo_create -> workspace row; second -> membership row.
    mock_create.side_effect = [
        [{
            "id": "workspace:acme",
            "name": "Acme",
            "slug": "acme",
            "kind": "company",
            "owner": "user:1",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }],
        [{
            "id": "membership:1",
            "user": "user:1",
            "workspace": "workspace:acme",
            "role": "owner",
            "status": "active",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }],
    ]
    workspace, membership = await create_workspace("user:1", "Acme")
    assert workspace.id == "workspace:acme"
    assert workspace.kind == "company"
    assert workspace.slug == "acme"
    assert membership.role == "owner"
    assert membership.status == "active"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_workspace_slug_collision_raises_duplicate(mock_create):
    mock_create.side_effect = RuntimeError(
        "Database index `idx_workspace_slug` already contains 'acme'"
    )
    with pytest.raises(DuplicateResourceError):
        await create_workspace("user:1", "Acme")


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_delete", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_workspace_orphan_cleanup_on_membership_failure(
    mock_create, mock_delete
):
    mock_create.side_effect = [
        [{"id": "workspace:acme", "name": "Acme", "slug": "acme", "kind": "company", "owner": "user:1"}],
        RuntimeError("boom"),
    ]
    with pytest.raises(RuntimeError):
        await create_workspace("user:1", "Acme")
    mock_delete.assert_awaited()  # workspace was cleaned up


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_list_memberships_maps_rows_including_kind(mock_query):
    mock_query.return_value = [
        {
            "role": "owner",
            "workspace": {
                "id": "workspace:p1",
                "name": "Personal",
                "slug": "personal-1",
                "kind": "personal",
                "created": "2026-07-11T00:00:00Z",
                "updated": "2026-07-11T00:00:00Z",
            },
        },
        {
            "role": "owner",
            "workspace": {
                "id": "workspace:acme",
                "name": "Acme",
                "slug": "acme",
                "kind": "company",
                "created": "2026-07-11T00:00:00Z",
                "updated": "2026-07-11T00:00:00Z",
            },
        },
    ]
    rows = await list_memberships("user:1")
    assert rows == [
        {
            "workspace_id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        },
        {
            "workspace_id": "workspace:acme",
            "name": "Acme",
            "slug": "acme",
            "kind": "company",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        },
    ]
    # Isolation: the query filters by the caller's user id.
    assert "WHERE user = $user" in mock_query.await_args.args[0]


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_get_membership_returns_none_when_absent(mock_query):
    mock_query.return_value = []
    assert await get_membership("user:1", "workspace:acme") is None


@pytest.mark.asyncio
@patch("api.workspace_service.repo_query", new_callable=AsyncMock)
async def test_get_membership_returns_membership(mock_query):
    mock_query.return_value = [{
        "id": "membership:1",
        "user": "user:1",
        "workspace": "workspace:acme",
        "role": "member",
        "status": "active",
    }]
    m = await get_membership("user:1", "workspace:acme")
    assert isinstance(m, Membership)
    assert m.role == "member"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_workspace_service.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'api.workspace_service'`.

- [ ] **Step 3: Write minimal implementation** — `api/workspace_service.py`:
```python
"""Workspace + membership business logic (routers stay thin, per api/AGENTS.md).

Identity-plane: every read filters explicitly by the caller's user id — there is
no SurrealDB RLS to fall back on. A workspace is either kind="personal" (exactly
one per user, auto-provisioned by ensure_personal_workspace, never created via
the API) or kind="company" (explicitly created via create_workspace). P2 only
ever writes an `active` `owner` membership; `invited`/`revoked` and other roles
arrive with P4.
"""

import re
from typing import List, Optional, Tuple

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import DuplicateResourceError

_SLUG_SUB = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Human-readable slug: lower-case, non-alphanumeric -> '-', trimmed, <=40.

    Lifted from arteamis-system companies._slugify but WITHOUT the random uuid
    suffix — we keep slugs clean and let the unique index reject collisions (409).
    """
    base = _SLUG_SUB.sub("-", name.strip().lower()).strip("-")
    base = base[:40].strip("-")
    return base or "workspace"


def _personal_slug(user_id: str) -> str:
    """Deterministic, per-user slug for the auto-provisioned personal workspace.

    Tied 1:1 to the user's own record id (not the display name), so it can
    never collide across users and needs no random suffix.
    """
    local = user_id.split(":", 1)[1] if ":" in user_id else user_id
    return f"personal-{local}"[:40]


def _is_slug_conflict(error: Exception) -> bool:
    msg = str(error)
    return "idx_workspace_slug" in msg or "already contains" in msg


async def ensure_personal_workspace(user_id: str) -> Workspace:
    """Idempotent get-or-create for the caller's personal workspace + owner membership.

    Called on every login/register/refresh (via auth_service.build_session_payload)
    so a logged-in user ALWAYS has an active workspace-scoped token — this is the
    ONLY place a kind="personal" workspace is ever created; there is no API
    endpoint for it. A personal workspace's owner IS its sole member, so
    (owner, kind='personal') uniquely identifies it — no separate lookup table
    or flag on `user` is needed.
    """
    rows = await repo_query(
        "SELECT * FROM workspace WHERE owner = $user AND kind = 'personal' LIMIT 1",
        {"user": ensure_record_id(user_id)},
    )
    if rows:
        return Workspace(**rows[0])

    workspace = Workspace(
        name="Personal", slug=_personal_slug(user_id), kind="personal", owner=user_id
    )
    try:
        await workspace.save()
    except Exception as e:
        if not _is_slug_conflict(e):
            raise
        # Slug is deterministic per user, so a conflict here only means a
        # concurrent call for this SAME user already created it — re-fetch.
        rows = await repo_query(
            "SELECT * FROM workspace WHERE owner = $user AND kind = 'personal' LIMIT 1",
            {"user": ensure_record_id(user_id)},
        )
        if not rows:
            raise
        return Workspace(**rows[0])

    membership_rows = await repo_query(
        "SELECT * FROM membership WHERE user = $user AND workspace = $workspace LIMIT 1",
        {
            "user": ensure_record_id(user_id),
            "workspace": ensure_record_id(workspace.id or ""),
        },
    )
    if not membership_rows:
        membership = Membership(
            user=user_id, workspace=workspace.id or "", role="owner", status="active"
        )
        await membership.save()
    return workspace


async def create_workspace(
    user_id: str, name: str, slug: Optional[str] = None
) -> Tuple[Workspace, Membership]:
    """Create a kind="company" workspace + its owner membership. 409 on slug collision.

    There is no `kind` parameter — this function ONLY ever creates a company
    workspace; personal workspaces are exclusively created by
    ensure_personal_workspace. This is the enforcement point for "you cannot
    create/treat a personal workspace as a company via the API."
    """
    slug_value = slugify(slug) if slug else slugify(name)

    workspace = Workspace(name=name, slug=slug_value, kind="company", owner=user_id)
    try:
        await workspace.save()
    except Exception as e:
        if _is_slug_conflict(e):
            raise DuplicateResourceError("Workspace slug already exists")
        raise

    try:
        membership = Membership(
            user=user_id, workspace=workspace.id or "", role="owner", status="active"
        )
        await membership.save()
    except Exception:
        # Best-effort: avoid an orphan workspace if the membership write fails.
        try:
            await workspace.delete()
        except Exception as ce:  # pragma: no cover - cleanup best effort
            logger.warning(f"Failed to clean up orphan workspace {workspace.id}: {ce}")
        raise

    return workspace, membership


async def list_memberships(user_id: str) -> List[dict]:
    """Active memberships for a user, each with its workspace's name/slug/kind/role.

    Ordered by `created ASC`: because ensure_personal_workspace always runs
    before a user can create any company workspace, the personal workspace is
    always the first row — callers (build_session_payload, the switcher) can
    rely on this ordering without a separate `kind` filter.
    """
    rows = await repo_query(
        "SELECT role, workspace FROM membership "
        "WHERE user = $user AND status = 'active' "
        "ORDER BY created ASC FETCH workspace",
        {"user": ensure_record_id(user_id)},
    )
    result: List[dict] = []
    for row in rows:
        workspace = row.get("workspace")
        if not isinstance(workspace, dict):
            continue
        result.append(
            {
                "workspace_id": str(workspace.get("id", "")),
                "name": workspace.get("name", ""),
                "slug": workspace.get("slug", ""),
                "kind": workspace.get("kind", "company"),
                "role": row.get("role", "member"),
                "created": str(workspace.get("created", "")),
                "updated": str(workspace.get("updated", "")),
            }
        )
    return result


async def get_membership(user_id: str, workspace_id: str) -> Optional[Membership]:
    """Single-row membership lookup on the (user, workspace) unique index.

    Status is NOT filtered here — the caller (switch-workspace) inspects
    `membership.status` so it can distinguish 'not a member' from 'revoked'.
    Works identically whether workspace_id is the caller's personal workspace
    or a company workspace — there is no kind branch.
    """
    rows = await repo_query(
        "SELECT * FROM membership WHERE user = $user AND workspace = $workspace LIMIT 1",
        {
            "user": ensure_record_id(user_id),
            "workspace": ensure_record_id(workspace_id),
        },
    )
    if not rows:
        return None
    return Membership(**rows[0])
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_workspace_service.py -q` — Expected: PASS (9 passed).

- [ ] **Step 5: Commit** — `git add api/workspace_service.py tests/test_p2_workspace_service.py && git commit -m "P2: workspace_service (slugify, ensure_personal_workspace, create/list/get)"`

---

## Task 4: Implement `create_access_token` in `api/security.py`

**Files:**
- Modify: `api/security.py` (replace P1's `create_access_token` stub with a real implementation)
- Test: `tests/test_p2_access_token.py`

**Interfaces:**
- Consumes: `jwt` (`from jose import jwt`), `AuthenticationError`, and module-level `JWT_SECRET`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` (already present in `api/security.py` after P1). `decode_access_token(token) -> AuthContext` (P1).
- Produces: `create_access_token(user_id, workspace_id, role, minutes=None) -> str` — a JWT with claims `sub`, `workspace_id`, `role`, `type="access"`, `exp`. Round-trips through `decode_access_token` into an `AuthContext` with populated `workspace_id`/`role`.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_access_token.py`:
```python
"""create_access_token mints a workspace-scoped token decode_access_token reads."""

import os

# Ensure a JWT secret exists before importing the security module (it reads
# config at import time). Mirrors tests/conftest.py's env-first pattern.
os.environ.setdefault("JWT_SECRET", "test-secret-p2-access-token")

import pytest

from api.security import create_access_token, decode_access_token
from open_notebook.exceptions import AuthenticationError


def test_access_token_round_trips_workspace_and_role():
    token = create_access_token(
        user_id="user:abc", workspace_id="workspace:xyz", role="owner"
    )
    ctx = decode_access_token(token)
    assert ctx.user_id == "user:abc"
    assert ctx.workspace_id == "workspace:xyz"
    assert ctx.role == "owner"


def test_access_token_rejects_non_user_subject():
    with pytest.raises(AuthenticationError):
        create_access_token(user_id="abc", workspace_id="workspace:xyz", role="owner")


def test_access_token_rejects_non_workspace_scope():
    with pytest.raises(AuthenticationError):
        create_access_token(user_id="user:abc", workspace_id="xyz", role="owner")


def test_access_token_round_trips_personal_workspace():
    # No special-case for a personal workspace id — same claim shape either way.
    token = create_access_token(
        user_id="user:abc", workspace_id="workspace:personal-abc", role="owner"
    )
    ctx = decode_access_token(token)
    assert ctx.workspace_id == "workspace:personal-abc"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_access_token.py -q` — Expected: FAIL — P1's stub raises `NotImplementedError`, so `test_access_token_round_trips_workspace_and_role` errors.

- [ ] **Step 3: Write minimal implementation** — In `api/security.py`, replace the `create_access_token` stub with:
```python
def create_access_token(
    user_id: str,
    workspace_id: str,
    role: str,
    minutes: int | None = None,
) -> str:
    """Workspace-scoped access token (claims: sub, workspace_id, role).

    Used for BOTH kinds of workspace: kind="personal" (auto-provisioned,
    minted on every login) and kind="company" (minted on create/switch) — the
    claim shape and validation are identical either way.

    SurrealDB record ids are strings like ``user:abc`` / ``workspace:xyz`` (not
    UUIDs), so validate the prefix instead of the arteamis-system UUID check.
    """
    if not isinstance(user_id, str) or not user_id.startswith("user:"):
        raise AuthenticationError("Access token subject must be a user record id")
    if not isinstance(workspace_id, str) or not workspace_id.startswith("workspace:"):
        raise AuthenticationError("Access token workspace must be a workspace record id")
    mins = ACCESS_TOKEN_EXPIRE_MINUTES if minutes is None else minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=mins)
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
```
> If P1's file does not already `from datetime import datetime, timedelta, timezone`, add it (the identity-token helper needs the same imports, so it is almost certainly present). If P1's `AuthContext`/stub used `company_id` instead of `workspace_id`, rename that field here (and in `decode_access_token`) as the one exception to "don't touch P1's file beyond this function" — see the terminology assumption at the top of this plan.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_access_token.py -q` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add api/security.py tests/test_p2_access_token.py && git commit -m "P2: implement workspace-scoped create_access_token"`

---

## Task 5: `api/deps.py` — `get_identity`, `get_auth_context`, `require_role`

**Files:**
- Create: `api/deps.py`
- Test: `tests/test_p2_deps.py`

**Interfaces:**
- Consumes: `decode_identity_token`, `decode_access_token`, `AuthContext` (from `api.security`); `AuthenticationError`.
- Produces:
  - `get_identity(creds) -> str` — user_id from an identity OR access token (the pre-workspace dependency). 401 on missing/invalid token.
  - `get_auth_context(creds) -> AuthContext` — requires a **workspace-scoped** token; 401 if the token carries no `workspace_id`/`role` (i.e. an identity-only token).
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
async def test_get_identity_accepts_access_token_too():
    # A caller with a workspace-scoped token (the common case post-P2) must
    # also be able to hit identity-level endpoints like POST /workspaces.
    token = create_access_token("user:abc", "workspace:xyz", "owner")
    assert await get_identity(_creds(token)) == "user:abc"


@pytest.mark.asyncio
async def test_get_identity_missing_header_401():
    with pytest.raises(AuthenticationError):
        await get_identity(None)


@pytest.mark.asyncio
async def test_get_auth_context_requires_workspace_scope():
    # An identity-only token has no workspace_id -> get_auth_context rejects it.
    token = create_identity_token("user:abc")
    with pytest.raises(AuthenticationError):
        await get_auth_context(_creds(token))


@pytest.mark.asyncio
async def test_get_auth_context_accepts_access_token():
    token = create_access_token("user:abc", "workspace:xyz", "owner")
    ctx = await get_auth_context(_creds(token))
    assert ctx.workspace_id == "workspace:xyz"
    assert ctx.role == "owner"


@pytest.mark.asyncio
async def test_require_role_allows_matching_role():
    dep = require_role("owner", "admin")
    ctx = AuthContext(user_id="user:abc", workspace_id="workspace:xyz", role="owner")
    assert await dep(ctx) is ctx


@pytest.mark.asyncio
async def test_require_role_forbids_other_role():
    dep = require_role("owner", "admin")
    ctx = AuthContext(user_id="user:abc", workspace_id="workspace:xyz", role="member")
    with pytest.raises(HTTPException) as exc:
        await dep(ctx)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_deps.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'api.deps'`.

- [ ] **Step 3: Write minimal implementation** — `api/deps.py`:
```python
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
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_deps.py -q` — Expected: PASS (7 passed).

- [ ] **Step 5: Commit** — `git add api/deps.py tests/test_p2_deps.py && git commit -m "P2: api/deps.py — get_identity, get_auth_context, require_role"`

---

## Task 6: Wire `ensure_personal_workspace` into `build_session_payload` (auto-provision on login)

**Files:**
- Modify: `api/auth_service.py` (P1 owns the file; P2 rewrites this one function)
- Modify: `api/models.py` (rename `SessionPayload`/`MeResponse`'s `active_company_id` → `active_workspace_id` if P1 used the old name; append if absent)
- Test: `tests/test_p2_session_payload.py`

**Interfaces:**
- Consumes: `ensure_personal_workspace`, `list_memberships` (Task 3); `create_access_token` (Task 4); `User` (P1's `open_notebook/domain/user.py`).
- Produces: `build_session_payload(user) -> dict` that ALWAYS returns a workspace-scoped `access_token` for the caller's personal workspace, `active_workspace_id` set (never `None`), `memberships` non-empty, and `needs_onboarding` repurposed to mean "has no company workspace yet" (a soft UI signal, not a redirect gate).

- [ ] **Step 1: Write the failing test** — `tests/test_p2_session_payload.py`:
```python
"""build_session_payload auto-provisions the personal workspace on every call."""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-p2-session-payload")

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.auth_service import build_session_payload
from api.security import decode_access_token


def _user(user_id="user:1", email="a@example.com", display_name="Ada"):
    return SimpleNamespace(id=user_id, email=email, display_name=display_name)


@pytest.mark.asyncio
@patch("api.auth_service.list_memberships", new_callable=AsyncMock)
@patch("api.auth_service.ensure_personal_workspace", new_callable=AsyncMock)
async def test_session_payload_is_workspace_scoped_for_new_user(
    mock_ensure, mock_list
):
    mock_ensure.return_value = SimpleNamespace(id="workspace:p1", kind="personal")
    mock_list.return_value = [
        {
            "workspace_id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]

    payload = await build_session_payload(_user())

    ctx = decode_access_token(payload["access_token"])
    assert ctx.workspace_id == "workspace:p1"
    assert ctx.role == "owner"
    assert payload["active_workspace_id"] == "workspace:p1"
    assert payload["needs_onboarding"] is True  # no company workspace yet
    assert payload["memberships"] == mock_list.return_value
    mock_ensure.assert_awaited_once_with("user:1")


@pytest.mark.asyncio
@patch("api.auth_service.list_memberships", new_callable=AsyncMock)
@patch("api.auth_service.ensure_personal_workspace", new_callable=AsyncMock)
async def test_session_payload_needs_onboarding_false_once_a_company_exists(
    mock_ensure, mock_list
):
    mock_ensure.return_value = SimpleNamespace(id="workspace:p1", kind="personal")
    mock_list.return_value = [
        {"workspace_id": "workspace:p1", "name": "Personal", "slug": "personal-1", "kind": "personal", "role": "owner", "created": "", "updated": ""},
        {"workspace_id": "workspace:acme", "name": "Acme", "slug": "acme", "kind": "company", "role": "owner", "created": "", "updated": ""},
    ]

    payload = await build_session_payload(_user())

    # Even with a company membership, a fresh login resets the ACTIVE workspace
    # to Personal (the stated default decision) — only the onboarding signal
    # changes, not which workspace is active.
    assert payload["active_workspace_id"] == "workspace:p1"
    assert payload["needs_onboarding"] is False


@pytest.mark.asyncio
@patch("api.auth_service.list_memberships", new_callable=AsyncMock)
@patch("api.auth_service.ensure_personal_workspace", new_callable=AsyncMock)
async def test_session_payload_never_returns_null_active_workspace(
    mock_ensure, mock_list
):
    mock_ensure.return_value = SimpleNamespace(id="workspace:p1", kind="personal")
    mock_list.return_value = []  # defensive: even if the list query races, don't crash

    payload = await build_session_payload(_user())

    assert payload["active_workspace_id"] == "workspace:p1"
    assert payload["memberships"] == []
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_session_payload.py -q` — Expected: FAIL — `api.auth_service` either doesn't exist yet (P1 not merged) or its `build_session_payload` still returns the P1 placeholder (`needs_onboarding: True` unconditionally, `active_workspace_id/active_company_id: None`, `memberships: []`, an identity-only `access_token`).

- [ ] **Step 3: Write minimal implementation** — In `api/auth_service.py`, replace `build_session_payload` with:
```python
from api.security import create_access_token
from api.workspace_service import ensure_personal_workspace, list_memberships


async def build_session_payload(user) -> dict:
    """Session payload for register/login/refresh/Google-callback.

    ALWAYS auto-provisions (idempotently) the caller's personal workspace and
    returns a workspace-scoped token for it — a logged-in user never holds a
    bare identity-only session. `needs_onboarding` is repurposed from P1's
    hard-coded placeholder: it no longer gates anything, it only signals
    "no company workspace yet" for an optional, dismissible frontend prompt.
    Every call resets the ACTIVE workspace to Personal (stated default
    decision — see the spec's Open questions) even if the user also owns
    companies; switching to one is a per-session action.
    """
    personal = await ensure_personal_workspace(str(user.id))
    memberships = await list_memberships(str(user.id))
    has_company = any(m["kind"] == "company" for m in memberships)
    access_token = create_access_token(
        user_id=str(user.id), workspace_id=personal.id or "", role="owner"
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "needs_onboarding": not has_company,
        "active_workspace_id": personal.id,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
        },
        "memberships": memberships,
    }
```
`api/models.py` — if P1's `SessionPayload`/`MeResponse` schemas used `active_company_id`, rename the field to `active_workspace_id` (the v2 terminology patch applies to every P1-owned schema too, per the brief); if P1 has not defined these schemas yet, this plan does not need to add them (P1 owns them) — Task 6 only requires that whatever P1 ships names the field `active_workspace_id`.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_session_payload.py -q` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add api/auth_service.py api/models.py tests/test_p2_session_payload.py && git commit -m "P2: auto-provision personal workspace in build_session_payload"`

---

## Task 7: Schemas + `POST /workspaces` + `GET /workspaces` router

**Files:**
- Modify: `api/models.py` (append `WorkspaceCreate`, `WorkspaceResponse`, `TokenResponse`)
- Create: `api/routers/workspaces.py`
- Modify: `api/main.py` (import + register the workspaces router)
- Test: `tests/test_p2_workspaces_router.py`

**Interfaces:**
- Consumes: `get_identity` (Task 5); `create_workspace`, `list_memberships` (Task 3); `create_access_token` (Task 4); the new schemas.
- Produces: `POST /api/workspaces` (201 → `TokenResponse` with a freshly minted owner access token for a NEW `kind="company"` workspace) and `GET /api/workspaces` (→ `List[WorkspaceResponse]`, caller's active memberships including their personal workspace). Slug collisions raise `DuplicateResourceError` → 409 (P1 handler).

- [ ] **Step 1: Write the failing test** — `tests/test_p2_workspaces_router.py`:
```python
"""API tests for POST/GET /workspaces (service + token minting exercised)."""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-p2-router")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token, decode_access_token
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import DuplicateResourceError


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _auth(user_id: str = "user:1") -> dict:
    return {"Authorization": f"Bearer {create_identity_token(user_id)}"}


@patch("api.routers.workspaces.create_workspace", new_callable=AsyncMock)
def test_create_workspace_returns_owner_token(mock_create, client):
    workspace = Workspace(id="workspace:acme", name="Acme", slug="acme", kind="company", owner="user:1")
    membership = Membership(
        id="membership:1", user="user:1", workspace="workspace:acme", role="owner"
    )
    mock_create.return_value = (workspace, membership)

    resp = client.post("/api/workspaces", json={"name": "Acme"}, headers=_auth())

    assert resp.status_code == 201
    body = resp.json()
    assert body["active_workspace_id"] == "workspace:acme"
    assert body["role"] == "owner"
    ctx = decode_access_token(body["access_token"])
    assert ctx.user_id == "user:1"
    assert ctx.workspace_id == "workspace:acme"
    assert ctx.role == "owner"
    mock_create.assert_awaited_once_with("user:1", "Acme", None)


@patch("api.routers.workspaces.create_workspace", new_callable=AsyncMock)
def test_create_workspace_slug_conflict_returns_409(mock_create, client):
    mock_create.side_effect = DuplicateResourceError("Workspace slug already exists")
    resp = client.post("/api/workspaces", json={"name": "Acme"}, headers=_auth())
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Workspace slug already exists"


def test_create_workspace_requires_auth(client):
    assert client.post("/api/workspaces", json={"name": "Acme"}).status_code == 401


def test_create_workspace_empty_name_422(client):
    resp = client.post("/api/workspaces", json={"name": ""}, headers=_auth())
    assert resp.status_code == 422


def test_create_workspace_body_has_no_kind_field(client):
    # A client CANNOT request kind="personal" — the schema has no such field, so
    # an extra "kind" in the body is silently ignored by Pydantic (not an error),
    # and the service always creates kind="company" regardless.
    with patch("api.routers.workspaces.create_workspace", new_callable=AsyncMock) as mock_create:
        workspace = Workspace(id="workspace:x", name="X", slug="x", kind="company", owner="user:1")
        membership = Membership(id="membership:1", user="user:1", workspace="workspace:x", role="owner")
        mock_create.return_value = (workspace, membership)
        resp = client.post(
            "/api/workspaces", json={"name": "X", "kind": "personal"}, headers=_auth()
        )
    assert resp.status_code == 201
    mock_create.assert_awaited_once_with("user:1", "X", None)  # "kind" was ignored


@patch("api.routers.workspaces.list_memberships", new_callable=AsyncMock)
def test_list_workspaces_returns_only_callers_memberships(mock_list, client):
    mock_list.return_value = [
        {
            "workspace_id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]
    resp = client.get("/api/workspaces", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "id": "workspace:p1",
            "name": "Personal",
            "slug": "personal-1",
            "kind": "personal",
            "role": "owner",
            "created": "2026-07-11T00:00:00Z",
            "updated": "2026-07-11T00:00:00Z",
        }
    ]
    mock_list.assert_awaited_once_with("user:1")


@patch("api.routers.workspaces.list_memberships", new_callable=AsyncMock)
def test_list_workspaces_never_empty_for_authenticated_user(mock_list, client):
    # Contrast with the superseded company-only draft: an authenticated user
    # always has at least their personal workspace.
    mock_list.return_value = [
        {"workspace_id": "workspace:p1", "name": "Personal", "slug": "personal-1", "kind": "personal", "role": "owner", "created": "", "updated": ""}
    ]
    resp = client.get("/api/workspaces", headers=_auth())
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["kind"] == "personal"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_workspaces_router.py -q` — Expected: FAIL — `api.routers.workspaces` does not exist yet (import error inside `api.main`), or 404 on the routes.

- [ ] **Step 3: Write minimal implementation** —

`api/models.py` — append (the file already imports `BaseModel`, `Field`, and `Optional`; if `Optional` is not imported there, add `from typing import Optional`):
```python
class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: Optional[str] = None  # optional explicit slug; else derived from name
    # NOTE: intentionally no `kind` field. POST /workspaces always creates
    # kind="company" — a client cannot request/relabel a personal workspace.


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    kind: str  # "personal" | "company"
    role: str  # caller's role in this workspace
    created: str
    updated: str


class TokenResponse(BaseModel):  # returned by workspace create + switch (+ reused by login/register)
    access_token: str
    token_type: str = "bearer"
    active_workspace_id: str
    role: str
```

`api/routers/workspaces.py`:
```python
from typing import List

from fastapi import APIRouter, Depends

from api.deps import get_identity
from api.models import WorkspaceCreate, WorkspaceResponse, TokenResponse
from api.security import create_access_token
from api.workspace_service import create_workspace, list_memberships

router = APIRouter()


@router.post("/workspaces", response_model=TokenResponse, status_code=201)
async def create_workspace_endpoint(
    body: WorkspaceCreate,
    user_id: str = Depends(get_identity),
) -> TokenResponse:
    """Create a company workspace; the caller becomes its owner.

    Open to any authenticated user (incl. one who has only ever used their
    personal workspace — you cannot require a role you do not yet have).
    ALWAYS creates kind="company" (WorkspaceCreate has no kind field). Re-mints
    a workspace-scoped `owner` access token so the very next request (P3
    project create) is scoped to the new workspace. A slug collision raises
    DuplicateResourceError -> 409 (global handler).
    """
    workspace, membership = await create_workspace(user_id, body.name, body.slug)
    access_token = create_access_token(
        user_id=user_id,
        workspace_id=workspace.id or "",
        role=membership.role,
    )
    return TokenResponse(
        access_token=access_token,
        active_workspace_id=workspace.id or "",
        role=membership.role,
    )


@router.get("/workspaces", response_model=List[WorkspaceResponse])
async def list_workspaces_endpoint(
    user_id: str = Depends(get_identity),
) -> List[WorkspaceResponse]:
    """List the caller's active memberships — always includes their personal workspace."""
    rows = await list_memberships(user_id)
    return [
        WorkspaceResponse(
            id=row["workspace_id"],
            name=row["name"],
            slug=row["slug"],
            kind=row["kind"],
            role=row["role"],
            created=row["created"],
            updated=row["updated"],
        )
        for row in rows
    ]
```

`api/main.py` — add `workspaces` to the routers import block (alphabetical, next to `transformations`):
```python
from api.routers import (
    auth,
    chat,
    commands,
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
    workspaces,
)
```
and register it alongside the other `app.include_router(...)` calls (e.g. right after the `auth` router):
```python
app.include_router(workspaces.router, prefix="/api", tags=["workspaces"])
```
> Adjust the exact import list to match whatever routers P1/P0 have already registered by the time this task runs (the list above reflects the routers present in `api/routers/` today, minus `companies`/`commands` naming drift — add `workspaces` wherever it sorts alphabetically).

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_workspaces_router.py -q` — Expected: PASS (7 passed).

- [ ] **Step 5: Commit** — `git add api/models.py api/routers/workspaces.py api/main.py tests/test_p2_workspaces_router.py && git commit -m "P2: /workspaces create + list endpoints"`

---

## Task 8: `POST /auth/switch-workspace/{workspace_id}` endpoint

**Files:**
- Modify: `api/routers/auth.py` (add the switch-workspace endpoint — P1 owns this file; P2 adds one route. NOTE: the file that exists in the repo TODAY is still the pre-P1 shared-password router; by the time this task runs, P1's rewrite must already be merged, per this plan's dependency on P1)
- Test: `tests/test_p2_switch_workspace.py`

**Interfaces:**
- Consumes: `get_identity` (Task 5); `get_membership` (Task 3); `create_access_token` (Task 4); `TokenResponse` (Task 7).
- Produces: `POST /api/auth/switch-workspace/{workspace_id}` — 403 if the caller has no membership in `{workspace_id}` or its `status != 'active'`; else 200 with a re-minted workspace-scoped `TokenResponse`. Works identically for a personal or company workspace id — switching back into your own personal workspace is ordinary, not a special case.

- [ ] **Step 1: Write the failing test** — `tests/test_p2_switch_workspace.py`:
```python
"""API tests for POST /auth/switch-workspace/{workspace_id}."""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-p2-switch")

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token, decode_access_token
from open_notebook.domain.workspace import Membership


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _auth(user_id: str = "user:1") -> dict:
    return {"Authorization": f"Bearer {create_identity_token(user_id)}"}


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_workspace_member_gets_scoped_token(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:1",
        user="user:1",
        workspace="workspace:acme",
        role="member",
        status="active",
    )
    resp = client.post("/api/auth/switch-workspace/workspace:acme", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_workspace_id"] == "workspace:acme"
    assert body["role"] == "member"
    ctx = decode_access_token(body["access_token"])
    assert ctx.workspace_id == "workspace:acme"
    assert ctx.role == "member"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_to_own_personal_workspace_works_like_any_other(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:0",
        user="user:1",
        workspace="workspace:p1",
        role="owner",
        status="active",
    )
    resp = client.post("/api/auth/switch-workspace/workspace:p1", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_workspace_non_member_403(mock_get, client):
    mock_get.return_value = None
    resp = client.post("/api/auth/switch-workspace/workspace:other", headers=_auth())
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Not a member of this workspace"


@patch("api.routers.auth.get_membership", new_callable=AsyncMock)
def test_switch_workspace_revoked_membership_403(mock_get, client):
    mock_get.return_value = Membership(
        id="membership:1",
        user="user:1",
        workspace="workspace:acme",
        role="member",
        status="revoked",
    )
    resp = client.post("/api/auth/switch-workspace/workspace:acme", headers=_auth())
    assert resp.status_code == 403


def test_switch_workspace_requires_auth(client):
    assert client.post("/api/auth/switch-workspace/workspace:acme").status_code == 401
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p2_switch_workspace.py -q` — Expected: FAIL — the route does not exist (404) so the 200/403 assertions fail.

- [ ] **Step 3: Write minimal implementation** — In `api/routers/auth.py`, add these imports (merge with P1's existing imports) and endpoint:
```python
from fastapi import Depends, HTTPException

from api.deps import get_identity
from api.models import TokenResponse
from api.security import create_access_token
from api.workspace_service import get_membership


@router.post("/switch-workspace/{workspace_id}", response_model=TokenResponse)
async def switch_workspace(
    workspace_id: str,
    user_id: str = Depends(get_identity),
) -> TokenResponse:
    """Re-mint a workspace-scoped token after re-verifying membership server-side.

    Never trusts a client-sent role: the role comes from the freshly-loaded
    membership. A non-member or a non-active (invited/revoked) membership -> 403.
    No kind branch: switching into a personal workspace (incl. your own) is
    handled by the exact same path as a company workspace.
    """
    membership = await get_membership(user_id, workspace_id)
    if membership is None or membership.status != "active":
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    access_token = create_access_token(
        user_id=user_id,
        workspace_id=workspace_id,
        role=membership.role,
    )
    return TokenResponse(
        access_token=access_token,
        active_workspace_id=workspace_id,
        role=membership.role,
    )
```
> The router is mounted at `prefix="/api"` with the router's own `prefix="/auth"`, so the full path is `/api/auth/switch-workspace/{workspace_id}`. It is NOT in P1's `JWTAuthMiddleware` excluded-paths list, so the middleware requires a valid token before the handler runs — consistent with `get_identity`.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p2_switch_workspace.py -q` — Expected: PASS (5 passed).

- [ ] **Step 5: Commit** — `git add api/routers/auth.py tests/test_p2_switch_workspace.py && git commit -m "P2: /auth/switch-workspace endpoint"`

- [ ] **Step 6: Run the full backend suite** — Run: `uv run pytest tests/ -q` — Expected: PASS (all P2 tests green, no regressions). Then `ruff check . --fix`.

---

## Task 9: Frontend API module + types + query key

**Files:**
- Modify: `frontend/src/lib/types/api.ts` (append workspace types)
- Create: `frontend/src/lib/api/workspaces.ts`
- Modify: `frontend/src/lib/api/query-client.ts` (add `workspaces` query key)
- Test: `frontend/src/lib/api/workspaces.test.ts`

**Interfaces:**
- Consumes: the shared `apiClient` (`frontend/src/lib/api/client.ts`).
- Produces: `workspacesApi.list()` → `WorkspaceResponse[]`, `workspacesApi.create(data)` → `TokenResponse`, `workspacesApi.switch(workspaceId)` → `TokenResponse`; types `WorkspaceResponse`, `CreateWorkspaceRequest`, `TokenResponse`, `Membership` (carrying `kind`); `QUERY_KEYS.workspaces`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/api/workspaces.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { workspacesApi } from './workspaces'
import apiClient from './client'

vi.mock('./client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

describe('workspacesApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('list GETs /workspaces', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [{ id: 'workspace:1', kind: 'personal' }] })
    const res = await workspacesApi.list()
    expect(apiClient.get).toHaveBeenCalledWith('/workspaces')
    expect(res).toEqual([{ id: 'workspace:1', kind: 'personal' }])
  })

  it('create POSTs /workspaces with the body', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { access_token: 't', token_type: 'bearer', active_workspace_id: 'workspace:1', role: 'owner' },
    })
    const res = await workspacesApi.create({ name: 'Acme' })
    expect(apiClient.post).toHaveBeenCalledWith('/workspaces', { name: 'Acme' })
    expect(res.active_workspace_id).toBe('workspace:1')
  })

  it('switch POSTs the switch-workspace path', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { access_token: 't', token_type: 'bearer', active_workspace_id: 'workspace:1', role: 'member' },
    })
    await workspacesApi.switch('workspace:1')
    expect(apiClient.post).toHaveBeenCalledWith('/auth/switch-workspace/workspace:1')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- workspaces` — Expected: FAIL — cannot resolve `./workspaces`.

- [ ] **Step 3: Write minimal implementation** —

`frontend/src/lib/types/api.ts` — append:
```ts
export interface WorkspaceResponse {
  id: string
  name: string
  slug: string
  kind: 'personal' | 'company'
  role: string
  created: string
  updated: string
}

export interface CreateWorkspaceRequest {
  name: string
  slug?: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  active_workspace_id: string
  role: string
}

// Shape of each row in the auth store's `memberships` (from GET /auth/me and
// workspace_service.list_memberships). Always includes the personal workspace.
export interface Membership {
  workspace_id: string
  name: string
  slug: string
  kind: 'personal' | 'company'
  role: string
}
```

`frontend/src/lib/api/workspaces.ts`:
```ts
import apiClient from './client'
import { CreateWorkspaceRequest, TokenResponse, WorkspaceResponse } from '@/lib/types/api'

export const workspacesApi = {
  list: () => apiClient.get<WorkspaceResponse[]>('/workspaces').then((r) => r.data),
  create: (data: CreateWorkspaceRequest) =>
    apiClient.post<TokenResponse>('/workspaces', data).then((r) => r.data),
  switch: (workspaceId: string) =>
    apiClient.post<TokenResponse>(`/auth/switch-workspace/${workspaceId}`).then((r) => r.data),
}
```

`frontend/src/lib/api/query-client.ts` — add to `QUERY_KEYS` (before the closing `}`):
```ts
  workspaces: ['workspaces'] as const,
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- workspaces` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/types/api.ts frontend/src/lib/api/workspaces.ts frontend/src/lib/api/query-client.ts frontend/src/lib/api/workspaces.test.ts && git commit -m "P2: frontend workspaces api + types + query key"`

---

## Task 10: Auth-store workspace slice (`applyToken`, `setSession`, `hasCompany`)

**Files:**
- Modify: `frontend/src/lib/stores/auth-store.ts` (extend the P1-rewritten store — NOTE: the file in the repo today is still the OLD shared-password version; P1's rewrite must land first per this plan's dependency)
- Test: `frontend/src/lib/stores/auth-store.workspace.test.ts`

**Interfaces:**
- Consumes: `Membership`, `TokenResponse` (Task 9). Assumes P1's store already holds `token`, `user`, `isAuthenticated`, `hasHydrated` and persists (`partialize`) `token`/`user`/`isAuthenticated` under `name: 'auth-storage'`.
- Produces (added to the store): state `memberships: Membership[]`, `activeWorkspaceId: string | null`, `role: string | null`; actions `applyToken(res)`, `setSession({ memberships, activeWorkspaceId })`, `setActiveWorkspace(workspaceId, role)`; extended `partialize` persisting `memberships`/`activeWorkspaceId`/`role`. **No `needsOnboarding` gate** — only a `hasCompany` selector for an optional, non-blocking UI prompt.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/stores/auth-store.workspace.test.ts`:
```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from './auth-store'

describe('auth-store workspace slice', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      memberships: [],
      activeWorkspaceId: null,
      role: null,
    })
  })

  it('applyToken swaps token, activeWorkspaceId and role', () => {
    useAuthStore.getState().applyToken({
      access_token: 'scoped-token',
      token_type: 'bearer',
      active_workspace_id: 'workspace:acme',
      role: 'owner',
    })
    const s = useAuthStore.getState()
    expect(s.token).toBe('scoped-token')
    expect(s.activeWorkspaceId).toBe('workspace:acme')
    expect(s.role).toBe('owner')
  })

  it('setSession stores memberships and the given activeWorkspaceId (always the personal workspace on login)', () => {
    useAuthStore.getState().setSession({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'member' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    const s = useAuthStore.getState()
    expect(s.memberships).toHaveLength(2)
    expect(s.activeWorkspaceId).toBe('workspace:p1')
    expect(s.role).toBe('owner')
  })

  it('hasCompany is false when only the personal workspace is present', () => {
    useAuthStore.getState().setSession({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    expect(useAuthStore.getState().hasCompany()).toBe(false)
  })

  it('hasCompany is true once a company membership exists', () => {
    useAuthStore.getState().setSession({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    expect(useAuthStore.getState().hasCompany()).toBe(true)
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- auth-store.workspace` — Expected: FAIL — `applyToken`/`setSession`/`hasCompany` are not functions.

- [ ] **Step 3: Write minimal implementation** — In `frontend/src/lib/stores/auth-store.ts` (the P1 version), merge in the workspace slice:

1. Import the types at the top:
```ts
import { Membership, TokenResponse } from '@/lib/types/api'
```
2. Add to the `AuthState` interface:
```ts
  memberships: Membership[]
  activeWorkspaceId: string | null
  role: string | null
  applyToken: (res: TokenResponse) => void
  setSession: (payload: { memberships: Membership[]; activeWorkspaceId: string | null }) => void
  setActiveWorkspace: (workspaceId: string, role: string) => void
  hasCompany: () => boolean
```
3. Add to the store's initial state object:
```ts
      memberships: [],
      activeWorkspaceId: null,
      role: null,
```
4. Add the four actions/selector inside the `(set, get) => ({ ... })` body:
```ts
      applyToken: (res: TokenResponse) => {
        // The single mutation shared by workspace create + switch: swap the
        // stored Bearer to the workspace-scoped access token (apiClient reads
        // state.token).
        set({
          token: res.access_token,
          activeWorkspaceId: res.active_workspace_id,
          role: res.role,
        })
      },

      setSession: ({ memberships, activeWorkspaceId }) => {
        // The backend's session payload always names the active workspace
        // (the caller's personal workspace on every fresh login — see the P2
        // spec's stated default) — trust it rather than re-deriving here.
        const active = memberships.find((m) => m.workspace_id === activeWorkspaceId)
        set({
          memberships,
          activeWorkspaceId,
          role: active ? active.role : null,
        })
      },

      setActiveWorkspace: (workspaceId: string, role: string) => {
        set({ activeWorkspaceId: workspaceId, role })
      },

      hasCompany: () => get().memberships.some((m) => m.kind === 'company'),
```
5. Extend `partialize` to persist the workspace slice (a workspace change must survive reload):
```ts
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        memberships: state.memberships,
        activeWorkspaceId: state.activeWorkspaceId,
        role: state.role,
      }),
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- auth-store.workspace` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/stores/auth-store.ts frontend/src/lib/stores/auth-store.workspace.test.ts && git commit -m "P2: auth-store workspace slice (applyToken/setSession/hasCompany)"`

---

## Task 11: `useWorkspaces` / `useCreateWorkspace` / `useSwitchWorkspace` hooks

**Files:**
- Create: `frontend/src/lib/hooks/use-workspaces.ts`
- Test: `frontend/src/lib/hooks/use-workspaces.test.tsx`

**Interfaces:**
- Consumes: `workspacesApi` (Task 9); `QUERY_KEYS.workspaces`; `useAuthStore.applyToken` (Task 10); `useToast`, `useTranslation`.
- Produces: `useWorkspaces()` (query), `useCreateWorkspace()` (mutation → `applyToken` + invalidate + toast; 409 → `workspace.slugTaken`), `useSwitchWorkspace()` (mutation → `applyToken` + `queryClient.clear()` + navigate).

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/hooks/use-workspaces.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useCreateWorkspace, useSwitchWorkspace } from './use-workspaces'
import { workspacesApi } from '@/lib/api/workspaces'
import { useAuthStore } from '@/lib/stores/auth-store'

vi.mock('@/lib/api/workspaces', () => ({
  workspacesApi: { list: vi.fn(), create: vi.fn(), switch: vi.fn() },
}))
vi.mock('@/lib/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))

const wrapper = (client: QueryClient) =>
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }

describe('use-workspaces', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({ token: null, activeWorkspaceId: null, role: null })
  })

  it('useCreateWorkspace success applies the token to the store', async () => {
    vi.mocked(workspacesApi.create).mockResolvedValue({
      access_token: 'scoped', token_type: 'bearer', active_workspace_id: 'workspace:1', role: 'owner',
    })
    const client = new QueryClient()
    const { result } = renderHook(() => useCreateWorkspace(), { wrapper: wrapper(client) })
    result.current.mutate({ name: 'Acme' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(useAuthStore.getState().token).toBe('scoped')
    expect(useAuthStore.getState().activeWorkspaceId).toBe('workspace:1')
  })

  it('useSwitchWorkspace success applies the token and clears the cache', async () => {
    vi.mocked(workspacesApi.switch).mockResolvedValue({
      access_token: 'scoped2', token_type: 'bearer', active_workspace_id: 'workspace:2', role: 'member',
    })
    const client = new QueryClient()
    const clearSpy = vi.spyOn(client, 'clear')
    const { result } = renderHook(() => useSwitchWorkspace(), { wrapper: wrapper(client) })
    result.current.mutate('workspace:2')
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(useAuthStore.getState().token).toBe('scoped2')
    expect(clearSpy).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- use-workspaces` — Expected: FAIL — cannot resolve `./use-workspaces`.

- [ ] **Step 3: Write minimal implementation** — `frontend/src/lib/hooks/use-workspaces.ts`:
```tsx
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { AxiosError } from 'axios'
import { workspacesApi } from '@/lib/api/workspaces'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateWorkspaceRequest } from '@/lib/types/api'

export function useWorkspaces() {
  return useQuery({
    queryKey: QUERY_KEYS.workspaces,
    queryFn: () => workspacesApi.list(),
  })
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const applyToken = useAuthStore((s) => s.applyToken)

  return useMutation({
    mutationFn: (data: CreateWorkspaceRequest) => workspacesApi.create(data),
    onSuccess: (res) => {
      applyToken(res)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaces })
      toast({ title: t('common.success'), description: t('workspace.createSuccess') })
    },
    onError: (error: unknown) => {
      const status = (error as AxiosError)?.response?.status
      const description =
        status === 409 ? t('workspace.slugTaken') : t(getApiErrorKey(error, t('common.error')))
      toast({ title: t('common.error'), description, variant: 'destructive' })
    },
  })
}

export function useSwitchWorkspace() {
  const queryClient = useQueryClient()
  const router = useRouter()
  const { toast } = useToast()
  const { t } = useTranslation()
  const applyToken = useAuthStore((s) => s.applyToken)

  return useMutation({
    mutationFn: (workspaceId: string) => workspacesApi.switch(workspaceId),
    onSuccess: (res) => {
      applyToken(res)
      // A workspace change invalidates ALL workspace-scoped caches.
      queryClient.clear()
      toast({ title: t('common.success'), description: t('workspace.switchSuccess') })
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

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- use-workspaces` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/hooks/use-workspaces.ts frontend/src/lib/hooks/use-workspaces.test.tsx && git commit -m "P2: use-workspaces hooks"`

---

## Task 12: Onboarding route + wizard — personal landing, company creation OPTIONAL

**Files:**
- Create: `frontend/src/app/onboarding/page.tsx`
- Create: `frontend/src/components/onboarding/OnboardingWizard.tsx`
- Create: `frontend/src/components/onboarding/WelcomeStep.tsx`
- Create: `frontend/src/components/onboarding/CompanyStep.tsx`
- Test: `frontend/src/components/onboarding/WelcomeStep.test.tsx`
- Test: `frontend/src/components/onboarding/CompanyStep.test.tsx`

**Interfaces:**
- Consumes: `useCreateWorkspace` (Task 11); `useTranslation`; UI primitives `Button`, `Input` (from `@/components/ui/*`). References i18n keys `onboarding.title`, `onboarding.welcomePersonalTitle`, `onboarding.welcomePersonalBody`, `onboarding.createCompanyCta`, `onboarding.skipCta`, `onboarding.companyStepTitle`, `onboarding.stepWelcome`, `onboarding.stepCompany`, `onboarding.stepProject`, `workspace.nameLabel`, `workspace.namePlaceholder`, `workspace.slugLabel`, `workspace.slugHelp` (added to all locales in Task 15).
- Produces: a top-level `/onboarding` route that is **never a forced redirect target** (see Task 14 — the dashboard renders immediately post-login regardless). Step 0 (`WelcomeStep`) tells the user they already have a working Personal workspace and offers two equal, non-nested actions: "Create a company" (→ step 1) and "Skip, go to my workspace" (→ `/notebooks`). Step 1 (`CompanyStep`) creates the optional company; on success `useCreateWorkspace` swaps the token and the wizard advances to a **P3 hand-off** step (step 2) which — until P3 exists — routes to `/notebooks`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/onboarding/WelcomeStep.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { WelcomeStep } from './WelcomeStep'

describe('WelcomeStep', () => {
  it('renders the personal-workspace welcome copy and both actions', () => {
    render(<WelcomeStep onCreateCompany={vi.fn()} onSkip={vi.fn()} />)
    expect(screen.getByText('onboarding.welcomePersonalTitle')).toBeDefined()
    expect(screen.getByText('onboarding.createCompanyCta')).toBeDefined()
    expect(screen.getByText('onboarding.skipCta')).toBeDefined()
  })

  it('skip is a first-class action, not hidden behind the company flow', () => {
    const onSkip = vi.fn()
    render(<WelcomeStep onCreateCompany={vi.fn()} onSkip={onSkip} />)
    fireEvent.click(screen.getByText('onboarding.skipCta'))
    expect(onSkip).toHaveBeenCalled()
  })

  it('create-company advances without creating anything itself', () => {
    const onCreateCompany = vi.fn()
    render(<WelcomeStep onCreateCompany={onCreateCompany} onSkip={vi.fn()} />)
    fireEvent.click(screen.getByText('onboarding.createCompanyCta'))
    expect(onCreateCompany).toHaveBeenCalled()
  })
})
```
and `frontend/src/components/onboarding/CompanyStep.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CompanyStep } from './CompanyStep'

const mutate = vi.fn()
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useCreateWorkspace: () => ({ mutate, isPending: false }),
}))

describe('CompanyStep', () => {
  it('renders the workspace name field (i18n keys via mocked t)', () => {
    render(<CompanyStep onCreated={vi.fn()} />)
    expect(screen.getByText('workspace.nameLabel')).toBeDefined()
    expect(screen.getByText('onboarding.createCompanyCta')).toBeDefined()
  })

  it('submits the trimmed name through useCreateWorkspace', () => {
    render(<CompanyStep onCreated={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('workspace.namePlaceholder'), {
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

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- WelcomeStep` and `npm run test -- CompanyStep` — Expected: FAIL — cannot resolve `./WelcomeStep` / `./CompanyStep`.

- [ ] **Step 3: Write minimal implementation** —

`frontend/src/components/onboarding/WelcomeStep.tsx`:
```tsx
'use client'

import { useTranslation } from '@/lib/hooks/use-translation'
import { Button } from '@/components/ui/button'

export function WelcomeStep({
  onCreateCompany,
  onSkip,
}: {
  onCreateCompany: () => void
  onSkip: () => void
}) {
  const { t } = useTranslation()

  return (
    <div className="space-y-5 text-center">
      <div>
        <h2 className="text-lg font-medium">{t('onboarding.welcomePersonalTitle')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('onboarding.welcomePersonalBody')}</p>
      </div>
      <div className="flex flex-col gap-2">
        <Button type="button" className="w-full" onClick={onCreateCompany}>
          {t('onboarding.createCompanyCta')}
        </Button>
        <Button type="button" variant="ghost" className="w-full" onClick={onSkip}>
          {t('onboarding.skipCta')}
        </Button>
      </div>
    </div>
  )
}
```

`frontend/src/components/onboarding/CompanyStep.tsx`:
```tsx
'use client'

import { useState } from 'react'
import { useCreateWorkspace } from '@/lib/hooks/use-workspaces'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function CompanyStep({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation()
  const createWorkspace = useCreateWorkspace()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createWorkspace.mutate(
      { name: name.trim(), slug: slug.trim() || undefined },
      { onSuccess: () => onCreated() },
    )
  }

  return (
    <form data-testid="company-step-form" onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <label className="block text-sm font-medium" htmlFor="workspace-name">
          {t('workspace.nameLabel')}
        </label>
        <Input
          id="workspace-name"
          autoFocus
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('workspace.namePlaceholder')}
        />
      </div>
      <div className="space-y-1.5">
        <label className="block text-sm font-medium" htmlFor="workspace-slug">
          {t('workspace.slugLabel')}
        </label>
        <Input
          id="workspace-slug"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t('workspace.slugHelp')}</p>
      </div>
      <Button type="submit" className="w-full" disabled={createWorkspace.isPending || !name.trim()}>
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
import { WelcomeStep } from './WelcomeStep'
import { CompanyStep } from './CompanyStep'

type Step = 'welcome' | 'company' | 'project'

export function OnboardingWizard() {
  const { t } = useTranslation()
  const router = useRouter()
  const [step, setStep] = useState<Step>('welcome')

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-lg flex-col justify-center px-4 py-12">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold">{t('onboarding.title')}</h1>
      </div>

      <div className="mb-5 flex items-center justify-center gap-2 text-xs font-medium">
        <span aria-current={step === 'welcome'}>{t('onboarding.stepWelcome')}</span>
        <span className="h-px w-8 bg-border" />
        <span aria-current={step === 'company'}>{t('onboarding.stepCompany')}</span>
        <span className="h-px w-8 bg-border" />
        <span aria-current={step === 'project'}>{t('onboarding.stepProject')}</span>
      </div>

      <div className="rounded-xl border p-6">
        {step === 'welcome' && (
          <WelcomeStep
            onCreateCompany={() => setStep('company')}
            onSkip={() => router.push('/notebooks')}
          />
        )}
        {step === 'company' && (
          <>
            <h2 className="mb-4 text-lg font-medium">{t('onboarding.companyStepTitle')}</h2>
            {/* On create, the token is already workspace-scoped to the new
                company (useCreateWorkspace applied it). Advance to the P3
                project hand-off. */}
            <CompanyStep onCreated={() => setStep('project')} />
          </>
        )}
        {step === 'project' && (
          // P3 fills in the first-project step here. Until then, hand off to
          // the dashboard now that the company + owner token exist.
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

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- WelcomeStep` and `npm run test -- CompanyStep` — Expected: PASS (3 + 2 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/app/onboarding frontend/src/components/onboarding && git commit -m "P2: onboarding route — personal landing + optional company step"`

---

## Task 13: `WorkspaceSwitcher` + mount in dashboard chrome

**Files:**
- Create: `frontend/src/components/workspace/WorkspaceSwitcher.tsx`
- Modify: the dashboard chrome that renders the sidebar/header — mount `<WorkspaceSwitcher />` (e.g. `frontend/src/components/layout/AppSidebar.tsx`; confirm the actual chrome component)
- Test: `frontend/src/components/workspace/WorkspaceSwitcher.test.tsx`

**Interfaces:**
- Consumes: `useAuthStore` (`memberships`, `activeWorkspaceId`), `useSwitchWorkspace` (Task 11), `useTranslation`, `useRouter`. References i18n keys `workspace.switchLabel`, `workspace.personalLabel`, `workspace.roleOwner`, `workspace.roleAdmin`, `workspace.roleMember`, `workspace.addCompanyCta` (added in Task 15).
- Produces: a dropdown listing `memberships` — the personal workspace first (labeled via `workspace.personalLabel`, no role badge needed beyond "Owner"), then companies with name + role badge — with a check/active marker on `activeWorkspaceId`; selecting a different membership calls `useSwitchWorkspace().mutate(workspaceId)`; a trailing "+ Create a company" row navigates to `/onboarding`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/workspace/WorkspaceSwitcher.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { useAuthStore } from '@/lib/stores/auth-store'

const mutate = vi.fn()
const push = vi.fn()
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useSwitchWorkspace: () => ({ mutate, isPending: false }),
}))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))

describe('WorkspaceSwitcher', () => {
  beforeEach(() => {
    mutate.mockClear()
    push.mockClear()
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'member' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
  })

  it('lists the personal workspace and companies with role badges', () => {
    render(<WorkspaceSwitcher />)
    expect(screen.getByText('workspace.personalLabel')).toBeDefined()
    expect(screen.getByText('Acme')).toBeDefined()
    expect(screen.getByText('workspace.roleMember')).toBeDefined()
  })

  it('switches when a different workspace is selected', () => {
    render(<WorkspaceSwitcher />)
    fireEvent.click(screen.getByTestId('workspace-option-workspace:acme'))
    expect(mutate).toHaveBeenCalledWith('workspace:acme')
  })

  it('does not switch when the active workspace is selected', () => {
    render(<WorkspaceSwitcher />)
    fireEvent.click(screen.getByTestId('workspace-option-workspace:p1'))
    expect(mutate).not.toHaveBeenCalled()
  })

  it('exposes a "create a company" entry that navigates to /onboarding', () => {
    render(<WorkspaceSwitcher />)
    fireEvent.click(screen.getByText('workspace.addCompanyCta'))
    expect(push).toHaveBeenCalledWith('/onboarding')
  })

  it('hides the "no company yet" banner once a company membership exists', () => {
    render(<WorkspaceSwitcher />)
    expect(screen.queryByText('workspace.createCompanyBanner')).toBeNull()
  })

  it('shows the "no company yet" banner when only the personal workspace is present', () => {
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.getByText('workspace.createCompanyBanner')).toBeDefined()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- WorkspaceSwitcher` — Expected: FAIL — cannot resolve `./WorkspaceSwitcher`.

- [ ] **Step 3: Write minimal implementation** — `frontend/src/components/workspace/WorkspaceSwitcher.tsx`:
```tsx
'use client'

import { Check, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useSwitchWorkspace } from '@/lib/hooks/use-workspaces'
import { useTranslation } from '@/lib/hooks/use-translation'

export function WorkspaceSwitcher() {
  const { t } = useTranslation()
  const router = useRouter()
  const memberships = useAuthStore((s) => s.memberships)
  const activeWorkspaceId = useAuthStore((s) => s.activeWorkspaceId)
  const switchWorkspace = useSwitchWorkspace()

  // Literal keys (not template strings) so the i18n usage test can find them.
  const roleLabels: Record<string, string> = {
    owner: t('workspace.roleOwner'),
    admin: t('workspace.roleAdmin'),
    member: t('workspace.roleMember'),
  }

  return (
    <div role="listbox" aria-label={t('workspace.switchLabel')} className="flex flex-col gap-1">
      {memberships.map((m) => {
        const isActive = m.workspace_id === activeWorkspaceId
        const label = m.kind === 'personal' ? t('workspace.personalLabel') : m.name
        return (
          <button
            key={m.workspace_id}
            type="button"
            role="option"
            aria-selected={isActive}
            data-testid={`workspace-option-${m.workspace_id}`}
            disabled={switchWorkspace.isPending}
            onClick={() => {
              if (!isActive) switchWorkspace.mutate(m.workspace_id)
            }}
            className="flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
          >
            <span className="truncate">{label}</span>
            <span className="flex items-center gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase">
                {roleLabels[m.role] ?? m.role}
              </span>
              {isActive && <Check className="h-4 w-4" aria-hidden />}
            </span>
          </button>
        )
      })}
      {!memberships.some((m) => m.kind === 'company') && (
        <p className="px-3 pt-1 text-[11px] text-muted-foreground">
          {t('workspace.createCompanyBanner')}
        </p>
      )}
      <button
        type="button"
        onClick={() => router.push('/onboarding')}
        className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent"
      >
        <Plus className="h-4 w-4" aria-hidden />
        {t('workspace.addCompanyCta')}
      </button>
    </div>
  )
}
```
Then mount it in the dashboard chrome. Confirm the chrome file (the sidebar rendered by `frontend/src/app/(dashboard)/layout.tsx` — likely `frontend/src/components/layout/AppSidebar.tsx`) and add near the top of its content:
```tsx
import { WorkspaceSwitcher } from '@/components/workspace/WorkspaceSwitcher'
// ...inside the sidebar body, above the nav links:
<WorkspaceSwitcher />
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- WorkspaceSwitcher` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/workspace frontend/src/components/layout/AppSidebar.tsx && git commit -m "P2: WorkspaceSwitcher + mount in dashboard chrome"`

---

## Task 14: Dashboard-layout — no forced onboarding gate (defensive auto-select only)

**Files:**
- Modify: `frontend/src/app/(dashboard)/layout.tsx`
- Test: `frontend/src/app/(dashboard)/layout.guard.test.tsx`

**Interfaces:**
- Consumes: `useAuthStore` (`memberships`, `activeWorkspaceId`, `setActiveWorkspace`), `useAuth` (`isAuthenticated`, `isLoading`), `useRouter`.
- Produces: guard behavior — unauthenticated → existing `/login` redirect (unchanged). **No `/onboarding` redirect of any kind** (the superseded company-only draft's forced redirect is removed entirely — onboarding is reachable only via the `WorkspaceSwitcher`'s "+ Create a company" entry or an optional dashboard banner, never a gate). The ONLY new behavior is a **defensive** fallback: authenticated + `!activeWorkspaceId` but `memberships.length > 0` → auto-select the first membership via `setActiveWorkspace` (covers a corrupted/partial persisted session; should not fire in the normal flow since `setSession` always sets `activeWorkspaceId` from the backend payload).

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

describe('DashboardLayout — no forced onboarding gate', () => {
  const push = vi.fn()
  beforeEach(() => {
    push.mockClear()
    vi.mocked(useRouter).mockReturnValue({ push } as any)
  })

  it('renders the dashboard directly for a user with ONLY a personal workspace (no redirect)', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, isLoading: false } as any)
    useAuthStore.setState({
      memberships: [{ workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' }],
      activeWorkspaceId: 'workspace:p1',
    })
    const { getByText } = render(<DashboardLayout>content</DashboardLayout>)
    expect(getByText('content')).toBeDefined()
    expect(push).not.toHaveBeenCalledWith('/onboarding')
  })

  it('auto-selects the first membership when a persisted session has none active', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, isLoading: false } as any)
    useAuthStore.setState({
      memberships: [{ workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' }],
      activeWorkspaceId: null,
    })
    render(<DashboardLayout>content</DashboardLayout>)
    expect(useAuthStore.getState().activeWorkspaceId).toBe('workspace:p1')
    expect(push).not.toHaveBeenCalledWith('/onboarding')
  })

  it('redirects to /login when unauthenticated (unchanged P1 behavior)', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: false, isLoading: false } as any)
    useAuthStore.setState({ memberships: [], activeWorkspaceId: null })
    render(<DashboardLayout>content</DashboardLayout>)
    expect(push).toHaveBeenCalledWith('/login')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- layout.guard` — Expected: FAIL — the current (pre-P2) layout has no `activeWorkspaceId` auto-select handling at all (the store fields don't exist until Task 10 lands).

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
  const activeWorkspaceId = useAuthStore((s) => s.activeWorkspaceId)
  const setActiveWorkspace = useAuthStore((s) => s.setActiveWorkspace)
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

      // Defensive only: a normal session always has activeWorkspaceId set by
      // setSession (the backend always names an active — Personal — workspace).
      // This guards a corrupted/partial persisted session, NOT a first-run gate
      // — there is intentionally no memberships.length === 0 redirect, because
      // an authenticated user's memberships list is never empty.
      if (!activeWorkspaceId && memberships.length > 0) {
        setActiveWorkspace(memberships[0].workspace_id, memberships[0].role)
      }
    }
  }, [isAuthenticated, isLoading, memberships, activeWorkspaceId, setActiveWorkspace, router])

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

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- layout.guard` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add "frontend/src/app/(dashboard)/layout.tsx" "frontend/src/app/(dashboard)/layout.guard.test.tsx" && git commit -m "P2: dashboard renders directly post-login; defensive workspace auto-select only"`

---

## Task 15: i18n keys in all 14 locales (7 enforced + 7 English-fallback)

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
- Consumes: nothing new. Every key added here is referenced literally by Tasks 11–14 (hooks + components), which the usage half of the locale test enforces.
- Produces: `onboarding.*` and `workspace.*` keys in all 14 locales (real translations in the 7 enforced, English fallback in the other 7).

Keys to add (14 `workspace.*` + 9 `onboarding.*`). Each locale file exports one nested object; add a `workspace` section and an `onboarding` section (or extend them if P1 already created an `onboarding` section — merge, don't duplicate; P1's onboarding-adjacent copy, if any, lives under `auth`, not `onboarding`).

- [ ] **Step 1: Write the failing test** — No new test file; the existing `frontend/src/lib/locales/index.test.ts` IS the gate. Run it first to confirm it currently fails (the keys are referenced by the components from Tasks 11–14 but not yet present in en-US, so the parity test also flags the other 13 locales once en-US has them). Run: `npm run test -- locales/index` — Expected: FAIL (usage test lists the new keys as missing once they exist in en-US; before adding, add to en-US first per Step 3, then the other locales).

- [ ] **Step 2: Confirm the failing signal** — After adding ONLY to `en-US` (do this to see the parity failure), Run: `npm run test -- locales/index` — Expected: FAIL — "Missing keys in pt-BR: onboarding.title, ..." (parity), proving the remaining 13 locales need the keys.

- [ ] **Step 3: Write minimal implementation** — Add to each locale. English (`en-US/index.ts`):
```ts
  onboarding: {
    title: "Welcome to Arteamis",
    stepWelcome: "Welcome",
    stepCompany: "Company",
    stepProject: "Project",
    welcomePersonalTitle: "You're all set",
    welcomePersonalBody: "This is your Personal workspace — private projects and sources, ready to use. Creating a company is optional.",
    createCompanyCta: "Create a company",
    skipCta: "Skip, go to my workspace",
    companyStepTitle: "Create your company",
  },
  workspace: {
    nameLabel: "Company name",
    namePlaceholder: "Acme Inc.",
    slugLabel: "Slug (optional)",
    slugHelp: "Used in URLs. Leave blank to generate one from the name.",
    createSuccess: "Company created",
    slugTaken: "That workspace slug is already taken. Try another name.",
    switchLabel: "Switch workspace",
    switchSuccess: "Switched workspace",
    roleOwner: "Owner",
    roleAdmin: "Admin",
    roleMember: "Member",
    personalLabel: "Personal",
    addCompanyCta: "Create a company",
    createCompanyBanner: "You haven't created a company yet.",
  },
```

Portuguese (`pt-BR/index.ts`):
```ts
  onboarding: {
    title: "Bem-vindo ao Arteamis",
    stepWelcome: "Boas-vindas",
    stepCompany: "Empresa",
    stepProject: "Projeto",
    welcomePersonalTitle: "Tudo pronto",
    welcomePersonalBody: "Este é o seu espaço Pessoal — projetos e fontes privados, prontos para usar. Criar uma empresa é opcional.",
    createCompanyCta: "Criar uma empresa",
    skipCta: "Pular, ir para meu espaço",
    companyStepTitle: "Crie sua empresa",
  },
  workspace: {
    nameLabel: "Nome da empresa",
    namePlaceholder: "Acme Ltda.",
    slugLabel: "Slug (opcional)",
    slugHelp: "Usado nas URLs. Deixe em branco para gerar a partir do nome.",
    createSuccess: "Empresa criada",
    slugTaken: "Esse identificador de espaço já está em uso. Tente outro nome.",
    switchLabel: "Trocar de espaço",
    switchSuccess: "Espaço alterado",
    roleOwner: "Proprietário",
    roleAdmin: "Administrador",
    roleMember: "Membro",
    personalLabel: "Pessoal",
    addCompanyCta: "Criar uma empresa",
    createCompanyBanner: "Você ainda não criou uma empresa.",
  },
```

Simplified Chinese (`zh-CN/index.ts`):
```ts
  onboarding: {
    title: "欢迎使用 Arteamis",
    stepWelcome: "欢迎",
    stepCompany: "公司",
    stepProject: "项目",
    welcomePersonalTitle: "一切就绪",
    welcomePersonalBody: "这是您的个人空间——私人项目和资料，随时可用。创建公司是可选的。",
    createCompanyCta: "创建公司",
    skipCta: "跳过，进入我的空间",
    companyStepTitle: "创建您的公司",
  },
  workspace: {
    nameLabel: "公司名称",
    namePlaceholder: "Acme 公司",
    slugLabel: "标识（可选）",
    slugHelp: "用于网址。留空则根据名称自动生成。",
    createSuccess: "公司已创建",
    slugTaken: "该空间标识已被占用，请换一个名称。",
    switchLabel: "切换空间",
    switchSuccess: "已切换空间",
    roleOwner: "所有者",
    roleAdmin: "管理员",
    roleMember: "成员",
    personalLabel: "个人",
    addCompanyCta: "创建公司",
    createCompanyBanner: "您还没有创建公司。",
  },
```

Traditional Chinese (`zh-TW/index.ts`):
```ts
  onboarding: {
    title: "歡迎使用 Arteamis",
    stepWelcome: "歡迎",
    stepCompany: "公司",
    stepProject: "專案",
    welcomePersonalTitle: "一切就緒",
    welcomePersonalBody: "這是您的個人空間——私人專案與資料，隨時可用。建立公司是選填的。",
    createCompanyCta: "建立公司",
    skipCta: "略過，前往我的空間",
    companyStepTitle: "建立您的公司",
  },
  workspace: {
    nameLabel: "公司名稱",
    namePlaceholder: "Acme 公司",
    slugLabel: "識別碼（選填）",
    slugHelp: "用於網址。留空則依名稱自動產生。",
    createSuccess: "公司已建立",
    slugTaken: "該空間識別碼已被使用，請換一個名稱。",
    switchLabel: "切換空間",
    switchSuccess: "已切換空間",
    roleOwner: "擁有者",
    roleAdmin: "管理員",
    roleMember: "成員",
    personalLabel: "個人",
    addCompanyCta: "建立公司",
    createCompanyBanner: "您尚未建立公司。",
  },
```

Japanese (`ja-JP/index.ts`):
```ts
  onboarding: {
    title: "Arteamis へようこそ",
    stepWelcome: "ようこそ",
    stepCompany: "会社",
    stepProject: "プロジェクト",
    welcomePersonalTitle: "準備が整いました",
    welcomePersonalBody: "ここはあなたの個人ワークスペースです。プライベートなプロジェクトとソースがすぐに使えます。会社の作成は任意です。",
    createCompanyCta: "会社を作成",
    skipCta: "スキップして自分のワークスペースへ",
    companyStepTitle: "会社を作成",
  },
  workspace: {
    nameLabel: "会社名",
    namePlaceholder: "Acme 株式会社",
    slugLabel: "スラッグ（任意）",
    slugHelp: "URL に使用されます。空欄の場合は名前から自動生成されます。",
    createSuccess: "会社を作成しました",
    slugTaken: "そのワークスペースのスラッグは既に使用されています。別の名前をお試しください。",
    switchLabel: "ワークスペースを切り替え",
    switchSuccess: "ワークスペースを切り替えました",
    roleOwner: "オーナー",
    roleAdmin: "管理者",
    roleMember: "メンバー",
    personalLabel: "個人",
    addCompanyCta: "会社を作成",
    createCompanyBanner: "まだ会社を作成していません。",
  },
```

Russian (`ru-RU/index.ts`):
```ts
  onboarding: {
    title: "Добро пожаловать в Arteamis",
    stepWelcome: "Приветствие",
    stepCompany: "Компания",
    stepProject: "Проект",
    welcomePersonalTitle: "Всё готово",
    welcomePersonalBody: "Это ваше личное рабочее пространство — приватные проекты и источники, готовые к использованию. Создание компании необязательно.",
    createCompanyCta: "Создать компанию",
    skipCta: "Пропустить, перейти в моё пространство",
    companyStepTitle: "Создайте компанию",
  },
  workspace: {
    nameLabel: "Название компании",
    namePlaceholder: "ООО «Акме»",
    slugLabel: "Slug (необязательно)",
    slugHelp: "Используется в URL. Оставьте пустым, чтобы сгенерировать из названия.",
    createSuccess: "Компания создана",
    slugTaken: "Такой slug рабочего пространства уже занят. Попробуйте другое название.",
    switchLabel: "Сменить рабочее пространство",
    switchSuccess: "Рабочее пространство изменено",
    roleOwner: "Владелец",
    roleAdmin: "Администратор",
    roleMember: "Участник",
    personalLabel: "Личное",
    addCompanyCta: "Создать компанию",
    createCompanyBanner: "Вы ещё не создали компанию.",
  },
```

Bengali (`bn-IN/index.ts`):
```ts
  onboarding: {
    title: "Arteamis-এ স্বাগতম",
    stepWelcome: "স্বাগতম",
    stepCompany: "কোম্পানি",
    stepProject: "প্রকল্প",
    welcomePersonalTitle: "সব প্রস্তুত",
    welcomePersonalBody: "এটি আপনার ব্যক্তিগত workspace — ব্যক্তিগত প্রকল্প ও উৎস, ব্যবহারের জন্য প্রস্তুত। কোম্পানি তৈরি করা ঐচ্ছিক।",
    createCompanyCta: "কোম্পানি তৈরি করুন",
    skipCta: "এড়িয়ে যান, আমার workspace-এ যান",
    companyStepTitle: "আপনার কোম্পানি তৈরি করুন",
  },
  workspace: {
    nameLabel: "কোম্পানির নাম",
    namePlaceholder: "Acme Inc.",
    slugLabel: "স্লাগ (ঐচ্ছিক)",
    slugHelp: "URL-এ ব্যবহৃত হয়। নাম থেকে তৈরি করতে ফাঁকা রাখুন।",
    createSuccess: "কোম্পানি তৈরি হয়েছে",
    slugTaken: "এই workspace স্লাগটি ইতিমধ্যে নেওয়া হয়েছে। অন্য নাম চেষ্টা করুন।",
    switchLabel: "workspace পরিবর্তন করুন",
    switchSuccess: "workspace পরিবর্তন করা হয়েছে",
    roleOwner: "মালিক",
    roleAdmin: "অ্যাডমিন",
    roleMember: "সদস্য",
    personalLabel: "ব্যক্তিগত",
    addCompanyCta: "কোম্পানি তৈরি করুন",
    createCompanyBanner: "আপনি এখনও কোনো কোম্পানি তৈরি করেননি।",
  },
```

> Placement: insert each `onboarding`/`workspace` block as a top-level section inside the exported object (sibling of `common`, `auth`, etc.), respecting the file's trailing-comma/formatting style.

- [ ] **Step 3b: Add the same keys (English fallback) to the 7 non-enforced locales** — the parity test iterates EVERY locale in the `resources` map, so `ca-ES, de-DE, es-ES, fr-FR, it-IT, pl-PL, tr-TR` (7 files) MUST also carry the new `onboarding.*` + `workspace.*` keys or `npm run test` fails. Add the exact same key structure to each of these 7 files using the **en-US English values** (silent en-US fallback is acceptable for non-enforced locales; a native pass can follow). If P1 already created an `onboarding` section in these files, merge — don't duplicate.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- locales/index` — Expected: PASS (parity: all 14 locales carry every new key; usage: every new key is referenced in a component/hook from Tasks 11–14).

- [ ] **Step 5: Run the full frontend gate** — Run (inside `frontend/`): `npm run test && npm run lint && npm run build` — Expected: all PASS.

- [ ] **Step 6: Commit** — `git add frontend/src/lib/locales && git commit -m "P2: i18n onboarding + workspace keys in all 14 locales"`

---

## Self-review

### Spec coverage (every spec section → task)
- Migration 20 (`workspace` incl. `kind`, `membership`, unique indexes, `_down`, manager registration) → **Task 1**.
- Domain models `Workspace`/`Membership` + `domain/__init__.py` import for polymorphic `get()` → **Task 2**.
- `workspace_service.py` (`slugify`, `ensure_personal_workspace` idempotent get-or-create, `create_workspace` + orphan cleanup, `list_memberships` incl. `kind`, `get_membership`) → **Task 3**.
- `create_access_token` (P1 stub → P2 impl, workspace-scoped) → **Task 4**.
- `api/deps.py` (`get_identity`, `get_auth_context`, `require_role`) → **Task 5**.
- `ensure_personal_workspace` wired into `build_session_payload` (auto-provision on signup/first-login; `needs_onboarding` repurposed; active workspace always Personal on fresh login) → **Task 6**.
- Schemas (`WorkspaceCreate`/`WorkspaceResponse`/`TokenResponse`, no client-settable `kind`) + `POST /workspaces` (201, token re-mint) + `GET /workspaces` (never empty) + main.py registration → **Task 7**.
- `POST /auth/switch-workspace/{id}` (membership re-verify, 403, token re-mint, works for personal or company) → **Task 8**.
- Frontend `workspaces.ts` + types (incl. `kind`) + `QUERY_KEYS.workspaces` → **Task 9**.
- auth-store workspace slice (`applyToken`/`setSession`/`setActiveWorkspace`/`hasCompany`, persisted, NO blocking `needsOnboarding`) → **Task 10**.
- `useWorkspaces`/`useCreateWorkspace`/`useSwitchWorkspace` (409 → `slugTaken`, `queryClient.clear()`) → **Task 11**.
- Onboarding route + wizard rewrite (personal-landing `WelcomeStep`, optional `CompanyStep`, P3 hand-off stub) → **Task 12**.
- `WorkspaceSwitcher` (Personal + companies + "+ Create a company") + dashboard mount → **Task 13**.
- Dashboard-layout: NO forced onboarding redirect; defensive auto-select only → **Task 14**.
- i18n in all 14 locales (7 enforced + 7 English-fallback) → **Task 15**.
- Spec's guardrail ("cannot invite into / cannot treat personal as company") — enforced today by `WorkspaceCreate` having no `kind` field (Task 7) and `GET /workspaces` exposing `kind` for the frontend to branch on (Task 7, Task 13); the invite-side 403 is explicitly P4's to build against this field — documented, not re-implemented here. Covered.
- Spec's RBAC table: create is open to any authenticated user (no role gate) — Task 7 uses `get_identity`, not `require_role`; `require_role` is delivered (Task 5) but consumed by P3+ (tested directly in Task 5). Covered.
- Spec's error contract: 401 (deps, Task 5/7/8), 403 (`require_role` Task 5, `switch-workspace` Task 8), 409 (slug, Tasks 3/7), 422 (empty name, Task 7). Covered.
- Spec's default decision ("every login resets the active workspace to Personal") — Task 6's tests explicitly assert this even when a company membership exists. Covered.
- Spec testing checklist: backend cases 1–8 map to Tasks 1/3/6/7/8 tests (case 5 identity-plane isolation → Task 3 `list_memberships` `WHERE user = $user` assertion; case 8 migration up/down → Task 1 DB-free DDL assertions, with a note that a live round-trip is out of unit scope). Frontend cases 1–5 → Tasks 9–15 tests. Covered.

### Placeholder scan
No "TBD/implement later/add error handling/similar to Task N". The onboarding step-2 (project) is an explicit, intentional P3 hand-off (spec-mandated), implemented concretely as an immediate route to `/notebooks` — not a placeholder. The P4 invite-guard reference is explicitly out-of-scope documentation, not a stubbed function pretending to be complete. Every code step is complete and runnable.

### Type/signature consistency
- `create_access_token(user_id, workspace_id, role, minutes=None) -> str` (Task 4) — called by Task 6, Task 7, and Task 8 with keyword args exactly matching.
- `AuthContext(user_id, workspace_id, role)` (P1, renamed per the v2 terminology assumption stated up top) — constructed in Task 5 tests and consumed by `require_role`/`get_auth_context`.
- `ensure_personal_workspace(user_id) -> Workspace` (Task 3) — consumed by Task 6's `build_session_payload`; idempotent (Task 3 tests both the create and no-op paths).
- `create_workspace(user_id, name, slug=None) -> (Workspace, Membership)` (Task 3) — Task 7 unpacks `workspace, membership` and reads `workspace.id`, `membership.role`; test asserts `mock_create.assert_awaited_once_with("user:1", "Acme", None)`.
- `get_membership(user_id, workspace_id) -> Optional[Membership]` (Task 3) — Task 8 checks `membership.status != "active"`; `Membership.status` exists (Task 2, default `"active"`).
- `TokenResponse{access_token, token_type, active_workspace_id, role}` (Task 7 schema) — matches frontend `TokenResponse` (Task 9) and `applyToken(res)` reads `res.access_token`/`res.active_workspace_id`/`res.role` (Task 10). Also the exact shape `build_session_payload` (Task 6) returns for `access_token`/`active_workspace_id`.
- `Membership` (frontend, Task 9) `{workspace_id, name, slug, kind, role}` — matches backend `list_memberships` row and `WorkspaceResponse` maps `workspace_id`→`id`.
- `applyToken`/`setSession`/`setActiveWorkspace`/`hasCompany` (Task 10) — consumed by Tasks 11/13/14 exactly as declared; `setSession`'s new `activeWorkspaceId` parameter (vs. the superseded draft's auto-derived-first-membership approach) matches the backend's explicit `active_workspace_id` field (Task 6).
- i18n keys referenced in Tasks 11–14 (`workspace.createSuccess`, `workspace.slugTaken`, `workspace.switchSuccess`, `workspace.roleOwner/Admin/Member`, `workspace.switchLabel`, `workspace.personalLabel`, `workspace.addCompanyCta`, `workspace.createCompanyBanner`, `onboarding.*`, `workspace.nameLabel/namePlaceholder/slugLabel/slugHelp`) all appear literally and are all added in Task 15 — satisfying both halves of the locale test. `workspace.createCompanyBanner` is rendered by `WorkspaceSwitcher` (Task 13) as a small caption shown only when `!memberships.some(m => m.kind === 'company')`, with dedicated show/hide test cases in Task 13's test file — closing the loop identified during self-review (an unreferenced key would otherwise fail the locale test's usage half).
