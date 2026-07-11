# P2 — Company + Membership + Roles + Onboarding — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft

## Goal (2-4 sentences)
Introduce the company (tenant boundary) and membership (user↔company with a role) tables, and the flows that let a
just-authenticated user with zero companies create their first one and become its `owner`. Ship the three backend
endpoints that back this (`POST /companies`, `GET /companies`, `POST /auth/switch-company/{id}`) plus a
`require_role(*roles)` FastAPI dependency that gates owner/admin-only endpoints in later phases. On the frontend, ship a
first-run onboarding wizard (create company → hand off to P3 for the first project), a company switcher, and expose the
active company + role through the existing Zustand auth store so any component can role-gate. No project, invitation, or
source machinery is built here.

## Depends on / Provides
**Depends on (P1 — auth + users):**
- Migration `19.surrealql` creating the `user` and `auth_identity` tables (identity plane). P2's migration (`20`) lands *after* it.
- Token helpers in `api/security.py` (P1 owns this file):
  `create_identity_token(user_id) -> str` (JWT with `sub` only) and the
  `create_access_token(user_id, company_id, role) -> str` stub (JWT with `sub`, `company_id`, `role`) that **P2 implements**, plus
  `decode_identity_token` / `decode_access_token`, the `AuthContext` dataclass (`user_id`, `company_id`, `role`), and refresh-cookie plumbing.
- The JWT auth middleware (P1) that populates `request.state.user_id`.
- `GET /auth/me` returning `{ user, memberships }` and the frontend `auth-store` (Zustand, persisted under localStorage key
  `auth-storage`) already holding `token`; P1 extends it to hold `user`, `memberships`, `activeCompanyId`, `role`.

**Provides (to P3–P6):**
- `company` + `membership` tables and the `Company` / `Membership` domain models.
- **A new `api/deps.py` module** introduced by P2, holding the shared FastAPI auth dependencies: `get_identity() -> str`
  (user_id from an identity **or** access token — the pre-company dependency), `get_auth_context() -> AuthContext`
  (requires a company-scoped token; wraps P1's `decode_access_token`), and the `require_role(*roles)` factory
  (owner|admin|member gate) reused by P3 (project create), P4 (invitations), P5/P6. **P6 extends this same module**
  with `require_company` + `get_request_context` + the `ScopedRepository` wiring and reuses `require_role` unchanged.
- The company-scoped access token minted on create/switch — every company-scoped endpoint in later phases reads
  `company_id` from it via `get_auth_context`.
- Frontend: `activeCompanyId` + `role` in the auth store and `useCompanies()` / `useSwitchCompany()` hooks.

## Scope (in) / Out of scope
**In:** `company` + `membership` migration; `Company`/`Membership` domain models; `company_service.py`;
`POST /companies`, `GET /companies`, `POST /auth/switch-company/{id}`; `require_role`; company-scoped token re-mint on
create/switch; slug generation + uniqueness (409); onboarding wizard route + company step; company switcher; auth-store
company slice; `useCompanies`/`useCreateCompany`/`useSwitchCompany` hooks; i18n keys in all 7 locales; dashboard-layout
"no company → /onboarding" guard.

**Out of scope:** email/password + Google login and `user`/`auth_identity` tables (P1); project create — the wizard's
"first project" step is a **hand-off to P3**, not built here; invitations / inviting members into a company (P4); source
ownership + visibility (P5); the application-layer `company_id` tenant-scoping helper and per-route leakage enforcement
across content endpoints (P6). P2 only enforces role at the endpoints it introduces.

## Data model changes (SurrealDB migration 20.surrealql + _down)
New files:
- `open_notebook/database/migrations/20.surrealql`
- `open_notebook/database/migrations/20_down.surrealql`
- Register both in `open_notebook/database/async_migrate.py` `AsyncMigrationManager.__init__` (append to `up_migrations`
  and `down_migrations` — migrations are hard-coded, not auto-discovered; current highest is 18, P1 adds 19, P2 adds 20).

`20.surrealql` (mirrors the SCHEMAFULL + `IF NOT EXISTS` style of `1.surrealql`/`18.surrealql`):
```surrealql
-- Migration 20: company + membership (multi-tenancy identity plane)
-- Identity-plane tables: NOT company-scoped. Login/onboarding must read a user's
-- memberships before any company is active, so these carry no tenant filter.

DEFINE TABLE IF NOT EXISTS company SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name  ON TABLE company TYPE string;
DEFINE FIELD IF NOT EXISTS slug  ON TABLE company TYPE string;
DEFINE FIELD IF NOT EXISTS owner ON TABLE company TYPE record<user>;
DEFINE FIELD IF NOT EXISTS created ON company DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON company DEFAULT time::now() VALUE time::now();
-- slug uniqueness → drives the 409 contract
DEFINE INDEX IF NOT EXISTS idx_company_slug ON TABLE company FIELDS slug UNIQUE;

DEFINE TABLE IF NOT EXISTS membership SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS user    ON TABLE membership TYPE record<user>;
DEFINE FIELD IF NOT EXISTS company ON TABLE membership TYPE record<company>;
DEFINE FIELD IF NOT EXISTS role    ON TABLE membership TYPE string
    ASSERT $value IN ['owner', 'admin', 'member'];
DEFINE FIELD IF NOT EXISTS status  ON TABLE membership TYPE string
    ASSERT $value IN ['active', 'invited', 'revoked'] DEFAULT 'active';
DEFINE FIELD IF NOT EXISTS created ON membership DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON membership DEFAULT time::now() VALUE time::now();
-- one membership per (user, company); also the lookup index for switch/list
DEFINE INDEX IF NOT EXISTS idx_membership_user_company ON TABLE membership FIELDS user, company UNIQUE;
```
`20_down.surrealql`:
```surrealql
REMOVE TABLE IF EXISTS membership;
REMOVE TABLE IF EXISTS company;
```
Notes: `slug` unique index is the source of the 409. `(user, company)` unique index prevents duplicate memberships and
backs the O(1) `switch-company` membership re-verify. Roles/statuses match the brief exactly
(owner|admin|member, active|invited|revoked) — `invited`/`revoked` are written by P4; P2 only ever creates `active`.

## Backend: endpoints, services, domain models (file paths)

### Domain models — `open_notebook/domain/company.py` (new)
Subclass `ObjectModel` from `open_notebook/domain/base.py` (like `open_notebook/domain/notebook.py`), so `save()`/`get()`/
`get_all()`/`delete()` and the `created`/`updated` handling come for free.
```python
class Company(ObjectModel):
    table_name: ClassVar[str] = "company"
    name: str
    slug: str
    owner: str            # "user:<id>" record link

class Membership(ObjectModel):
    table_name: ClassVar[str] = "membership"
    user: str             # "user:<id>"
    company: str          # "company:<id>"
    role: str             # owner|admin|member
    status: str = "active"
```
`ObjectModel.get()` resolves subclasses by ID prefix, so `open_notebook/domain/company.py` must be imported at app
startup (add to `open_notebook/domain/__init__.py`) for polymorphic `get()` to find it.

### Schemas — add to `api/models.py`
```python
class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: Optional[str] = None          # optional explicit slug; else derived from name

class CompanyResponse(BaseModel):
    id: str
    name: str
    slug: str
    role: str                           # caller's role in this company
    created: str
    updated: str

class TokenResponse(BaseModel):         # returned by create + switch
    access_token: str
    token_type: str = "bearer"
    active_company_id: str
    role: str
```

### Service — `api/company_service.py` (new; routes-thin, logic-here per api/AGENTS.md)
- `slugify(name: str) -> str`: lower-case, `[^a-z0-9]+ → "-"`, strip dashes, truncate to 40 (pattern lifted from
  `arteamis-system/backend/app/api/companies.py::_slugify`, but WITHOUT the random uuid suffix — we keep slugs
  human-readable and let the unique index reject collisions with a 409).
- `async def create_company(user_id, name, slug=None) -> tuple[Company, Membership]`:
  1. `slug = slug or slugify(name)`.
  2. Create `Company(name, slug, owner=f"user:{...}")` via `await company.save()`. A slug collision surfaces as a
     SurrealDB unique-index error from `repo_*`; catch it and raise `InvalidInputError`-adjacent → 409 (see Error handling).
  3. Create `Membership(user=user_id, company=company.id, role="owner", status="active")` via `await membership.save()`.
  4. Return both. (Best-effort: if membership save fails, delete the just-created company to avoid an orphan.)
- `async def list_memberships(user_id) -> list[dict]`: `repo_query` joining membership→company, `status = 'active'`,
  returning `{company_id, name, slug, role}` rows for the switcher / `GET /companies`.
- `async def get_membership(user_id, company_id) -> Optional[Membership]`: single-row lookup on the
  `(user, company)` index; used by `switch-company` to re-verify server-side.

### Router — `api/routers/companies.py` (new; registered in `api/main.py` alongside the others)
Mirrors `api/routers/notebooks.py` structure (thin handlers, typed exceptions map to HTTP via global handlers).
- `POST /companies` — `Depends(get_identity)` (identity **or** access token; a first-time user has only an identity
  token). Body `CompanyCreate`. Calls `create_company`, then **re-mints a company-scoped access token** for the new
  company and returns `TokenResponse` (see token flow). `status_code=201`.
- `GET /companies` — `Depends(get_identity)`. Returns `List[CompanyResponse]` from `list_memberships` (the caller's
  active memberships only). Works pre-company (empty list when the user has none).

### Router additions — `api/routers/auth.py` (P1 owns this file; P2 adds one endpoint)
- `POST /auth/switch-company/{company_id}` — `Depends(get_identity)`. Calls `get_membership`; if `None` or
  `status != 'active'` → 403. Else re-mint a company-scoped token and return `TokenResponse`. (Mirrors
  `arteamis-system/backend/app/api/auth.py::switch_company`, adapted to identity-token dependency + membership re-verify.)

### Dependency — `require_role(*roles)` in a **new** `api/deps.py` (introduced by P2, alongside `get_identity` + `get_auth_context`)
P2 creates `api/deps.py` (the module P6 later extends with `require_company`/`get_request_context`/`ScopedRepository`). It holds
`get_identity`, `get_auth_context` (both built on P1's `api/security.py` decoders + `AuthContext`), and the `require_role`
factory below — a dependency that reads the caller's company-scoped `AuthContext` and 403s if `role` not in `roles`
(direct port of `arteamis-system/backend/app/api/deps.py::require_role`):
```python
def require_role(*roles: str):
    allowed = set(roles)
    async def _dep(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if ctx.role not in allowed:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(sorted(allowed))}")
        return ctx
    return _dep
```
Not consumed by any P2 endpoint (create/switch are identity-level, open to any authenticated user); it is the RBAC
primitive P3+ import, e.g. `Depends(require_role("owner", "admin"))` on project-create.

### Token re-mint flow (exact)
Two token shapes exist (per the brief's token model): the **identity token** (`sub` only) and the **company-scoped
access token** (`sub`, `company_id`, `role`).

**On `POST /companies` (create):**
1. Caller arrives with an identity token (user has 0 companies) → `get_identity` yields `user_id`.
2. Service creates `company` + owner `membership`.
3. Handler calls `create_access_token(user_id, company_id=company.id, role="owner")`.
4. Response `TokenResponse{ access_token, active_company_id=company.id, role="owner" }`.
5. Frontend replaces the stored token in `auth-store` with `access_token` — subsequent requests (P3 project create) are
   now company-scoped. **This is the swap point** that authorizes the wizard's next step.

**On `POST /auth/switch-company/{id}` (switch):**
1. `get_identity` yields `user_id` (accepts the currently-active company-scoped token too).
2. `get_membership(user_id, id)` re-verifies an **active** membership server-side (never trust a client-sent role).
3. `create_access_token(user_id, company_id=id, role=membership.role)`.
4. Response `TokenResponse`; frontend swaps token + `activeCompanyId` + `role` in the store.

The refresh token (httpOnly cookie, P1) is unchanged by switching — refresh re-mints against the user's first/active
membership. Switching only changes the in-memory/localStorage access token.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

### API module — `frontend/src/lib/api/companies.ts` (new; uses the shared `apiClient`, never a 2nd axios instance)
```ts
export const companiesApi = {
  list:   () => apiClient.get<CompanyResponse[]>('/companies').then(r => r.data),
  create: (data: CreateCompanyRequest) => apiClient.post<TokenResponse>('/companies', data).then(r => r.data),
  switch: (companyId: string) =>
    apiClient.post<TokenResponse>(`/auth/switch-company/${companyId}`).then(r => r.data),
}
```
Types `CompanyResponse`, `CreateCompanyRequest`, `TokenResponse` added to `frontend/src/lib/types/api.ts`.

### Store — extend `frontend/src/lib/stores/auth-store.ts` (P1 reshapes it; P2 adds the company slice)
Add to the persisted Zustand store (keep the `auth-storage` name; `apiClient` reads `state.token` from it):
- state: `memberships: Membership[]`, `activeCompanyId: string | null`, `role: string | null`.
- `setSession(payload)` (from P1's `/auth/me` / login): sets `memberships` + `activeCompanyId` (first active membership,
  or `null`) + derives `role`.
- `applyToken(res: TokenResponse)`: sets `token = res.access_token`, `activeCompanyId = res.active_company_id`,
  `role = res.role` — the single mutation used by both create and switch.
- selector `needsOnboarding = isAuthenticated && memberships.length === 0`.
Respect the `hasHydrated` guard before rendering persisted company state (frontend/AGENTS.md SSR rule).

### Hooks — `frontend/src/lib/hooks/use-companies.ts` (new; TanStack Query shape like `use-notebooks.ts`)
- `useCompanies()` → `useQuery({ queryKey: QUERY_KEYS.companies, queryFn: companiesApi.list })`.
- `useCreateCompany()` → `useMutation(companiesApi.create)`; `onSuccess`: `applyToken(res)`, invalidate
  `QUERY_KEYS.companies`, toast `t('company.createSuccess')`. `onError`: toast `getApiErrorKey(error, ...)` (409 → a
  dedicated `company.slugTaken` message).
- `useSwitchCompany()` → `useMutation(companiesApi.switch)`; `onSuccess`: `applyToken(res)`, then
  `queryClient.clear()` (a company change invalidates ALL company-scoped caches), toast, and navigate to the dashboard.
- Add `companies: ['companies'] as const` to `QUERY_KEYS` in `frontend/src/lib/api/query-client.ts`.

### Routes / components
- `frontend/src/app/onboarding/page.tsx` (new, top-level route — outside `(dashboard)` because the dashboard requires an
  active company). First-run wizard, structure mirrors `arteamis-system/app/onboarding/page.tsx` (two step-dots: 1 Company
  → 2 Project) but only **step 1 (company)** is implemented here; step 2 is a stub that immediately hands off to P3's
  project-create (P3 fills it in). On successful create, `useCreateCompany` swaps the token; the wizard then routes to the
  P3 project step (until P3 exists, route to `/notebooks`).
- `frontend/src/components/onboarding/OnboardingWizard.tsx`, `CompanyStep.tsx` (new) — presentational; strings via `t()`.
- `frontend/src/components/company/CompanySwitcher.tsx` (new) — a dropdown listing `memberships` (name + role badge) with
  a check on `activeCompanyId`; selecting one calls `useSwitchCompany`. Mounted in the dashboard sidebar/header
  (`frontend/src/app/(dashboard)/layout.tsx` chrome).
- Guard in `frontend/src/app/(dashboard)/layout.tsx`: extend the existing `useEffect` (currently only redirects
  unauthenticated → `/login`) so that `isAuthenticated && needsOnboarding` → `router.push('/onboarding')`, and
  `isAuthenticated && !activeCompanyId && memberships.length > 0` → auto-select first membership (call switch or
  `setActiveCompany`).

### i18n keys — add to ALL 7 enforced locales under `frontend/src/lib/locales/`
(en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN — missing keys silently fall back to en-US, so add to every file):
- `onboarding.title`, `onboarding.welcome`, `onboarding.companyStepTitle`, `onboarding.stepCompany`,
  `onboarding.stepProject`, `onboarding.createCompanyCta`.
- `company.nameLabel`, `company.namePlaceholder`, `company.slugLabel`, `company.slugHelp`,
  `company.createSuccess`, `company.slugTaken`, `company.switchLabel`, `company.switchSuccess`,
  `company.roleOwner`, `company.roleAdmin`, `company.roleMember`, `company.switcherEmpty`.

## Permissions / RBAC rules (explicit table: who can do what)

| Action | Endpoint | Auth token required | Who is allowed | Resulting role / effect |
|---|---|---|---|---|
| Create a company | `POST /companies` | Identity **or** access token (any authenticated user) | Any authenticated user, incl. one with 0 companies | Creator becomes **`owner`** (active membership); a company-scoped `owner` token is minted |
| List my companies | `GET /companies` | Identity or access token | Any authenticated user (sees only their own `active` memberships) | Read-only; empty list when none |
| Switch active company | `POST /auth/switch-company/{id}` | Identity or access token | Only a user with an **`active`** membership in `{id}`; else 403 | Company-scoped token re-minted with that membership's role |
| Role-gated endpoints (P3+) | via `Depends(require_role(...))` | Company-scoped access token | Caller whose token `role` ∈ allowed set; else 403 | e.g. `require_role("owner","admin")` for project create, invites |

**Rules stated explicitly (per brief's "write defaults explicitly"):**
- The user who creates a company is always its `owner`. Exactly one owner is created at creation time. (Ownership transfer
  is out of scope.)
- Company creation is open to **any** authenticated user — there is no role gate on create (you cannot require a role you
  do not yet have). The role gate begins at company-scoped actions (P3+).
- `require_role` reads the role baked into the **access token** at create/switch time, never a client-supplied value; a
  revoked/removed membership takes effect on the next switch or refresh (documented risk below).
- `member` is the default role for future invited users (P4); P2 never mints `admin`/`member` — only `owner` on create.

## Error handling
Follows the brief's contract and `api/AGENTS.md` (raise typed exceptions → global handlers map to HTTP; consistent
`{ "detail": "..." }` body):
- **401** — missing/invalid token on any of these endpoints → P1's dependency raises; frontend `apiClient`/auth-store
  clears `auth-storage` and redirects `/login`.
- **403** — `switch-company` when the caller has no active membership in the target company (`detail: "Not a member of
  this company"`); `require_role` when the token role is not allowed (`detail: "Requires role: ..."`).
- **409** — duplicate company slug. The `idx_company_slug UNIQUE` index rejects the insert; `company_service.create_company`
  catches the unique-violation from `repo_*` and raises so the handler returns `409` with
  `detail: "Company slug already exists"`. Frontend maps 409 → `t('company.slugTaken')` and lets the user rename.
- **400** — empty/invalid `name` (Pydantic `min_length=1`) → 422/400 per FastAPI validation.
- No 410 in P2 (invitations are P4).

## Testing (concrete test cases)
**Backend — `tests/` (`uv run pytest tests/`), new `tests/test_p2_company_membership.py`:**
1. `POST /companies` with an identity token → 201, response has `access_token` decoding to `{sub, company_id, role:"owner"}`;
   a `company` row and an `active` owner `membership` exist.
2. Creating two companies with names that slugify to the same value → second returns **409** `"Company slug already exists"`.
3. Explicit `slug` in body is honored; a taken explicit slug → 409.
4. `GET /companies` returns only the caller's active memberships; a second user does not see the first user's company
   (identity-plane isolation via explicit `user` filter — precursor to the P6 leakage suite,
   mirroring `arteamis-system` `test_X3_suite1_tenant_leakage.py`).
5. `POST /auth/switch-company/{id}` as a member → 200, token re-minted with the correct role; as a non-member → **403**;
   against a company where membership `status='revoked'` → 403.
6. `require_role`: endpoint wrapped in `require_role("owner")` returns 200 for an owner token, **403** for a member token,
   **401** for an identity-only token (no company scope).
7. Migration up/down: apply `20.surrealql`, assert `company`/`membership` tables + unique indexes exist; apply
   `20_down.surrealql`, assert both tables removed.

**Frontend — `frontend/` (`npm run test` vitest, `npm run lint`, `npm run build`):**
1. `useCreateCompany` success calls `applyToken` (token/activeCompanyId/role updated) and invalidates `companies`.
2. `useSwitchCompany` success swaps token and clears the query cache.
3. Dashboard-layout guard: authenticated + `needsOnboarding` redirects to `/onboarding`; with an active company, renders.
4. `CompanySwitcher` lists memberships with role badges and marks `activeCompanyId`.
5. i18n: every new key exists in all 7 enforced locales (extend the existing locale-parity test in
   `frontend/src/lib/locales/index.test.ts`).

## Open questions / risks
- **Slug policy chosen:** human-readable slug derived from name, unique-index-enforced, 409 on collision (user renames).
  Alternative (arteamis-system behavior) is auto-appending a random suffix so create never 409s — rejected here to keep
  slugs clean and satisfy the brief's explicit "409 duplicate company slug" contract. Flag for the user to flip.
- **Stale role in token:** because `require_role` trusts the token, a membership revoked mid-session keeps its old role
  until the next switch/refresh. Acceptable for P2 (short-lived access tokens); P6 may add a per-request membership check
  for sensitive actions.
- **Migration numbering coupling:** P2's migration number (20) assumes P1 takes 19 for `user`/`auth_identity`. If P1's
  number shifts, renumber P2's file and its `async_migrate.py` registration accordingly — the number must be the next
  free integer, contiguous.
- **`company`/`membership` on the identity plane, not tenant-scoped:** isolation depends entirely on explicit `user`/
  `company` filters in `company_service` queries (SurrealDB has no RLS). Any query that forgets the `user` filter leaks
  memberships — covered by test case 4 and hardened project-wide in P6.
- **Auto-select on multiple companies:** the layout auto-selects the first active membership when none is active. Whether
  to instead restore the last-used company (persist `activeCompanyId`) is a UX call deferred; the store already persists
  it, so restore-last is a small follow-up.
