# P6 — Multi-tenancy application-layer scoping (replaces Postgres RLS) + frontend role-gating — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft

## Goal
SurrealDB has no row-level security, so tenant isolation must be enforced in the application
layer. This phase (1) adds a FastAPI request-context dependency that resolves the authenticated
user + active `company_id` + role from the access token, (2) adds a centralized scoping
helper / repository wrapper so every query against a company-scoped table is automatically
filtered by `company_id` — a developer must not be able to forget it, (3) role-gates the
frontend (hide/disable admin-only actions for members, add a dashboard route guard, surface
`role`/company context in the UI), and (4) ships a tenant-leakage test suite that proves
company A can never read or mutate company B's rows, even by guessing record ids. This is the
SurrealDB analogue of `arteamis-system`'s `SET LOCAL app.current_tenant_id` + `USING/WITH CHECK`
RLS policy (`arteamis-system/backend/app/core/db.py`, `test_projects_rls.py`), re-implemented
because there is no `SET LOCAL`/policy mechanism to lean on.

## Depends on / Provides
**Depends on:**
- **P1 (auth):** the JWT layer that mints/decodes tokens. P6 assumes P1 has landed
  `api/security.py` with `AuthContext` (fields `user_id`, `company_id: str | None`, `role: str | None`)
  and `decode_access_token()` / `decode_identity_token()` (mirrors `arteamis-system/backend/app/core/security.py`),
  plus the frontend `auth-store` carrying the decoded token claims.
- **P2 (company+membership+roles):** the `company`/`membership` tables, and the **`api/deps.py`
  module P2 introduced** — `get_identity`, `get_auth_context`, and the `require_role` factory. P6
  **extends this same file** (adds `require_company`, `get_request_context`, `ScopedRepository`
  wiring) and **reuses `require_role` unchanged — it does not redefine it**. `require_role` semantics
  (owner|admin|member) baked into the access token.
- **P3 (project):** the `notebook`→`project` rename with `company` + `owner` columns.
- **P4 (invitation)** and **P5 (source permissions):** the `invitation`, `project_member` tables
  and `source.owner`/`source.visibility` columns that P6 must also scope.

**Provides:**
- Extensions to P2's `api/deps.py`: **new** `require_company`, `get_request_context`, and the typed
  aliases (`AuthDep`, `CtxDep`) that every scoped router depends on. (`get_identity`,
  `get_auth_context`, and `require_role` are P2's and are reused unchanged, not redefined.)
- `open_notebook/database/scoping.py`: `ScopedRepository` — the single sanctioned entry point
  for all reads/writes/deletes against company-scoped tables. Once P6 lands, P3/P4/P5 routers
  are migrated to consume it.
- The concrete **`PermissionContext` that P5 declares the shape of** — the request-context object
  P5's `can_view_source`/`can_mutate_source` bind to. P6 supplies its full implementation:
  `user_id`, `company_id`, `company_role` (= the token's `role`), and an async
  `project_role(project_id) -> "admin"|"member"|None` resolver (via a `project_member` lookup with
  company owner/admin → project-admin escalation). P5 ships a JWT-claims stub of this until P6 lands;
  the two specs keep this interface in sync.
- `COMPANY_SCOPED_TABLES` / `GLOBAL_TABLES` policy constants (single source of truth for
  which plane a table lives in).
- Frontend `useRole()` hook, `<RoleGate>` component, and a dashboard route guard.
- The tenant-leakage pytest suite (`tests/test_tenant_leakage.py`) as a reusable pattern for
  P3/P4/P5 to extend.

## Scope (in)
- Request-context dependency + role dependency (backend).
- Central `ScopedRepository` wrapper enforcing `company_id` on every scoped query.
- The scoped-vs-global table policy and how a missing/invalid `company_id` becomes a 403.
- The developer contract ("never call raw `repo_*` for scoped tables").
- Frontend role-gating (`useRole`, `<RoleGate>`, route guard, company/role surfacing in the sidebar).
- The tenant-leakage test suite.

## Scope (out)
- Minting/refreshing tokens, Google OAuth, login/signup UI (P1).
- Company create/switch/onboarding flows and `require_role` on individual company endpoints (P2).
- The `notebook`→`project` migration itself (P3) and the source-visibility rules (P5) — P6
  only guarantees they are *company*-scoped; the intra-company `private|project` visibility
  logic is P5's.
- A denial audit-event table. `arteamis-system` writes `AuditEvent` rows on cross-tenant denial
  (`test_X3_suite1_tenant_leakage.py`); we log at WARNING for now and note the audit table as a
  follow-up (see Open questions).

## Data model changes — none (P6 owns no migration)
Per the canonical migration sequence, **P6 adds no migration file** (P1=19, P2=20, P3=21, P4=22,
P5=23; **P6=none**). P6 introduces no tables and no columns of its own. It relies entirely on the
`company` link columns the earlier phases already added, and on the physical table names those
phases established — in particular the project table stays physically named **`notebook`** (P3
repurpose-in-place); there is **no** physical `project` table.

Which scoped tables carry a native `company` column vs. inherit it:
- **Native `company` column** — `notebook` (exposed as *project*) and `project_member` (P3,
  migration 21); `invitation` (P4, migration 22). `ScopedRepository`'s direct
  `WHERE company = $company_id` filter applies to these.
- **Company inherited via parent** — `source` (P5, migration 23) carries `owner`+`visibility` but
  **no** denormalized `company` column; it resolves company through the `notebook` it is
  referenced by (the `reference` edge). `note`, `chat_session`, `source_insight`,
  `source_embedding` likewise inherit company via their parent project/source. These are scoped
  through a parent join (`repo.raw()` with an explicit `company = $company_id` on the joined
  project, and — for `source` — P5's `can_view_source`/`visible_source_ids`), not by a plain
  column filter.

Fail-closed hardening (an `ASSERT company != NONE` field constraint + a `company` index so an
un-scoped `SELECT` is a *detectable bug* rather than a silent leak) belongs to the **owning
phase's** migration where a native company column exists — P3 for `notebook`/`project_member`,
P4 for `invitation`. If that hardening is wanted, it is folded into those phases' migrations; P6
does **not** introduce a new migration file to carry it (and `AsyncMigrationManager` therefore
gains no P6 entry).

> Rationale: RLS in `arteamis-system` uses `FORCE ROW LEVEL SECURITY` so even the table owner
> cannot bypass it. We have no equivalent, so the `ASSERT company != NONE` field constraint (on the
> native-column tables) is our fail-closed backstop: a scoped row can never be persisted
> company-less, which makes an un-scoped `SELECT * FROM notebook` a *bug we can detect*, not a
> silent leak.

## Backend: endpoints, services, domain models (file paths)

### 1. Request-context dependency — `api/deps.py` (P2 introduced this file; P6 **extends** it)
`api/deps.py` was created by **P2** with `get_identity`, `get_auth_context`, and `require_role`.
P6 **adds** `require_company`, `get_request_context`, and the `AuthDep`/`CtxDep` aliases to the
**same** module, and returns a `ScopedRepository` (the SurrealDB analogue of arteamis-system's
tenant-bound SQLAlchemy session from `get_db_with_tenant`). `require_role`, `get_identity`, and
`get_auth_context` below are **reproduced from P2 for context and are NOT redefined by P6** — P6
imports and reuses them. Only `require_company`, `get_request_context`, and the aliases are new here.

```python
# api/deps.py  (P6 additions shown alongside P2's existing get_identity/get_auth_context/require_role)
from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import AuthContext, decode_access_token, decode_identity_token  # from P1
from open_notebook.database.scoping import ScopedRepository

bearer = HTTPBearer()

async def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> AuthContext:
    """Decode a company-scoped access token. 401 if invalid/expired."""
    try:
        return decode_access_token(credentials.credentials)  # -> AuthContext(user_id, company_id, role)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

async def get_identity(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> str:
    """user_id from an identity OR access token — for pre-company endpoints
    (list/switch/create company). Never used by scoped routers."""
    try:
        return decode_identity_token(credentials.credentials)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

def require_company(auth: Annotated[AuthContext, Depends(get_auth_context)]) -> AuthContext:
    """Reject a token that carries no active company. This is the 403 gate that
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
    return ScopedRepository(company_id=auth.company_id, user_id=auth.user_id, role=auth.role)

def require_role(*roles: str):
    """Dependency factory: require the caller's active-company role ∈ roles.
    e.g. Depends(require_role("owner", "admin")) — mirrors arteamis-system."""
    allowed = set(roles)
    async def _dep(auth: Annotated[AuthContext, Depends(require_company)]) -> AuthContext:
        if auth.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires role: {', '.join(sorted(allowed))}",
            )
        return auth
    return _dep

AuthDep = Annotated[AuthContext, Depends(require_company)]
CtxDep  = Annotated[ScopedRepository, Depends(get_request_context)]
```

The current `PasswordAuthMiddleware` (`api/auth.py`) is replaced by P1's JWT middleware; P6 does
not touch middleware wiring beyond confirming `/api/auth/*` and health/docs remain excluded
(`api/main.py` lines 237–248). P6 adds `Depends(get_request_context)` / `Depends(require_role(...))`
at the **router** layer, not the middleware.

### 2. Central scoping wrapper — `open_notebook/database/scoping.py` (new file)
This is the heart of P6. It wraps the module-level `repo_*` helpers
(`open_notebook/database/repository.py`) so that **every** operation on a company-scoped table
is filtered / stamped by `company_id`. Developers get a repository object from the request
context and never call raw `repo_query`/`repo_create`/`repo_update`/`repo_delete` for scoped
tables again.

```python
# open_notebook/database/scoping.py
from typing import Any, Optional
from open_notebook.database.repository import (
    repo_query, repo_create, repo_update, repo_delete, ensure_record_id,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError

# ── Table-plane policy (single source of truth) ────────────────────────────────
# Identity plane — GLOBAL, never company-scoped. Login/company selection must
# read these BEFORE a company is active, so they can never carry a company filter.
GLOBAL_TABLES: frozenset[str] = frozenset({
    "user", "auth_identity", "company", "membership",
})
# Tenant/content plane — every row belongs to exactly one company and MUST be
# filtered by company_id on every read/write/delete. NOTE: the project table is
# PHYSICALLY named `notebook` (P3 repurpose-in-place, exposed as "project" at the
# API/UI); there is no physical `project` table, so the physical name is what goes
# here (record ids are `notebook:<id>` and `ScopedRepository.get` derives the table
# from that prefix). `notebook`, `project_member`, `invitation` carry a native
# `company` column; `source`, `note`, `chat_session`, `source_insight`,
# `source_embedding` inherit company via their parent project/source and are scoped
# through a parent join in `repo.raw()` (see Data model changes).
COMPANY_SCOPED_TABLES: frozenset[str] = frozenset({
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
    if table not in COMPANY_SCOPED_TABLES:
        # fail closed: an unknown table must be explicitly classified before use.
        raise InvalidInputError(f"Unknown table {table!r}; add it to COMPANY_SCOPED_TABLES or GLOBAL_TABLES")

class ScopedRepository:
    """Company-scoped view over the SurrealDB repo_* helpers.

    Construct once per request via api.deps.get_request_context. Every method
    injects `WHERE company = $company_id` (reads/deletes) or stamps `company`
    (writes). There is no method that touches a scoped table without the filter.
    """
    def __init__(self, company_id: str, user_id: str, role: Optional[str]):
        self.company_id = company_id
        self.user_id = user_id
        self.role = role

    @property
    def _company_rid(self):
        return ensure_record_id(self.company_id)

    # ---- reads --------------------------------------------------------------
    async def list(self, table: str, *, where: str = "", vars: Optional[dict] = None,
                   order_by: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
        _assert_scoped(table)
        clauses = ["company = $company_id"]
        if where:
            clauses.append(f"({where})")             # caller predicate is AND-ed, never replaces the scope
        q = f"SELECT * FROM {table} WHERE {' AND '.join(clauses)}"
        if order_by:
            q += f" ORDER BY {order_by}"              # caller must pre-validate via ObjectModel._validate_order_by
        if limit is not None:
            q += " LIMIT $limit"
        params = {"company_id": self._company_rid, **(vars or {})}
        if limit is not None:
            params["limit"] = limit
        return await repo_query(q, params)

    async def get(self, record_id: str) -> dict:
        """Fetch one row by id AND company. A cross-company id returns 404, never the row."""
        table = record_id.split(":")[0]
        _assert_scoped(table)
        rows = await repo_query(
            "SELECT * FROM $rid WHERE company = $company_id",
            {"rid": ensure_record_id(record_id), "company_id": self._company_rid},
        )
        if not rows:
            raise NotFoundError(f"{table} {record_id} not found")   # deliberately indistinguishable from wrong-company
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
        data = {**data, "company": self._company_rid}          # server-set; a client-supplied company is overwritten
        return await repo_create(table, data)

    async def update(self, record_id: str, data: dict) -> list[dict]:
        table = record_id.split(":")[0]
        _assert_scoped(table)
        await self.get(record_id)                              # ownership check first → 404 on cross-company
        data = {k: v for k, v in data.items() if k != "company"}  # company is immutable post-create
        return await repo_update(table, record_id, data)

    async def delete(self, record_id: str) -> bool:
        table = record_id.split(":")[0]
        _assert_scoped(table)
        await self.get(record_id)                              # ownership check first → 404 on cross-company
        return await repo_delete(record_id)

    # ---- raw escape hatch (AUDITED) ----------------------------------------
    async def raw(self, query: str, vars: Optional[dict] = None) -> list[dict]:
        """For multi-table joins the helpers can't express (e.g. graph traversals
        with counts, like notebooks.py's count(<-reference.in)). The caller MUST
        include `company = $company_id` in the query themselves; $company_id is
        always injected into vars so it's available. Every use requires a
        `# scoped-raw: <reason>` comment and is covered by a leakage test."""
        params = {"company_id": self._company_rid, **(vars or {})}
        return await repo_query(query, params)
```

Notes on the wrapper:
- `list()` AND-s the caller predicate with the scope so a caller can never widen past their
  company (a la RLS `USING`). `create()` stamps `company` server-side (a la RLS `WITH CHECK`).
- `get()/update()/delete()` do a company-checked fetch first, so a **guessed** cross-company
  id (`notebook:abc123`) resolves to `NotFoundError` → 404 — never the other company's row, and
  the 404 is indistinguishable from a genuinely missing id (no existence oracle).
- `raw()` is the only escape hatch and is the one place the filter is the developer's
  responsibility; it is grep-able (`.raw(`) and requires a `# scoped-raw:` comment for review.

### 3. Router migration (P3/P4/P5 consume this in P6)
Every scoped router swaps raw `repo_query`/`Notebook.get(...)` calls for the injected repo. Example,
migrating `api/routers/notebooks.py` (which becomes `projects.py` in P3) `get_notebook`:

```python
@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, repo: CtxDep):
    row = await repo.get(project_id)             # 404 if not in caller's company
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
        "WHERE company = $company_id ORDER BY updated DESC",
    )
```

`ObjectModel.get/get_all/save/delete` (`open_notebook/domain/base.py`) stay as-is for **global**
domain models but MUST NOT be used directly for scoped tables in routers — the contract below
enforces that. (A follow-up may add a `company_id` kwarg to `ObjectModel.save`; for P6 the
router-layer `ScopedRepository` is the enforcement point, which keeps the blast radius small.)

### Developer contract (enforced, not just documented)
1. **Never call `repo_query`/`repo_create`/`repo_update`/`repo_delete` (or `ObjectModel.get/save/
   delete`) for a table in `COMPANY_SCOPED_TABLES` from a router or service.** Use the
   request-injected `ScopedRepository` (`CtxDep`).
2. Global-table access (`user`, `company`, `membership`, `auth_identity`) uses the raw helpers —
   `ScopedRepository` refuses them (`_assert_scoped` raises).
3. Any cross-table SurrealQL that can't go through a helper uses `repo.raw()` with an inline
   `# scoped-raw: <reason>` comment and its own leakage test.
4. **Guardrail test** (`tests/test_scoping_contract.py`): greps `api/routers/` and `api/*_service.py`
   for `repo_query(`/`repo_create(`/`repo_update(`/`repo_delete(`/`Notebook.get`/`Source.get` and
   fails if any appears in a scoped-router module outside an allowlist. This is the "developers
   must not be able to forget it" backstop — a forgotten scope fails CI, not production.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

### 1. Role + company in the auth store — `frontend/src/lib/stores/auth-store.ts`
P1 already decodes the access token into the store. P6 requires the store to expose the active
company + role (persisted alongside `token`):
- Add to `AuthState`: `companyId: string | null`, `companyName: string | null`,
  `role: 'owner' | 'admin' | 'member' | null`, and `setActiveCompany(...)`.
- `partialize` (line 213) must persist `companyId`, `companyName`, `role` too, so a refresh
  keeps the active company. These are set from the decoded JWT claims (`sub`, `company_id`, `role`).

### 2. `useRole()` hook — `frontend/src/lib/hooks/use-role.ts` (new)
```ts
'use client'
import { useAuthStore } from '@/lib/stores/auth-store'

export type CompanyRole = 'owner' | 'admin' | 'member'

export function useRole() {
  const role = useAuthStore((s) => s.role)
  const companyId = useAuthStore((s) => s.companyId)
  const companyName = useAuthStore((s) => s.companyName)
  const is = (...roles: CompanyRole[]) => !!role && roles.includes(role)
  return {
    role,
    companyId,
    companyName,
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin',   // owner ⊇ admin
    isMember: role === 'member',
    can: is,                                          // can('owner','admin')
  }
}
```

### 3. `<RoleGate>` component — `frontend/src/components/common/RoleGate.tsx` (new)
Declarative hide/disable wrapper for admin-only UI. Two modes: `hide` (default — render nothing)
and `disable` (render children disabled + tooltip explaining why).
```tsx
export function RoleGate({
  allow, mode = 'hide', children,
}: { allow: CompanyRole[]; mode?: 'hide' | 'disable'; children: React.ReactNode }) {
  const { can } = useRole()
  if (can(...allow)) return <>{children}</>
  if (mode === 'hide') return null
  // disable: wrap in a tooltip'd, aria-disabled, pointer-events-none span
  return <span aria-disabled className="opacity-50 pointer-events-none" title={t('roles.adminOnly')}>{children}</span>
}
```

### 4. Route guard — `frontend/src/app/(dashboard)/layout.tsx`
The existing layout already redirects unauthenticated users to `/login` (lines 25–38). P6 extends it:
- If authenticated but `companyId == null` → redirect to `/onboarding` (the P2 company-create
  wizard). A scoped API call without an active company returns 403 (`require_company`); the guard
  keeps the user out of scoped screens before that can happen.
- Admin-only *routes* (`/settings/*`, `/advanced`, `/transformations`, and P2's
  `/settings/members`) get a per-segment guard: a small `<RequireRole allow={['owner','admin']}>`
  wrapper (thin client-side redirect to `/notebooks` + toast on deny). This is defense-in-UX only —
  the backend `require_role` is the real gate.

### 5. Sidebar gating + company surfacing — `frontend/src/components/layout/AppSidebar.tsx`
Concrete admin actions gated (member sees them hidden):
- **"Manage" nav section** (lines 66–74): `Models` (`/settings/api-keys`), `Transformations`,
  `Settings`, `Advanced` are owner/admin-only → wrap each item in `<RoleGate allow={['owner','admin']}>`.
  Members keep `Collect`/`Process`/`Create` (Sources, Notebooks, Search, Podcasts).
- **Create menu** (lines 172–240): creating a **notebook/project** is owner/admin-only (brief:
  "Project creation is allowed for company owner/admin; members are invited into projects") →
  gate the `notebook` `DropdownMenuItem`. `source`/`podcast` remain available to members.
- **Company + role badge**: add a company-name header + role pill near the logo (lines 141–146),
  reading `useRole().companyName` / `role`. If P2 ships multi-company, this becomes the
  company-switcher dropdown; P6 only requires read-only surfacing.
- Per-project **delete/archive/invite** buttons (in the project detail screens under
  `frontend/src/app/(dashboard)/notebooks/`) get `<RoleGate allow={['owner','admin']} mode="disable">`.

### 6. i18n keys (add to ALL 7 enforced locales under `frontend/src/lib/locales/`:
`en-US`, `pt-BR`, `zh-CN`, `zh-TW`, `ja-JP`, `ru-RU`, `bn-IN`)
- `roles.owner`, `roles.admin`, `roles.member` — role pill labels.
- `roles.adminOnly` — "Only company admins can do this" (RoleGate disabled tooltip).
- `roles.noCompany` — onboarding-redirect toast.
- `roles.accessDenied` — admin-route deny toast.
- `company.activeCompany` — sidebar company header aria-label.

## Permissions / RBAC rules (explicit table: who can do what)

### Table-plane policy (which tables are company-scoped)
| Table | Plane | Filter |
|---|---|---|
| `user`, `auth_identity`, `company`, `membership` | **Global (identity)** | none — read before a company is active; raw `repo_*` only |
| `project`, `source`, `note`, `chat_session` | **Company-scoped** | `WHERE company = $company_id` |
| `source_insight`, `source_embedding` | **Company-scoped** | via parent source's company / own `company` col |
| `project_member`, `invitation` | **Company-scoped** | `WHERE company = $company_id` |

### Action gating (backend dependency + frontend gate)
| Action | Company role required | Backend enforcement | Frontend gate |
|---|---|---|---|
| Read any scoped row | any active-company member | `require_company` + `ScopedRepository` filter | route guard (has company) |
| Create project | owner, admin | `require_role("owner","admin")` on `POST /projects` | RoleGate on Create→Notebook |
| Update/delete/archive project | owner, admin | `require_role` + `repo.get` ownership | RoleGate (disable) on buttons |
| Create/upload source | any member | `require_company` + `repo.create("source")` | not gated |
| Manage models/credentials/settings/advanced | owner, admin | `require_role("owner","admin")` on those routers | RoleGate on "Manage" nav |
| Invite into company/project | owner, admin | `require_role` (P4) | RoleGate on invite UI |
| Any request with no active company | — | **403** via `require_company` | redirect to `/onboarding` |
| Any request, wrong role | — | **403** via `require_role` | route redirect + toast |
| Read/mutate another company's row (guessed id) | — | **404** via `ScopedRepository.get` | n/a |

## Error handling
Consistent with the brief's cross-phase contract (`{"detail": "..."}` JSON body):
- **401** — missing/invalid/expired token (`get_auth_context`). Frontend clears `auth-storage`
  and redirects `/login` (existing `apiClient` behavior).
- **403** — authenticated but (a) **no active `company_id`** (`require_company`) or (b) **wrong
  role** (`require_role`). Distinct `detail` strings ("No active company selected…" vs
  "Requires role: …"). Frontend: (a) → `/onboarding`; (b) → toast + stay/redirect.
- **404** — a scoped `get/update/delete` for a record id that isn't in the caller's company.
  **Deliberately a 404, not 403**, so cross-company ids are indistinguishable from non-existent
  ids (no existence oracle; matches `arteamis-system` returning "not_found_or_cross_tenant").
- **400 (`InvalidInputError`)** — `ScopedRepository` used against a global/unknown table
  (`_assert_scoped`) — a developer bug surfaced loudly, mapped to 400 by the existing handler in
  `api/main.py`.
- Cross-company denial is logged at **WARNING** with `company_id`+`record_id` (no audit table yet).

## Testing (concrete test cases)

### `tests/test_tenant_leakage.py` — mirrors `arteamis-system/backend/tests/test_projects_rls.py` and `test_X3_suite1_tenant_leakage.py`
Fixtures seed two companies `company:A` / `company:B`, a user + membership in each, and build
`AuthContext`/tokens for both (`_headers(company="A"|"B")`, like `test_X3_suite1`'s `_headers`).
Run against a real SurrealDB test DB (mirrors the `TEST_DATABASE_URL` skip guard).

1. **`test_company_b_cannot_list_company_a_projects`** — seed `project` in A; `GET /projects`
   with B's token returns `[]` (A's project absent). The direct analogue of
   `test_second_tenant_cannot_see_first_tenants_project`.
2. **`test_company_b_cannot_get_company_a_project_by_guessed_id`** — B calls
   `GET /projects/{A_project_id}` with A's real id → **404** (not 200, not 403).
3. **`test_company_b_cannot_update_company_a_project`** — B `PUT /projects/{A_project_id}` → 404,
   and re-reading as A shows the row unchanged (WITH CHECK analogue).
4. **`test_company_b_cannot_delete_company_a_project`** — B `DELETE` → 404; A still sees the row.
5. **`test_company_b_cannot_read_company_a_source_by_guessed_id`** — same as #2 for `source`
   (covers the P5 plane too).
6. **`test_company_b_cannot_read_company_a_notes_and_chat`** — list `note` / `chat_session`
   scoped to B never contains A's rows.
7. **`test_create_stamps_callers_company_not_client_value`** — B POSTs a project with a forged
   body `{"company": "company:A"}`; the created row's `company` is B (server overwrites) — the
   WITH CHECK backstop.
8. **`test_missing_company_token_is_403`** — a valid identity token (no `company_id`) hitting a
   scoped endpoint → 403 "No active company selected".
9. **`test_scoped_repository_rejects_global_table`** — unit test: `ScopedRepository.list("user")`
   raises `InvalidInputError` (contract guard).
10. **`test_unknown_table_fails_closed`** — `ScopedRepository.list("widget")` raises (new table
    must be classified before use).

### `tests/test_scoping_contract.py`
- **`test_no_raw_repo_calls_in_scoped_routers`** — static grep guard described in the developer
  contract; asserts no `repo_query(`/`repo_create(`/`Notebook.get`/`Source.get` outside the
  allowlist. Fails CI on a forgotten scope.

### Frontend — `frontend/src/lib/hooks/use-role.test.ts`, `RoleGate.test.tsx`, `AppSidebar.test.tsx`
- `useRole()` derives `isAdmin` (owner⊇admin), `isMember`, `can()` from store role.
- `<RoleGate allow={['owner','admin']}>` renders children for admin, `null` for member (hide),
  and disabled+tooltip in `disable` mode.
- `AppSidebar` (extend existing `AppSidebar.test.tsx`): a `member` role does not render the
  "Manage" section nor the Create→Notebook item; an `admin` role does.
- All new strings exist in all 7 enforced locales (existing locale-sync test covers this).
- Backend: `uv run pytest tests/`. Frontend: `npm run test && npm run lint && npm run build`.

## Open questions / risks
- **Denial audit table.** `arteamis-system` writes `AuditEvent` on cross-workspace denial
  (`test_X3_suite1_tenant_leakage.py`). P6 only logs at WARNING. A follow-up phase should add a
  SurrealDB `audit_event` table + best-effort write on 404-by-cross-company. Flagged, not built.
- **`source_insight`/`source_embedding` scoping.** These reference a source, not a company,
  directly today. Because **P6 owns no migration** (canonical: P6=none), they get **no** new
  denormalized `company` column here; they are scoped by joining through their parent `source`
  (which in turn resolves company via its `notebook`), matching the "company inherited via parent"
  model in Data model changes. If a future phase wants a denormalized `company` column on them for
  uniform `ScopedRepository` filtering + to keep vector search from joining across companies, that
  column must be added by an **owning-phase migration** (e.g. folded into P5's migration 23), not by
  P6 — and the embedding-rebuild job (`api/routers/embedding_rebuild.py`) would then stamp `company`
  on regenerate. Flagged, not built in P6.
- **`ObjectModel` bypass.** P6 enforces scoping at the router/`ScopedRepository` layer, leaving
  `ObjectModel.get/save` able to touch scoped tables un-scoped. The grep guard
  (`test_scoping_contract.py`) is the mitigation. A stronger fix (a `company_id`-aware base class)
  is deferred to avoid rewriting every domain model in this phase.
- **Search + graph traversals.** Full-text/vector search (`api/routers/search.py`) and the
  `count(<-reference.in)` join style must all route through `repo.raw()` with an explicit
  `company = $company_id`. Each such query needs its own leakage test; the risk is a missed one,
  which the raw-call grep guard + per-feature leakage tests are designed to catch.
- **Token freshness on role change.** If an admin demotes a member, the member's existing access
  token still says `admin` until refresh. Mitigation (P1/P2): short access-token TTL + refresh;
  P6 assumes that and does not re-check role against the DB per request (a deliberate
  performance/complexity trade-off matching `arteamis-system`'s token-baked role).
