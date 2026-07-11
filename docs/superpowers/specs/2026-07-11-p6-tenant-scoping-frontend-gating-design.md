# P6 — Multi-tenancy application-layer scoping (replaces Postgres RLS) + frontend role-gating — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft (v2 — workspace model)

## Goal
SurrealDB has no row-level security, so tenant isolation must be enforced in the application
layer. This phase (1) adds a FastAPI request-context dependency that resolves the authenticated
user + active `workspace_id` + role from the access token, (2) adds a centralized scoping
helper / repository wrapper so every query against a workspace-scoped table is automatically
filtered by `workspace_id` — a developer must not be able to forget it, (3) role-gates the
frontend (hide/disable admin-only and company-only actions for members/personal workspaces, add
a dashboard route guard, surface the active workspace + role + a Personal/company switcher in the
UI), and (4) ships a tenant-leakage test suite that proves workspace A can never read or mutate
workspace B's rows, even by guessing record ids — including the case where "workspace B" is
someone else's **personal** workspace. This is the SurrealDB analogue of `arteamis-system`'s
`SET LOCAL app.current_tenant_id` + `USING/WITH CHECK` RLS policy (`arteamis-system/backend/app/core/db.py`,
`test_projects_rls.py`), re-implemented because there is no `SET LOCAL`/policy mechanism to lean on.

### Why ONE code path for personal and company (Option A, restated from the brief)
Per the shared architecture brief's v2 design revision, the tenant entity is a **`workspace`**
with `kind ∈ {personal, company}`. A personal workspace is not a special case of the isolation
layer — it is just a tenant with exactly one member. **`ScopedRepository` and `api/deps.py` never
read or branch on `kind` at all.** They only ever see a `workspace_id`, a `user_id`, and a role.
This is the entire point of choosing Option A over a two-model design (e.g. a separate "no
tenant" path for personal data): a single, small, exhaustively-tested filtering code path covers
100% of scoped reads/writes, for both a solo user's personal notes and a 500-person company's
projects. Two code paths would mean two leak surfaces and two sets of tests to keep in sync
forever; one path, proven once by the leakage suite (including a personal-vs-personal case),
covers both. Concretely:
- `ScopedRepository.__init__(workspace_id, user_id, role)` has **no `kind` parameter** — it is
  structurally incapable of branching on kind.
- `require_workspace`/`get_request_context` in `api/deps.py` don't ask "is this a company?" —
  they only ask "does the token have an active `workspace_id`?". Since signup auto-provisions a
  personal workspace, that is true for every logged-in user by default.
- The only place `kind` is ever inspected is in the **frontend**, to hide company-only UI (invite,
  manage members) that has no meaning in a personal workspace — and in **P4**, to 403 invitation
  creation against a personal workspace. Neither of those is part of the isolation layer itself.

## Depends on / Provides
**Depends on:**
- **P1 (auth):** the JWT layer that mints/decodes tokens. P6 assumes P1 has landed
  `api/security.py` with `AuthContext` (fields `user_id`, `workspace_id: str | None`, `role: str | None`)
  and `decode_access_token()` / `decode_identity_token()` (mirrors `arteamis-system/backend/app/core/security.py`,
  renamed `tenant_id`→`workspace_id`), plus the frontend `auth-store` carrying the decoded token claims.
- **P2 (workspace+membership+roles):** the `workspace`/`membership` tables (workspace has `kind:
  "personal"|"company"`), signup auto-provisioning of a personal workspace, the `/workspaces`
  list/create(kind=company)/`/auth/switch-workspace/{id}` endpoints, and the **`api/deps.py`
  module P2 introduced** — `get_identity`, `get_auth_context`, and the `require_role` factory. P6
  **extends this same file** (adds `require_workspace`, `get_request_context`,
  `PermissionContext`/`get_permission_context` wiring) and **reuses `require_role` unchanged — it
  does not redefine it**. `require_role` semantics (owner|admin|member) baked into the access
  token; for a personal workspace the token's role is always `owner`.
- **P3 (project):** the `notebook`→`project` rename with `workspace` + `owner` columns.
- **P4 (invitation)** and **P5 (source permissions):** the `invitation`, `project_member` tables
  (both **company-workspace-only** — a personal workspace has no rows in either) and
  `source.owner`/`source.scope` columns that P6 must also scope uniformly regardless of the
  owning workspace's kind.

**Provides:**
- Extensions to P2's `api/deps.py`: **new** `require_workspace`, `get_request_context`, and the
  typed aliases (`AuthDep`, `CtxDep`) that every scoped router depends on. (`get_identity`,
  `get_auth_context`, and `require_role` are P2's and are reused unchanged, not redefined.)
- `open_notebook/database/scoping.py`: `ScopedRepository` — the single sanctioned entry point
  for all reads/writes/deletes against workspace-scoped tables, uniform across personal and
  company workspaces. Once P6 lands, P3/P4/P5 routers are migrated to consume it.
- The concrete **`PermissionContext` that P5 declares the shape of** — the request-context object
  P5's `can_view_source`/`can_mutate_source` bind to. P6 supplies its full implementation:
  `user_id`, `workspace_id`, `workspace_role` (= the token's `role`), and an async
  `project_role(project_id) -> "admin"|"member"|None` resolver (via a `project_member` lookup with
  workspace owner/admin → project-admin escalation — which is also how a personal workspace's sole
  owner always resolves to project-admin, with zero extra code). P5 ships a JWT-claims stub of
  this until P6 lands; the two specs keep this interface in sync.
- `WORKSPACE_SCOPED_TABLES` / `GLOBAL_TABLES` policy constants (single source of truth for
  which plane a table lives in).
- Frontend `useRole()` hook, `<RoleGate>` component, and a dashboard route guard. The
  **`WorkspaceSwitcher`** (Personal + each company workspace the user belongs to) is P2's
  component (`frontend/src/components/workspace/WorkspaceSwitcher.tsx`, already mounted in the
  sidebar) — P6 **extends** it with a company-workspace-only "Manage members" affordance via
  `<RoleGate requireCompanyWorkspace>`; it does not re-create the component, its API wrapper, or
  its hooks.
- The tenant-leakage pytest suite (`tests/test_tenant_leakage.py`) as a reusable pattern for
  P3/P4/P5 to extend — including the personal-workspace isolation case.

## Scope (in)
- Request-context dependency + role dependency (backend), uniform for personal and company.
- Central `ScopedRepository` wrapper enforcing `workspace_id` on every scoped query.
- The scoped-vs-global table policy and how a missing/invalid `workspace_id` becomes a 403.
- The developer contract ("never call raw `repo_*` for scoped tables").
- Frontend role-gating (`useRole`, `<RoleGate>`, route guard, workspace/role surfacing), and
  hiding company-only admin actions (invite, manage members) in a personal workspace — including
  inside P2's `WorkspaceSwitcher` in the sidebar, which P6 extends rather than re-implements.
- The tenant-leakage test suite, including a personal-workspace isolation case.

## Scope (out)
- Minting/refreshing tokens, Google OAuth, login/signup UI (P1).
- Workspace create/switch/onboarding flows themselves and `require_role` on individual workspace
  endpoints (P2) — P6's frontend only **consumes** P2's `/workspaces` list + switch endpoints,
  P2's `workspacesApi`/`useWorkspaces`/`useSwitchWorkspace`, and P2's `WorkspaceSwitcher` component
  itself; it does not design, implement, or duplicate any of them.
- The `notebook`→`project` migration itself (P3) and the source-scope rules (P5) — P6
  only guarantees they are *workspace*-scoped; the intra-workspace `personal|project|company`
  scope logic is P5's.
- A denial audit-event table. `arteamis-system` writes `AuditEvent` rows on cross-tenant denial
  (`test_X3_suite1_tenant_leakage.py`); we log at WARNING for now and note the audit table as a
  follow-up (see Open questions).

## Data model changes — none (P6 owns no migration)
Per the canonical migration sequence, **P6 adds no migration file** (P1=19, P2=20, P3=21, P4=22,
P5=23; **P6=none**). P6 introduces no tables and no columns of its own. It relies entirely on the
`workspace` link columns the earlier phases already added, and on the physical table names those
phases established — in particular the project table stays physically named **`notebook`** (P3
repurpose-in-place); there is **no** physical `project` table.

Which scoped tables carry a native `workspace` column vs. inherit it:
- **Native `workspace` column** — `notebook` (exposed as *project*) and `project_member` (P3,
  migration 21); `invitation` (P4, migration 22). `ScopedRepository`'s direct
  `WHERE workspace = $workspace_id` filter applies to these. For a personal workspace, `notebook`
  rows exist (personal projects) but `project_member`/`invitation` rows never do — that is a
  data-shape fact enforced upstream (P3/P4), not something `ScopedRepository` special-cases.
- **Workspace inherited via parent** — `source` (P5, migration 23) carries `owner`+`scope` but
  **no** denormalized `workspace` column; it resolves workspace through the `notebook` it is
  referenced by (the `reference` edge). `note`, `chat_session`, `source_insight`,
  `source_embedding` likewise inherit workspace via their parent project/source. These are scoped
  through a parent join (`repo.raw()` with an explicit `workspace = $workspace_id` on the joined
  project, and — for `source` — P5's `can_view_source`/`visible_source_ids`), not by a plain
  column filter. This is identical for a personal or a company workspace's project — the join
  shape never changes.

Fail-closed hardening (an `ASSERT workspace != NONE` field constraint + a `workspace` index so an
un-scoped `SELECT` is a *detectable bug* rather than a silent leak) belongs to the **owning
phase's** migration where a native workspace column exists — P3 for `notebook`/`project_member`,
P4 for `invitation`. If that hardening is wanted, it is folded into those phases' migrations; P6
does **not** introduce a new migration file to carry it (and `AsyncMigrationManager` therefore
gains no P6 entry).

> Rationale: RLS in `arteamis-system` uses `FORCE ROW LEVEL SECURITY` so even the table owner
> cannot bypass it. We have no equivalent, so the `ASSERT workspace != NONE` field constraint (on
> the native-column tables) is our fail-closed backstop: a scoped row can never be persisted
> workspace-less, which makes an un-scoped `SELECT * FROM notebook` a *bug we can detect*, not a
> silent leak.

## Backend: endpoints, services, domain models (file paths)

### 1. Request-context dependency — `api/deps.py` (P2 introduced this file; P6 **extends** it)
`api/deps.py` was created by **P2** with `get_identity`, `get_auth_context`, and `require_role`.
P6 **adds** `require_workspace`, `get_request_context`, `PermissionContext`/`get_permission_context`,
and the `AuthDep`/`CtxDep`/`PermCtxDep` aliases to the **same** module, and returns a
`ScopedRepository` (the SurrealDB analogue of arteamis-system's tenant-bound SQLAlchemy session
from `get_db_with_tenant`). `require_role`, `get_identity`, and `get_auth_context` below are
**reproduced from P2 for context and are NOT redefined by P6** — P6 imports and reuses them. Only
`require_workspace`, `get_request_context`, `PermissionContext`, and the aliases are new here.
None of this code inspects `workspace.kind` — a personal-workspace request and a company-workspace
request are indistinguishable at this layer, by design.

```python
# api/deps.py  (P6 additions shown alongside P2's existing get_identity/get_auth_context/require_role)
from dataclasses import dataclass
from typing import Annotated, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import AuthContext, decode_access_token, decode_identity_token  # from P1
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.database.scoping import ScopedRepository

bearer = HTTPBearer()

async def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> AuthContext:
    """Decode a workspace-scoped access token. 401 if invalid/expired."""
    try:
        return decode_access_token(credentials.credentials)  # -> AuthContext(user_id, workspace_id, role)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

async def get_identity(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> str:
    """user_id from an identity OR access token — for pre-workspace endpoints
    (list/switch/create workspace). Never used by scoped routers."""
    try:
        return decode_identity_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

def require_workspace(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
    """Reject a token that carries no active workspace. This is the 403 gate that
    guarantees ScopedRepository always has a concrete workspace_id to filter on.
    Because signup auto-provisions a personal workspace, this passes for every
    logged-in user by default — it is NOT a "has a company" check, it is a
    "has ANY active workspace, personal or company" check."""
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
    return ScopedRepository(workspace_id=auth.workspace_id, user_id=auth.user_id, role=auth.role)

def require_role(*roles: str):
    """Dependency factory: require the caller's active-workspace role ∈ roles.
    e.g. Depends(require_role("owner", "admin")) — mirrors arteamis-system.
    In a personal workspace the caller's role is always "owner", so
    require_role("owner","admin") always passes there — no special-casing needed."""
    allowed = set(roles)
    async def _dep(auth: Annotated[AuthContext, Depends(require_workspace)]) -> AuthContext:
        if auth.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires role: {', '.join(sorted(allowed))}",
            )
        return auth
    return _dep

@dataclass
class PermissionContext:
    """The request-context object P5's can_view_source/can_mutate_source bind to.

    workspace_role is the caller's active-workspace role from the token. project_role
    resolves a caller's role in a specific project via project_member, with workspace
    owner/admin escalating to project 'admin' (matches P5's expected semantics). This
    is also how a personal workspace's sole owner resolves to project-admin: they are
    always workspace_role == "owner", so they escalate without a project_member row
    ever needing to exist (and, for personal workspaces, it never does)."""

    user_id: str
    workspace_id: str
    workspace_role: str  # owner | admin | member

    async def project_role(self, project_id: str) -> Optional[str]:
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
        return rows[0].get("role") if rows else None

async def get_permission_context(
    auth: Annotated[AuthContext, Depends(require_workspace)],
) -> PermissionContext:
    """P6's concrete PermissionContext, injected into P5's source-permission routers."""
    return PermissionContext(
        user_id=auth.user_id, workspace_id=auth.workspace_id, workspace_role=auth.role
    )

AuthDep = Annotated[AuthContext, Depends(require_workspace)]
CtxDep  = Annotated[ScopedRepository, Depends(get_request_context)]
PermCtxDep = Annotated[PermissionContext, Depends(get_permission_context)]
```

The current `PasswordAuthMiddleware` (`api/auth.py`) is replaced by P1's JWT middleware; P6 does
not touch middleware wiring beyond confirming `/api/auth/*` and health/docs remain excluded
(`api/main.py` lines 237–248). P6 adds `Depends(get_request_context)` / `Depends(require_role(...))`
at the **router** layer, not the middleware.

### 2. Central scoping wrapper — `open_notebook/database/scoping.py` (new file)
This is the heart of P6. It wraps the module-level `repo_*` helpers
(`open_notebook/database/repository.py`) so that **every** operation on a workspace-scoped table
is filtered / stamped by `workspace_id`. Developers get a repository object from the request
context and never call raw `repo_query`/`repo_create`/`repo_update`/`repo_delete` for scoped
tables again. Notice `ScopedRepository` never takes or reads a `kind` — it cannot branch on
personal-vs-company even if a future developer wanted it to.

```python
# open_notebook/database/scoping.py
from typing import Any, Optional
from open_notebook.database.repository import (
    repo_query, repo_create, repo_update, repo_delete, ensure_record_id,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError

# ── Table-plane policy (single source of truth) ────────────────────────────────
# Identity plane — GLOBAL, never workspace-scoped. Login/workspace selection must
# read these BEFORE a workspace is active, so they can never carry a workspace
# filter. `workspace` itself is global: you don't scope a workspace row BY a
# workspace_id (that's circular) — membership resolves which workspaces a user
# can see, and that lookup happens in P2's own (non-scoped) endpoints.
GLOBAL_TABLES: frozenset[str] = frozenset({
    "user", "auth_identity", "workspace", "membership",
})
# Tenant/content plane — every row belongs to exactly one workspace (personal OR
# company — the filter is identical either way) and MUST be filtered by
# workspace_id on every read/write/delete. NOTE: the project table is PHYSICALLY
# named `notebook` (P3 repurpose-in-place, exposed as "project" at the API/UI);
# there is no physical `project` table, so the physical name is what goes here
# (record ids are `notebook:<id>` and `ScopedRepository.get` derives the table
# from that prefix). `notebook`, `project_member`, `invitation` carry a native
# `workspace` column (`project_member`/`invitation` rows simply never exist for a
# personal workspace — nothing here needs to know that). `source`, `note`,
# `chat_session`, `source_insight`, `source_embedding` inherit workspace via their
# parent project/source and are scoped through a parent join in `repo.raw()`
# (see Data model changes).
WORKSPACE_SCOPED_TABLES: frozenset[str] = frozenset({
    "notebook",  # exposed as "project"
    "source", "note", "chat_session",
    "source_insight", "source_embedding",
    "project_member", "invitation",
})

def _assert_scoped(table: str) -> None:
    if table in GLOBAL_TABLES:
        raise InvalidInputError(
            f"{table!r} is a GLOBAL table — use raw repo_* helpers, not ScopedRepository"
        )
    if table not in WORKSPACE_SCOPED_TABLES:
        # fail closed: an unknown table must be explicitly classified before use.
        raise InvalidInputError(f"Unknown table {table!r}; add it to WORKSPACE_SCOPED_TABLES or GLOBAL_TABLES")

class ScopedRepository:
    """Workspace-scoped view over the SurrealDB repo_* helpers — uniform for a
    personal workspace (solo tenant) and a company workspace (multi-member
    tenant) alike. There is deliberately NO `kind` parameter: this class cannot
    distinguish personal from company, which is the whole point of Option A —
    one code path, one leak surface, one test suite.

    Construct once per request via api.deps.get_request_context. Every method
    injects `WHERE workspace = $workspace_id` (reads/deletes) or stamps
    `workspace` (writes). There is no method that touches a scoped table without
    the filter.
    """
    def __init__(self, workspace_id: str, user_id: str, role: Optional[str]):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.role = role

    @property
    def _workspace_rid(self):
        return ensure_record_id(self.workspace_id)

    # ---- reads --------------------------------------------------------------
    async def list(self, table: str, *, where: str = "", vars: Optional[dict] = None,
                   order_by: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
        _assert_scoped(table)
        clauses = ["workspace = $workspace_id"]
        if where:
            clauses.append(f"({where})")             # caller predicate is AND-ed, never replaces the scope
        q = f"SELECT * FROM {table} WHERE {' AND '.join(clauses)}"
        if order_by:
            q += f" ORDER BY {order_by}"              # caller must pre-validate via ObjectModel._validate_order_by
        if limit is not None:
            q += " LIMIT $limit"
        params = {"workspace_id": self._workspace_rid, **(vars or {})}
        if limit is not None:
            params["limit"] = limit
        return await repo_query(q, params)

    async def get(self, record_id: str) -> dict:
        """Fetch one row by id AND workspace. A cross-workspace id returns 404,
        never the row — including when the "other" workspace is a different
        user's personal workspace."""
        table = record_id.split(":")[0]
        _assert_scoped(table)
        rows = await repo_query(
            "SELECT * FROM $rid WHERE workspace = $workspace_id",
            {"rid": ensure_record_id(record_id), "workspace_id": self._workspace_rid},
        )
        if not rows:
            raise NotFoundError(f"{table} {record_id} not found")   # deliberately indistinguishable from wrong-workspace
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
        data = {**data, "workspace": self._workspace_rid}       # server-set; a client-supplied workspace is overwritten
        return await repo_create(table, data)

    async def update(self, record_id: str, data: dict) -> list[dict]:
        table = record_id.split(":")[0]
        _assert_scoped(table)
        await self.get(record_id)                              # ownership check first → 404 on cross-workspace
        data = {k: v for k, v in data.items() if k != "workspace"}  # workspace is immutable post-create
        return await repo_update(table, record_id, data)

    async def delete(self, record_id: str) -> bool:
        table = record_id.split(":")[0]
        _assert_scoped(table)
        await self.get(record_id)                              # ownership check first → 404 on cross-workspace
        return await repo_delete(record_id)

    # ---- raw escape hatch (AUDITED) ----------------------------------------
    async def raw(self, query: str, vars: Optional[dict] = None) -> list[dict]:
        """For multi-table joins the helpers can't express (e.g. graph traversals
        with counts, like notebooks.py's count(<-reference.in)). The caller MUST
        include `workspace = $workspace_id` in the query themselves; $workspace_id
        is always injected into vars so it's available. Every use requires a
        `# scoped-raw: <reason>` comment and is covered by a leakage test."""
        params = {"workspace_id": self._workspace_rid, **(vars or {})}
        return await repo_query(query, params)
```

Notes on the wrapper:
- `list()` AND-s the caller predicate with the scope so a caller can never widen past their
  workspace (a la RLS `USING`). `create()` stamps `workspace` server-side (a la RLS `WITH CHECK`).
- `get()/update()/delete()` do a workspace-checked fetch first, so a **guessed** cross-workspace
  id (`notebook:abc123`) resolves to `NotFoundError` → 404 — never the other workspace's row
  (personal or company), and the 404 is indistinguishable from a genuinely missing id (no
  existence oracle).
- `raw()` is the only escape hatch and is the one place the filter is the developer's
  responsibility; it is grep-able (`.raw(`) and requires a `# scoped-raw:` comment for review.

### 3. Router migration (P3/P4/P5 consume this in P6)
Every scoped router swaps raw `repo_query`/`Notebook.get(...)` calls for the injected repo. Example,
migrating `api/routers/notebooks.py` (which becomes `projects.py` in P3) `get_notebook`:

```python
@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, repo: CtxDep):
    row = await repo.get(project_id)             # 404 if not in caller's workspace
    ...
# list: pass the PHYSICAL table name `notebook` (exposed as project at the API):
@router.get("/projects")
async def list_projects(repo: CtxDep, archived: bool | None = None):
    rows = await repo.list("notebook", order_by="updated desc")
    ...
# the count-join query keeps its shape but goes through raw() WITH the scope:
    rows = await repo.raw(
        # scoped-raw: needs count(<-reference.in) graph traversal
        "SELECT *, count(<-reference.in) AS source_count FROM notebook "
        "WHERE workspace = $workspace_id ORDER BY updated DESC",
    )
```

This exact router code runs unmodified whether `repo.workspace_id` points at a personal or a
company workspace — the router has no branch for either.

`ObjectModel.get/get_all/save/delete` (`open_notebook/domain/base.py`) stay as-is for **global**
domain models but MUST NOT be used directly for scoped tables in routers — the contract below
enforces that. (A follow-up may add a `workspace_id` kwarg to `ObjectModel.save`; for P6 the
router-layer `ScopedRepository` is the enforcement point, which keeps the blast radius small.)

### Developer contract (enforced, not just documented)
1. **Never call `repo_query`/`repo_create`/`repo_update`/`repo_delete` (or `ObjectModel.get/save/
   delete`) for a table in `WORKSPACE_SCOPED_TABLES` from a router or service.** Use the
   request-injected `ScopedRepository` (`CtxDep`).
2. Global-table access (`user`, `workspace`, `membership`, `auth_identity`) uses the raw helpers —
   `ScopedRepository` refuses them (`_assert_scoped` raises).
3. Any cross-table SurrealQL that can't go through a helper uses `repo.raw()` with an inline
   `# scoped-raw: <reason>` comment and its own leakage test.
4. **Guardrail test** (`tests/test_scoping_contract.py`): greps `api/routers/` and `api/*_service.py`
   for `repo_query(`/`repo_create(`/`repo_update(`/`repo_delete(`/`Notebook.get`/`Source.get` and
   fails if any appears in a scoped-router module outside an allowlist. This is the "developers
   must not be able to forget it" backstop — a forgotten scope fails CI, not production.
5. **No `kind`-branching in the isolation layer.** Neither `ScopedRepository` nor `api/deps.py`
   may import or reference `workspace.kind` / the strings `"personal"`/`"company"`. If a future
   change needs that, it belongs in a router/service, not the scoping layer — keep the isolation
   layer's leak surface a single path.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

### 1. Workspace + role in the auth store — `frontend/src/lib/stores/auth-store.ts`
**P2 already put `role: string | null`, `activeWorkspaceId: string | null`, `memberships:
Membership[]`, and an action `setActiveWorkspace(workspaceId, role)` on this store (its Task 10).
P6 does not redeclare `activeWorkspaceId` under a new name, and does not reuse the name
`setActiveWorkspace` for a differently-shaped action** — doing either would be a direct field/name
collision with P2's own switch/create flows. P6 adds only:
- Two NEW fields to `AuthState`: `workspaceName: string | null`, `workspaceKind: 'personal' |
  'company' | null` — a flat display mirror of the active row in P2's `memberships[]` (each
  already carries `name`/`kind`). `role`'s TS type may be narrowed to `'owner' | 'admin' |
  'member' | null` (same field P2 already has, not a new one).
- A NEW action, deliberately named `setWorkspaceContext({ workspaceName, workspaceKind, role })`
  — distinct from P2's `setActiveWorkspace`, which remains the one function that changes the
  active workspace id and re-points the access token.
- `workspaceKind` is what the frontend uses to hide company-only actions — it is **not** read by
  any backend scoping code (see "no kind-branching in the isolation layer" above); it exists
  purely for UX.
- `partialize` must additionally persist `workspaceName`, `workspaceKind` (P2 already persists
  `activeWorkspaceId`/`role`/`memberships`/`token`).
- **Residual, flagged for follow-up:** P2's existing `setActiveWorkspace`/`applyToken` call sites
  do not yet call `setWorkspaceContext`, so `workspaceName`/`workspaceKind` only update once
  something invokes the new setter. Wiring that in (or deriving both fields from
  `memberships`/`activeWorkspaceId` inside `useRole()` instead of storing them at all) is not
  resolved by this reconciliation pass.

### 2. `useRole()` hook — `frontend/src/lib/hooks/use-role.ts` (new)
```ts
'use client'
import { useAuthStore } from '@/lib/stores/auth-store'

export type WorkspaceRole = 'owner' | 'admin' | 'member'

export function useRole() {
  const role = useAuthStore((s) => s.role)
  const workspaceId = useAuthStore((s) => s.activeWorkspaceId) // P2's existing field
  const workspaceName = useAuthStore((s) => s.workspaceName)
  const workspaceKind = useAuthStore((s) => s.workspaceKind)
  const is = (...roles: WorkspaceRole[]) => !!role && roles.includes(role)
  return {
    role,
    workspaceId,
    workspaceName,
    workspaceKind,
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin',   // owner ⊇ admin
    isMember: role === 'member',
    isPersonalWorkspace: workspaceKind === 'personal',
    isCompanyWorkspace: workspaceKind === 'company',
    can: is,                                          // can('owner','admin')
  }
}
```

### 3. `<RoleGate>` component — `frontend/src/components/common/RoleGate.tsx` (new)
Declarative hide/disable wrapper for admin-only and company-only UI. Two modes: `hide` (default —
render nothing) and `disable` (render children disabled + tooltip explaining why). A
`requireCompanyWorkspace` flag additionally hides content that has no meaning in a personal
workspace (invite, manage members) regardless of role — a personal workspace's sole owner would
otherwise pass a plain `allow={['owner']}` check, so this is a second, independent condition, not
a role.
```tsx
export function RoleGate({
  allow, mode = 'hide', requireCompanyWorkspace = false, children,
}: {
  allow: WorkspaceRole[]
  mode?: 'hide' | 'disable'
  requireCompanyWorkspace?: boolean
  children: React.ReactNode
}) {
  const { can, isCompanyWorkspace } = useRole()
  const allowed = can(...allow) && (!requireCompanyWorkspace || isCompanyWorkspace)
  if (allowed) return <>{children}</>
  if (mode === 'hide') return null
  // disable: wrap in a tooltip'd, aria-disabled, pointer-events-none span
  return <span aria-disabled className="opacity-50 pointer-events-none" title={t('roles.adminOnly')}>{children}</span>
}
```

### 4. Route guard — `frontend/src/app/(dashboard)/layout.tsx`
The existing layout already redirects unauthenticated users to `/login` (lines 25–38). P6 extends it:
- If authenticated but `workspaceId == null` → redirect to `/onboarding`. In practice this should
  be unreachable post-P2 (signup always auto-provisions a personal workspace, so a logged-in user
  always has an active workspace), but it is kept as the defense-in-depth backstop for the brief
  window between an identity token and a workspace-scoped one, and it mirrors the backend's
  `require_workspace` 403. A scoped API call without an active workspace returns 403; the guard
  keeps the user out of scoped screens before that can happen.
- Admin-only *routes* (`/settings/*`, `/advanced`, `/transformations`, and P2's
  `/settings/members`) get a per-segment guard: a small `<RequireRole allow={['owner','admin']}>`
  wrapper (thin client-side redirect to `/notebooks` + toast on deny). This is defense-in-UX only —
  the backend `require_role` is the real gate. `/settings/members` additionally is unreachable in a
  personal workspace (the switcher never routes there for Personal — see below).

### 5. Sidebar gating, role + workspace surfacing — `frontend/src/components/layout/AppSidebar.tsx`
Concrete admin actions gated (member sees them hidden):
- **"Manage" nav section** (lines 66–74): `Models` (`/settings/api-keys`), `Transformations`,
  `Settings`, `Advanced` are owner/admin-only → wrap each item in `<RoleGate allow={['owner','admin']}>`.
  Since a personal workspace's sole member is always `owner`, this section is always visible there
  — it's not company-gated, only role-gated. Members keep `Collect`/`Process`/`Create` (Sources,
  Notebooks, Search, Podcasts).
- **"Manage members" / invite** nav items (P2/P4-added) additionally get
  `<RoleGate allow={['owner','admin']} requireCompanyWorkspace>` — hidden entirely in a personal
  workspace, regardless of role, because invitation/membership management has no meaning for a
  solo tenant.
- **Create menu** (lines 172–240): creating a **notebook/project** is owner/admin-only (brief:
  "Project creation in a COMPANY workspace is allowed for workspace owner/admin; in a PERSONAL
  workspace the owner creates freely") → gate the `notebook` `DropdownMenuItem` with
  `<RoleGate allow={['owner','admin']}>` (no `requireCompanyWorkspace` — a personal owner must
  still be able to create). `source`/`podcast` remain available to members.
- **`WorkspaceSwitcher`** (P2's component, already built and mounted at
  `frontend/src/components/workspace/WorkspaceSwitcher.tsx` — **P6 extends it, it does not
  re-create it**): P2 already renders the active workspace's name + role badge and a list of
  memberships — **Personal** first, then every company workspace the user belongs to (from P2's
  `GET /workspaces`), each with its role — and a "+ Create a company" entry. Selecting an entry
  calls P2's `POST /auth/switch-workspace/{id}` via P2's own `useSwitchWorkspace()`, which already
  swaps the token and invalidates the relevant caches. **P6's only addition** is a
  `<RoleGate allow={['owner','admin']} requireCompanyWorkspace>`-gated "Manage members" link
  rendered inside the same component — hidden for a personal workspace regardless of role, and for
  a company-workspace member. No new file, path, API wrapper, or hook is introduced.

### 6. i18n keys (add to ALL 7 enforced locales under `frontend/src/lib/locales/`:
`en-US`, `pt-BR`, `zh-CN`, `zh-TW`, `ja-JP`, `ru-RU`, `bn-IN`)
- `roles.owner`, `roles.admin`, `roles.member` — role pill labels.
- `roles.adminOnly` — "Only admins can do this" (RoleGate disabled tooltip).
- `roles.noWorkspace` — onboarding-redirect toast (defense-in-depth; see route guard above).
- `roles.accessDenied` — admin-route deny toast.
- `workspace.manageMembers` — the `WorkspaceSwitcher` "Manage members" link label, P6's one
  addition to P2's already-shipped `workspace.*` key set (`workspace.personalLabel`,
  `workspace.switchLabel`, `workspace.switchSuccess`, `workspace.addCompanyCta`, etc. — all P2's,
  unaffected by P6).

## Permissions / RBAC rules (explicit table: who can do what)

### Table-plane policy (which tables are workspace-scoped)
| Table | Plane | Filter |
|---|---|---|
| `user`, `auth_identity`, `workspace`, `membership` | **Global (identity)** | none — read before a workspace is active; raw `repo_*` only |
| `project`, `source`, `note`, `chat_session` | **Workspace-scoped** (personal or company, uniform) | `WHERE workspace = $workspace_id` |
| `source_insight`, `source_embedding` | **Workspace-scoped** | via parent source's workspace / own `workspace` col |
| `project_member`, `invitation` | **Workspace-scoped**, **company-workspace-only in practice** | `WHERE workspace = $workspace_id` (no rows exist for a personal workspace, enforced upstream by P3/P4, not by this filter) |

### Action gating (backend dependency + frontend gate)
| Action | Workspace role required | Backend enforcement | Frontend gate |
|---|---|---|---|
| Read any scoped row | any active-workspace member (incl. a personal workspace's sole owner) | `require_workspace` + `ScopedRepository` filter | route guard (has workspace) |
| Create project | owner, admin (personal: owner, trivially) | `require_role("owner","admin")` on `POST /projects` | RoleGate on Create→Notebook |
| Update/delete/archive project | owner, admin | `require_role` + `repo.get` ownership | RoleGate (disable) on buttons |
| Create/upload source | any member | `require_workspace` + `repo.create("source")` | not gated |
| Manage models/credentials/settings/advanced | owner, admin | `require_role("owner","admin")` on those routers | RoleGate on "Manage" nav |
| Invite into workspace/project | owner, admin, **AND workspace `kind == "company"`** | `require_role` + P4's `kind` check (403 on personal) | `RoleGate ... requireCompanyWorkspace` on invite UI |
| Switch active workspace | any workspace the user is a member of | P2's `/auth/switch-workspace/{id}` | `WorkspaceSwitcher` |
| Any request with no active workspace | — | **403** via `require_workspace` | redirect to `/onboarding` |
| Any request, wrong role | — | **403** via `require_role` | route redirect + toast |
| Read/mutate another workspace's row (guessed id), incl. another user's personal workspace | — | **404** via `ScopedRepository.get` | n/a |

## Error handling
Consistent with the brief's cross-phase contract (`{"detail": "..."}` JSON body):
- **401** — missing/invalid/expired token (`get_auth_context`). Frontend clears `auth-storage`
  and redirects `/login` (existing `apiClient` behavior).
- **403** — authenticated but (a) **no active `workspace_id`** (`require_workspace`) or (b)
  **wrong role** (`require_role`) or (c) **inviting into a `kind="personal"` workspace** (P4's
  check, not P6's, but surfaced through the same `require_role`-adjacent pattern). Distinct
  `detail` strings ("No active workspace selected…" vs "Requires role: …"). Frontend: (a) →
  `/onboarding`; (b) → toast + stay/redirect.
- **404** — a scoped `get/update/delete` for a record id that isn't in the caller's workspace
  (personal or company). **Deliberately a 404, not 403**, so cross-workspace ids are
  indistinguishable from non-existent ids (no existence oracle; matches `arteamis-system`
  returning "not_found_or_cross_tenant").
- **400 (`InvalidInputError`)** — `ScopedRepository` used against a global/unknown table
  (`_assert_scoped`) — a developer bug surfaced loudly, mapped to 400 by the existing handler in
  `api/main.py`.
- Cross-workspace denial is logged at **WARNING** with `workspace_id`+`record_id` (no audit table
  yet).

## Testing (concrete test cases)

### `tests/test_tenant_leakage.py` — mirrors `arteamis-system/backend/tests/test_projects_rls.py` and `test_X3_suite1_tenant_leakage.py`
Fixtures seed two **company** workspaces `workspace:A` / `workspace:B`, a user + membership in
each, and build `AuthContext`/tokens for both (`_headers(workspace="A"|"B")`, like
`test_X3_suite1`'s `_headers`), PLUS a third case with two **personal** workspaces to prove the
uniform code path also isolates solo tenants from each other. Run against a real SurrealDB test DB
(mirrors the `TEST_DATABASE_URL` skip guard).

1. **`test_workspace_b_cannot_list_workspace_a_projects`** — seed `project` in A; `GET /projects`
   with B's token returns `[]` (A's project absent). The direct analogue of
   `test_second_tenant_cannot_see_first_tenants_project`.
2. **`test_workspace_b_cannot_get_workspace_a_project_by_guessed_id`** — B calls
   `GET /projects/{A_project_id}` with A's real id → **404** (not 200, not 403).
3. **`test_workspace_b_cannot_update_workspace_a_project`** — B `PUT /projects/{A_project_id}` → 404,
   and re-reading as A shows the row unchanged (WITH CHECK analogue).
4. **`test_workspace_b_cannot_delete_workspace_a_project`** — B `DELETE` → 404; A still sees the row.
5. **`test_workspace_b_cannot_read_workspace_a_source_by_guessed_id`** — same as #2 for `source`
   (covers the P5 plane too).
6. **`test_workspace_b_cannot_read_workspace_a_notes_and_chat`** — list `note` / `chat_session`
   scoped to B never contains A's rows.
7. **`test_create_stamps_callers_workspace_not_client_value`** — B POSTs a project with a forged
   body `{"workspace": "workspace:A"}`; the created row's `workspace` is B (server overwrites) —
   the WITH CHECK backstop.
8. **`test_missing_workspace_token_is_403`** — a valid identity token (no `workspace_id`) hitting a
   scoped endpoint → 403 "No active workspace selected".
9. **`test_scoped_repository_rejects_global_table`** — unit test: `ScopedRepository.list("user")`
   raises `InvalidInputError` (contract guard).
10. **`test_unknown_table_fails_closed`** — `ScopedRepository.list("widget")` raises (new table
    must be classified before use).
11. **`test_personal_workspace_x_not_visible_to_personal_workspace_y`** — seed user X's personal
    workspace with a project; user Y (a different user, with their own separate personal
    workspace) requests `GET /projects` and `GET /projects/{x_project_id}` with Y's token. Assert
    the list omits X's project and the direct-get is **404** — same assertions, same code path, as
    the company A/B cases above, proving personal workspaces get zero special treatment in the
    isolation layer.
12. **`test_scoped_repository_has_no_kind_parameter`** — unit/reflection test:
    `inspect.signature(ScopedRepository.__init__)` does not contain a `kind` parameter, and the
    module source of `open_notebook/database/scoping.py` contains neither the literal `"personal"`
    nor `"company"` — a structural guard against a future PR quietly reintroducing kind-branching
    into the isolation layer.

### `tests/test_scoping_contract.py`
- **`test_no_raw_repo_calls_in_scoped_routers`** — static grep guard described in the developer
  contract; asserts no `repo_query(`/`repo_create(`/`Notebook.get`/`Source.get` outside the
  allowlist. Fails CI on a forgotten scope.

### Frontend — `frontend/src/lib/hooks/use-role.test.ts`, `RoleGate.test.tsx`, `AppSidebar.test.tsx`, `WorkspaceSwitcher.test.tsx`
- `useRole()` derives `isAdmin` (owner⊇admin), `isMember`, `isPersonalWorkspace`/
  `isCompanyWorkspace`, `can()` from store role/kind.
- `<RoleGate allow={['owner','admin']}>` renders children for admin, `null` for member (hide),
  and disabled+tooltip in `disable` mode; `requireCompanyWorkspace` hides for an owner whose
  active workspace is `kind: 'personal'`.
- `AppSidebar` (extend existing `AppSidebar.test.tsx`): a `member` role does not render the
  "Manage" section nor the Create→Notebook item; an `admin` role does; a personal-workspace
  `owner` does not render "Manage members"/invite entries.
- `WorkspaceSwitcher` (P2's existing test file, extended here — P2's own switching/listing cases
  are untouched): a company-workspace owner/admin sees a "Manage members" link; a personal
  workspace's owner and a company-workspace member do not.
- All new strings exist in all 7 enforced locales (existing locale-sync test covers this).
- Backend: `uv run pytest tests/`. Frontend: `npm run test && npm run lint && npm run build`.

## Open questions / risks
- **Denial audit table.** `arteamis-system` writes `AuditEvent` on cross-workspace denial
  (`test_X3_suite1_tenant_leakage.py`). P6 only logs at WARNING. A follow-up phase should add a
  SurrealDB `audit_event` table + best-effort write on 404-by-cross-workspace. Flagged, not built.
- **`source_insight`/`source_embedding` scoping.** These reference a source, not a workspace,
  directly today. Because **P6 owns no migration** (canonical: P6=none), they get **no** new
  denormalized `workspace` column here; they are scoped by joining through their parent `source`
  (which in turn resolves workspace via its `notebook`), matching the "workspace inherited via
  parent" model in Data model changes. If a future phase wants a denormalized `workspace` column
  on them for uniform `ScopedRepository` filtering + to keep vector search from joining across
  workspaces, that column must be added by an **owning-phase migration** (e.g. folded into P5's
  migration 23), not by P6 — and the embedding-rebuild job (`api/routers/embedding_rebuild.py`)
  would then stamp `workspace` on regenerate. Flagged, not built in P6.
- **`ObjectModel` bypass.** P6 enforces scoping at the router/`ScopedRepository` layer, leaving
  `ObjectModel.get/save` able to touch scoped tables un-scoped. The grep guard
  (`test_scoping_contract.py`) is the mitigation. A stronger fix (a `workspace_id`-aware base
  class) is deferred to avoid rewriting every domain model in this phase.
- **Search + graph traversals.** Full-text/vector search (`api/routers/search.py`) and the
  `count(<-reference.in)` join style must all route through `repo.raw()` with an explicit
  `workspace = $workspace_id`. Each such query needs its own leakage test; the risk is a missed
  one, which the raw-call grep guard + per-feature leakage tests are designed to catch.
- **Token freshness on role/workspace change.** If an admin demotes a member, or a user switches
  workspaces, the caller's existing access token still carries the old claims until refresh/switch
  completes. Mitigation (P1/P2): short access-token TTL + refresh, and switch-workspace mints a
  fresh token synchronously; P6 assumes that and does not re-check role against the DB per request
  (a deliberate performance/complexity trade-off matching `arteamis-system`'s token-baked role).
- **Personal workspace promotion (PRD §4.3).** The brief scopes only the schema hook
  (`promoted_from`) for this phase set, not the governed review flow. P6's scoping layer needs no
  changes to support a future "move this project from workspace A to workspace B" operation beyond
  what `ScopedRepository.update` already allows for an owner — but the *write path* for such a
  move (which touches two workspaces at once) is explicitly out of scope here and flagged for the
  phase that implements promotion.
