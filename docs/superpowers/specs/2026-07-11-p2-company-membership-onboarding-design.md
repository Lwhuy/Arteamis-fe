# P2 — Workspace + Membership + Roles + Onboarding — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft (v2 — workspace model)

> Supersedes the earlier "company-only" draft of this spec. Ground truth: the shared
> `ARCHITECTURE_BRIEF.md` v2 revision — **Personal Mode is the default; creating a
> company is optional.** The tenant entity is `workspace` (`kind = "personal" | "company"`),
> not `company`. See "Naming" below for the verbatim renames this spec enforces.

## Goal (2-4 sentences)
Introduce the `workspace` (tenant boundary, `kind = "personal" | "company"`) and `membership`
(user↔workspace with a role) tables, and **auto-provision exactly one personal workspace for
every user at signup/first-login** so a logged-in user always has an active, workspace-scoped
session — no forced setup step. Ship the three backend endpoints for the *optional* company
path (`POST /workspaces`, `GET /workspaces`, `POST /auth/switch-workspace/{id}`) plus a
`require_role(*roles)` FastAPI dependency that gates owner/admin-only endpoints in later
phases. On the frontend, ship a non-blocking onboarding surface (the user lands straight in
their Personal workspace; "Create a company" is an optional next step, not a gate), a
workspace switcher (Personal + companies), and expose the active workspace + role through the
auth store so any component can role-gate. No project, invitation, or source machinery is
built here.

## Naming (use verbatim, everywhere — per brief v2)
- Entity/table: **`workspace`** (NOT `company`). Field `kind` ∈ `{personal, company}`. `slug`
  unique. `owner` → user. `name`.
- Token claim + `AuthContext` field: **`workspace_id`** (NOT `company_id`) + `role`.
- "Company" is a product/UI word for a `kind="company"` workspace; the DB/API/token always say
  `workspace`. A **personal workspace** is a `kind="personal"` workspace with exactly one member
  (its owner) — it is never listed as a "company" in the UI.

## Depends on / Provides
**Depends on (P1 — auth + users):**
- Migration `19.surrealql` creating the `user` and `auth_identity` tables (identity plane). P2's
  migration (`20`) lands *after* it.
- Token helpers in `api/security.py` (P1 owns this file): `create_identity_token(user_id) -> str`
  (JWT with `sub` only) and the `create_access_token(user_id, workspace_id, role) -> str` stub
  (JWT with `sub`, `workspace_id`, `role`) that **P2 implements**, plus `decode_identity_token` /
  `decode_access_token`, the `AuthContext` dataclass (`user_id`, `workspace_id`, `role`), and
  refresh-cookie plumbing.
  **Naming assumption (stated per the brief's v2 terminology patch):** P1's stub/`AuthContext`
  are assumed to already use `workspace_id` (not `company_id`) — the brief mandates this rename
  project-wide. If P1 has not yet been patched and still emits `company_id`, rename that one
  field in `api/security.py` before starting Task 4; every other line in this plan is unaffected.
- `auth_service.build_session_payload(user) -> dict` (P1) returning
  `{ access_token, token_type, needs_onboarding: True, active_workspace_id: None, user,
  memberships: [] }` — an **identity-only** token, since P1 ends before any workspace exists.
  **P2 rewrites this function (Task 6)** so it always returns a **workspace-scoped** token.
- The JWT auth middleware (P1) that populates `request.state.user_id`.
- `GET /auth/me` returning `{ user, memberships }` and the frontend `auth-store` (Zustand,
  persisted under localStorage key `auth-storage`) already holding `token`; P1 extends it to
  hold `user`. P2 adds `memberships`, `activeWorkspaceId`, `role`.

**Provides (to P3–P6):**
- `workspace` + `membership` tables and the `Workspace` / `Membership` domain models.
- **`ensure_personal_workspace(user_id) -> Workspace`** in `api/workspace_service.py` — the
  idempotent get-or-create that guarantees every user has exactly one `kind="personal"`
  workspace. This is where personal-workspace provisioning lives; P3's migration 21 (backfilling
  pre-existing notebooks) mirrors the identical lookup semantics in raw SurrealQL (it cannot call
  this Python helper directly from a migration) — a `SELECT * FROM workspace WHERE owner = $user
  AND kind = 'personal'` lookup, never a hardcoded id.
  **Cross-phase note (P2 ↔ P3):** because this lookup keys on `(owner, kind='personal')` and
  never on a hardcoded record id, if migration 21 has already self-seeded a fixed-id
  `workspace:personal_default` for the first pre-existing user (see P3's spec/plan), the *next*
  time that same user logs in, this function finds and reuses that exact row — it never creates a
  duplicate personal workspace for them.
- **A new `api/deps.py` module** introduced by P2, holding the shared FastAPI auth dependencies:
  `get_identity() -> str` (user_id from an identity **or** access token — the pre-workspace
  dependency), `get_auth_context() -> AuthContext` (requires a workspace-scoped token; wraps
  P1's `decode_access_token`), and the `require_role(*roles)` factory (owner|admin|member gate)
  reused by P3 (project create), P4 (invitations), P5/P6. **P6 extends this same module** with
  `require_workspace` + `get_request_context` + the `ScopedRepository` wiring and reuses
  `require_role` unchanged.
- The workspace-scoped access token minted on login/create/switch — every workspace-scoped
  endpoint in later phases reads `workspace_id` from it via `get_auth_context`.
- Frontend: `activeWorkspaceId` + `role` + `memberships` (each carrying `kind`) in the auth
  store and `useWorkspaces()` / `useCreateWorkspace()` / `useSwitchWorkspace()` hooks.
- The `kind` field on `workspace`, which P3 (project ownership), P4 (invite guard — "cannot
  invite into a personal workspace"), and P5 (source-scope collapse in a personal workspace)
  all branch on.

## Scope (in) / Out of scope
**In:** `workspace` (+`kind`) + `membership` migration; `Workspace`/`Membership` domain models;
`workspace_service.py` (`slugify`, `ensure_personal_workspace`, `create_workspace`,
`list_memberships`, `get_membership`); wiring `ensure_personal_workspace` into
`auth_service.build_session_payload` so every login/register response carries a
workspace-scoped token; `POST /workspaces` (creates a `kind="company"` workspace only —
`kind` is never client-settable), `GET /workspaces` (lists ALL the caller's active
memberships, personal included), `POST /auth/switch-workspace/{id}`; `require_role`;
workspace-scoped token re-mint on login/create/switch; slug generation + uniqueness (409);
a non-blocking onboarding surface (personal landing + optional "create a company" step);
workspace switcher (Personal + companies); auth-store workspace slice; `useWorkspaces` /
`useCreateWorkspace` / `useSwitchWorkspace` hooks; i18n keys in all 14 locales; dashboard
renders immediately post-login (no forced redirect) with a defensive auto-select fallback.

**Out of scope:** email/password + Google login and `user`/`auth_identity` tables (P1);
project create — the onboarding wizard's "first project" step is a **hand-off to P3**, not
built here; invitations / inviting members into a company workspace (P4) — P2 only delivers
the `kind` field P4's invite guard checks, it does not implement the guard's endpoint;
source ownership + visibility (P5); the application-layer `workspace_id` tenant-scoping helper
and per-route leakage enforcement across content endpoints (P6). P2 only enforces role at the
endpoints it introduces. **Persisting a "last active workspace" across logins is explicitly
NOT built** (see Open questions) — every fresh login/register resets the active workspace to
Personal; switching to a company is a per-session action.

## Data model changes (SurrealDB migration 20.surrealql + _down)
New files:
- `open_notebook/database/migrations/20.surrealql`
- `open_notebook/database/migrations/20_down.surrealql`
- Register both in `open_notebook/database/async_migrate.py` `AsyncMigrationManager.__init__`
  (append to `up_migrations` and `down_migrations` — migrations are hard-coded, not
  auto-discovered; current highest is 18, P1 adds 19, P2 adds 20).

`20.surrealql` (mirrors the SCHEMAFULL + `IF NOT EXISTS` style of `1.surrealql`/`18.surrealql`):
```surrealql
-- Migration 20: workspace + membership (multi-tenancy identity plane).
-- Identity-plane tables: NOT workspace-scoped. Login/onboarding must read a user's
-- memberships before any workspace is active, so these carry no tenant filter.
-- workspace.kind distinguishes a solo "personal" tenant (auto-provisioned at
-- signup, exactly one member: its owner) from an explicitly-created "company"
-- tenant that supports invites + RBAC (P4+).

DEFINE TABLE IF NOT EXISTS workspace SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name  ON TABLE workspace TYPE string;
DEFINE FIELD IF NOT EXISTS slug  ON TABLE workspace TYPE string;
DEFINE FIELD IF NOT EXISTS kind  ON TABLE workspace TYPE string ASSERT $value IN ['personal', 'company'];
DEFINE FIELD IF NOT EXISTS owner ON TABLE workspace TYPE record<user>;
DEFINE FIELD IF NOT EXISTS created ON workspace DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON workspace DEFAULT time::now() VALUE time::now();
-- slug uniqueness → drives the 409 contract (personal-workspace slugs are
-- deterministic per user — see ensure_personal_workspace — so they never collide).
DEFINE INDEX IF NOT EXISTS idx_workspace_slug ON TABLE workspace FIELDS slug UNIQUE;

DEFINE TABLE IF NOT EXISTS membership SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS user      ON TABLE membership TYPE record<user>;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE membership TYPE record<workspace>;
DEFINE FIELD IF NOT EXISTS role      ON TABLE membership TYPE string
    ASSERT $value IN ['owner', 'admin', 'member'];
DEFINE FIELD IF NOT EXISTS status    ON TABLE membership TYPE string
    ASSERT $value IN ['active', 'invited', 'revoked'] DEFAULT 'active';
DEFINE FIELD IF NOT EXISTS created ON membership DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON membership DEFAULT time::now() VALUE time::now();
-- one membership per (user, workspace); also the lookup index for switch/list
DEFINE INDEX IF NOT EXISTS idx_membership_user_workspace ON TABLE membership FIELDS user, workspace UNIQUE;
```
`20_down.surrealql`:
```surrealql
-- Migration 20 rollback: drop membership first (references workspace), then workspace.
REMOVE TABLE IF EXISTS membership;
REMOVE TABLE IF EXISTS workspace;
```
Notes: `slug` unique index is the source of the 409 for **company** creation. `(user, workspace)`
unique index prevents duplicate memberships and backs the O(1) `switch-workspace` membership
re-verify. Roles/statuses match the brief exactly (owner|admin|member, active|invited|revoked)
— `invited`/`revoked` are written by P4; P2 only ever creates `active`. `kind` is the field P3
(project ownership), P4 (invite guard), and P5 (source-scope collapse) all branch on; P2 writes
it but does not itself gate any endpoint on it beyond "you cannot request a personal workspace
through `POST /workspaces`" (see Backend below).

## Backend: endpoints, services, domain models (file paths)

### Domain models — `open_notebook/domain/workspace.py` (new)
Subclass `ObjectModel` from `open_notebook/domain/base.py` (like `open_notebook/domain/notebook.py`),
so `save()`/`get()`/`get_all()`/`delete()` and the `created`/`updated` handling come for free.
```python
class Workspace(ObjectModel):
    table_name: ClassVar[str] = "workspace"
    name: str
    slug: str
    kind: str             # "personal" | "company"
    owner: str             # "user:<id>" record link

class Membership(ObjectModel):
    table_name: ClassVar[str] = "membership"
    user: str              # "user:<id>"
    workspace: str          # "workspace:<id>"
    role: str               # owner|admin|member
    status: str = "active"
```
`ObjectModel.get()` resolves subclasses by ID prefix, so `open_notebook/domain/workspace.py` must
be imported at app startup (add to `open_notebook/domain/__init__.py`) for polymorphic `get()` to
find it.

### Schemas — add to `api/models.py`
```python
class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: Optional[str] = None          # optional explicit slug; else derived from name
    # NOTE: no `kind` field — POST /workspaces always creates kind="company".
    # A client cannot request a personal workspace; those are auto-provisioned
    # server-side by ensure_personal_workspace at signup/login.

class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    kind: str                           # "personal" | "company"
    role: str                           # caller's role in this workspace
    created: str
    updated: str

class TokenResponse(BaseModel):         # returned by create + switch (+ reused by login/register)
    access_token: str
    token_type: str = "bearer"
    active_workspace_id: str
    role: str
```

### Service — `api/workspace_service.py` (new; routes-thin, logic-here per api/AGENTS.md)
- `slugify(name: str) -> str`: lower-case, `[^a-z0-9]+ → "-"`, strip dashes, truncate to 40
  (pattern lifted from `arteamis-system/backend/app/api/companies.py::_slugify`, but WITHOUT the
  random uuid suffix — we keep slugs human-readable and let the unique index reject collisions
  with a 409).
- `async def ensure_personal_workspace(user_id: str) -> Workspace`: **idempotent get-or-create**.
  1. `SELECT * FROM workspace WHERE owner = $user AND kind = 'personal' LIMIT 1` — a personal
     workspace's owner IS its sole member, so `(owner, kind='personal')` uniquely identifies it;
     if found, return it (no-op on every subsequent login).
  2. Else create `Workspace(name="Personal", slug=f"personal-{user_local_id}", kind="personal",
     owner=user_id)`. The slug is **deterministic per user** (derived from the user's own record
     id, not the display name), so it can never collide across users and needs no random suffix.
  3. On a slug-conflict save error (only possible under a concurrent double-call for the same
     user), re-select and return the row created by the other call — idempotent under races.
  4. Create the owner `Membership(user=user_id, workspace=workspace.id, role="owner",
     status="active")` if one doesn't already exist (re-select before insert — see Task 3 for
     the exact guard), then return the workspace.
  This is the ONLY place a `kind="personal"` workspace is ever created; there is no API endpoint
  for it (contrast with `create_workspace` below, which is `POST /workspaces` and always
  `kind="company"`).
- `async def create_workspace(user_id, name, slug=None) -> tuple[Workspace, Membership]`:
  1. `slug = slugify(slug) if slug else slugify(name)`.
  2. Create `Workspace(name, slug, kind="company", owner=f"user:{...}")` via `await
     workspace.save()`. A slug collision surfaces as a SurrealDB unique-index error from
     `repo_*`; catch it and raise `DuplicateResourceError` → 409.
  3. Create `Membership(user=user_id, workspace=workspace.id, role="owner", status="active")` via
     `await membership.save()`. Return both. (Best-effort: if membership save fails, delete the
     just-created workspace to avoid an orphan.)
- `async def list_memberships(user_id) -> list[dict]`: `repo_query` joining membership→workspace,
  `status = 'active'`, returning `{workspace_id, name, slug, kind, role}` rows for the switcher /
  `GET /workspaces` / the session payload. Ordered `created ASC` — because
  `ensure_personal_workspace` always runs (and therefore the personal workspace is always
  created) before any company workspace, the personal one is always first in this list.
- `async def get_membership(user_id, workspace_id) -> Optional[Membership]`: single-row lookup on
  the `(user, workspace)` index; used by `switch-workspace` to re-verify server-side. Works
  identically whether `workspace_id` refers to a personal or a company workspace — switching
  *into* your own personal workspace is ordinary, expected behavior, not a special case.

### `ensure_personal_workspace` wiring — `api/auth_service.py` (P1 owns this file; P2 rewrites `build_session_payload`)
```python
async def build_session_payload(user: User) -> dict:
    personal = await ensure_personal_workspace(str(user.id))
    memberships = await list_memberships(str(user.id))
    has_company = any(m["kind"] == "company" for m in memberships)
    access_token = create_access_token(
        user_id=str(user.id), workspace_id=personal.id or "", role="owner"
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        # Repurposed (was a hard-coded P1 placeholder): no longer gates the
        # dashboard — a user ALWAYS has an active workspace after this call.
        # The frontend reads it only to show a dismissible, optional
        # "Create a company" prompt on first login (has_company == False).
        "needs_onboarding": not has_company,
        "active_workspace_id": personal.id,
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name},
        "memberships": memberships,
    }
```
**Default decision, stated explicitly:** every successful `register`/`login`/`refresh` call resets
the *active* workspace to Personal, even for a user who also owns companies. Restoring the
last-used workspace across logins is a deferred UX enhancement (see Open questions) — switching
to a company is always a fresh, per-session action via `POST /auth/switch-workspace/{id}`.
This function is called by every P1 endpoint that returns a `SessionPayload`
(`register`, `login`, `refresh`, the Google callback's user-creation path) — P2 does not touch
those call sites, only the shared payload builder they all funnel through.

### Router — `api/routers/workspaces.py` (new; registered in `api/main.py` alongside the others)
Mirrors `api/routers/notebooks.py` structure (thin handlers, typed exceptions map to HTTP via
global handlers).
- `POST /workspaces` — `Depends(get_identity)` (identity **or** access token — any authenticated
  user, including one who has only ever used their personal workspace). Body `WorkspaceCreate`.
  Calls `create_workspace` (always `kind="company"`), then **re-mints a workspace-scoped access
  token** for the new company and returns `TokenResponse`. `status_code=201`.
- `GET /workspaces` — `Depends(get_identity)`. Returns `List[WorkspaceResponse]` from
  `list_memberships` (the caller's active memberships **including their personal workspace**) —
  never empty for an authenticated user, since `ensure_personal_workspace` guarantees at least
  one row.

### Router additions — `api/routers/auth.py` (P1 owns this file; P2 adds one endpoint)
- `POST /auth/switch-workspace/{workspace_id}` — `Depends(get_identity)`. Calls
  `get_membership`; if `None` or `status != 'active'` → 403. Else re-mint a workspace-scoped
  token and return `TokenResponse`. Works uniformly for personal and company workspace ids — no
  `kind` branch needed here (mirrors `arteamis-system/backend/app/api/auth.py::switch_company`,
  adapted to identity-token dependency + membership re-verify + workspace naming).

### Dependency — `require_role(*roles)` in a **new** `api/deps.py` (introduced by P2, alongside `get_identity` + `get_auth_context`)
P2 creates `api/deps.py` (the module P6 later extends with `require_workspace`/
`get_request_context`/`ScopedRepository`). It holds `get_identity`, `get_auth_context` (both
built on P1's `api/security.py` decoders + `AuthContext`), and the `require_role` factory below —
a dependency that reads the caller's workspace-scoped `AuthContext` and 403s if `role` not in
`roles` (direct port of `arteamis-system/backend/app/api/deps.py::require_role`, renamed):
```python
def require_role(*roles: str):
    allowed = set(roles)
    async def _dep(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(sorted(allowed))}")
        return ctx
    return _dep
```
Not consumed by any P2 endpoint (create/switch are identity-level, open to any authenticated
user); it is the RBAC primitive P3+ import, e.g. `Depends(require_role("owner", "admin"))` on
project-create. A personal workspace's sole member always holds `role="owner"`, so
`require_role("owner")` on a personal-workspace-scoped request always passes for that workspace's
owner — there is no separate "solo" role.

### Guardrail: "cannot invite into / cannot treat personal as company" (documented now, enforced starting P4)
P2 delivers the mechanism (`workspace.kind`) this guardrail is built on but does not itself
implement an invite endpoint (that is P4's scope). Two concrete, P2-owned enforcement points
exist today:
1. `WorkspaceCreate` has **no `kind` field** — `POST /workspaces` cannot be used to create or
   relabel a workspace as `kind="personal"`; the service hardcodes `kind="company"`. This is the
   entire "cannot treat personal as company" guard that is P2's to build; the rest ("cannot
   invite into a personal workspace") is P4's 403 check against `workspace.kind` before writing
   an `invitation` row — P4's spec must cite this field.
2. `GET /workspaces` returns `kind` on every row so the frontend can render a personal workspace
   distinctly (no "Invite" affordance, no role badge beyond "Owner") well before P4 ships.

### Token re-mint flow (exact)
Two token shapes exist (per the brief's token model): the **identity token** (`sub` only) and the
**workspace-scoped access token** (`sub`, `workspace_id`, `role`). Because `ensure_personal_workspace`
runs on every login/register, a logged-in user is (almost) never holding a bare identity token in
normal use — the only place one is minted standalone is transiently by P1's identity-token helper
itself, and by `POST /workspaces`'s `Depends(get_identity)` accepting either shape from a caller
who is switching or creating.

**On `POST /workspaces` (create a company):**
1. Caller arrives with a workspace-scoped token (their personal workspace, or another company)
   → `get_identity` yields `user_id` regardless of which token shape it decodes.
2. Service creates `workspace` (`kind="company"`) + owner `membership`.
3. Handler calls `create_access_token(user_id, workspace_id=workspace.id, role="owner")`.
4. Response `TokenResponse{ access_token, active_workspace_id=workspace.id, role="owner" }`.
5. Frontend replaces the stored token in `auth-store` with `access_token` — subsequent requests
   (P3 project create) are now scoped to the new company. **This is the swap point** that
   authorizes the optional wizard's next step.

**On `POST /auth/switch-workspace/{id}` (switch, incl. switching back to Personal):**
1. `get_identity` yields `user_id` (accepts the currently-active workspace-scoped token too).
2. `get_membership(user_id, id)` re-verifies an **active** membership server-side (never trust a
   client-sent role).
3. `create_access_token(user_id, workspace_id=id, role=membership.role)`.
4. Response `TokenResponse`; frontend swaps token + `activeWorkspaceId` + `role` in the store.

The refresh token (httpOnly cookie, P1) is unchanged by switching — refresh re-mints against the
user's Personal workspace (`build_session_payload` always resets to Personal; see the default
decision above). Switching only changes the in-memory/localStorage access token for the current
session.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

### API module — `frontend/src/lib/api/workspaces.ts` (new; uses the shared `apiClient`, never a 2nd axios instance)
```ts
export const workspacesApi = {
  list:   () => apiClient.get<WorkspaceResponse[]>('/workspaces').then(r => r.data),
  create: (data: CreateWorkspaceRequest) => apiClient.post<TokenResponse>('/workspaces', data).then(r => r.data),
  switch: (workspaceId: string) =>
    apiClient.post<TokenResponse>(`/auth/switch-workspace/${workspaceId}`).then(r => r.data),
}
```
Types `WorkspaceResponse`, `CreateWorkspaceRequest`, `TokenResponse`, `Membership` (now carrying
`kind`) added to `frontend/src/lib/types/api.ts`.

### Store — extend `frontend/src/lib/stores/auth-store.ts` (P1 reshapes it; P2 adds the workspace slice)
Add to the persisted Zustand store (keep the `auth-storage` name; `apiClient` reads `state.token`
from it):
- state: `memberships: Membership[]`, `activeWorkspaceId: string | null`, `role: string | null`.
- `setSession(payload)` (from P1's `/auth/me` / login/register/refresh): sets `memberships` +
  `activeWorkspaceId` (the session payload's `active_workspace_id` — always the Personal
  workspace on a fresh login, see the default decision above) + derives `role` from the matching
  membership.
- `applyToken(res: TokenResponse)`: sets `token = res.access_token`, `activeWorkspaceId =
  res.active_workspace_id`, `role = res.role` — the single mutation used by both create and
  switch.
- selector `hasCompany = memberships.some(m => m.kind === 'company')` — used ONLY to show an
  optional, dismissible "Create a company" prompt; it never gates rendering or navigation. There
  is deliberately **no** `needsOnboarding`-style boolean that blocks the dashboard — every
  authenticated user always has `activeWorkspaceId` set (their personal workspace, at minimum)
  the moment `setSession` runs.
Respect the `hasHydrated` guard before rendering persisted workspace state (frontend/AGENTS.md
SSR rule).

### Hooks — `frontend/src/lib/hooks/use-workspaces.ts` (new; TanStack Query shape like `use-notebooks.ts`)
- `useWorkspaces()` → `useQuery({ queryKey: QUERY_KEYS.workspaces, queryFn: workspacesApi.list })`.
- `useCreateWorkspace()` → `useMutation(workspacesApi.create)`; `onSuccess`: `applyToken(res)`,
  invalidate `QUERY_KEYS.workspaces`, toast `t('workspace.createSuccess')`. `onError`: toast
  `getApiErrorKey(error, ...)` (409 → a dedicated `workspace.slugTaken` message).
- `useSwitchWorkspace()` → `useMutation(workspacesApi.switch)`; `onSuccess`: `applyToken(res)`,
  then `queryClient.clear()` (a workspace change invalidates ALL workspace-scoped caches),
  toast, and navigate to the dashboard.
- Add `workspaces: ['workspaces'] as const` to `QUERY_KEYS` in
  `frontend/src/lib/api/query-client.ts`.

### Routes / components
- `frontend/src/app/onboarding/page.tsx` (new, top-level route). Unlike the superseded
  company-only draft, this is **never a forced redirect target** — the dashboard renders
  immediately after login regardless of whether the user has visited it. It is reachable at any
  time from the workspace switcher's "+ Create a company" entry, or (once, non-blocking) from a
  first-login banner when `!hasCompany`. Structure mirrors
  `arteamis-system/app/onboarding/page.tsx` (two step-dots: 1 Company → 2 Project) but:
  step 0 is a **Personal-landing welcome** ("You're all set — this is your Personal workspace")
  with two explicit actions, "Create a company" (→ step 1) and "Skip, go to my workspace" (→
  `/notebooks`); step 1 (company) is implemented here; step 2 is a stub that immediately hands
  off to P3's project-create (P3 fills it in). On successful create, `useCreateWorkspace` swaps
  the token; the wizard then routes to the P3 project step (until P3 exists, route to
  `/notebooks`).
- `frontend/src/components/onboarding/OnboardingWizard.tsx`, `WelcomeStep.tsx`,
  `CompanyStep.tsx` (new) — presentational; strings via `t()`.
- `frontend/src/components/workspace/WorkspaceSwitcher.tsx` (new) — a dropdown listing
  `memberships` (Personal first — labeled distinctly via `kind === 'personal'`, then companies
  with name + role badge) with a check on `activeWorkspaceId`, plus a trailing "+ Create a
  company" row that links to `/onboarding`; selecting an existing membership calls
  `useSwitchWorkspace`. Mounted in the dashboard sidebar/header
  (`frontend/src/app/(dashboard)/layout.tsx` chrome).
- No forced guard in `frontend/src/app/(dashboard)/layout.tsx`: the existing `useEffect`
  (unauthenticated → `/login`) is preserved unchanged. P2 adds only a **defensive** fallback —
  `isAuthenticated && !activeWorkspaceId && memberships.length > 0` → auto-select the first
  membership (covers a corrupted/partial persisted session; should not trigger in the normal
  flow, since `setSession` always sets `activeWorkspaceId` from the payload). There is
  intentionally no `memberships.length === 0` branch, because an authenticated user's
  memberships list is never empty (personal workspace guaranteed) — a truly empty list means
  `/auth/me` failed and belongs to the existing unauthenticated/error path, not an onboarding
  redirect.

### i18n keys — add to ALL 14 locales under `frontend/src/lib/locales/`
(7 enforced get real translations — en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN; the other 7
— it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR — get English-fallback values so the parity
test stays green):
- `onboarding.title`, `onboarding.welcomePersonalTitle`, `onboarding.welcomePersonalBody`,
  `onboarding.createCompanyCta`, `onboarding.skipCta`, `onboarding.companyStepTitle`,
  `onboarding.stepWelcome`, `onboarding.stepCompany`, `onboarding.stepProject`.
- `workspace.nameLabel`, `workspace.namePlaceholder`, `workspace.slugLabel`,
  `workspace.slugHelp`, `workspace.createSuccess`, `workspace.slugTaken`,
  `workspace.switchLabel`, `workspace.switchSuccess`, `workspace.roleOwner`,
  `workspace.roleAdmin`, `workspace.roleMember`, `workspace.personalLabel`,
  `workspace.addCompanyCta`, `workspace.createCompanyBanner`.

## Permissions / RBAC rules (explicit table: who can do what)

| Action | Endpoint | Auth token required | Who is allowed | Resulting role / effect |
|---|---|---|---|---|
| Signup / first login | `POST /auth/register`, `POST /auth/login` (P1) | none / credentials | Any user | `ensure_personal_workspace` runs; caller becomes **`owner`** of a new `kind="personal"` workspace; a workspace-scoped token is minted |
| Create a company | `POST /workspaces` | Identity **or** access token (any authenticated user) | Any authenticated user | Creator becomes **`owner`** (active membership) of a new `kind="company"` workspace; a workspace-scoped `owner` token is minted |
| List my workspaces | `GET /workspaces` | Identity or access token | Any authenticated user (sees only their own `active` memberships) | Read-only; always includes the personal workspace, never empty |
| Switch active workspace | `POST /auth/switch-workspace/{id}` | Identity or access token | Only a user with an **`active`** membership in `{id}` (personal or company); else 403 | Workspace-scoped token re-minted with that membership's role |
| Role-gated endpoints (P3+) | via `Depends(require_role(...))` | Workspace-scoped access token | Caller whose token `role` ∈ allowed set; else 403 | e.g. `require_role("owner","admin")` for project create, invites — only meaningful for `kind="company"`; a personal workspace's sole member is always `owner` |

**Rules stated explicitly (per brief's "write defaults explicitly"):**
- Every user has exactly one personal workspace, auto-created at signup/first-login, and is
  always its sole `owner`. There is no way to have zero workspaces or more than one personal
  workspace.
- Company creation is open to **any** authenticated user — there is no role gate on create (you
  cannot require a role you do not yet have). The role gate begins at workspace-scoped actions
  (P3+).
- A fresh login/register/refresh always resets the active workspace to Personal (the default
  decision above); the user must explicitly `switch-workspace` back into a company each session.
- `require_role` reads the role baked into the **access token** at create/switch time, never a
  client-supplied value; a revoked/removed membership takes effect on the next switch or refresh
  (documented risk below).
- `member` is the default role for future invited users (P4); P2 never mints `admin`/`member` —
  only `owner`, on personal-workspace auto-provision and on company create.
- You cannot create a `kind="personal"` workspace via the API (`WorkspaceCreate` has no `kind`
  field); the invite guard against a personal workspace is P4's to enforce using the `kind` field
  P2 ships.

## Error handling
Follows the brief's contract and `api/AGENTS.md` (raise typed exceptions → global handlers map
to HTTP; consistent `{ "detail": "..." }` body):
- **401** — missing/invalid token on any of these endpoints → P1's dependency raises; frontend
  `apiClient`/auth-store clears `auth-storage` and redirects `/login`.
- **403** — `switch-workspace` when the caller has no active membership in the target workspace
  (`detail: "Not a member of this workspace"`); `require_role` when the token role is not
  allowed (`detail: "Requires role: ..."`).
- **409** — duplicate workspace slug (company creation only — personal-workspace slugs are
  deterministic per user and cannot collide). The `idx_workspace_slug UNIQUE` index rejects the
  insert; `workspace_service.create_workspace` catches the unique-violation from `repo_*` and
  raises so the handler returns `409` with `detail: "Workspace slug already exists"`. Frontend
  maps 409 → `t('workspace.slugTaken')` and lets the user rename.
- **400** — empty/invalid `name` (Pydantic `min_length=1`) → 422/400 per FastAPI validation.
- No 410 in P2 (invitations are P4).

## Testing (concrete test cases)
**Backend — `tests/` (`uv run pytest tests/`), new `tests/test_p2_workspace_membership.py`:**
1. `ensure_personal_workspace(user_id)` called twice returns the SAME workspace both times
   (idempotent get-or-create); a `workspace` row with `kind="personal"` and an `active` owner
   `membership` exist after the first call; the second call performs no additional writes.
2. `POST /auth/login` (or a direct `build_session_payload` unit test) → the response's
   `access_token` decodes to `{sub, workspace_id, role:"owner"}` pointing at the caller's
   personal workspace; `active_workspace_id` matches; `needs_onboarding` is `True` (no company
   yet) and flips to `False` once a company exists.
3. `POST /workspaces` with an identity-or-access token → 201, response has `access_token`
   decoding to `{sub, workspace_id, role:"owner"}` for a NEW `kind="company"` workspace; a
   `workspace` row and an `active` owner `membership` exist; `WorkspaceCreate`'s absence of a
   `kind` field means it is impossible to request `kind="personal"` through this endpoint.
4. Creating two companies with names that slugify to the same value → second returns **409**
   `"Workspace slug already exists"`. Explicit `slug` in body is honored; a taken explicit slug
   → 409.
5. `GET /workspaces` returns the caller's personal workspace **and** every active company
   membership; a second user does not see the first user's workspaces (identity-plane isolation
   via explicit `user` filter — precursor to the P6 leakage suite, mirroring `arteamis-system`
   `test_X3_suite1_tenant_leakage.py`); the list is never empty.
6. `POST /auth/switch-workspace/{id}` as a member → 200, token re-minted with the correct role;
   switching to your OWN personal workspace id works identically (no special-case 403); as a
   non-member → **403**; against a workspace where membership `status='revoked'` → 403.
7. `require_role`: endpoint wrapped in `require_role("owner")` returns 200 for an owner token,
   **403** for a member token, **401** for an identity-only token (no workspace scope).
8. Migration up/down: apply `20.surrealql`, assert `workspace`/`membership` tables + unique
   indexes + the `kind` field assertion exist; apply `20_down.surrealql`, assert both tables
   removed.

**Frontend — `frontend/` (`npm run test` vitest, `npm run lint`, `npm run build`):**
1. `useCreateWorkspace` success calls `applyToken` (token/activeWorkspaceId/role updated) and
   invalidates `workspaces`.
2. `useSwitchWorkspace` success swaps token and clears the query cache.
3. Dashboard-layout: an authenticated session with `memberships = [{kind:'personal', ...}]` and
   no active company renders the dashboard directly (NO redirect to `/onboarding`); a session
   with `activeWorkspaceId: null` but non-empty `memberships` auto-selects the first membership
   (defensive fallback).
4. `WorkspaceSwitcher` lists the personal workspace distinctly from company memberships with role
   badges, marks `activeWorkspaceId`, and exposes a "+ Create a company" entry.
5. i18n: every new key exists in all 14 locales (extend the existing locale-parity test in
   `frontend/src/lib/locales/index.test.ts`).

## Open questions / risks
- **Slug policy chosen:** human-readable slug derived from name (companies) / deterministic from
  user id (personal), unique-index-enforced, 409 on company-slug collision (user renames).
  Alternative (arteamis-system behavior) is auto-appending a random suffix so create never 409s
  — rejected here to keep slugs clean and satisfy the brief's explicit "409 duplicate slug"
  contract. Flag for the user to flip.
- **Stale role in token:** because `require_role` trusts the token, a membership revoked
  mid-session keeps its old role until the next switch/refresh. Acceptable for P2 (short-lived
  access tokens); P6 may add a per-request membership check for sensitive actions.
- **Migration numbering coupling:** P2's migration number (20) assumes P1 takes 19 for
  `user`/`auth_identity`. If P1's number shifts, renumber P2's file and its `async_migrate.py`
  registration accordingly — the number must be the next free integer, contiguous.
- **`workspace`/`membership` on the identity plane, not tenant-scoped:** isolation depends
  entirely on explicit `user`/`workspace` filters in `workspace_service` queries (SurrealDB has
  no RLS). Any query that forgets the `user` filter leaks memberships — covered by test case 5
  and hardened project-wide in P6.
- **No "restore last active workspace" across logins (chosen default, not a bug):** every fresh
  login resets to Personal; a user who spends all their time in one company must
  `switch-workspace` back into it each session. Persisting `activeWorkspaceId` server-side (e.g.
  on the `user` row) and reading it in `build_session_payload` is a small, well-contained future
  enhancement — flagged here rather than built, to keep P2's auth-payload contract simple and
  match the brief's "state the default explicitly" instruction.
- **Personal-workspace slug collision under true concurrency:** `ensure_personal_workspace`'s
  re-select-after-conflict handles the (very unlikely) case of two concurrent first-logins for
  the same brand-new user racing each other; it is not wrapped in a DB transaction (SurrealDB
  offers no easy row lock here), matching the existing best-effort pattern used by
  `create_workspace`'s orphan cleanup.
