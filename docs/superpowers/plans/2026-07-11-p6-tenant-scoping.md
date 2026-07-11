# P6 — App-layer Tenant Scoping (replaces RLS) + Frontend Role-Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce workspace-tenant isolation in the application layer (SurrealDB has no RLS) via a single sanctioned `ScopedRepository`, gate scoped routers with `require_workspace`/`require_role`, supply the `PermissionContext` P5 consumes, role-gate the frontend (including a Personal/company workspace switcher), and prove isolation with a tenant-leakage test suite — uniformly across personal and company workspaces, with NO personal/company branching anywhere in the isolation layer.

**Architecture:** A request-scoped `ScopedRepository` (`open_notebook/database/scoping.py`) wraps the existing async `repo_*` helpers so every read AND-s `WHERE workspace = $workspace_id` and every write stamps `workspace`; a guessed cross-workspace record id resolves to 404 (no existence oracle) — this applies identically whether the "other" workspace is a company or someone else's personal workspace. `api/deps.py` (created by P2) gains `require_workspace`, `get_request_context`, the `CtxDep`/`AuthDep`/`PermCtxDep` aliases, and the concrete `PermissionContext` (workspace_role + async `project_role`). The project (physically `notebook`) router migrates onto the wrapper; a grep contract-guard test forbids raw `repo_*` on scoped tables in migrated routers. The frontend adds a `useRole()` hook and a `<RoleGate>` component (with a `requireCompanyWorkspace` flag for invite/manage-members UI), a dashboard route guard, and gates concrete admin/company-only actions; the **`WorkspaceSwitcher` itself is P2's component** (`frontend/src/components/workspace/WorkspaceSwitcher.tsx`, already mounted in the sidebar) — P6 only **extends** it with the role-gating primitives above, it does not re-create it.

**Tech Stack:** Next.js 16 (App Router), FastAPI, SurrealDB (async `repo_*`), TanStack Query, Zustand (`persist`), python-jose (JWT via P1 `api/security.py`), vitest, pytest.

**Spec:** docs/superpowers/specs/2026-07-11-p6-tenant-scoping-frontend-gating-design.md
**Depends on:** P1 (auth/JWT `api/security.py`), P2 (`api/deps.py`: `get_identity`/`get_auth_context`/`require_role`; `workspace`(kind personal|company)/`membership`; `/workspaces` list/create + `/auth/switch-workspace/{id}`; the frontend `frontend/src/lib/api/workspaces.ts` (`workspacesApi`), `frontend/src/lib/hooks/use-workspaces.ts` (`useWorkspaces`/`useCreateWorkspace`/`useSwitchWorkspace`), and the `WorkspaceSwitcher` component itself at `frontend/src/components/workspace/WorkspaceSwitcher.tsx`, already mounted in `AppSidebar.tsx` — P6 extends this component in place, it does not re-create it), P3 (`notebook`→`project` rename, `workspace`/`owner` columns, `project_member`, `api/routers/projects.py`), P4 (`invitation`, company-workspace-only guard), P5 (`source.owner`/`scope`, `api/source_permissions.py` consuming `PermissionContext`) · **Branch:** feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB call is awaited (no sync DB access).
- All frontend HTTP goes through the single axios `apiClient` (`frontend/src/lib/api/client.ts`) — never a 2nd instance.
- i18n MANDATORY: every UI string via `t('section.key')`; add the key to ALL locale files under `frontend/src/lib/locales/` (the parity test `locales/index.test.ts` checks EVERY locale in `resources`, not just the 7 enforced — a key added to en-US but missing elsewhere FAILS the test; the "Unused Key Detection" test also requires every en-US leaf key be referenced in a source file).
- New SurrealDB schema = new migration pair. **P6 introduces NO migration** (canonical: P1=19, P2=20, P3=21, P4=22, P5=23; P6=none). `AsyncMigrationManager` gains no P6 entry.
- Physical SurrealDB table stays `notebook` (exposed as "project"); domain class `Project` (`table_name = "notebook"`); API `/api/projects`; UI "Project".
- Tokens: identity token (`sub`) vs workspace-scoped access token (`sub`, `workspace_id`, `role`) + refresh cookie. P6 reads `AuthContext(user_id, workspace_id, role)` from P1's `api/security.py`; it does not mint tokens.
- **Uniform scoping, no `kind` branching.** `workspace.kind ∈ {personal, company}` is a product/UI distinction only. Neither `open_notebook/database/scoping.py` nor the P6 additions to `api/deps.py` may read or branch on `kind` — a personal workspace is scoped by the exact same `WHERE workspace = $workspace_id` path as a company workspace. `kind` is inspected ONLY in the frontend (hide invite/manage-members in a personal workspace) and in P4 (403 an invitation into a personal workspace). This is Option A's entire rationale (see spec) and Task 1/Task 5 include structural guards against regressing it.
- Backend tests: `uv run pytest tests/`. Frontend (inside `frontend/`): `npm run lint`, `npm run test`, `npm run build`.
- Backend errors: raise typed exceptions from `open_notebook.exceptions` — global handlers in `api/main.py` map `NotFoundError`→404, `InvalidInputError`→400, `AuthenticationError`→401. Do NOT raise bare `HTTPException` for domain errors from services; the FastAPI dependencies (`require_workspace`/`require_role`) DO raise `HTTPException` (they mirror `arteamis-system/backend/app/api/deps.py`, renamed `tenant_id`→`workspace_id`).

---

## Reference facts (verified against real code — do not re-derive)

- `open_notebook/database/repository.py` exposes async helpers: `repo_query(query_str, vars=None) -> list[dict]`, `repo_create(table, data) -> dict`, `repo_update(table, id, data) -> list[dict]`, `repo_delete(record_id) -> Any`, and `ensure_record_id(value) -> RecordID` (parses `"notebook:abc"` → `RecordID`). `repo_create` auto-sets `created`/`updated`. Record ids come back as strings (via `parse_record_ids`).
- `open_notebook/exceptions.py`: `InvalidInputError` (→400), `NotFoundError` (→404), `OpenNotebookError` base.
- `open_notebook/domain/base.py`: `ObjectModel.get(id)` is polymorphic by id-prefix; `ObjectModel._validate_order_by(order_by)` is the ORDER BY allowlist validator (`InvalidInputError` on bad input).
- `api/security.py` (P1) provides `AuthContext` (dataclass: `user_id: str`, `workspace_id: str | None`, `role: str | None`), `decode_access_token(token) -> AuthContext`, `decode_identity_token(token) -> str`, `create_access_token(user_id, workspace_id, role) -> str`, `create_identity_token(user_id) -> str`.
- `api/deps.py` (P2) already defines `bearer = HTTPBearer()`, `async def get_auth_context(...) -> AuthContext`, `async def get_identity(...) -> str`, and `def require_role(*roles)`. **P6 EDITS this file — it must NOT redefine those three.**
- `api/routers/projects.py` (P3) is the canonical `/projects` router (replaced `notebooks.py`); domain class `Project` (`open_notebook/domain/notebook.py`, `table_name="notebook"`); Pydantic schemas `ProjectCreate`/`ProjectUpdate`/`ProjectResponse` in `api/models.py`. Native `workspace` column lives on `notebook`, `project_member`, `invitation`. `source`/`note`/`chat_session`/`source_insight`/`source_embedding` have NO native `workspace` column — they inherit via parent join. `project_member`/`invitation` rows never exist for a `kind="personal"` workspace (enforced by P3/P4, not by P6's filter).
- `api/main.py` registers exception handlers (`NotFoundError`→404, `InvalidInputError`→400) around line 299–316 and includes routers around line 372+.
- Frontend: `frontend/src/lib/stores/auth-store.ts` is a Zustand `persist` store (localStorage key `auth-storage`). `frontend/src/app/(dashboard)/layout.tsx` is the route guard (redirects unauthenticated → `/login`). `frontend/src/components/layout/AppSidebar.tsx` holds the nav (`Manage` section lines 66–74) and Create dropdown (notebook item lines 219–228). Locales live in `frontend/src/lib/locales/<code>/index.ts`, each exporting a nested object; `frontend/src/lib/locales/index.ts` aggregates them into `resources`. TanStack Query hooks follow the `use-notebooks.ts` pattern: a `<domain>Api` wrapper in `frontend/src/lib/api/<domain>.ts` (default-imports `apiClient` from `./client`), consumed by hooks in `frontend/src/lib/hooks/` keyed via `QUERY_KEYS` in `frontend/src/lib/api/query-client.ts`.
- **P2 already ships the workspace-switching frontend stack** (P2 Tasks 11–13): `frontend/src/lib/api/workspaces.ts` (`workspacesApi.list/create/switch`), `frontend/src/lib/hooks/use-workspaces.ts` (`useWorkspaces`, `useCreateWorkspace`, `useSwitchWorkspace`), and `frontend/src/components/workspace/WorkspaceSwitcher.tsx` (reads `useAuthStore`'s `memberships`/`activeWorkspaceId`, lists Personal first then companies with a role badge, offers "+ Create a company"), already mounted inside `AppSidebar.tsx`. **P6 (Task 10) extends this exact component and reuses these exact files — it does not create a second implementation.**

---

### Task 1: `ScopedRepository` + table-plane policy — `open_notebook/database/scoping.py`

**Files:**
- Create: `open_notebook/database/scoping.py`
- Test: `tests/test_scoping_unit.py`

**Interfaces:**
- Consumes: `repo_query`, `repo_create`, `repo_update`, `repo_delete`, `ensure_record_id` (from `open_notebook/database/repository.py`); `InvalidInputError`, `NotFoundError` (from `open_notebook/exceptions.py`).
- Produces: `GLOBAL_TABLES: frozenset[str]`, `WORKSPACE_SCOPED_TABLES: frozenset[str]`, and `class ScopedRepository` with `__init__(workspace_id: str, user_id: str, role: str | None)` (deliberately **no** `kind` parameter), async `list(table, *, where="", vars=None, order_by=None, limit=None) -> list[dict]`, async `get(record_id) -> dict`, async `exists(record_id) -> bool`, async `create(table, data) -> dict`, async `update(record_id, data) -> list[dict]`, async `delete(record_id) -> bool`, async `raw(query, vars=None) -> list[dict]`.

- [ ] **Step 1: Write the failing test** — `tests/test_scoping_unit.py`. These tests exercise the pure guard logic (no DB): `_assert_scoped` via the public methods on global/unknown tables, that `list`/`get` build the correct scoped query (repo layer patched), AND a structural guard that the isolation layer has no personal/company branching.

```python
# tests/test_scoping_unit.py
"""Unit tests for ScopedRepository guard logic (no live DB — repo_* patched)."""
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.database.scoping import (
    GLOBAL_TABLES,
    WORKSPACE_SCOPED_TABLES,
    ScopedRepository,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError


def _repo() -> ScopedRepository:
    return ScopedRepository(workspace_id="workspace:A", user_id="user:1", role="owner")


def test_policy_sets_are_disjoint_and_cover_expected_tables():
    assert GLOBAL_TABLES.isdisjoint(WORKSPACE_SCOPED_TABLES)
    assert {"user", "auth_identity", "workspace", "membership"} <= GLOBAL_TABLES
    assert {
        "notebook", "source", "note", "chat_session",
        "source_insight", "source_embedding", "project_member", "invitation",
    } <= WORKSPACE_SCOPED_TABLES


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
async def test_list_ands_workspace_filter_onto_caller_predicate():
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(return_value=[])) as q:
        await _repo().list("notebook", where="archived = false", order_by="updated desc")
    query, params = q.call_args[0]
    assert "workspace = $workspace_id" in query
    assert "(archived = false)" in query
    assert " AND " in query  # caller predicate AND-ed, never replaces the scope
    assert "ORDER BY updated desc" in query
    assert str(params["workspace_id"]) == "workspace:A"


@pytest.mark.asyncio
async def test_get_filters_by_workspace_and_404s_on_empty():
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(return_value=[])) as q:
        with pytest.raises(NotFoundError):
            await _repo().get("notebook:guessed")
    query, params = q.call_args[0]
    assert "workspace = $workspace_id" in query
    assert str(params["rid"]) == "notebook:guessed"


@pytest.mark.asyncio
async def test_create_stamps_workspace_and_overwrites_client_value():
    async def _fake_create(table, data):
        return {"id": f"{table}:new", **data}
    with patch("open_notebook.database.scoping.repo_create", new=AsyncMock(side_effect=_fake_create)) as c:
        await _repo().create("notebook", {"name": "x", "workspace": "workspace:EVIL"})
    _table, data = c.call_args[0]
    assert str(data["workspace"]) == "workspace:A"  # server-set, client value discarded


@pytest.mark.asyncio
async def test_update_strips_workspace_and_ownership_checks_first():
    calls = {"n": 0}
    async def _fake_query(q, params=None):
        calls["n"] += 1
        return [{"id": "notebook:1", "workspace": "workspace:A"}]  # get() ownership check passes
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(side_effect=_fake_query)), \
         patch("open_notebook.database.scoping.repo_update", new=AsyncMock(return_value=[{"id": "notebook:1"}])) as u:
        await _repo().update("notebook:1", {"name": "y", "workspace": "workspace:EVIL"})
    _table, _id, data = u.call_args[0]
    assert "workspace" not in data  # workspace immutable post-create
    assert calls["n"] == 1  # get() ran before update


def test_scoped_repository_has_no_kind_parameter():
    """Structural guard for Option A's uniformity: the isolation layer must never
    branch on workspace.kind. If a future change adds a `kind` param or the
    literal strings "personal"/"company" to this module, that's a regression —
    fail loudly here rather than discovering it via a leaked personal workspace."""
    sig = inspect.signature(ScopedRepository.__init__)
    assert "kind" not in sig.parameters

    src = Path(inspect.getfile(ScopedRepository)).read_text(encoding="utf-8")
    # Comments are allowed to explain the invariant (this test's own docstring
    # references the words); the PRODUCTION module must not contain the
    # branching literals as quoted strings.
    assert '"personal"' not in src
    assert '"company"' not in src
    assert "'personal'" not in src
    assert "'company'" not in src
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_scoping_unit.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'open_notebook.database.scoping'`.

- [ ] **Step 3: Write minimal implementation** — `open_notebook/database/scoping.py`:

```python
# open_notebook/database/scoping.py
"""Application-layer tenant scoping (the SurrealDB analogue of Postgres RLS).

SurrealDB has no row-level security, so tenant isolation is enforced here. A
ScopedRepository is constructed once per request from the caller's access-token
workspace_id (via api.deps.get_request_context) and is the ONLY sanctioned entry
point for reads/writes/deletes against workspace-scoped tables. Every read AND-s
`WHERE workspace = $workspace_id`; every write stamps `workspace`; a guessed
cross-workspace id resolves to NotFoundError (404) — never the other workspace's
row.

Uniform scoping (Option A): a workspace is either kind="personal" (a solo
tenant) or kind="company" (a multi-member tenant). This module NEVER reads or
branches on `kind` — it only ever sees a workspace_id. That is deliberate: one
code path covers both, so there is exactly one leak surface to test, not two.
See tests/test_scoping_unit.py::test_scoped_repository_has_no_kind_parameter
for the structural guard.
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
# Identity plane — GLOBAL, never workspace-scoped. Login/workspace selection
# must read these BEFORE a workspace is active, so they can never carry a
# workspace filter. `workspace` itself is global (you don't scope a workspace
# row BY a workspace_id — that's circular); `membership` resolves which
# workspaces a user can see, via P2's own non-scoped endpoints.
GLOBAL_TABLES: frozenset[str] = frozenset(
    {"user", "auth_identity", "workspace", "membership"}
)

# Tenant/content plane — every row belongs to exactly one workspace (personal OR
# company — the filter is identical either way) and MUST be filtered by
# workspace_id on every read/write/delete. NOTE: the project table is
# PHYSICALLY named `notebook` (P3 repurpose-in-place, exposed as "project" at
# the API/UI); record ids are `notebook:<id>` and ScopedRepository derives the
# table from that prefix. `notebook`, `project_member`, `invitation` carry a
# NATIVE `workspace` column (`project_member`/`invitation` rows simply never
# exist for a personal workspace — a data-shape fact enforced by P3/P4
# upstream, not by this filter). `source`, `note`, `chat_session`,
# `source_insight`, `source_embedding` inherit workspace via their parent
# project/source and are scoped through a parent join via `raw()` (see spec
# "Data model changes").
WORKSPACE_SCOPED_TABLES: frozenset[str] = frozenset(
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
    if table not in WORKSPACE_SCOPED_TABLES:
        raise InvalidInputError(
            f"Unknown table {table!r}; add it to WORKSPACE_SCOPED_TABLES or GLOBAL_TABLES"
        )


class ScopedRepository:
    """Workspace-scoped view over the SurrealDB repo_* helpers — uniform for a
    personal workspace (solo tenant) and a company workspace (multi-member
    tenant) alike. There is deliberately NO `kind` constructor argument: this
    class cannot distinguish personal from company even if asked to.

    Construct once per request via api.deps.get_request_context. Every method
    injects the workspace filter; there is no method that touches a scoped
    table without it. `raw()` is the audited escape hatch.
    """

    def __init__(self, workspace_id: str, user_id: str, role: Optional[str]):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.role = role

    @property
    def _workspace_rid(self):
        return ensure_record_id(self.workspace_id)

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
        clauses = ["workspace = $workspace_id"]
        if where:
            clauses.append(f"({where})")  # caller predicate AND-ed, never replaces the scope
        q = f"SELECT * FROM {table} WHERE {' AND '.join(clauses)}"
        if order_by:
            q += f" ORDER BY {order_by}"  # caller MUST pre-validate via ObjectModel._validate_order_by
        if limit is not None:
            q += " LIMIT $limit"
        params: dict[str, Any] = {"workspace_id": self._workspace_rid, **(vars or {})}
        if limit is not None:
            params["limit"] = limit
        return await repo_query(q, params)

    async def get(self, record_id: str) -> dict:
        """Fetch one row by id AND workspace. A cross-workspace id → NotFoundError
        (404), deliberately indistinguishable from a genuinely missing id (no
        oracle) — including when the "other" workspace is a different user's
        personal workspace."""
        table = _table_of(record_id)
        _assert_scoped(table)
        rows = await repo_query(
            "SELECT * FROM $rid WHERE workspace = $workspace_id",
            {"rid": ensure_record_id(record_id), "workspace_id": self._workspace_rid},
        )
        if not rows:
            logger.warning(
                f"Scoped get miss: record_id={record_id} workspace_id={self.workspace_id} "
                f"user_id={self.user_id} (missing or cross-workspace)"
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
        data = {**data, "workspace": self._workspace_rid}  # server-set; client workspace overwritten
        return await repo_create(table, data)

    async def update(self, record_id: str, data: dict) -> list[dict]:
        table = _table_of(record_id)
        _assert_scoped(table)
        await self.get(record_id)  # ownership check first → 404 on cross-workspace
        data = {k: v for k, v in data.items() if k != "workspace"}  # workspace immutable post-create
        return await repo_update(table, record_id, data)

    async def delete(self, record_id: str) -> bool:
        table = _table_of(record_id)
        _assert_scoped(table)
        await self.get(record_id)  # ownership check first → 404 on cross-workspace
        await repo_delete(record_id)
        return True

    # ---- raw escape hatch (AUDITED) ----------------------------------------
    async def raw(self, query: str, vars: Optional[dict] = None) -> list[dict]:
        """For multi-table joins the helpers can't express (e.g. count(<-reference.in)).
        The caller MUST include `workspace = $workspace_id` in the query themselves;
        $workspace_id is always injected into vars. Every call site needs a
        `# scoped-raw: <reason>` comment and its own leakage test."""
        params = {"workspace_id": self._workspace_rid, **(vars or {})}
        return await repo_query(query, params)
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_scoping_unit.py -q` — Expected: PASS (9 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/database/scoping.py tests/test_scoping_unit.py && git commit -m "P6: ScopedRepository + table-plane policy (uniform app-layer tenant scoping)"`

---

### Task 2: Extend `api/deps.py` — `require_workspace`, `get_request_context`, `PermissionContext`

**Files:**
- Modify: `api/deps.py` (P2 file — ADD to it; do NOT redefine `get_identity`/`get_auth_context`/`require_role`)
- Test: `tests/test_deps_context.py`

**Interfaces:**
- Consumes: `AuthContext`, `decode_access_token`, `decode_identity_token` (`api/security.py`); `ScopedRepository` (Task 1); `repo_query`, `ensure_record_id` (`open_notebook/database/repository.py`).
- Produces (all NEW, added alongside P2's existing symbols): `require_workspace(auth) -> AuthContext`, async `get_request_context(auth) -> ScopedRepository`, `AuthDep = Annotated[AuthContext, Depends(require_workspace)]`, `CtxDep = Annotated[ScopedRepository, Depends(get_request_context)]`; dataclass `PermissionContext(user_id, workspace_id, workspace_role)` with async `project_role(project_id) -> "admin"|"member"|None`; async `get_permission_context(auth) -> PermissionContext`; `PermCtxDep = Annotated[PermissionContext, Depends(get_permission_context)]`.

- [ ] **Step 1: Write the failing test** — `tests/test_deps_context.py`:

```python
# tests/test_deps_context.py
"""Unit tests for P6 additions to api/deps.py: require_workspace, get_request_context,
and PermissionContext.project_role (repo_query patched — no live DB)."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api.deps import (
    PermissionContext,
    get_permission_context,
    get_request_context,
    require_workspace,
)
from api.security import AuthContext
from open_notebook.database.scoping import ScopedRepository


def _auth(workspace_id="workspace:A", role="owner"):
    return AuthContext(user_id="user:1", workspace_id=workspace_id, role=role)


def test_require_workspace_passes_with_active_workspace():
    assert require_workspace(_auth()) is not None


def test_require_workspace_403_without_workspace():
    with pytest.raises(HTTPException) as exc:
        require_workspace(_auth(workspace_id=None, role=None))
    assert exc.value.status_code == 403
    assert "No active workspace" in exc.value.detail


@pytest.mark.asyncio
async def test_get_request_context_returns_bound_scoped_repository():
    repo = await get_request_context(_auth())
    assert isinstance(repo, ScopedRepository)
    assert repo.workspace_id == "workspace:A"
    assert repo.user_id == "user:1"
    assert repo.role == "owner"


@pytest.mark.asyncio
async def test_project_role_escalates_workspace_owner_admin_to_project_admin():
    ctx = PermissionContext(user_id="user:1", workspace_id="workspace:A", workspace_role="admin")
    # No project_member query should be needed for workspace admin — returns "admin".
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])) as q:
        assert await ctx.project_role("notebook:p1") == "admin"
    q.assert_not_called()


@pytest.mark.asyncio
async def test_project_role_escalates_personal_workspace_owner_with_no_membership_row():
    """A personal workspace's sole member is always workspace_role='owner'. This
    must resolve to project-admin via the SAME escalation path as a company
    owner/admin — with zero project_member rows and zero branching on kind."""
    ctx = PermissionContext(user_id="user:1", workspace_id="workspace:personal-1", workspace_role="owner")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])) as q:
        assert await ctx.project_role("notebook:solo-project") == "admin"
    q.assert_not_called()


@pytest.mark.asyncio
async def test_project_role_reads_project_member_for_plain_member():
    ctx = PermissionContext(user_id="user:2", workspace_id="workspace:A", workspace_role="member")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[{"role": "member"}])) as q:
        assert await ctx.project_role("notebook:p1") == "member"
    q.assert_called_once()
    query, params = q.call_args[0]
    assert "project_member" in query
    assert "workspace = $workspace" in query  # membership lookup is itself workspace-scoped


@pytest.mark.asyncio
async def test_project_role_none_when_not_a_member():
    ctx = PermissionContext(user_id="user:3", workspace_id="workspace:A", workspace_role="member")
    with patch("api.deps.repo_query", new=AsyncMock(return_value=[])):
        assert await ctx.project_role("notebook:p1") is None


@pytest.mark.asyncio
async def test_get_permission_context_maps_role_to_workspace_role():
    ctx = await get_permission_context(_auth(role="member"))
    assert ctx.workspace_role == "member"
    assert ctx.workspace_id == "workspace:A"
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
# are reused UNCHANGED above — do not redefine them here. None of this code
# reads workspace.kind: a personal-workspace request and a company-workspace
# request are indistinguishable at this layer, by design (Option A).
# ==========================================================================

def require_workspace(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    """Reject a token that carries no active workspace. The 403 gate that
    guarantees ScopedRepository always has a concrete workspace_id to filter
    on. Because signup auto-provisions a personal workspace, this is NOT a
    "has a company" check — it passes for every logged-in user by default,
    personal or company alike."""
    if not auth.workspace_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "No active workspace selected for this request",
        )
    return auth


async def get_request_context(
    auth: Annotated[AuthContext, Depends(require_workspace)],
) -> ScopedRepository:
    """The dependency every workspace-scoped router uses. Hands back a repository
    pre-bound to auth.workspace_id — callers physically cannot query another
    workspace, personal or company alike."""
    return ScopedRepository(
        workspace_id=auth.workspace_id, user_id=auth.user_id, role=auth.role
    )


@dataclass
class PermissionContext:
    """The request-context object P5's can_view_source/can_mutate_source bind to.

    workspace_role is the caller's active-workspace role from the token.
    project_role resolves a caller's role in a specific project via
    project_member, with workspace owner/admin escalating to project 'admin'
    (matches P5's expected semantics). This is ALSO how a personal workspace's
    sole owner resolves to project-admin: they are always workspace_role ==
    "owner", so they escalate without a project_member row ever needing to
    exist (and for personal workspaces, it never does) — one escalation path,
    not two."""

    user_id: str
    workspace_id: str
    workspace_role: str  # owner | admin | member

    async def project_role(self, project_id: str) -> Optional[str]:
        """Return 'admin' | 'member' | None for this caller in `project_id`.
        Workspace owner/admin escalate to project 'admin' without a membership
        row — this covers a personal workspace's sole owner automatically."""
        if self.workspace_role in ("owner", "admin"):
            return "admin"
        rows = await repo_query(
            "SELECT role FROM project_member "
            "WHERE user = $user AND project = $project "
            "AND workspace = $workspace AND status = 'active'",
            {
                "user": ensure_record_id(self.user_id),
                "project": ensure_record_id(project_id),
                "workspace": ensure_record_id(self.workspace_id),
            },
        )
        if rows:
            return rows[0].get("role")
        return None


async def get_permission_context(
    auth: Annotated[AuthContext, Depends(require_workspace)],
) -> PermissionContext:
    """P6's concrete PermissionContext, injected into P5's source-permission routers."""
    return PermissionContext(
        user_id=auth.user_id, workspace_id=auth.workspace_id, workspace_role=auth.role
    )


AuthDep = Annotated[AuthContext, Depends(require_workspace)]
CtxDep = Annotated[ScopedRepository, Depends(get_request_context)]
PermCtxDep = Annotated[PermissionContext, Depends(get_permission_context)]
```

Note: `require_workspace` is a plain (non-async) function — FastAPI supports sync dependencies and the unit test calls it directly. `get_request_context`/`get_permission_context` are async to match the codebase's async-first convention and allow future DB lookups.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_deps_context.py -q` — Expected: PASS (9 passed).

- [ ] **Step 5: Commit** — `git add api/deps.py tests/test_deps_context.py && git commit -m "P6: extend api/deps.py with require_workspace, get_request_context, PermissionContext"`

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
repo_* helpers or ObjectModel.get/save/delete for a workspace-scoped table — it
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


def test_scoping_module_has_no_kind_literals():
    """Belt-and-suspenders alongside test_scoping_unit's reflection test: the
    scoping module's source must never mention "personal"/"company" — those
    words belong in the frontend and in P4's invitation guard, not here."""
    src = (_REPO_ROOT / "open_notebook/database/scoping.py").read_text(encoding="utf-8")
    for token in ('"personal"', "'personal'", '"company"', "'company'"):
        assert token not in src, f"scoping.py must not branch on kind literal {token!r}"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_scoping_contract.py -q` — Expected: FAIL — `test_migrated_scoped_routers_have_no_raw_repo_calls` reports `api/routers/projects.py` still uses `repo_query(`/`Project.get` (the router is migrated in Task 4). If `api/routers/projects.py` does not yet exist on your branch (P3 not landed), the `assert path.exists()` fails first — land P3 before this task. `test_scoping_module_has_no_kind_literals` should already PASS once Task 1 lands (it's a regression guard, not something this task implements).

- [ ] **Step 3: Write minimal implementation** — no implementation file; the router-migration assertion is satisfied by migrating the router in Task 4. This task delivers only the guard. (Keep `test_migrated_scoped_routers_have_no_raw_repo_calls` RED until Task 4 turns it GREEN — do NOT weaken the guard to make it pass early.)

- [ ] **Step 4: Run test, verify current state** — Run: `uv run pytest tests/test_scoping_contract.py -q` — Expected: one FAIL (router migration) now, GREEN after Task 4; `test_scoping_module_has_no_kind_literals` and `test_migrated_modules_all_exist` already PASS. Proceed to Task 4.

- [ ] **Step 5: Commit** — `git add tests/test_scoping_contract.py && git commit -m "P6: grep contract-guard test forbidding raw repo_* + kind-literals in scoped code"`

---

### Task 4: Migrate the project router onto `ScopedRepository` — `api/routers/projects.py`

**Files:**
- Modify: `api/routers/projects.py` (P3 router; grounded in the real `api/routers/notebooks.py` it replaced)
- Test: covered by Task 3 (contract guard) turning GREEN and Task 5 (leakage suite).

**Interfaces:**
- Consumes: `CtxDep`, `require_role` (`api/deps.py`); `ProjectCreate`, `ProjectUpdate`, `ProjectResponse` (`api/models.py`).
- Produces: workspace-scoped `/projects` CRUD. `GET /projects`, `GET /projects/{id}` require an active workspace (`CtxDep`); `POST/PUT/DELETE /projects` additionally require `require_role("owner","admin")`. This is the SAME code path for a personal or a company workspace's `repo.workspace_id` — nothing here checks which kind it is.

This migrates the five endpoints exercised by the leakage suite. Reads AND-in the scope; writes stamp/ownership-check via `ScopedRepository`. The `count(<-reference.in)` join keeps its shape but goes through `repo.raw()` WITH the scope. Replace the endpoints as follows (leave any P3-only helpers like `_stamp_project_view` intact; if P3's file still names it `_stamp_notebook_view`, keep that name):

```python
# api/routers/projects.py  (P6-migrated endpoints)
from typing import Optional

from fastapi import APIRouter, Depends, Query
from loguru import logger

from api.deps import CtxDep, require_role
from api.models import ProjectCreate, ProjectResponse, ProjectUpdate
from open_notebook.database.repository import ensure_record_id
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
        workspace=str(nb.get("workspace", "")),
        owner=str(nb.get("owner", "")),
        default_source_scope=nb.get("default_source_scope", "project"),
    )


@router.get("/projects", response_model=list[ProjectResponse])
async def get_projects(
    repo: CtxDep,
    archived: Optional[bool] = Query(None, description="Filter by archived status"),
    order_by: str = Query("updated desc", description="Order by field and direction"),
):
    """List the active workspace's projects with source/note counts. Identical
    behavior whether `repo.workspace_id` is a personal or a company workspace."""
    validated_order_by = ObjectModel._validate_order_by(order_by)  # allowlist → InvalidInputError (400)
    rows = await repo.raw(
        # scoped-raw: needs count(<-reference.in)/count(<-artifact.in) graph traversal
        "SELECT *, count(<-reference.in) AS source_count, count(<-artifact.in) AS note_count "
        f"FROM notebook WHERE workspace = $workspace_id ORDER BY {validated_order_by}",
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
    """Create a project in the active workspace (owner/admin only — trivially
    satisfied by a personal workspace's sole owner). workspace is stamped
    server-side by ScopedRepository; owner is the caller."""
    created = await repo.create(
        "notebook",
        {
            "name": project.name,
            "description": project.description,
            "owner": repo.user_id,
            "default_source_scope": getattr(project, "default_source_scope", "project"),
            "archived": False,
        },
    )
    # Seed the creator as the sole project admin (mirrors P3 create semantics).
    # For a personal workspace this row exists too — project_member isn't
    # forbidden there, only invitation is; PermissionContext.project_role's
    # owner-escalation makes this row unnecessary for access checks, but P3
    # still writes it for consistency with company-workspace projects.
    await repo.create(
        "project_member",
        {"project": created["id"], "user": repo.user_id, "role": "admin", "status": "active"},
    )
    return _project_response({**created, "source_count": 0, "note_count": 0})


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, repo: CtxDep):
    """Get one project. 404 if not in the caller's workspace (no cross-workspace
    oracle) — including when the "other" workspace is someone else's personal
    workspace."""
    await repo.get(project_id)  # workspace-checked; raises NotFoundError (404) on miss/cross-workspace
    rows = await repo.raw(
        # scoped-raw: needs count(<-reference.in)/count(<-artifact.in) graph traversal
        "SELECT *, count(<-reference.in) AS source_count, count(<-artifact.in) AS note_count "
        "FROM $rid WHERE workspace = $workspace_id",
        {"rid": ensure_record_id(project_id)},
    )
    return _project_response(rows[0])


@router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_update: ProjectUpdate,
    repo: CtxDep,
    _auth=Depends(require_role("owner", "admin")),
):
    """Update a project (owner/admin only). 404 on cross-workspace id."""
    patch = {
        k: v
        for k, v in {
            "name": project_update.name,
            "description": project_update.description,
            "archived": project_update.archived,
            "default_source_scope": getattr(project_update, "default_source_scope", None),
        }.items()
        if v is not None
    }
    if not patch:
        raise InvalidInputError("No updatable fields provided")
    await repo.update(project_id, patch)  # ownership-checked → 404 on cross-workspace
    return await get_project(project_id, repo)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    repo: CtxDep,
    _auth=Depends(require_role("owner", "admin")),
):
    """Delete a project (owner/admin only). 404 on cross-workspace id."""
    await repo.delete(project_id)  # ownership-checked → 404 on cross-workspace
    return {"message": "Project deleted successfully"}
```

Notes:
- If P3's `ProjectResponse` lacks `workspace`/`owner`/`default_source_scope`, they exist per the P3 spec (§ "Add `ProjectResponse` (existing NotebookResponse fields + `workspace`, `owner`, `default_source_scope`)"). If your branch's `ProjectResponse` omits them, drop those three kwargs from `_project_response`.
- `_stamp_project_view` / `last_viewed_at` stamping (P3) may be re-added inside `get_project` after `repo.get(...)`; it uses `repo.raw("UPDATE $rid SET last_viewed_at = time::now() WHERE workspace = $workspace_id", {...})` with a `# scoped-raw:` marker so it stays scoped. Optional for P6.

- [ ] **Step 1: (no new test)** — this task is validated by re-running Task 3's guard and Task 5's leakage suite.

- [ ] **Step 2: Apply the migration** — edit `api/routers/projects.py` to replace the five endpoints as above; add `from open_notebook.database.repository import ensure_record_id` and use it in `get_project`.

- [ ] **Step 3: Run the contract guard** — Run: `uv run pytest tests/test_scoping_contract.py -q` — Expected: PASS (3 passed) — the migrated router no longer contains raw `repo_query(`/`Project.get` outside `.raw(`.

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
test_projects_rls.py + test_X3_suite1_tenant_leakage.py. Proves workspace A can
never read or mutate workspace B's rows, even by guessing record ids — for two
COMPANY workspaces AND for two PERSONAL workspaces belonging to different
users, using the exact same ScopedRepository code path in both cases.

Requires a live SurrealDB (the API's configured DB). Skipped unless
RUN_TENANT_LEAKAGE_DB=1 so `uv run pytest tests/` is green in CI without a DB.
Seeds two company workspaces A/B + a user/membership in each, then drives
/api/projects with each workspace's access token.
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


def _headers(user_id: str, workspace_id: str, role: str = "owner") -> dict:
    tok = create_access_token(user_id=user_id, workspace_id=workspace_id, role=role)
    return {"Authorization": f"Bearer {tok}"}


@pytest_asyncio.fixture
async def seeded():
    """Create two COMPANY workspaces, a user + membership in each, and one
    project in A."""
    tag = uuid.uuid4().hex[:8]
    ua = await repo_create("user", {"email": f"a-{tag}@t.io", "display_name": "A"})
    ub = await repo_create("user", {"email": f"b-{tag}@t.io", "display_name": "B"})
    wa = await repo_create("workspace", {"name": f"A-{tag}", "slug": f"a-{tag}", "kind": "company", "owner": ua["id"]})
    wb = await repo_create("workspace", {"name": f"B-{tag}", "slug": f"b-{tag}", "kind": "company", "owner": ub["id"]})
    await repo_create("membership", {"user": ua["id"], "workspace": wa["id"], "role": "owner", "status": "active"})
    await repo_create("membership", {"user": ub["id"], "workspace": wb["id"], "role": "owner", "status": "active"})
    proj_a = await repo_create(
        "notebook",
        {"name": f"A-proj-{tag}", "description": "secret", "workspace": wa["id"],
         "owner": ua["id"], "default_source_scope": "project", "archived": False},
    )
    data = {
        "user_a": str(ua["id"]), "user_b": str(ub["id"]),
        "workspace_a": str(wa["id"]), "workspace_b": str(wb["id"]),
        "project_a": str(proj_a["id"]),
    }
    yield data
    # teardown — best effort
    for rid in (proj_a["id"], wa["id"], wb["id"], ua["id"], ub["id"]):
        try:
            await repo_delete(rid)
        except Exception:
            pass
    await repo_query("DELETE membership WHERE workspace = $w1 OR workspace = $w2",
                     {"w1": wa["id"], "w2": wb["id"]})


@pytest_asyncio.fixture
async def seeded_personal():
    """Create two PERSONAL workspaces belonging to two different users, each
    with exactly one member (its owner) and one project. Proves the SAME
    ScopedRepository/require_workspace path isolates solo tenants from each
    other with no personal/company special-casing."""
    tag = uuid.uuid4().hex[:8]
    ux = await repo_create("user", {"email": f"x-{tag}@t.io", "display_name": "X"})
    uy = await repo_create("user", {"email": f"y-{tag}@t.io", "display_name": "Y"})
    wx = await repo_create("workspace", {"name": "Personal", "slug": f"x-{tag}", "kind": "personal", "owner": ux["id"]})
    wy = await repo_create("workspace", {"name": "Personal", "slug": f"y-{tag}", "kind": "personal", "owner": uy["id"]})
    await repo_create("membership", {"user": ux["id"], "workspace": wx["id"], "role": "owner", "status": "active"})
    await repo_create("membership", {"user": uy["id"], "workspace": wy["id"], "role": "owner", "status": "active"})
    proj_x = await repo_create(
        "notebook",
        {"name": f"X-solo-project-{tag}", "description": "private notes", "workspace": wx["id"],
         "owner": ux["id"], "default_source_scope": "personal", "archived": False},
    )
    data = {
        "user_x": str(ux["id"]), "user_y": str(uy["id"]),
        "workspace_x": str(wx["id"]), "workspace_y": str(wy["id"]),
        "project_x": str(proj_x["id"]),
    }
    yield data
    for rid in (proj_x["id"], wx["id"], wy["id"], ux["id"], uy["id"]):
        try:
            await repo_delete(rid)
        except Exception:
            pass
    await repo_query("DELETE membership WHERE workspace = $w1 OR workspace = $w2",
                     {"w1": wx["id"], "w2": wy["id"]})


@pytest_asyncio.fixture
async def client():
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_workspace_b_cannot_list_workspace_a_projects(client, seeded):
    r = await client.get("/api/projects", headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()]
    assert seeded["project_a"] not in ids  # A's project absent from B's list


async def test_workspace_a_can_list_own_projects(client, seeded):
    r = await client.get("/api/projects", headers=_headers(seeded["user_a"], seeded["workspace_a"]))
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert seeded["project_a"] in ids


async def test_workspace_b_cannot_get_workspace_a_project_by_guessed_id(client, seeded):
    r = await client.get(f"/api/projects/{seeded['project_a']}",
                         headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 404, r.text  # not 200, not 403 — no existence oracle


async def test_workspace_b_cannot_update_workspace_a_project(client, seeded):
    r = await client.put(f"/api/projects/{seeded['project_a']}",
                         json={"name": "hijacked"},
                         headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 404
    # A re-reads → unchanged (WITH CHECK analogue)
    ra = await client.get(f"/api/projects/{seeded['project_a']}",
                          headers=_headers(seeded["user_a"], seeded["workspace_a"]))
    assert ra.status_code == 200
    assert ra.json()["name"] != "hijacked"


async def test_workspace_b_cannot_delete_workspace_a_project(client, seeded):
    r = await client.delete(f"/api/projects/{seeded['project_a']}",
                            headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 404
    ra = await client.get(f"/api/projects/{seeded['project_a']}",
                          headers=_headers(seeded["user_a"], seeded["workspace_a"]))
    assert ra.status_code == 200  # A still sees it


async def test_create_stamps_callers_workspace_not_client_value(client, seeded):
    # B forges workspace=A in the body; server must stamp B.
    r = await client.post("/api/projects",
                          json={"name": "forge", "workspace": seeded["workspace_a"]},
                          headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 200, r.text
    created_id = r.json()["id"]
    from open_notebook.database.repository import ensure_record_id
    rows = await repo_query("SELECT workspace FROM $rid", {"rid": ensure_record_id(created_id)})
    assert str(rows[0]["workspace"]) == seeded["workspace_b"]  # stamped B, not A
    await repo_delete(created_id)


async def test_missing_workspace_token_is_403(client, seeded):
    from api.security import create_identity_token
    tok = create_identity_token(seeded["user_b"])  # identity token: no workspace_id
    r = await client.get("/api/projects", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert "No active workspace" in r.json()["detail"]


async def test_member_cannot_create_project(client, seeded):
    # A plain member is refused project creation by require_role("owner","admin").
    r = await client.post("/api/projects", json={"name": "nope"},
                          headers=_headers(seeded["user_a"], seeded["workspace_a"], role="member"))
    assert r.status_code == 403
    assert "Requires role" in r.json()["detail"]


async def test_personal_workspace_x_not_visible_to_personal_workspace_y(client, seeded_personal):
    """The uniformity guarantee: user Y (a different user, with their own
    separate personal workspace) cannot list or fetch user X's personal
    project — same 200/404 assertions as the company A/B cases, no special
    personal-workspace code path involved."""
    r_list = await client.get(
        "/api/projects", headers=_headers(seeded_personal["user_y"], seeded_personal["workspace_y"])
    )
    assert r_list.status_code == 200, r_list.text
    assert seeded_personal["project_x"] not in [p["id"] for p in r_list.json()]

    r_get = await client.get(
        f"/api/projects/{seeded_personal['project_x']}",
        headers=_headers(seeded_personal["user_y"], seeded_personal["workspace_y"]),
    )
    assert r_get.status_code == 404, r_get.text  # not 200, not 403 — no existence oracle

    # X still sees their own project in their own personal workspace.
    r_own = await client.get(
        f"/api/projects/{seeded_personal['project_x']}",
        headers=_headers(seeded_personal["user_x"], seeded_personal["workspace_x"]),
    )
    assert r_own.status_code == 200
```

- [ ] **Step 2: Run test, verify it fails (or skips without DB)** — Run: `RUN_TENANT_LEAKAGE_DB=1 uv run pytest tests/test_tenant_leakage.py -q` (SurrealDB must be up: `make database`). Expected before Task 4's router is complete: FAILs on cross-workspace reads. After Task 4: all pass. Without the env var: `uv run pytest tests/test_tenant_leakage.py -q` → SKIPPED.

- [ ] **Step 3: (implementation already done in Tasks 1–4)** — no new production code; this suite is the acceptance test for the backend half of P6.

- [ ] **Step 4: Run test, verify it passes** — Run: `make database && RUN_TENANT_LEAKAGE_DB=1 uv run pytest tests/test_tenant_leakage.py -q` — Expected: PASS (10 passed). Also confirm CI-safe skip: `uv run pytest tests/test_tenant_leakage.py -q` → 10 skipped.

- [ ] **Step 5: Commit** — `git add tests/test_tenant_leakage.py && git commit -m "P6: tenant-leakage suite proving cross-workspace reads/mutations 404, incl. personal-vs-personal"`

---

### Task 6: i18n keys — `roles.*` + `workspace.*` across all locales

**Files:**
- Modify: every locale file under `frontend/src/lib/locales/<code>/index.ts` (the parity test checks ALL locales in `resources`, not only the 7 enforced).
- Test: `frontend/src/lib/locales/index.test.ts` (existing parity + unused-key detection — must stay green).

**Interfaces:**
- Produces the leaf keys consumed by Tasks 7–10: `roles.owner`, `roles.admin`, `roles.member`, `roles.adminOnly`, `roles.noWorkspace`, `roles.accessDenied`, `workspace.manageMembers`. (Every key MUST be referenced in a source file or the unused-key test fails — Tasks 8/9/10 reference all of them.) **Note:** P6 does NOT define `workspace.activeWorkspace`/`workspace.personal`/`workspace.switchWorkspace`/`workspace.switchSuccess`/`workspace.createCompany` — those were only needed by a from-scratch `WorkspaceSwitcher`, which P6 no longer builds (see Task 10: it extends P2's existing component instead). P2 already ships its own equivalent keys under different names (`workspace.personalLabel`, `workspace.switchLabel`, `workspace.switchSuccess`, `workspace.addCompanyCta`, `workspace.roleOwner`/`roleAdmin`/`roleMember`, etc. — see P2's spec) — P6 must not duplicate or shadow them. `workspace.manageMembers` is the ONE new `workspace.*` key this phase adds.

- [ ] **Step 1: Add the keys to en-US** — in `frontend/src/lib/locales/en-US/index.ts`, add a new top-level `roles` object (place it anywhere among the existing top-level sections, e.g. after the `common` block) and ONE new leaf under the `workspace` object P2 already created. Use exactly these leaf keys:

```ts
  roles: {
    owner: "Owner",
    admin: "Admin",
    member: "Member",
    adminOnly: "Only admins can do this",
    noWorkspace: "Select a workspace to continue",
    accessDenied: "You do not have access to this page",
  },
```
and, merged into P2's existing top-level `workspace` object (do not create a second one):
```ts
    manageMembers: "Manage members",
```

- [ ] **Step 2: Add the SAME key set to the 6 other enforced locales** — with these translations:

```ts
// pt-BR
  roles: { owner: "Proprietário", admin: "Administrador", member: "Membro",
    adminOnly: "Somente administradores podem fazer isso",
    noWorkspace: "Selecione um espaço de trabalho para continuar",
    accessDenied: "Você não tem acesso a esta página" },
  workspace: { manageMembers: "Gerenciar membros" },
// zh-CN
  roles: { owner: "所有者", admin: "管理员", member: "成员",
    adminOnly: "只有管理员可以执行此操作",
    noWorkspace: "请选择一个工作区以继续",
    accessDenied: "您无权访问此页面" },
  workspace: { manageMembers: "管理成员" },
// zh-TW
  roles: { owner: "擁有者", admin: "管理員", member: "成員",
    adminOnly: "只有管理員可以執行此操作",
    noWorkspace: "請選擇一個工作區以繼續",
    accessDenied: "您無權存取此頁面" },
  workspace: { manageMembers: "管理成員" },
// ja-JP
  roles: { owner: "オーナー", admin: "管理者", member: "メンバー",
    adminOnly: "この操作は管理者のみ実行できます",
    noWorkspace: "続行するにはワークスペースを選択してください",
    accessDenied: "このページにアクセスする権限がありません" },
  workspace: { manageMembers: "メンバーを管理" },
// ru-RU
  roles: { owner: "Владелец", admin: "Администратор", member: "Участник",
    adminOnly: "Только администраторы могут это делать",
    noWorkspace: "Выберите рабочее пространство, чтобы продолжить",
    accessDenied: "У вас нет доступа к этой странице" },
  workspace: { manageMembers: "Управление участниками" },
// bn-IN
  roles: { owner: "মালিক", admin: "অ্যাডমিন", member: "সদস্য",
    adminOnly: "শুধুমাত্র অ্যাডমিনরা এটি করতে পারেন",
    noWorkspace: "চালিয়ে যেতে একটি ওয়ার্কস্পেস নির্বাচন করুন",
    accessDenied: "আপনার এই পৃষ্ঠায় প্রবেশাধিকার নেই" },
  workspace: { manageMembers: "সদস্য পরিচালনা করুন" },
```
Each `workspace: { manageMembers: ... }` line is merged into that locale's existing P2-created `workspace` object — never a second top-level `workspace` key.

- [ ] **Step 3: Add the key set to the remaining (non-enforced) locales to satisfy strict parity** — `ca-ES`, `de-DE`, `es-ES`, `fr-FR`, `it-IT`, `pl-PL`, `tr-TR`. The parity test requires identical key sets across ALL locales in `resources`. Provide translations if known; otherwise copy the en-US English values verbatim (English fallback is acceptable for non-enforced locales and keeps parity green). Use the exact same `roles`/`workspace.manageMembers` leaf keys as Step 1.

- [ ] **Step 4: Run the locale tests** — Run (inside `frontend/`): `npm run test -- src/lib/locales/index.test.ts` — Expected: PASS for parity. The "Unused Key Detection" test may still report `roles.*`/`workspace.manageMembers` as unused UNTIL Tasks 8/9/10 reference them — run the full locale test again after Task 10. (If executing tasks strictly in order, expect this one unused-key assertion to be RED between Task 6 and Task 10; that is intended.)

- [ ] **Step 5: Commit** — `git add frontend/src/lib/locales && git commit -m "P6: add roles.* + workspace.* i18n keys across all locales"`

---

### Task 7: Auth-store workspace/role fields + `useRole()` hook

**Files:**
- Modify: `frontend/src/lib/stores/auth-store.ts`
- Create: `frontend/src/lib/hooks/use-role.ts`
- Test: `frontend/src/lib/hooks/use-role.test.ts`

**Interfaces:**
- **Naming note (P2 collision avoided):** P2 (Task 10) already put `role: string | null`, `activeWorkspaceId: string | null`, `memberships: Membership[]`, and an action `setActiveWorkspace(workspaceId: string, role: string) => void` on this same store. P6 reuses P2's `role` field as-is (just narrows its TS type below) and does **not** reuse the name `activeWorkspaceId` or the name `setActiveWorkspace` for the new pieces below, to avoid two incompatible things sharing one identifier. P6 adds two NEW fields (`workspaceName`, `workspaceKind`) that mirror data already present per-row in P2's `memberships[]` (each row carries `name`/`kind`) for the active workspace, kept as a flat convenience view `useRole()`/`RoleGate`/`AppSidebar` read directly rather than re-deriving from the array on every render; the new setter is named `setWorkspaceContext` (not `setActiveWorkspace`) for exactly this reason. **Residual (flagged, not resolved in this pass):** P2's own `setActiveWorkspace`/`applyToken` call sites (Tasks 10/11/13/14) do not call `setWorkspaceContext`, so `workspaceName`/`workspaceKind` are only populated once something calls the new setter; wiring `setWorkspaceContext` into P2's switch/create success handlers (or deriving these two fields from `memberships`/`activeWorkspaceId` inside `useRole()` instead of storing them) is out of scope for this reconciliation pass and should be revisited before this phase ships.
- Produces on the store: `workspaceName: string | null`, `workspaceKind: 'personal' | 'company' | null`, `role: 'owner' | 'admin' | 'member' | null` (P2's field, retyped), `setWorkspaceContext(args: { workspaceName: string | null; workspaceKind: WorkspaceKind | null; role: WorkspaceRole | null }) => void`; all three (`workspaceName`/`workspaceKind`/`role`) persisted via `partialize`. `workspaceId` for `useRole()` (below) reads P2's existing `activeWorkspaceId` field directly — no new id field is added.
- Produces the hook: `useRole()` → `{ role, workspaceId, workspaceName, workspaceKind, isOwner, isAdmin, isMember, isPersonalWorkspace, isCompanyWorkspace, can(...roles: WorkspaceRole[]): boolean }` (`workspaceId` sourced from P2's `activeWorkspaceId`); and `type WorkspaceRole = 'owner' | 'admin' | 'member'`, `type WorkspaceKind = 'personal' | 'company'`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/hooks/use-role.test.ts`:

```ts
// frontend/src/lib/hooks/use-role.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRole } from './use-role'
import { useAuthStore } from '@/lib/stores/auth-store'

function setRole(role: 'owner' | 'admin' | 'member' | null, kind: 'personal' | 'company' | null = 'company') {
  useAuthStore.setState({
    activeWorkspaceId: role ? 'workspace:A' : null, // P2's existing field, not a new one
    workspaceName: role ? 'Acme' : null,
    workspaceKind: role ? kind : null,
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

  it('no role → nothing granted, workspace null', () => {
    const { result } = renderHook(() => useRole())
    expect(result.current.role).toBeNull()
    expect(result.current.workspaceId).toBeNull()
    expect(result.current.isAdmin).toBe(false)
    expect(result.current.can('member')).toBe(false)
  })

  it('surfaces workspaceName', () => {
    setRole('owner')
    const { result } = renderHook(() => useRole())
    expect(result.current.workspaceName).toBe('Acme')
  })

  it('a personal workspace owner is isPersonalWorkspace, not isCompanyWorkspace', () => {
    setRole('owner', 'personal')
    const { result } = renderHook(() => useRole())
    expect(result.current.isPersonalWorkspace).toBe(true)
    expect(result.current.isCompanyWorkspace).toBe(false)
  })

  it('a company workspace member is isCompanyWorkspace, not isPersonalWorkspace', () => {
    setRole('member', 'company')
    const { result } = renderHook(() => useRole())
    expect(result.current.isCompanyWorkspace).toBe(true)
    expect(result.current.isPersonalWorkspace).toBe(false)
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/lib/hooks/use-role.test.ts` — Expected: FAIL — `Cannot find module './use-role'`.

- [ ] **Step 3a: Extend the auth store** — in `frontend/src/lib/stores/auth-store.ts`. P2 already defined `role: string | null`, `activeWorkspaceId: string | null`, and `memberships: Membership[]` here (Task 10) — do not redeclare `activeWorkspaceId` and do not add a second `workspaceId` field:
  1. Add to the `AuthState` interface (only the two NEW fields + the new, distinctly-named setter):
     ```ts
     workspaceName: string | null
     workspaceKind: 'personal' | 'company' | null
     setWorkspaceContext: (args: {
       workspaceName: string | null
       workspaceKind: 'personal' | 'company' | null
       role: 'owner' | 'admin' | 'member' | null
     }) => void
     ```
     (`role`'s type may be narrowed from P2's `string | null` to `'owner' | 'admin' | 'member' | null` here; it is the same field, not a new one.)
  2. Add to the initial state object (next to `activeWorkspaceId: null` / `role: null`):
     ```ts
     workspaceName: null,
     workspaceKind: null,
     ```
  3. Add the action inside the store body (next to P2's `setActiveWorkspace`/`setHasHydrated`) —
     deliberately named `setWorkspaceContext`, NOT `setActiveWorkspace`, so it cannot collide with
     or silently override P2's existing action of that name (which has a different, positional
     `(workspaceId, role)` signature and is still the one that changes the active workspace id and
     token; this action only updates the two display fields + the shared `role`):
     ```ts
     setWorkspaceContext: ({ workspaceName, workspaceKind, role }) => {
       set({ workspaceName, workspaceKind, role })
     },
     ```
  4. Extend `partialize` (the object it returns) to persist the two new fields alongside the existing ones:
     ```ts
     partialize: (state) => ({
       // ...existing persisted fields (token, activeWorkspaceId, memberships, role, etc.) stay here...
       workspaceName: state.workspaceName,
       workspaceKind: state.workspaceKind,
     }),
     ```
     Only ADD `workspaceName`/`workspaceKind` — do not remove or rename anything P2 already persists.

- [ ] **Step 3b: Create the hook** — `frontend/src/lib/hooks/use-role.ts`:

```ts
// frontend/src/lib/hooks/use-role.ts
'use client'

import { useAuthStore } from '@/lib/stores/auth-store'

export type WorkspaceRole = 'owner' | 'admin' | 'member'
export type WorkspaceKind = 'personal' | 'company'

export function useRole() {
  const role = useAuthStore((s) => s.role) as WorkspaceRole | null
  const workspaceId = useAuthStore((s) => s.activeWorkspaceId) // P2's field, not a new one
  const workspaceName = useAuthStore((s) => s.workspaceName)
  const workspaceKind = useAuthStore((s) => s.workspaceKind)

  const can = (...roles: WorkspaceRole[]) => !!role && roles.includes(role)

  return {
    role,
    workspaceId,
    workspaceName,
    workspaceKind,
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin', // owner ⊇ admin
    isMember: role === 'member',
    isPersonalWorkspace: workspaceKind === 'personal',
    isCompanyWorkspace: workspaceKind === 'company',
    can, // can('owner', 'admin')
  }
}
```

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/lib/hooks/use-role.test.ts` — Expected: PASS (7 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/stores/auth-store.ts frontend/src/lib/hooks/use-role.ts frontend/src/lib/hooks/use-role.test.ts && git commit -m "P6: auth-store workspace/role fields + useRole hook"`

---

### Task 8: `<RoleGate>` component

**Files:**
- Create: `frontend/src/components/common/RoleGate.tsx`
- Test: `frontend/src/components/common/RoleGate.test.tsx`

**Interfaces:**
- Consumes: `useRole()` (Task 7), `useTranslation()` (`@/lib/hooks/use-translation`).
- Produces: `RoleGate({ allow, mode = 'hide', requireCompanyWorkspace = false, children })` where `allow: WorkspaceRole[]`, `mode: 'hide' | 'disable'`, `requireCompanyWorkspace: boolean`. `hide` → renders `null` when not allowed; `disable` → renders children inside an `aria-disabled`, `pointer-events-none`, dimmed span with `title={t('roles.adminOnly')}`. `requireCompanyWorkspace` additionally hides content for a personal workspace regardless of role (invite/manage-members has no meaning for a solo tenant).

- [ ] **Step 1: Write the failing test** — `frontend/src/components/common/RoleGate.test.tsx`:

```tsx
// frontend/src/components/common/RoleGate.test.tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RoleGate } from './RoleGate'
import { useAuthStore } from '@/lib/stores/auth-store'

function setRole(role: 'owner' | 'admin' | 'member' | null, kind: 'personal' | 'company' = 'company') {
  useAuthStore.setState({ role, activeWorkspaceId: 'workspace:A', workspaceName: 'Acme', workspaceKind: kind } as never)
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

  it('requireCompanyWorkspace hides for a personal-workspace owner even though role passes', () => {
    setRole('owner', 'personal')
    render(
      <RoleGate allow={['owner', 'admin']} requireCompanyWorkspace>
        <button>Invite</button>
      </RoleGate>,
    )
    expect(screen.queryByText('Invite')).toBeNull()
  })

  it('requireCompanyWorkspace renders for a company-workspace admin', () => {
    setRole('admin', 'company')
    render(
      <RoleGate allow={['owner', 'admin']} requireCompanyWorkspace>
        <button>Invite</button>
      </RoleGate>,
    )
    expect(screen.getByText('Invite')).toBeDefined()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/components/common/RoleGate.test.tsx` — Expected: FAIL — `Cannot find module './RoleGate'`.

- [ ] **Step 3: Write the component** — `frontend/src/components/common/RoleGate.tsx`:

```tsx
// frontend/src/components/common/RoleGate.tsx
'use client'

import type { ReactNode } from 'react'
import { useRole, type WorkspaceRole } from '@/lib/hooks/use-role'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RoleGate({
  allow,
  mode = 'hide',
  requireCompanyWorkspace = false,
  children,
}: {
  allow: WorkspaceRole[]
  mode?: 'hide' | 'disable'
  requireCompanyWorkspace?: boolean
  children: ReactNode
}) {
  const { can, isCompanyWorkspace } = useRole()
  const { t } = useTranslation()

  const allowed = can(...allow) && (!requireCompanyWorkspace || isCompanyWorkspace)

  if (allowed) return <>{children}</>
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

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- src/components/common/RoleGate.test.tsx` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/common/RoleGate.tsx frontend/src/components/common/RoleGate.test.tsx && git commit -m "P6: RoleGate component (hide/disable admin-only + company-only UI)"`

---

### Task 9: Dashboard route guard + `<RequireRole>` + AppSidebar role gating

**Files:**
- Create: `frontend/src/components/common/RequireRole.tsx`
- Modify: `frontend/src/app/(dashboard)/layout.tsx`
- Modify: `frontend/src/components/layout/AppSidebar.tsx`
- Test: `frontend/src/components/layout/AppSidebar.test.tsx` (extend existing)

**Interfaces:**
- Consumes: `useRole()` (Task 7), `RoleGate` (Task 8), `useRouter`/`usePathname` (`next/navigation`), `useToast` (`@/lib/hooks/use-toast`), `useTranslation`.
- Produces: `RequireRole({ allow, children })` — thin client-side redirect to `/notebooks` + `t('roles.accessDenied')` toast on deny; the dashboard layout redirect to `/onboarding` when authenticated but `workspaceId == null`; the sidebar's `Manage` section gated to owner/admin, "manage members"/invite items additionally gated to company workspaces, and the Create→Notebook item gated to owner/admin. The active-workspace name + role pill are already rendered by P2's `WorkspaceSwitcher` (Task 13), already mounted — Task 10 extends that same component with role-gating, it does not build a new trigger.

- [ ] **Step 1: Write/extend the failing test** — append to `frontend/src/components/layout/AppSidebar.test.tsx` (keep the existing tests and the Tooltip mock at the top; add a mock for `useRole` and role/kind-based cases). Add:

```tsx
// --- append to frontend/src/components/layout/AppSidebar.test.tsx ---
import { useRole } from '@/lib/hooks/use-role'

vi.mock('@/lib/hooks/use-role', () => ({
  useRole: vi.fn(),
}))

function mockRole(role: 'owner' | 'admin' | 'member', kind: 'personal' | 'company' = 'company') {
  vi.mocked(useRole).mockReturnValue({
    role,
    workspaceId: 'workspace:A',
    workspaceName: 'Acme',
    workspaceKind: kind,
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin',
    isMember: role === 'member',
    isPersonalWorkspace: kind === 'personal',
    isCompanyWorkspace: kind === 'company',
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

  it('a personal-workspace owner does not see manage-members/invite entries', () => {
    mockRole('owner', 'personal')
    render(<AppSidebar />)
    expect(screen.queryByText('navigation.manageMembers')).toBeNull()
  })

  it('a company-workspace admin sees manage-members/invite entries', () => {
    mockRole('admin', 'company')
    render(<AppSidebar />)
    expect(screen.getByText('navigation.manageMembers')).toBeDefined()
  })
})
```

Note: the existing `AppSidebar` tests render without mocking `useRole`; add a `beforeEach(() => mockRole('owner'))` inside the ORIGINAL `describe('AppSidebar', ...)` block too, so those legacy tests still see a Manage section. (If they don't assert on Manage, no change needed beyond the mock returning a value — `vi.mock` hoists, so provide a default: add `mockRole('owner')` in a top-level `beforeEach`.) The `navigation.manageMembers` label is a P2/P4-introduced nav item; if it does not yet exist on your branch, gate whatever the equivalent "invite/manage members" nav entry is named there instead — the assertion pattern is what matters.

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/components/layout/AppSidebar.test.tsx` — Expected: FAIL — member case still shows `navigation.manage` (not yet gated), the personal-workspace case still shows manage-members, and/or `useRole` undefined return.

- [ ] **Step 3a: Create `RequireRole`** — `frontend/src/components/common/RequireRole.tsx`:

```tsx
// frontend/src/components/common/RequireRole.tsx
'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import type { ReactNode } from 'react'
import { useRole, type WorkspaceRole } from '@/lib/hooks/use-role'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RequireRole({
  allow,
  children,
}: {
  allow: WorkspaceRole[]
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

- [ ] **Step 3b: Extend the dashboard route guard** — `frontend/src/app/(dashboard)/layout.tsx`. Add `useRole` and a workspace-redirect. Insert after the existing unauthenticated redirect logic (inside the same `useEffect`, guarded by `isAuthenticated`):

```tsx
// add import
import { useRole } from '@/lib/hooks/use-role'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

// inside the component, near the top:
const { workspaceId } = useRole()
const { toast } = useToast()
const { t } = useTranslation()

// inside the existing useEffect, AFTER the `if (!isAuthenticated) { ... }` block,
// add an else-branch that requires an active workspace. Because signup
// auto-provisions a personal workspace, this should be unreachable in normal
// operation — it is a defense-in-depth backstop, not the primary "has a
// company" gate (there is no such gate; every workspace, personal or
// company, satisfies this check):
if (isAuthenticated && workspaceId == null) {
  toast({ title: t('roles.noWorkspace') })
  router.push('/onboarding')
}
```

Add `workspaceId`, `toast`, `t` to the `useEffect` dependency array. This keeps a user without an active workspace out of scoped screens before a scoped API call can 403.

- [ ] **Step 3c: Gate the sidebar** — `frontend/src/components/layout/AppSidebar.tsx`:
  1. Import the gate and role hook at the top:
     ```tsx
     import { RoleGate } from '@/components/common/RoleGate'
     import { useRole } from '@/lib/hooks/use-role'
     ```
  2. Inside `AppSidebar`, add `const { role } = useRole()` (kept for the Manage-section check below). The workspace name/role pill are already rendered by P2's `<WorkspaceSwitcher />` (Task 13), already mounted here — Task 10 extends that existing component in place with role-gating; it does not move or re-render anything new into this file.
  3. Wrap the entire `Manage` nav section so members don't see it. The nav is data-driven (`getNavigation(t)`); the `Manage` section has `title: t('navigation.manage')`. In the `navigation.map(...)` render, gate that one section:
     ```tsx
     {navigation.map((section, index) => {
       const sectionNode = (
         <div key={section.title}>
           {/* ...existing section body unchanged... */}
         </div>
       )
       // Manage is owner/admin-only (true in a personal workspace too, since its
       // sole member is always "owner" — this is a role gate, not a kind gate).
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
  4. If the nav has a distinct "Manage members" / invite entry (from P2/P4), gate it with BOTH the role and the company-workspace requirement, since it has no meaning for a solo tenant:
     ```tsx
     <RoleGate allow={['owner', 'admin']} requireCompanyWorkspace>
       {/* existing "Manage members" / invite nav item, unchanged */}
     </RoleGate>
     ```
  5. Gate the Create → Notebook item (the `DropdownMenuItem` calling `handleCreateSelection('notebook')`, lines ~219–228) with `<RoleGate allow={['owner','admin']}>` — **no** `requireCompanyWorkspace`, because a personal workspace's owner must still be able to create projects freely:
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
  6. P2 (Task 13) already replaced the old static app-name/logo text block with `{!isCollapsed && <WorkspaceSwitcher />}` (imported from `@/components/workspace/WorkspaceSwitcher`) and mounted it here. If both the static block and the switcher are still present on your branch (e.g. P2 landed as an addition rather than a replacement), remove the leftover static text now — do not introduce a second switcher or a second import path. Task 10 does not mount anything new; it only edits the component P2 already mounted.

- [ ] **Step 4: Run tests + lint + build** — Run (inside `frontend/`):
  - `npm run test -- src/components/layout/AppSidebar.test.tsx` — Expected: PASS (member hides Manage, admin shows it, personal-workspace owner hides manage-members, company-workspace admin shows it). `WorkspaceSwitcher` (P2's component, at `@/components/workspace/WorkspaceSwitcher`) is already implemented and mounted by the time this task runs, so its render is exercised directly here; its own extended behavior (role-gating) is tested in Task 10.
  - `npm run lint` — Expected: no errors.
  - `npm run build` — Expected: build succeeds (may still show the unused-key locale warning until Task 10 references the remaining `workspace.*` keys — resolved there).

- [ ] **Step 5: Commit** — `git add frontend/src/components/common/RequireRole.tsx frontend/src/app/\(dashboard\)/layout.tsx frontend/src/components/layout/AppSidebar.tsx frontend/src/components/layout/AppSidebar.test.tsx && git commit -m "P6: dashboard route guard, RequireRole, sidebar role + company-only gating"`

---

### Task 10: Extend P2's `WorkspaceSwitcher` with company-only role-gating (no new component)

**Ownership (read once):** `WorkspaceSwitcher` was built and mounted by **P2** (Task 13, `frontend/src/components/workspace/WorkspaceSwitcher.tsx`), driven by `useAuthStore`'s `memberships`/`activeWorkspaceId`, backed by P2's own `frontend/src/lib/api/workspaces.ts` (`workspacesApi`) and `frontend/src/lib/hooks/use-workspaces.ts` (`useWorkspaces`/`useCreateWorkspace`/`useSwitchWorkspace`). **P6 does not re-create any of this** — no second component, no second path (`layout/` vs P2's `workspace/`), no second API wrapper or hooks file. This task only ADDS role-gating to the existing component, using Task 7's `useRole()`/Task 8's `<RoleGate>`.

**Files:**
- Modify: `frontend/src/components/workspace/WorkspaceSwitcher.tsx` (P2's file — edit in place)
- Modify: `frontend/src/components/workspace/WorkspaceSwitcher.test.tsx` (P2's file — extend with the new gating cases)
- No new files.

**Interfaces:**
- Consumes: P2's `WorkspaceSwitcher` as-is (its switching behavior is untouched), P2's `useAuthStore` `memberships`/`activeWorkspaceId` (the store shape P2's component already reads — **not** the separate `workspaceId`/`workspaceName`/`workspaceKind` scalar fields Task 7 adds to the store; those are a parallel derived view `useRole()`/`RoleGate`/`AppSidebar` consume elsewhere, and this task reaches them only indirectly through `<RoleGate>`, never by calling `useRole()` in the switcher itself). `<RoleGate>` (Task 8).
- Produces: the SAME exported `WorkspaceSwitcher`, extended with one `<RoleGate allow={['owner','admin']} requireCompanyWorkspace>`-gated "Manage members" link (→ `/settings/members`, the same admin-only route the P6 route guard already protects) — hidden for a personal workspace regardless of role (a solo tenant has no members to manage) and for a company-workspace `member`.

- [ ] **Step 1: Write/extend the failing test** — append to P2's `frontend/src/components/workspace/WorkspaceSwitcher.test.tsx` (keep the existing `describe('WorkspaceSwitcher', ...)` block and its `beforeEach` exactly as P2 wrote them):

```tsx
// --- append to frontend/src/components/workspace/WorkspaceSwitcher.test.tsx ---
import { RoleGate } from '@/components/common/RoleGate'
import { useRole } from '@/lib/hooks/use-role'

vi.mock('@/lib/hooks/use-role', () => ({ useRole: vi.fn() }))

function mockRole(role: 'owner' | 'admin' | 'member', kind: 'personal' | 'company') {
  vi.mocked(useRole).mockReturnValue({
    role,
    isAdmin: role === 'owner' || role === 'admin',
    isCompanyWorkspace: kind === 'company',
    isPersonalWorkspace: kind === 'personal',
    can: (...roles: Array<'owner' | 'admin' | 'member'>) => roles.includes(role),
  } as unknown as ReturnType<typeof useRole>)
}

describe('WorkspaceSwitcher company-only gating', () => {
  it('shows "Manage members" for a company-workspace admin', () => {
    mockRole('admin', 'company')
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'admin' },
      ],
      activeWorkspaceId: 'workspace:acme',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.getByText('workspace.manageMembers')).toBeDefined()
  })

  it('hides "Manage members" for a personal-workspace owner', () => {
    mockRole('owner', 'personal')
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.queryByText('workspace.manageMembers')).toBeNull()
  })

  it('hides "Manage members" for a company-workspace member', () => {
    mockRole('member', 'company')
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'member' },
      ],
      activeWorkspaceId: 'workspace:acme',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.queryByText('workspace.manageMembers')).toBeNull()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- WorkspaceSwitcher` — Expected: FAIL — `workspace.manageMembers` never renders (P2's component has no such link yet; `useRole`/`RoleGate` are not yet imported there).

- [ ] **Step 3: Extend the component** — in `frontend/src/components/workspace/WorkspaceSwitcher.tsx` (P2's file — add to it, do not touch or restructure the existing switching logic above it):
  1. Add one import: `import { RoleGate } from '@/components/common/RoleGate'`.
  2. Immediately after the `memberships.map(...)` block (and before the "no company yet" banner / "+ Create a company" button P2 already renders), add:
  ```tsx
  <RoleGate allow={['owner', 'admin']} requireCompanyWorkspace>
    <a
      href="/settings/members"
      className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent"
    >
      {t('workspace.manageMembers')}
    </a>
  </RoleGate>
  ```
  `RoleGate`'s `requireCompanyWorkspace` flag (Task 8) is what hides this for a personal workspace's owner, who would otherwise pass the plain `allow={['owner','admin']}` check — this is the concrete instance of the brief's "hide invite/manage members in a personal workspace" guardrail applied to the switcher. `RoleGate` reads `useRole()` (Task 7) internally; the switcher itself does not need to call `useRole()` directly.

- [ ] **Step 4: Run test, verify it passes** — Run (inside `frontend/`): `npm run test -- WorkspaceSwitcher` — Expected: PASS (P2's original 6 cases, unchanged, plus this task's 3 new gating cases).

- [ ] **Step 5: i18n key** — add `workspace.manageMembers` ("Manage members") to all 7 enforced locales under `frontend/src/lib/locales/` (Task 6 already opened the `workspace.*`/`roles.*` block in each locale file for this phase; add this one key alongside it).

- [ ] **Step 6: Run locales + lint + build** — Run (inside `frontend/`):
  - `npm run test -- src/lib/locales/index.test.ts` — Expected: PASS.
  - `npm run lint` — Expected: no errors.
  - `npm run build` — Expected: build succeeds.

- [ ] **Step 7: Commit** — `git add frontend/src/components/workspace/WorkspaceSwitcher.tsx frontend/src/components/workspace/WorkspaceSwitcher.test.tsx frontend/src/lib/locales && git commit -m "P6: extend P2's WorkspaceSwitcher with a company-workspace-only Manage-members link"`

---

## Final verification (run before declaring P6 done)

- [ ] Backend unit + contract (no DB): `uv run pytest tests/test_scoping_unit.py tests/test_deps_context.py tests/test_scoping_contract.py -q` — Expected: all PASS.
- [ ] Backend leakage (live DB): `make database && RUN_TENANT_LEAKAGE_DB=1 uv run pytest tests/test_tenant_leakage.py -q` — Expected: all PASS (including the personal-vs-personal case).
- [ ] Full backend suite stays green (leakage auto-skips without the env var): `uv run pytest tests/ -q`.
- [ ] Lint/type: `ruff check . --fix` and `uv run python -m mypy api/deps.py open_notebook/database/scoping.py`.
- [ ] Frontend: `cd frontend && npm run test && npm run lint && npm run build` — Expected: all PASS (parity + unused-key locale tests green).

---

## Self-review (performed; issues fixed inline)

**1. Spec coverage — every spec section maps to a task:**
- Request-context dependency (`require_workspace`, `get_request_context`, `AuthDep`/`CtxDep`) → Task 2. `get_identity`/`get_auth_context`/`require_role` explicitly NOT redefined (reused from P2) → stated in Task 2 header and code comment.
- `ScopedRepository` + `WORKSPACE_SCOPED_TABLES`/`GLOBAL_TABLES` policy, reads filtered / writes stamped / global refused / cross-workspace 404-no-oracle / audited `raw()`, with NO `kind` parameter and a structural regression guard → Task 1.
- `PermissionContext` (user_id, workspace_id, workspace_role, async `project_role` with workspace owner/admin → project-admin escalation, explicitly covering the personal-workspace-owner case with zero extra code) that P5 consumes → Task 2.
- Router migration to `ScopedRepository` → Task 4 (projects/notebook router; the surface the leakage suite drives; explicitly kind-agnostic).
- Developer contract + grep guard (`test_scoping_contract.py`), including a kind-literal regression guard → Task 3.
- Tenant-leakage suite (`test_tenant_leakage.py`) covering list/get/update/delete/create-stamp/missing-workspace-403/role-403 for two COMPANY workspaces AND two PERSONAL workspaces → Task 5 (maps to spec test cases 1–4, 7, 8, 11; case 9/10/12 unit-guard covered in Task 1; case 5 source-by-id and 6 note/chat are P5-router-owned and follow when those routers migrate — noted below).
- Frontend `useRole()` + auth-store workspace/role/kind fields → Task 7; `<RoleGate>` (+ `requireCompanyWorkspace`) → Task 8; dashboard route guard + `<RequireRole>` + AppSidebar gating → Task 9; `WorkspaceSwitcher` (Personal + companies) — **built and mounted by P2, extended here with company-only role-gating, not re-created** → Task 10; i18n keys across all locales → Task 6.
- Error contract (401/403/404/400) → enforced by `require_workspace`/`require_role` (403), `ScopedRepository.get` (404 via `NotFoundError`→existing handler), `_assert_scoped` (400 via `InvalidInputError`→existing handler); WARNING log on cross-workspace miss included in `ScopedRepository.get`.
- **Uniformity ("one code path" — the whole reason Option A was chosen)** → explicitly enforced, not just asserted: `ScopedRepository.__init__` has no `kind` parameter (Task 1), a reflection test + source-literal grep guard both fail CI if `"personal"`/`"company"` ever appear in `scoping.py` (Task 1 + Task 3), `PermissionContext.project_role`'s escalation path is proven to cover a personal workspace's owner with the identical code as a company owner/admin (Task 2's `test_project_role_escalates_personal_workspace_owner_with_no_membership_row`), and the leakage suite runs the SAME assertions against a personal-vs-personal fixture as the company-vs-company fixture (Task 5).

**Gaps closed / consciously deferred (matches spec "Out of scope"/"Open questions"):**
- Leakage cases 5 (source-by-guessed-id) and 6 (note/chat lists) require the `sources.py`/`notes.py`/`chat.py` routers to be migrated onto `ScopedRepository`/`PermCtxDep` — those routers are P5/P3-owned; P6 supplies the `PermissionContext` + `ScopedRepository` they consume and migrates the project router as the reference migration. Each router adds itself to `MIGRATED_MODULES` (Task 3) and its own leakage test as it migrates. This is the spec's stated shape ("Once P6 lands, P3/P4/P5 routers are migrated to consume it") and is called out in Task 4/Task 5 notes rather than silently dropped.
- Denial audit table → deferred (spec Open questions); P6 logs at WARNING (`ScopedRepository.get`).
- `source_insight`/`source_embedding` denormalized workspace column → not added (P6 owns no migration); scoped via parent join through `raw()` when their routers migrate.
- No P6 migration file; `AsyncMigrationManager` untouched — consistent with Global Constraints.
- Workspace create/switch/onboarding endpoints, and the frontend `workspacesApi`/`useWorkspaces`/`useSwitchWorkspace`/`WorkspaceSwitcher` that consume them, are all P2's; Task 10 adds only a `<RoleGate>`-wrapped "Manage members" link to P2's existing component and does not re-implement or re-specify any of it.

**2. Placeholder scan:** No "TBD/TODO/implement later"; every code block is complete runnable Python/TS with real imports and real paths. The one deliberate RED-until-later state (Task 3's router-migration assertion is RED until Task 4; Task 6's unused-key test RED until Task 10) is explicitly documented, not hidden.

**3. Type consistency:** `AuthContext(user_id, workspace_id, role)` used identically in Tasks 2/5. `ScopedRepository(workspace_id, user_id, role)` signature (no `kind`) consistent across Tasks 1/2. `CtxDep`/`AuthDep`/`PermCtxDep` defined in Task 2, consumed in Task 4. `PermissionContext(user_id, workspace_id, workspace_role)` + `project_role` consistent Task 2 ↔ P5 spec (§ "ctx.workspace_role", "async ctx.project_role"). `WorkspaceRole`/`WorkspaceKind` types + `useRole()` return shape consistent Tasks 7/8/9. Task 10 introduces no new types of its own — it consumes P2's existing `Membership`/`WorkspaceResponse`/`TokenResponse` types (`frontend/src/lib/types/api.ts`) exactly as P2's `WorkspaceSwitcher`/`useWorkspaces`/`useSwitchWorkspace` already do, reached through `<RoleGate>` for the one gated addition. i18n keys defined in Task 6 are exactly those referenced in Tasks 8 (`roles.adminOnly`), 9 (`roles.accessDenied`, `roles.noWorkspace`, `roles.<role>`), and 10 (`workspace.manageMembers`, added alongside P2's own `workspace.*` keys) — no unreferenced key, no undefined reference.
