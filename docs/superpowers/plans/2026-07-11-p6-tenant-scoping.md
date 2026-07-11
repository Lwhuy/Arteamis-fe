# P6 — App-layer Tenant Scoping (replaces RLS) + Frontend Role-Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce company-tenant isolation in the application layer (SurrealDB has no RLS) via a single sanctioned `ScopedRepository`, gate scoped routers with `require_company`/`require_role`, supply the `PermissionContext` P5 consumes, role-gate the frontend, and prove isolation with a tenant-leakage test suite.

**Architecture:** A request-scoped `ScopedRepository` (`open_notebook/database/scoping.py`) wraps the existing async `repo_*` helpers so every read AND-s `WHERE company = $company_id` and every write stamps `company`; a guessed cross-company record id resolves to 404 (no existence oracle). `api/deps.py` (created by P2) gains `require_company`, `get_request_context`, the `CtxDep`/`AuthDep` aliases, and the concrete `PermissionContext` (company_role + async `project_role`). The project (physically `notebook`) router migrates onto the wrapper; a grep contract-guard test forbids raw `repo_*` on scoped tables in migrated routers. The frontend adds a `useRole()` hook, a `<RoleGate>` component, a dashboard route guard, and gates concrete admin actions.

**Tech Stack:** Next.js 16 (App Router), FastAPI, SurrealDB (async `repo_*`), TanStack Query, Zustand (`persist`), python-jose (JWT via P1 `api/security.py`), vitest, pytest.

**Spec:** docs/superpowers/specs/2026-07-11-p6-tenant-scoping-frontend-gating-design.md
**Depends on:** P1 (auth/JWT `api/security.py`), P2 (`api/deps.py`: `get_identity`/`get_auth_context`/`require_role`; `company`/`membership`), P3 (`notebook`→`project` rename, `company`/`owner` columns, `project_member`, `api/routers/projects.py`), P4 (`invitation`), P5 (`source.owner`/`visibility`, `api/source_permissions.py` consuming `PermissionContext`) · **Branch:** feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB call is awaited (no sync DB access).
- All frontend HTTP goes through the single axios `apiClient` (frontend/src/lib/api/client.ts) — never a 2nd instance.
- i18n MANDATORY: every UI string via `t('section.key')`; add the key to ALL locale files under `frontend/src/lib/locales/` (the parity test `locales/index.test.ts` checks EVERY locale in `resources`, not just the 7 enforced — a key added to en-US but missing elsewhere FAILS the test; the "Unused Key Detection" test also requires every en-US leaf key be referenced in a source file).
- New SurrealDB schema = new migration pair. **P6 introduces NO migration** (canonical: P1=19, P2=20, P3=21, P4=22, P5=23; P6=none). `AsyncMigrationManager` gains no P6 entry.
- Physical SurrealDB table stays `notebook` (exposed as "project"); domain class `Project` (`table_name = "notebook"`); API `/api/projects`; UI "Project".
- Tokens: identity token (`sub`) vs company-scoped access token (`sub`, `company_id`, `role`) + refresh cookie. P6 reads `AuthContext(user_id, company_id, role)` from P1's `api/security.py`; it does not mint tokens.
- Backend tests: `uv run pytest tests/`. Frontend (inside `frontend/`): `npm run lint`, `npm run test`, `npm run build`.
- Backend errors: raise typed exceptions from `open_notebook.exceptions` — global handlers in `api/main.py` map `NotFoundError`→404, `InvalidInputError`→400, `AuthenticationError`→401. Do NOT raise bare `HTTPException` for domain errors from services; the FastAPI dependencies (`require_company`/`require_role`) DO raise `HTTPException` (they mirror `arteamis-system/backend/app/api/deps.py`).

---

## Reference facts (verified against real code — do not re-derive)

- `open_notebook/database/repository.py` exposes async helpers: `repo_query(query_str, vars=None) -> list[dict]`, `repo_create(table, data) -> dict`, `repo_update(table, id, data) -> list[dict]`, `repo_delete(record_id) -> Any`, and `ensure_record_id(value) -> RecordID` (parses `"notebook:abc"` → `RecordID`). `repo_create` auto-sets `created`/`updated`. Record ids come back as strings (via `parse_record_ids`).
- `open_notebook/exceptions.py`: `InvalidInputError` (→400), `NotFoundError` (→404), `OpenNotebookError` base.
- `open_notebook/domain/base.py`: `ObjectModel.get(id)` is polymorphic by id-prefix; `ObjectModel._validate_order_by(order_by)` is the ORDER BY allowlist validator (`InvalidInputError` on bad input).
- `api/security.py` (P1) provides `AuthContext` (dataclass: `user_id: str`, `company_id: str | None`, `role: str | None`), `decode_access_token(token) -> AuthContext`, `decode_identity_token(token) -> str`, `create_access_token(user_id, company_id, role) -> str`, `create_identity_token(user_id) -> str`.
- `api/deps.py` (P2) already defines `bearer = HTTPBearer()`, `async def get_auth_context(...) -> AuthContext`, `async def get_identity(...) -> str`, and `def require_role(*roles)`. **P6 EDITS this file — it must NOT redefine those three.**
- `api/routers/projects.py` (P3) is the canonical `/projects` router (replaced `notebooks.py`); domain class `Project` (`open_notebook/domain/notebook.py`, `table_name="notebook"`); Pydantic schemas `ProjectCreate`/`ProjectUpdate`/`ProjectResponse` in `api/models.py`. Native `company` column lives on `notebook`, `project_member`, `invitation`. `source`/`note`/`chat_session`/`source_insight`/`source_embedding` have NO native `company` column — they inherit via parent join.
- `api/main.py` registers exception handlers (`NotFoundError`→404, `InvalidInputError`→400) around line 299–316 and includes routers around line 372+.
- Frontend: `frontend/src/lib/stores/auth-store.ts` is a Zustand `persist` store (localStorage key `auth-storage`). `frontend/src/app/(dashboard)/layout.tsx` is the route guard (redirects unauthenticated → `/login`). `frontend/src/components/layout/AppSidebar.tsx` holds the nav (`Manage` section lines 66–74) and Create dropdown (notebook item lines 219–228). Locales live in `frontend/src/lib/locales/<code>/index.ts`, each exporting a nested object; `frontend/src/lib/locales/index.ts` aggregates them into `resources`.

---

### Task 1: `ScopedRepository` + table-plane policy — `open_notebook/database/scoping.py`

**Files:**
- Create: `open_notebook/database/scoping.py`
- Test: `tests/test_scoping_unit.py`

**Interfaces:**
- Consumes: `repo_query`, `repo_create`, `repo_update`, `repo_delete`, `ensure_record_id` (from `open_notebook/database/repository.py`); `InvalidInputError`, `NotFoundError` (from `open_notebook/exceptions.py`).
- Produces: `GLOBAL_TABLES: frozenset[str]`, `COMPANY_SCOPED_TABLES: frozenset[str]`, and `class ScopedRepository` with `__init__(company_id: str, user_id: str, role: str | None)`, async `list(table, *, where="", vars=None, order_by=None, limit=None) -> list[dict]`, async `get(record_id) -> dict`, async `exists(record_id) -> bool`, async `create(table, data) -> dict`, async `update(record_id, data) -> list[dict]`, async `delete(record_id) -> bool`, async `raw(query, vars=None) -> list[dict]`.

- [ ] **Step 1: Write the failing test** — `tests/test_scoping_unit.py`. These tests exercise the pure guard logic (no DB): `_assert_scoped` via the public methods on global/unknown tables, and that `list`/`get` build the correct scoped query (repo layer patched).

```python
# tests/test_scoping_unit.py
"""Unit tests for ScopedRepository guard logic (no live DB — repo_* patched)."""
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.database.scoping import (
    COMPANY_SCOPED_TABLES,
    GLOBAL_TABLES,
    ScopedRepository,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError


def _repo() -> ScopedRepository:
    return ScopedRepository(company_id="company:A", user_id="user:1", role="owner")


def test_policy_sets_are_disjoint_and_cover_expected_tables():
    assert GLOBAL_TABLES.isdisjoint(COMPANY_SCOPED_TABLES)
    assert {"user", "auth_identity", "company", "membership"} <= GLOBAL_TABLES
    assert {
        "notebook", "source", "note", "chat_session",
        "source_insight", "source_embedding", "project_member", "invitation",
    } <= COMPANY_SCOPED_TABLES


@pytest.mark.asyncio
async def test_list_rejects_global_table():
    with pytest.raises(InvalidInputError, match="GLOBAL table"):
        await _repo().list("user")


@pytest.mark.asyncio
async def test_list_rejects_unknown_table_fails_closed():
    with pytest.raises(InvalidInputError, match="Unknown table"):
        await _repo().list("widget")


@pytest.mark.asyncio
async def test_create_rejects_global_table():
    with pytest.raises(InvalidInputError, match="GLOBAL table"):
        await _repo().create("membership", {"role": "owner"})


@pytest.mark.asyncio
async def test_list_ands_company_filter_onto_caller_predicate():
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(return_value=[])) as q:
        await _repo().list("notebook", where="archived = false", order_by="updated desc")
    query, params = q.call_args[0]
    assert "company = $company_id" in query
    assert "(archived = false)" in query
    assert " AND " in query  # caller predicate AND-ed, never replaces the scope
    assert "ORDER BY updated desc" in query
    assert str(params["company_id"]) == "company:A"


@pytest.mark.asyncio
async def test_get_filters_by_company_and_404s_on_empty():
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(return_value=[])) as q:
        with pytest.raises(NotFoundError):
            await _repo().get("notebook:guessed")
    query, params = q.call_args[0]
    assert "company = $company_id" in query
    assert str(params["rid"]) == "notebook:guessed"


@pytest.mark.asyncio
async def test_create_stamps_company_and_overwrites_client_value():
    async def _fake_create(table, data):
        return {"id": f"{table}:new", **data}
    with patch("open_notebook.database.scoping.repo_create", new=AsyncMock(side_effect=_fake_create)) as c:
        await _repo().create("notebook", {"name": "x", "company": "company:EVIL"})
    _table, data = c.call_args[0]
    assert str(data["company"]) == "company:A"  # server-set, client value discarded


@pytest.mark.asyncio
async def test_update_strips_company_and_ownership_checks_first():
    calls = {"n": 0}
    async def _fake_query(q, params=None):
        calls["n"] += 1
        return [{"id": "notebook:1", "company": "company:A"}]  # get() ownership check passes
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(side_effect=_fake_query)), \
         patch("open_notebook.database.scoping.repo_update", new=AsyncMock(return_value=[{"id": "notebook:1"}])) as u:
        await _repo().update("notebook:1", {"name": "y", "company": "company:EVIL"})
    _table, _id, data = u.call_args[0]
    assert "company" not in data  # company immutable post-create
    assert calls["n"] == 1  # get() ran before update
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_scoping_unit.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'open_notebook.database.scoping'`.

- [ ] **Step 3: Write minimal implementation** — `open_notebook/database/scoping.py`:

```python
# open_notebook/database/scoping.py
"""Application-layer tenant scoping (the SurrealDB analogue of Postgres RLS).

SurrealDB has no row-level security, so tenant isolation is enforced here. A
ScopedRepository is constructed once per request from the caller's access-token
company_id (via api.deps.get_request_context) and is the ONLY sanctioned entry
point for reads/writes/deletes against company-scoped tables. Every read AND-s
`WHERE company = $company_id`; every write stamps `company`; a guessed
cross-company id resolves to NotFoundError (404) — never the other company's row.
"""
from typing import Any, Optional

from loguru import logger

from open_notebook.database.repository import (
    ensure_record_id,
    repo_create,
    repo_delete,
    repo_query,
    repo_update,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError

# ── Table-plane policy (single source of truth) ────────────────────────────────
# Identity plane — GLOBAL, never company-scoped. Login/company selection must read
# these BEFORE a company is active, so they can never carry a company filter.
GLOBAL_TABLES: frozenset[str] = frozenset(
    {"user", "auth_identity", "company", "membership"}
)

# Tenant/content plane — every row belongs to exactly one company and MUST be
# filtered by company_id on every read/write/delete. NOTE: the project table is
# PHYSICALLY named `notebook` (P3 repurpose-in-place, exposed as "project" at the
# API/UI); record ids are `notebook:<id>` and ScopedRepository derives the table
# from that prefix. `notebook`, `project_member`, `invitation` carry a NATIVE
# `company` column. `source`, `note`, `chat_session`, `source_insight`,
# `source_embedding` inherit company via their parent project/source and are
# scoped through a parent join via `raw()` (see spec "Data model changes").
COMPANY_SCOPED_TABLES: frozenset[str] = frozenset(
    {
        "notebook",  # exposed as "project"
        "source",
        "note",
        "chat_session",
        "source_insight",
        "source_embedding",
        "project_member",
        "invitation",
    }
)


def _table_of(record_id: str) -> str:
    """Table name is the record-id prefix (everything before the first ':')."""
    return record_id.split(":")[0] if ":" in record_id else record_id


def _assert_scoped(table: str) -> None:
    """Fail closed: a table must be an explicitly-classified scoped table."""
    if table in GLOBAL_TABLES:
        raise InvalidInputError(
            f"{table!r} is a GLOBAL table — use raw repo_* helpers, not ScopedRepository"
        )
    if table not in COMPANY_SCOPED_TABLES:
        raise InvalidInputError(
            f"Unknown table {table!r}; add it to COMPANY_SCOPED_TABLES or GLOBAL_TABLES"
        )


class ScopedRepository:
    """Company-scoped view over the SurrealDB repo_* helpers.

    Construct once per request via api.deps.get_request_context. Every method
    injects the company filter; there is no method that touches a scoped table
    without it. `raw()` is the audited escape hatch.
    """

    def __init__(self, company_id: str, user_id: str, role: Optional[str]):
        self.company_id = company_id
        self.user_id = user_id
        self.role = role

    @property
    def _company_rid(self):
        return ensure_record_id(self.company_id)

    # ---- reads --------------------------------------------------------------
    async def list(
        self,
        table: str,
        *,
        where: str = "",
        vars: Optional[dict] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        _assert_scoped(table)
        clauses = ["company = $company_id"]
        if where:
            clauses.append(f"({where})")  # caller predicate AND-ed, never replaces the scope
        q = f"SELECT * FROM {table} WHERE {' AND '.join(clauses)}"
        if order_by:
            q += f" ORDER BY {order_by}"  # caller MUST pre-validate via ObjectModel._validate_order_by
        if limit is not None:
            q += " LIMIT $limit"
        params: dict[str, Any] = {"company_id": self._company_rid, **(vars or {})}
        if limit is not None:
            params["limit"] = limit
        return await repo_query(q, params)

    async def get(self, record_id: str) -> dict:
        """Fetch one row by id AND company. A cross-company id → NotFoundError (404),
        deliberately indistinguishable from a genuinely missing id (no oracle)."""
        table = _table_of(record_id)
        _assert_scoped(table)
        rows = await repo_query(
            "SELECT * FROM $rid WHERE company = $company_id",
            {"rid": ensure_record_id(record_id), "company_id": self._company_rid},
        )
        if not rows:
            logger.warning(
                f"Scoped get miss: record_id={record_id} company_id={self.company_id} "
                f"user_id={self.user_id} (missing or cross-company)"
            )
            raise NotFoundError(f"{table} {record_id} not found")
        return rows[0]

    async def exists(self, record_id: str) -> bool:
        try:
            await self.get(record_id)
            return True
        except NotFoundError:
            return False

    # ---- writes -------------------------------------------------------------
    async def create(self, table: str, data: dict) -> dict:
        _assert_scoped(table)
        data = {**data, "company": self._company_rid}  # server-set; client company overwritten
        return await repo_create(table, data)

    async def update(self, record_id: str, data: dict) -> list[dict]:
        table = _table_of(record_id)
        _assert_scoped(table)
        await self.get(record_id)  # ownership check first → 404 on cross-company
        data = {k: v for k, v in data.items() if k != "company"}  # company immutable post-create
        return await repo_update(table, record_id, data)

    async def delete(self, record_id: str) -> bool:
        table = _table_of(record_id)
        _assert_scoped(table)
        await self.get(record_id)  # ownership check first → 404 on cross-company
        await repo_delete(record_id)
        return True

    # ---- raw escape hatch (AUDITED) ----------------------------------------
    async def raw(self, query: str, vars: Optional[dict] = None) -> list[dict]:
        """For multi-table joins the helpers can't express (e.g. count(<-reference.in)).
        The caller MUST include `company = $company_id` in the query themselves;
        $company_id is always injected into vars. Every call site needs a
        `# scoped-raw: <reason>` comment and its own leakage test."""
        params = {"company_id": self._company_rid, **(vars or {})}
        return await repo_query(query, params)
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_scoping_unit.py -q` — Expected: PASS (8 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/database/scoping.py tests/test_scoping_unit.py && git commit -m "P6: ScopedRepository + table-plane policy (app-layer tenant scoping)"`

---

### Task 2: Extend `api/deps.py` — `require_company`, `get_request_context`, `PermissionContext`

**Files:**
- Modify: `api/deps.py` (P2 file — ADD to it; do NOT redefine `get_identity`/`get_auth_context`/`require_role`)
- Test: `tests/test_deps_context.py`

**Interfaces:**
- Consumes: `AuthContext`, `decode_access_token`, `decode_identity_token` (`api/security.py`); `ScopedRepository` (Task 1); `repo_query`, `ensure_record_id` (`open_notebook/database/repository.py`).
- Produces (all NEW, added alongside P2's existing symbols): `require_company(auth) -> AuthContext`, async `get_request_context(auth) -> ScopedRepository`, `AuthDep = Annotated[AuthContext, Depends(require_company)]`, `CtxDep = Annotated[ScopedRepository, Depends(get_request_context)]`; dataclass `PermissionContext(user_id, company_id, company_role)` with async `project_role(project_id) -> "admin"|"member"|None`; async `get_permission_context(auth) -> PermissionContext`; `PermCtxDep = Annotated[PermissionContext, Depends(get_permission_context)]`.

- [ ] **Step 1: Write the failing test** — `tests/test_deps_context.py`:

```python
# tests/test_deps_context.py
"""Unit tests for P6 additions to api/deps.py: require_company, get_request_context,
and PermissionContext.project_role (repo_query patched — no live DB)."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.deps import (
    PermissionContext,
    get_permission_context,
    get_request_context,
    require_company,
)
from api.security import AuthContext
from open_notebook.database.scoping import ScopedRepository


def _auth(company_id="company:A", role="owner"):
    return AuthContext(user_id="user:1", company_id=company_id, role=role)


def test_require_company_passes_with_active_company():
    assert require_company(_auth()) is not None


def test_require_company_403_without_company():
    with pytest.raises(HTTPException) as exc:
        require_company(_auth(company_id=None, role=None))
    assert exc.value.status_code == 403
    assert "No active company" in exc.value.detail


@pytest.mark.asyncio
async def test_get_request_context_returns_bound_scoped_repository():
    repo = await get_request_context(_auth())
    assert isinstance(repo, ScopedRepository)
    assert repo.company_id == "company:A"
    assert repo.user_id == "user:1"
    assert repo.role == "owner"


@pytest.mark.asyncio
async def test_project_role_escalates_company_owner_admin_to_project_admin():
    ctx = PermissionContext(user_id="user:1", company_id="company:A", company_role="admin")
    # No project_member query should be needed for company admin — returns "admin".
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])) as q:
        assert await ctx.project_role("notebook:p1") == "admin"
    q.assert_not_called()


@pytest.mark.asyncio
async def test_project_role_reads_project_member_for_plain_member():
    ctx = PermissionContext(user_id="user:2", company_id="company:A", company_role="member")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[{"role": "member"}])) as q:
        assert await ctx.project_role("notebook:p1") == "member"
    q.assert_called_once()
    query, params = q.call_args[0]
    assert "project_member" in query
    assert "company = $company" in query  # membership lookup is itself company-scoped


@pytest.mark.asyncio
async def test_project_role_none_when_not_a_member():
    ctx = PermissionContext(user_id="user:3", company_id="company:A", company_role="member")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])):
        assert await ctx.project_role("notebook:p1") is None


@pytest.mark.asyncio
async def test_get_permission_context_maps_role_to_company_role():
    ctx = await get_permission_context(_auth(role="member"))
    assert ctx.company_role == "member"
    assert ctx.company_id == "company:A"
    assert ctx.user_id == "user:1"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_deps_context.py -q` — Expected: FAIL with `ImportError: cannot import name 'PermissionContext' from 'api.deps'`.

- [ ] **Step 3: Write minimal implementation** — Append to `api/deps.py` (keep P2's `bearer`, `get_auth_context`, `get_identity`, `require_role` exactly as they are). Add these imports at the top of the file if absent, and append the new symbols:

```python
# --- add to the imports block at the top of api/deps.py (P2 file) ---
from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, status

from api.security import AuthContext  # already imported by P2 alongside the decoders
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.database.scoping import ScopedRepository


# ==========================================================================
# P6 additions. get_identity / get_auth_context / require_role are P2's and
# are reused UNCHANGED above — do not redefine them here.
# ==========================================================================

def require_company(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    """Reject a token that carries no active company. The 403 gate that
    guarantees ScopedRepository always has a concrete company_id to filter on."""
    if not auth.company_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No active company selected for this request",
        )
    return auth


async def get_request_context(
    auth: Annotated[AuthContext, Depends(require_company)],
) -> ScopedRepository:
    """The dependency every company-scoped router uses. Hands back a repository
    pre-bound to auth.company_id — callers physically cannot query another company."""
    return ScopedRepository(
        company_id=auth.company_id, user_id=auth.user_id, role=auth.role
    )


@dataclass
class PermissionContext:
    """The request-context object P5's can_view_source/can_mutate_source bind to.

    company_role is the caller's active-company role from the token. project_role
    resolves a caller's role in a specific project via project_member, with company
    owner/admin escalating to project 'admin' (matches P5's expected semantics)."""

    user_id: str
    company_id: str
    company_role: str  # owner | admin | member

    async def project_role(self, project_id: str) -> Optional[str]:
        """Return 'admin' | 'member' | None for this caller in `project_id`.
        Company owner/admin escalate to project 'admin' without a membership row."""
        if self.company_role in ("owner", "admin"):
            return "admin"
        rows = await repo_query(
            "SELECT role FROM project_member "
            "WHERE user = $user AND project = $project "
            "AND company = $company AND status = 'active'",
            {
                "user": ensure_record_id(self.user_id),
                "project": ensure_record_id(project_id),
                "company": ensure_record_id(self.company_id),
            },
        )
        if rows:
            return rows[0].get("role")
        return None


async def get_permission_context(
    auth: Annotated[AuthContext, Depends(require_company)],
) -> PermissionContext:
    """P6's concrete PermissionContext, injected into P5's source-permission routers."""
    return PermissionContext(
        user_id=auth.user_id, company_id=auth.company_id, company_role=auth.role
    )


AuthDep = Annotated[AuthContext, Depends(require_company)]
CtxDep = Annotated[ScopedRepository, Depends(get_request_context)]
PermCtxDep = Annotated[PermissionContext, Depends(get_permission_context)]
```

Note: `require_company` is a plain (non-async) function — FastAPI supports sync dependencies and the unit test calls it directly. `get_request_context`/`get_permission_context` are async to match the codebase's async-first convention and allow future DB lookups.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_deps_context.py -q` — Expected: PASS (8 passed).

- [ ] **Step 5: Commit** — `git add api/deps.py tests/test_deps_context.py && git commit -m "P6: extend api/deps.py with require_company, get_request_context, PermissionContext"`

---

### Task 3: Grep contract-guard test — no raw `repo_*` on scoped tables in migrated routers

**Files:**
- Create: `tests/test_scoping_contract.py`

**Interfaces:**
- Consumes: the source tree under `api/routers/` and `api/*_service.py`. No runtime imports of app code.
- Produces: the CI backstop. `MIGRATED_MODULES` is the set of router/service files that HAVE been moved onto `ScopedRepository`; the guard fails if any raw scoped-table call reappears in them. Each later phase ADDS its migrated file here as it converts (this is the intentional, honest shape: the guard protects converted surface and grows).

- [ ] **Step 1: Write the failing test** — `tests/test_scoping_contract.py`:

```python
# tests/test_scoping_contract.py
"""Contract guard: a migrated scoped router/service must never call the raw
repo_* helpers or ObjectModel.get/save/delete for a company-scoped table — it
must go through the request-injected ScopedRepository (CtxDep). This is the
"developers must not be able to forget the scope" backstop: a regression fails
CI, not production.

MIGRATED_MODULES lists files already converted to ScopedRepository. As each
later phase migrates a router, it appends the file here. `raw()` call sites are
allowed (audited escape hatch) and are excluded by the regex below.
"""
import re
from pathlib import Path

# Files converted onto ScopedRepository (grows as phases migrate their routers).
MIGRATED_MODULES = {
    "api/routers/projects.py",
}

# Banned tokens: raw scoped-table access outside ScopedRepository.
_BANNED = [
    re.compile(r"\brepo_query\s*\("),
    re.compile(r"\brepo_create\s*\("),
    re.compile(r"\brepo_update\s*\("),
    re.compile(r"\brepo_delete\s*\("),
    re.compile(r"\bProject\.get\b"),
    re.compile(r"\bNotebook\.get\b"),
    re.compile(r"\bSource\.get\b"),
    re.compile(r"\bProject\.get_all\b"),
    re.compile(r"\bNotebook\.get_all\b"),
]

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _strip_scoped_raw_lines(src: str) -> str:
    """Drop lines that are part of a `repo.raw(` / `self.raw(` / `.raw(` call so
    the audited escape hatch does not trip the raw-repo_query guard. We only strip
    the `repo_query`-equivalent inside ScopedRepository.raw usage, identified by a
    `# scoped-raw:` marker on or above the call."""
    out_lines = []
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "# scoped-raw:" in line:
            out_lines.append("")  # neutralize the marker line
            continue
        out_lines.append(line)
    return "\n".join(out_lines)


def test_migrated_scoped_routers_have_no_raw_repo_calls():
    offenders = []
    for rel in sorted(MIGRATED_MODULES):
        path = _REPO_ROOT / rel
        assert path.exists(), f"MIGRATED_MODULES lists a missing file: {rel}"
        src = _strip_scoped_raw_lines(path.read_text(encoding="utf-8"))
        for pattern in _BANNED:
            for m in pattern.finditer(src):
                # allow `repo.raw(` and `.raw(` — that's ScopedRepository's own hatch
                start = src.rfind("\n", 0, m.start()) + 1
                line = src[start : src.find("\n", m.start())]
                if ".raw(" in line:
                    continue
                offenders.append(f"{rel}: {line.strip()!r} matched {pattern.pattern}")
    assert not offenders, "Raw scoped-table access found in migrated router(s):\n" + "\n".join(offenders)


def test_migrated_modules_all_exist():
    for rel in MIGRATED_MODULES:
        assert (_REPO_ROOT / rel).exists(), f"{rel} not found"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_scoping_contract.py -q` — Expected: FAIL — `test_migrated_scoped_routers_have_no_raw_repo_calls` reports `api/routers/projects.py` still uses `repo_query(`/`Project.get` (the router is migrated in Task 4). If `api/routers/projects.py` does not yet exist on your branch (P3 not landed), the `assert path.exists()` fails first — land P3 before this task.

- [ ] **Step 3: Write minimal implementation** — no implementation file; the test is satisfied by migrating the router in Task 4. This task delivers only the guard. (Keep it RED until Task 4 turns it GREEN — do NOT weaken the guard to make it pass early.)

- [ ] **Step 4: Run test, verify current state** — Run: `uv run pytest tests/test_scoping_contract.py -q` — Expected: FAIL now, GREEN after Task 4. Proceed to Task 4.

- [ ] **Step 5: Commit** — `git add tests/test_scoping_contract.py && git commit -m "P6: grep contract-guard test forbidding raw repo_* on scoped tables in migrated routers"`

---

### Task 4: Migrate the project router onto `ScopedRepository` — `api/routers/projects.py`

**Files:**
- Modify: `api/routers/projects.py` (P3 router; grounded in the real `api/routers/notebooks.py` it replaced)
- Test: covered by Task 3 (contract guard) turning GREEN and Task 5 (leakage suite).

**Interfaces:**
- Consumes: `CtxDep`, `require_role` (`api/deps.py`); `ProjectCreate`, `ProjectUpdate`, `ProjectResponse` (`api/models.py`).
- Produces: company-scoped `/projects` CRUD. `GET /projects`, `GET /projects/{id}` require an active company (`CtxDep`); `POST/PUT/DELETE /projects` additionally require `require_role("owner","admin")`.

This migrates the five endpoints exercised by the leakage suite. Reads AND-in the scope; writes stamp/ownership-check via `ScopedRepository`. The `count(<-reference.in)` join keeps its shape but goes through `repo.raw()` WITH the scope. Replace the endpoints as follows (leave any P3-only helpers like `_stamp_project_view` intact; if P3's file still names it `_stamp_notebook_view`, keep that name):

```python
# api/routers/projects.py  (P6-migrated endpoints)
from typing import Optional

from fastapi import APIRouter, Depends, Query
from loguru import logger

from api.deps import CtxDep, require_role
from api.models import ProjectCreate, ProjectResponse, ProjectUpdate
from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import InvalidInputError

router = APIRouter()


def _project_response(nb: dict) -> ProjectResponse:
    return ProjectResponse(
        id=str(nb.get("id", "")),
        name=nb.get("name", ""),
        description=nb.get("description", ""),
        archived=nb.get("archived", False),
        created=str(nb.get("created", "")),
        updated=str(nb.get("updated", "")),
        source_count=nb.get("source_count", 0),
        note_count=nb.get("note_count", 0),
        company=str(nb.get("company", "")),
        owner=str(nb.get("owner", "")),
        default_visibility=nb.get("default_visibility", "private"),
    )


@router.get("/projects", response_model=list[ProjectResponse])
async def get_projects(
    repo: CtxDep,
    archived: Optional[bool] = Query(None, description="Filter by archived status"),
    order_by: str = Query("updated desc", description="Order by field and direction"),
):
    """List the active company's projects with source/note counts."""
    validated_order_by = ObjectModel._validate_order_by(order_by)  # allowlist → InvalidInputError (400)
    rows = await repo.raw(
        # scoped-raw: needs count(<-reference.in)/count(<-artifact.in) graph traversal
        "SELECT *, count(<-reference.in) AS source_count, count(<-artifact.in) AS note_count "
        f"FROM notebook WHERE company = $company_id ORDER BY {validated_order_by}",
    )
    if archived is not None:
        rows = [nb for nb in rows if nb.get("archived") == archived]
    return [_project_response(nb) for nb in rows]


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    project: ProjectCreate,
    repo: CtxDep,
    _auth=Depends(require_role("owner", "admin")),
):
    """Create a project in the active company (owner/admin only). company is
    stamped server-side by ScopedRepository; owner is the caller."""
    created = await repo.create(
        "notebook",
        {
            "name": project.name,
            "description": project.description,
            "owner": repo.user_id,
            "default_visibility": getattr(project, "default_visibility", "private"),
            "archived": False,
        },
    )
    # Seed the creator as the sole project admin (mirrors P3 create semantics).
    await repo.create(
        "project_member",
        {"project": created["id"], "user": repo.user_id, "role": "admin", "status": "active"},
    )
    return _project_response({**created, "source_count": 0, "note_count": 0})


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, repo: CtxDep):
    """Get one project. 404 if not in the caller's company (no cross-company oracle)."""
    await repo.get(project_id)  # company-checked; raises NotFoundError (404) on miss/cross-company
    rows = await repo.raw(
        # scoped-raw: needs count(<-reference.in)/count(<-artifact.in) graph traversal
        "SELECT *, count(<-reference.in) AS source_count, count(<-artifact.in) AS note_count "
        "FROM $rid WHERE company = $company_id",
        {"rid": __import__("open_notebook.database.repository", fromlist=["ensure_record_id"]).ensure_record_id(project_id)},
    )
    return _project_response(rows[0])


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_update: ProjectUpdate,
    repo: CtxDep,
    _auth=Depends(require_role("owner", "admin")),
):
    """Update a project (owner/admin only). 404 on cross-company id."""
    patch = {
        k: v
        for k, v in {
            "name": project_update.name,
            "description": project_update.description,
            "archived": project_update.archived,
            "default_visibility": getattr(project_update, "default_visibility", None),
        }.items()
        if v is not None
    }
    if not patch:
        raise InvalidInputError("No updatable fields provided")
    await repo.update(project_id, patch)  # ownership-checked → 404 on cross-company
    return await get_project(project_id, repo)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    repo: CtxDep,
    _auth=Depends(require_role("owner", "admin")),
):
    """Delete a project (owner/admin only). 404 on cross-company id."""
    await repo.delete(project_id)  # ownership-checked → 404 on cross-company
    return {"message": "Project deleted successfully"}
```

Notes:
- The inline `__import__(...ensure_record_id)` in `get_project` is ugly; prefer a top-of-file `from open_notebook.database.repository import ensure_record_id` and use `ensure_record_id(project_id)`. It is shown inline only to keep this block self-contained; when editing the real file, add the clean import and use `ensure_record_id(project_id)` — but that import in a router would trip the contract guard only if it precedes a `repo_query(` call, which it does not. `ensure_record_id` is not a banned token.
- If P3's `ProjectResponse` lacks `company`/`owner`/`default_visibility`, they exist per the P3 spec (§ "Add `ProjectResponse` (existing NotebookResponse fields + `company`, `owner`, `default_visibility`)"). If your branch's `ProjectResponse` omits them, drop those three kwargs from `_project_response`.
- `_stamp_project_view` / `last_viewed_at` stamping (P3) may be re-added inside `get_project` after `repo.get(...)`; it uses `repo.raw("UPDATE $rid SET last_viewed_at = time::now() WHERE company = $company_id", {...})` with a `# scoped-raw:` marker so it stays scoped. Optional for P6.

- [ ] **Step 1: (no new test)** — this task is validated by re-running Task 3's guard and Task 5's leakage suite.

- [ ] **Step 2: Apply the migration** — edit `api/routers/projects.py` to replace the five endpoints as above; add `from open_notebook.database.repository import ensure_record_id` and use it in `get_project`.

- [ ] **Step 3: Run the contract guard** — Run: `uv run pytest tests/test_scoping_contract.py -q` — Expected: PASS (2 passed) — the migrated router no longer contains raw `repo_query(`/`Project.get` outside `.raw(`.

- [ ] **Step 4: Sanity-import the app** — Run: `uv run python -c "import api.main"` — Expected: no ImportError (router wiring intact).

- [ ] **Step 5: Commit** — `git add api/routers/projects.py && git commit -m "P6: migrate /projects router onto ScopedRepository + require_role"`

---

### Task 5: Tenant-leakage test suite — `tests/test_tenant_leakage.py`

**Files:**
- Create: `tests/test_tenant_leakage.py`

**Interfaces:**
- Consumes: `api.main:app` (ASGI), `api.security.create_access_token`, `create_identity_token`, and the `repo_*` helpers for seeding/teardown. Runs against a live SurrealDB test database; guarded by env `RUN_TENANT_LEAKAGE_DB` (mirrors `arteamis-system`'s `TEST_DATABASE_URL` skip guard) so `uv run pytest tests/` stays green in CI without a DB.

- [ ] **Step 1: Write the failing test** — `tests/test_tenant_leakage.py`:

```python
# tests/test_tenant_leakage.py
"""Tenant-leakage suite — the SurrealDB analogue of arteamis-system's
test_projects_rls.py + test_X3_suite1_tenant_leakage.py. Proves company A can
never read or mutate company B's rows, even by guessing record ids.

Requires a live SurrealDB (the API's configured DB). Skipped unless
RUN_TENANT_LEAKAGE_DB=1 so `uv run pytest tests/` is green in CI without a DB.
Seeds two companies A/B + a user/membership in each, then drives /api/projects
with each company's access token.
"""
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.security import create_access_token
from open_notebook.database.repository import repo_create, repo_delete, repo_query

_requires_db = pytest.mark.skipif(
    os.getenv("RUN_TENANT_LEAKAGE_DB") != "1",
    reason="RUN_TENANT_LEAKAGE_DB not set (needs a live SurrealDB)",
)

pytestmark = [pytest.mark.asyncio, _requires_db]


def _headers(user_id: str, company_id: str, role: str = "owner") -> dict:
    tok = create_access_token(user_id=user_id, company_id=company_id, role=role)
    return {"Authorization": f"Bearer {tok}"}


@pytest_asyncio.fixture
async def seeded():
    """Create two companies, a user + membership in each, and one project in A."""
    tag = uuid.uuid4().hex[:8]
    ua = await repo_create("user", {"email": f"a-{tag}@t.io", "display_name": "A"})
    ub = await repo_create("user", {"email": f"b-{tag}@t.io", "display_name": "B"})
    ca = await repo_create("company", {"name": f"A-{tag}", "slug": f"a-{tag}", "owner": ua["id"]})
    cb = await repo_create("company", {"name": f"B-{tag}", "slug": f"b-{tag}", "owner": ub["id"]})
    await repo_create("membership", {"user": ua["id"], "company": ca["id"], "role": "owner", "status": "active"})
    await repo_create("membership", {"user": ub["id"], "company": cb["id"], "role": "owner", "status": "active"})
    proj_a = await repo_create(
        "notebook",
        {"name": f"A-proj-{tag}", "description": "secret", "company": ca["id"],
         "owner": ua["id"], "default_visibility": "private", "archived": False},
    )
    data = {
        "user_a": str(ua["id"]), "user_b": str(ub["id"]),
        "company_a": str(ca["id"]), "company_b": str(cb["id"]),
        "project_a": str(proj_a["id"]),
    }
    yield data
    # teardown — best effort
    for rid in (proj_a["id"], ca["id"], cb["id"], ua["id"], ub["id"]):
        try:
            await repo_delete(rid)
        except Exception:
            pass
    await repo_query("DELETE membership WHERE company = $c1 OR company = $c2",
                     {"c1": ca["id"], "c2": cb["id"]})


@pytest_asyncio.fixture
async def client():
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_company_b_cannot_list_company_a_projects(client, seeded):
    r = await client.get("/api/projects", headers=_headers(seeded["user_b"], seeded["company_b"]))
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()]
    assert seeded["project_a"] not in ids  # A's project absent from B's list


async def test_company_a_can_list_own_projects(client, seeded):
    r = await client.get("/api/projects", headers=_headers(seeded["user_a"], seeded["company_a"]))
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert seeded["project_a"] in ids


async def test_company_b_cannot_get_company_a_project_by_guessed_id(client, seeded):
    r = await client.get(f"/api/projects/{seeded['project_a']}",
                         headers=_headers(seeded["user_b"], seeded["company_b"]))
    assert r.status_code == 404, r.text  # not 200, not 403 — no existence oracle


async def test_company_b_cannot_update_company_a_project(client, seeded):
    r = await client.put(f"/api/projects/{seeded['project_a']}",
                         json={"name": "hijacked"},
                         headers=_headers(seeded["user_b"], seeded["company_b"]))
    assert r.status_code == 404
    # A re-reads → unchanged (WITH CHECK analogue)
    ra = await client.get(f"/api/projects/{seeded['project_a']}",
                          headers=_headers(seeded["user_a"], seeded["company_a"]))
    assert ra.status_code == 200
    assert ra.json()["name"] != "hijacked"


async def test_company_b_cannot_delete_company_a_project(client, seeded):
    r = await client.delete(f"/api/projects/{seeded['project_a']}",
                            headers=_headers(seeded["user_b"], seeded["company_b"]))
    assert r.status_code == 404
    ra = await client.get(f"/api/projects/{seeded['project_a']}",
                          headers=_headers(seeded["user_a"], seeded["company_a"]))
    assert ra.status_code == 200  # A still sees it


async def test_create_stamps_callers_company_not_client_value(client, seeded):
    # B forges company=A in the body; server must stamp B.
    r = await client.post("/api/projects",
                          json={"name": "forge", "company": seeded["company_a"]},
                          headers=_headers(seeded["user_b"], seeded["company_b"]))
    assert r.status_code == 200, r.text
    created_id = r.json()["id"]
    rows = await repo_query("SELECT company FROM $rid",
                            {"rid": __import__("open_notebook.database.repository",
                                               fromlist=["ensure_record_id"]).ensure_record_id(created_id)})
    assert str(rows[0]["company"]) == seeded["company_b"]  # stamped B, not A
    await repo_delete(created_id)


async def test_missing_company_token_is_403(client, seeded):
    from api.security import create_identity_token
    tok = create_identity_token(seeded["user_b"])  # identity token: no company_id
    r = await client.get("/api/projects", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert "No active company" in r.json()["detail"]


async def test_member_cannot_create_project(client, seeded):
    # A plain member is refused project creation by require_role("owner","admin").
    r = await client.post("/api/projects", json={"name": "nope"},
                          headers=_headers(seeded["user_a"], seeded["company_a"], role="member"))
    assert r.status_code == 403
    assert "Requires role" in r.json()["detail"]
```

- [ ] **Step 2: Run test, verify it fails (or skips without DB)** — Run: `RUN_TENANT_LEAKAGE_DB=1 uv run pytest tests/test_tenant_leakage.py -q` (SurrealDB must be up: `make database`). Expected before Task 4's router is complete: FAILs on cross-company reads. After Task 4: all pass. Without the env var: `uv run pytest tests/test_tenant_leakage.py -q` → SKIPPED.

- [ ] **Step 3: (implementation already done in Tasks 1–4)** — no new production code; this suite is the acceptance test for the backend half of P6.

- [ ] **Step 4: Run test, verify it passes** — Run: `make database && RUN_TENANT_LEAKAGE_DB=1 uv run pytest tests/test_tenant_leakage.py -q` — Expected: PASS (8 passed). Also confirm CI-safe skip: `uv run pytest tests/test_tenant_leakage.py -q` → 8 skipped.

- [ ] **Step 5: Commit** — `git add tests/test_tenant_leakage.py && git commit -m "P6: tenant-leakage suite proving cross-company reads/mutations 404"`

---

### Task 6: i18n keys — `roles.*` + `company.activeCompany` across all locales

**Files:**
- Modify: every locale file under `frontend/src/lib/locales/<code>/index.ts` (the parity test checks ALL locales in `resources`, not only the 7 enforced).
- Test: `frontend/src/lib/locales/index.test.ts` (existing parity + unused-key detection — must stay green).

**Interfaces:**
- Produces the leaf keys consumed by Tasks 7–9: `roles.owner`, `roles.admin`, `roles.member`, `roles.adminOnly`, `roles.noCompany`, `roles.accessDenied`, `company.activeCompany`. (Every key MUST be referenced in a source file or the unused-key test fails — Tasks 8/9 reference all of them.)

- [ ] **Step 1: Add the keys to en-US** — in `frontend/src/lib/locales/en-US/index.ts`, add a new top-level `roles` object and a `company` object (place them anywhere among the existing top-level sections, e.g. after the `common` block). Use exactly these leaf keys:

```ts
  roles: {
    owner: "Owner",
    admin: "Admin",
    member: "Member",
    adminOnly: "Only company admins can do this",
    noCompany: "Select a company to continue",
    accessDenied: "You do not have access to this page",
  },
  company: {
    activeCompany: "Active company",
  },
```

If a top-level `company` object already exists in a locale (from P2), MERGE `activeCompany` into it rather than adding a duplicate key.

- [ ] **Step 2: Add the SAME key set to the 6 other enforced locales** — with these translations:

```ts
// pt-BR
  roles: { owner: "Proprietário", admin: "Administrador", member: "Membro",
    adminOnly: "Apenas administradores da empresa podem fazer isso",
    noCompany: "Selecione uma empresa para continuar",
    accessDenied: "Você não tem acesso a esta página" },
  company: { activeCompany: "Empresa ativa" },
// zh-CN
  roles: { owner: "所有者", admin: "管理员", member: "成员",
    adminOnly: "只有公司管理员可以执行此操作",
    noCompany: "请选择一个公司以继续",
    accessDenied: "您无权访问此页面" },
  company: { activeCompany: "当前公司" },
// zh-TW
  roles: { owner: "擁有者", admin: "管理員", member: "成員",
    adminOnly: "只有公司管理員可以執行此操作",
    noCompany: "請選擇一間公司以繼續",
    accessDenied: "您無權存取此頁面" },
  company: { activeCompany: "目前公司" },
// ja-JP
  roles: { owner: "オーナー", admin: "管理者", member: "メンバー",
    adminOnly: "この操作は会社の管理者のみ実行できます",
    noCompany: "続行するには会社を選択してください",
    accessDenied: "このページにアクセスする権限がありません" },
  company: { activeCompany: "現在の会社" },
// ru-RU
  roles: { owner: "Владелец", admin: "Администратор", member: "Участник",
    adminOnly: "Только администраторы компании могут это делать",
    noCompany: "Выберите компанию, чтобы продолжить",
    accessDenied: "У вас нет доступа к этой странице" },
  company: { activeCompany: "Активная компания" },
// bn-IN
  roles: { owner: "মালিক", admin: "অ্যাডমিন", member: "সদস্য",
    adminOnly: "শুধুমাত্র কোম্পানির অ্যাডমিনরা এটি করতে পারেন",
    noCompany: "চালিয়ে যেতে একটি কোম্পানি নির্বাচন করুন",
    accessDenied: "আপনার এই পৃষ্ঠায় প্রবেশাধিকার নেই" },
  company: { activeCompany: "সক্রিয় কোম্পানি" },
```

- [ ] **Step 3: Add the key set to the remaining (non-enforced) locales to satisfy strict parity** — `ca-ES`, `de-DE`, `es-ES`, `fr-FR`, `it-IT`, `pl-PL`, `tr-TR`. The parity test requires identical key sets across ALL locales in `resources`. Provide translations if known; otherwise copy the en-US English values verbatim (English fallback is acceptable for non-enforced locales and keeps parity green). Use the exact same `roles`/`company` leaf keys as Step 1.

- [ ] **Step 4: Run the locale tests** — Run (inside `frontend/`): `npm run test -- src/lib/locales/index.test.ts` — Expected: PASS for parity. The "Unused Key Detection" test may still report `roles.*`/`company.activeCompany` as unused UNTIL Tasks 8/9 reference them — run the full locale test again after Task 9. (If executing tasks strictly in order, expect this one unused-key assertion to be RED between Task 6 and Task 9; that is intended.)

- [ ] **Step 5: Commit** — `git add frontend/src/lib/locales && git commit -m "P6: add roles.* + company.activeCompany i18n keys across all locales"`

---

### Task 7: Auth-store role/company fields + `useRole()` hook

**Files:**
- Modify: `frontend/src/lib/stores/auth-store.ts`
- Create: `frontend/src/lib/hooks/use-role.ts`
- Test: `frontend/src/lib/hooks/use-role.test.ts`

**Interfaces:**
- Produces on the store: `companyId: string | null`, `companyName: string | null`, `role: 'owner' | 'admin' | 'member' | null`, `setActiveCompany(args: { companyId: string | null; companyName: string | null; role: CompanyRole | null }) => void`; all three persisted via `partialize`.
- Produces the hook: `useRole()` → `{ role, companyId, companyName, isOwner, isAdmin, isMember, can(...roles: CompanyRole[]): boolean }`; and `type CompanyRole = 'owner' | 'admin' | 'member'`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/hooks/use-role.test.ts`:

```ts
// frontend/src/lib/hooks/use-role.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRole } from './use-role'
import { useAuthStore } from '@/lib/stores/auth-store'

function setRole(role: 'owner' | 'admin' | 'member' | null) {
  useAuthStore.setState({
    companyId: role ? 'company:A' : null,
    companyName: role ? 'Acme' : null,
    role,
  } as Partial<ReturnType<typeof useAuthStore.getState>>)
}

describe('useRole', () => {
  beforeEach(() => setRole(null))

  it('owner is owner and admin (owner ⊇ admin)', () => {
    setRole('owner')
    const { result } = renderHook(() => useRole())
    expect(result.current.isOwner).toBe(true)
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.isMember).toBe(false)
    expect(result.current.can('owner', 'admin')).toBe(true)
  })

  it('admin is admin but not owner', () => {
    setRole('admin')
    const { result } = renderHook(() => useRole())
    expect(result.current.isOwner).toBe(false)
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.can('owner', 'admin')).toBe(true)
    expect(result.current.can('owner')).toBe(false)
  })

  it('member is only member', () => {
    setRole('member')
    const { result } = renderHook(() => useRole())
    expect(result.current.isAdmin).toBe(false)
    expect(result.current.isMember).toBe(true)
    expect(result.current.can('owner', 'admin')).toBe(false)
    expect(result.current.can('member')).toBe(true)
  })

  it('no role → nothing granted, company null', () => {
    const { result } = renderHook(() => useRole())
    expect(result.current.role).toBeNull()
    expect(result.current.companyId).toBeNull()
    expect(result.current.isAdmin).toBe(false)
    expect(result.current.can('member')).toBe(false)
  })

  it('surfaces companyName', () => {
    setRole('owner')
    const { result } = renderHook(() => useRole())
    expect(result.current.companyName).toBe('Acme')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/lib/hooks/use-role.test.ts` — Expected: FAIL — `Cannot find module './use-role'`.

- [ ] **Step 3a: Extend the auth store** — in `frontend/src/lib/stores/auth-store.ts`:
  1. Add to the `AuthState` interface:
     ```ts
     companyId: string | null
     companyName: string | null
     role: 'owner' | 'admin' | 'member' | null
     setActiveCompany: (args: {
       companyId: string | null
       companyName: string | null
       role: 'owner' | 'admin' | 'member' | null
     }) => void
     ```
  2. Add to the initial state object (next to `token: null`):
     ```ts
     companyId: null,
     companyName: null,
     role: null,
     ```
  3. Add the action inside the store body (next to `setHasHydrated`):
     ```ts
     setActiveCompany: ({ companyId, companyName, role }) => {
       set({ companyId, companyName, role })
     },
     ```
  4. Extend `partialize` (the object it returns) to persist the three new fields alongside `token`:
     ```ts
     partialize: (state) => ({
       // ...existing persisted fields (e.g. token) stay here...
       token: state.token,
       companyId: state.companyId,
       companyName: state.companyName,
       role: state.role,
     }),
     ```
     If `partialize` currently persists other keys (e.g. `isAuthenticated`), keep them — only ADD `companyId`/`companyName`/`role`.

- [ ] **Step 3b: Create the hook** — `frontend/src/lib/hooks/use-role.ts`:

```ts
// frontend/src/lib/hooks/use-role.ts
'use client'

import { useAuthStore } from '@/lib/stores/auth-store'

export type CompanyRole = 'owner' | 'admin' | 'member'

export function useRole() {
  const role = useAuthStore((s) => s.role)
  const companyId = useAuthStore((s) => s.companyId)
  const companyName = useAuthStore((s) => s.companyName)

  const can = (...roles: CompanyRole[]) => !!role && roles.includes(role)

  return {
    role,
    companyId,
    companyName,
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin', // owner ⊇ admin
    isMember: role === 'member',
    can, // can('owner', 'admin')
  }
}
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/lib/hooks/use-role.test.ts` — Expected: PASS (5 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/stores/auth-store.ts frontend/src/lib/hooks/use-role.ts frontend/src/lib/hooks/use-role.test.ts && git commit -m "P6: auth-store company/role fields + useRole hook"`

---

### Task 8: `<RoleGate>` component

**Files:**
- Create: `frontend/src/components/common/RoleGate.tsx`
- Test: `frontend/src/components/common/RoleGate.test.tsx`

**Interfaces:**
- Consumes: `useRole()` (Task 7), `useTranslation()` (`@/lib/hooks/use-translation`).
- Produces: `RoleGate({ allow, mode = 'hide', children })` where `allow: CompanyRole[]`, `mode: 'hide' | 'disable'`. `hide` → renders `null` when not allowed; `disable` → renders children inside an `aria-disabled`, `pointer-events-none`, dimmed span with `title={t('roles.adminOnly')}`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/common/RoleGate.test.tsx`:

```tsx
// frontend/src/components/common/RoleGate.test.tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RoleGate } from './RoleGate'
import { useAuthStore } from '@/lib/stores/auth-store'

function setRole(role: 'owner' | 'admin' | 'member' | null) {
  useAuthStore.setState({ role, companyId: 'company:A', companyName: 'Acme' } as never)
}

describe('RoleGate', () => {
  beforeEach(() => setRole(null))

  it('renders children for an allowed role', () => {
    setRole('admin')
    render(<RoleGate allow={['owner', 'admin']}><button>Delete</button></RoleGate>)
    expect(screen.getByText('Delete')).toBeDefined()
  })

  it('hides children for a disallowed role (default mode)', () => {
    setRole('member')
    render(<RoleGate allow={['owner', 'admin']}><button>Delete</button></RoleGate>)
    expect(screen.queryByText('Delete')).toBeNull()
  })

  it('disable mode renders children but aria-disabled', () => {
    setRole('member')
    render(
      <RoleGate allow={['owner', 'admin']} mode="disable">
        <button>Delete</button>
      </RoleGate>,
    )
    const el = screen.getByText('Delete').parentElement as HTMLElement
    expect(el.getAttribute('aria-disabled')).toBe('true')
    expect(el.className).toContain('pointer-events-none')
  })

  it('owner passes an admin-only gate (owner ⊇ admin)', () => {
    setRole('owner')
    render(<RoleGate allow={['admin']}><span>Manage</span></RoleGate>)
    expect(screen.getByText('Manage')).toBeDefined()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/components/common/RoleGate.test.tsx` — Expected: FAIL — `Cannot find module './RoleGate'`.

- [ ] **Step 3: Write the component** — `frontend/src/components/common/RoleGate.tsx`:

```tsx
// frontend/src/components/common/RoleGate.tsx
'use client'

import type { ReactNode } from 'react'
import { useRole, type CompanyRole } from '@/lib/hooks/use-role'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RoleGate({
  allow,
  mode = 'hide',
  children,
}: {
  allow: CompanyRole[]
  mode?: 'hide' | 'disable'
  children: ReactNode
}) {
  const { can } = useRole()
  const { t } = useTranslation()

  if (can(...allow)) return <>{children}</>
  if (mode === 'hide') return null

  return (
    <span
      aria-disabled="true"
      className="opacity-50 pointer-events-none"
      title={t('roles.adminOnly')}
    >
      {children}
    </span>
  )
}
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/components/common/RoleGate.test.tsx` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/common/RoleGate.tsx frontend/src/components/common/RoleGate.test.tsx && git commit -m "P6: RoleGate component (hide/disable admin-only UI)"`

---

### Task 9: Dashboard route guard + `<RequireRole>` + AppSidebar gating + company badge

**Files:**
- Create: `frontend/src/components/common/RequireRole.tsx`
- Modify: `frontend/src/app/(dashboard)/layout.tsx`
- Modify: `frontend/src/components/layout/AppSidebar.tsx`
- Test: `frontend/src/components/layout/AppSidebar.test.tsx` (extend existing)

**Interfaces:**
- Consumes: `useRole()` (Task 7), `RoleGate` (Task 8), `useRouter`/`usePathname` (`next/navigation`), `useToast` (`@/lib/hooks/use-toast`), `useTranslation`.
- Produces: `RequireRole({ allow, children })` — thin client-side redirect to `/notebooks` + `t('roles.accessDenied')` toast on deny; the dashboard layout redirect to `/onboarding` when authenticated but `companyId == null`; the sidebar's `Manage` section + Create→notebook item gated to owner/admin; a company-name header + role pill.

- [ ] **Step 1: Write/extend the failing test** — append to `frontend/src/components/layout/AppSidebar.test.tsx` (keep the existing tests and the Tooltip mock at the top; add a mock for `useRole` and role-based cases). Add:

```tsx
// --- append to frontend/src/components/layout/AppSidebar.test.tsx ---
import { useRole } from '@/lib/hooks/use-role'

vi.mock('@/lib/hooks/use-role', () => ({
  useRole: vi.fn(),
}))

function mockRole(role: 'owner' | 'admin' | 'member') {
  vi.mocked(useRole).mockReturnValue({
    role,
    companyId: 'company:A',
    companyName: 'Acme',
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin',
    isMember: role === 'member',
    can: (...roles: Array<'owner' | 'admin' | 'member'>) => roles.includes(role),
  } as unknown as ReturnType<typeof useRole>)
}

describe('AppSidebar role gating', () => {
  it('admin sees the Manage section and Create→Notebook', () => {
    mockRole('admin')
    render(<AppSidebar />)
    expect(screen.getByText('navigation.manage')).toBeDefined()
  })

  it('member does NOT see the Manage section', () => {
    mockRole('member')
    render(<AppSidebar />)
    expect(screen.queryByText('navigation.manage')).toBeNull()
  })

  it('surfaces the active company name', () => {
    mockRole('owner')
    render(<AppSidebar />)
    expect(screen.getByText('Acme')).toBeDefined()
  })
})
```

Note: the existing `AppSidebar` tests render without mocking `useRole`; add a `beforeEach(() => mockRole('owner'))` inside the ORIGINAL `describe('AppSidebar', ...)` block too, so those legacy tests still see a Manage section. (If they don't assert on Manage, no change needed beyond the mock returning a value — `vi.mock` hoists, so provide a default: add `mockRole('owner')` in a top-level `beforeEach`.)

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/components/layout/AppSidebar.test.tsx` — Expected: FAIL — member case still shows `navigation.manage` (not yet gated) and/or `useRole` undefined return.

- [ ] **Step 3a: Create `RequireRole`** — `frontend/src/components/common/RequireRole.tsx`:

```tsx
// frontend/src/components/common/RequireRole.tsx
'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import type { ReactNode } from 'react'
import { useRole, type CompanyRole } from '@/lib/hooks/use-role'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RequireRole({
  allow,
  children,
}: {
  allow: CompanyRole[]
  children: ReactNode
}) {
  const { can, role } = useRole()
  const router = useRouter()
  const { toast } = useToast()
  const { t } = useTranslation()
  const allowed = can(...allow)

  useEffect(() => {
    if (role && !allowed) {
      toast({ title: t('roles.accessDenied'), variant: 'destructive' })
      router.push('/notebooks')
    }
  }, [allowed, role, router, toast, t])

  if (!allowed) return null
  return <>{children}</>
}
```

- [ ] **Step 3b: Extend the dashboard route guard** — `frontend/src/app/(dashboard)/layout.tsx`. Add `useRole` and a company-redirect. Insert after the existing unauthenticated redirect logic (inside the same `useEffect`, guarded by `isAuthenticated`):

```tsx
// add import
import { useRole } from '@/lib/hooks/use-role'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

// inside the component, near the top:
const { companyId } = useRole()
const { toast } = useToast()
const { t } = useTranslation()

// inside the existing useEffect, AFTER the `if (!isAuthenticated) { ... }` block,
// add an else-branch that requires an active company:
if (isAuthenticated && companyId == null) {
  toast({ title: t('roles.noCompany') })
  router.push('/onboarding')
}
```

Add `companyId`, `toast`, `t` to the `useEffect` dependency array. This keeps a member without an active company out of scoped screens before a scoped API call can 403.

- [ ] **Step 3c: Gate the sidebar** — `frontend/src/components/layout/AppSidebar.tsx`:
  1. Import the gate and role hook at the top:
     ```tsx
     import { RoleGate } from '@/components/common/RoleGate'
     import { useRole } from '@/lib/hooks/use-role'
     ```
  2. Read the company for the header: inside `AppSidebar`, add `const { companyName, role } = useRole()`.
  3. Wrap the entire `Manage` nav section so members don't see it. The nav is data-driven (`getNavigation(t)`); the `Manage` section has `title: t('navigation.manage')`. In the `navigation.map(...)` render, gate that one section:
     ```tsx
     {navigation.map((section, index) => {
       const sectionNode = (
         <div key={section.title}>
           {/* ...existing section body unchanged... */}
         </div>
       )
       // Manage is owner/admin-only
       if (section.title === t('navigation.manage')) {
         return (
           <RoleGate key={section.title} allow={['owner', 'admin']}>
             {sectionNode}
           </RoleGate>
         )
       }
       return sectionNode
     })}
     ```
  4. Gate the Create → Notebook item (the `DropdownMenuItem` calling `handleCreateSelection('notebook')`, lines ~219–228) with `<RoleGate allow={['owner','admin']}>`:
     ```tsx
     <RoleGate allow={['owner', 'admin']}>
       <DropdownMenuItem
         onSelect={(event) => { event.preventDefault(); handleCreateSelection('notebook') }}
         className="gap-2"
       >
         <Book className="h-4 w-4" />
         {t('common.notebook')}
       </DropdownMenuItem>
     </RoleGate>
     ```
     Leave `source` and `podcast` items available to members.
  5. Add a company + role badge near the logo (in the expanded header, after the app-name span, ~line 145). Only render when not collapsed and a company is active:
     ```tsx
     {!isCollapsed && companyName && (
       <div className="mt-0.5 flex items-center gap-1.5" aria-label={t('company.activeCompany')}>
         <span className="text-xs text-sidebar-foreground/70 truncate">{companyName}</span>
         {role && (
           <span className="rounded bg-sidebar-accent px-1.5 py-0.5 text-[10px] uppercase text-sidebar-accent-foreground">
             {t(`roles.${role}`)}
           </span>
         )}
       </div>
     )}
     ```
     Place it so it doesn't break the existing flex layout (e.g. wrap the app-name span + this badge in a `flex-col` container).

- [ ] **Step 4: Run tests + lint + build** — Run (inside `frontend/`):
  - `npm run test -- src/components/layout/AppSidebar.test.tsx` — Expected: PASS (member hides Manage, admin shows it, company name shown).
  - `npm run test -- src/lib/locales/index.test.ts` — Expected: PASS (now that `roles.*`/`company.activeCompany` are referenced by RoleGate/RequireRole/AppSidebar/layout, the unused-key test is satisfied).
  - `npm run lint` — Expected: no errors.
  - `npm run build` — Expected: build succeeds.

- [ ] **Step 5: Commit** — `git add frontend/src/components/common/RequireRole.tsx frontend/src/app/\(dashboard\)/layout.tsx frontend/src/components/layout/AppSidebar.tsx frontend/src/components/layout/AppSidebar.test.tsx && git commit -m "P6: dashboard route guard, RequireRole, sidebar role-gating + company badge"`

---

## Final verification (run before declaring P6 done)

- [ ] Backend unit + contract (no DB): `uv run pytest tests/test_scoping_unit.py tests/test_deps_context.py tests/test_scoping_contract.py -q` — Expected: all PASS.
- [ ] Backend leakage (live DB): `make database && RUN_TENANT_LEAKAGE_DB=1 uv run pytest tests/test_tenant_leakage.py -q` — Expected: all PASS.
- [ ] Full backend suite stays green (leakage auto-skips without the env var): `uv run pytest tests/ -q`.
- [ ] Lint/type: `ruff check . --fix` and `uv run python -m mypy api/deps.py open_notebook/database/scoping.py`.
- [ ] Frontend: `cd frontend && npm run test && npm run lint && npm run build` — Expected: all PASS (parity + unused-key locale tests green).

---

## Self-review (performed; issues fixed inline)

**1. Spec coverage — every spec section maps to a task:**
- Request-context dependency (`require_company`, `get_request_context`, `AuthDep`/`CtxDep`) → Task 2. `get_identity`/`get_auth_context`/`require_role` explicitly NOT redefined (reused from P2) → stated in Task 2 header and code comment.
- `ScopedRepository` + `COMPANY_SCOPED_TABLES`/`GLOBAL_TABLES` policy, reads filtered / writes stamped / global refused / cross-company 404-no-oracle / audited `raw()` → Task 1.
- `PermissionContext` (user_id, company_id, company_role, async `project_role` with company owner/admin → project-admin escalation) that P5 consumes → Task 2.
- Router migration to `ScopedRepository` → Task 4 (projects/notebook router; the surface the leakage suite drives).
- Developer contract + grep guard (`test_scoping_contract.py`) → Task 3.
- Tenant-leakage suite (`test_tenant_leakage.py`) covering list/get/update/delete/create-stamp/missing-company-403/role-403 → Task 5 (maps to spec test cases 1–4, 7, 8; case 9/10 unit-guard covered in Task 1; case 5 source-by-id and 6 note/chat are P5-router-owned and follow when those routers migrate — noted below).
- Frontend `useRole()` + auth-store role/company → Task 7; `<RoleGate>` → Task 8; dashboard route guard + `<RequireRole>` + AppSidebar gating + company badge → Task 9; i18n keys across all locales → Task 6.
- Error contract (401/403/404/400) → enforced by `require_company`/`require_role` (403), `ScopedRepository.get` (404 via `NotFoundError`→existing handler), `_assert_scoped` (400 via `InvalidInputError`→existing handler); WARNING log on cross-company miss included in `ScopedRepository.get`.

**Gaps closed / consciously deferred (matches spec "Out of scope"/"Open questions"):**
- Leakage cases 5 (source-by-guessed-id) and 6 (note/chat lists) require the `sources.py`/`notes.py`/`chat.py` routers to be migrated onto `ScopedRepository`/`PermCtxDep` — those routers are P5/P3-owned; P6 supplies the `PermissionContext` + `ScopedRepository` they consume and migrates the project router as the reference migration. Each router adds itself to `MIGRATED_MODULES` (Task 3) and its own leakage test as it migrates. This is the spec's stated shape ("Once P6 lands, P3/P4/P5 routers are migrated to consume it") and is called out in Task 4/Task 5 notes rather than silently dropped.
- Denial audit table → deferred (spec Open questions); P6 logs at WARNING (`ScopedRepository.get`).
- `source_insight`/`source_embedding` denormalized company column → not added (P6 owns no migration); scoped via parent join through `raw()` when their routers migrate.
- No P6 migration file; `AsyncMigrationManager` untouched — consistent with Global Constraints.

**2. Placeholder scan:** No "TBD/TODO/implement later"; every code block is complete runnable Python/TS with real imports and real paths. The one deliberate RED-until-later state (Task 3 guard is RED until Task 4; Task 6 unused-key test RED until Task 9) is explicitly documented, not hidden.

**3. Type consistency:** `AuthContext(user_id, company_id, role)` used identically in Tasks 2/5. `ScopedRepository(company_id, user_id, role)` signature consistent across Tasks 1/2. `CtxDep`/`AuthDep`/`PermCtxDep` defined in Task 2, consumed in Task 4. `PermissionContext(user_id, company_id, company_role)` + `project_role` consistent Task 2 ↔ P5 spec (§ "ctx.company_role", "async ctx.project_role"). `CompanyRole` type + `useRole()` return shape consistent Tasks 7/8/9. i18n keys defined in Task 6 are exactly those referenced in Tasks 8 (`roles.adminOnly`) and 9 (`roles.accessDenied`, `roles.noCompany`, `roles.<role>`, `company.activeCompany`) — no unreferenced key, no undefined reference.
