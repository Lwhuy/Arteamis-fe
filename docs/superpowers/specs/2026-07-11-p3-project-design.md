# P3 — Project (repurpose Notebook) — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft

## Goal
Repurpose Open Notebook's `notebook` concept as a company-owned **project**. A project belongs to a `company`, has an `owner` (user), and a `default_visibility` (`private|project`). Sources, notes, chat sessions, and insights re-anchor from notebook→project. Backend CRUD becomes company-scoped, with project creation restricted to company `owner`/`admin`. The existing notebooks UI becomes the projects UI (routes/labels/hooks), scoped to the active company. This phase also introduces the `project_member` table (user↔project, role `admin|member`); the invite flow that populates it lands in P4.

## Depends on / Provides
- **Depends on:**
  - P1 (auth): real JWT identity, `user` table, an auth dependency exposing the current user.
  - P2 (company + membership + roles): `company`, `membership`, the company-scoped access token (`sub`, `company_id`, `role`), the `require_role(...)` FastAPI dependency, and the frontend active-company context. P3 consumes these — it does NOT define them.
- **Provides:**
  - `project` (the repurposed `notebook` table) with `company`/`owner`/`default_visibility`, and a company-scoped `/api/projects` CRUD surface.
  - `project_member` table + domain model — the join table P4's invitation-accept flow writes into and P5's source-visibility check reads from.
  - Frontend `projects` feature (routes, hooks, API client, i18n) scoped to the active company.

## Scope (in)
- Additive SurrealDB migration: add `company`, `owner`, `default_visibility` to the `notebook` table; create `project_member`; backfill a default company + owner for pre-existing rows.
- Rename the Python domain class `Notebook`→`Project` (keeping `table_name = "notebook"`).
- New `api/routers/projects.py` (company-scoped CRUD) replacing `api/routers/notebooks.py` as the canonical top-level surface, wired through `require_role`.
- New `Project` Pydantic schemas in `api/models.py`; `ProjectMember` domain model.
- Frontend: rename the `notebooks` feature to `projects` (route folder, API module, hooks, query keys, nav label, i18n), reading the active company from the P2 context.

## Out of scope
- **Do NOT rename the SurrealDB table `notebook`, nor the relation tables `reference` / `artifact` / `refers_to`.** They stay; only columns are added (see Decision).
- **Do NOT rename the `notebook_id` path/query/body params in the child routers** (`sources.py`, `notes.py`, `chat.py`, `context.py`, `search.py`). Those params keep their name in P3 and now simply carry project IDs (same table, same IDs). A cosmetic `notebook_id`→`project_id` param rename is a later, optional cleanup — pulling it into P3 would multiply the blast radius for zero behavioural gain.
- Source `owner`/`visibility` columns and enforcement — that is **P5**.
- The invitation lifecycle that populates `project_member` — that is **P4**. P3 only creates the table + model and lets a project owner see themselves as the sole `admin` member (seeded at create time).
- Tenant-leakage hardening / app-layer `company_id` scoping helper and frontend role-gating — that is **P6**. P3 scopes queries by `company` directly; P6 generalizes the pattern.

## Decision: keep table `notebook`, expose "project" everywhere else

**Recommendation: repurpose in place. Keep the SurrealDB table named `notebook` and the three relation tables (`reference`, `artifact`, `refers_to`) exactly as defined in `1.surrealql`. Add columns via an additive migration. Rename only the Python domain class (`Notebook`→`Project`, `table_name` stays `"notebook"`), the API path (`/notebooks`→`/projects`), and the frontend feature.**

Justification (lower-risk path):
1. **Relations are typed to the table.** `1.surrealql` defines `reference TYPE RELATION FROM source TO notebook`, `artifact TYPE RELATION FROM note TO notebook`, and `refers_to` (chat_session→notebook). Renaming the table forces redefining all three relation tables and every graph query in `open_notebook/domain/notebook.py` (`<-reference.in`, `<-artifact.in`, `->reference`, `refers_to` traversals).
2. **Record IDs are the table name.** Every existing record is `notebook:<ulid>` and every edge in `reference`/`artifact`/`refers_to` stores those IDs in `in`/`out`. A table rename in SurrealDB is not a metadata op — it means copying every record to a new table and rewriting every edge, with real risk of dangling edges. Additive column changes carry none of that risk.
3. **Fixed migration history.** Migrations 1–18 are hard-coded and already applied in every existing deployment (`AsyncMigrationManager` in `open_notebook/database/async_migrate.py`). A rename would have to reconcile with that immutable history; an additive migration 21 is clean.
4. **IDs are already opaque at the boundary.** `api/routers/notebooks.py` returns `str(nb["id"])` and the frontend treats it as an opaque string in URLs (`/notebooks/[id]`). The `notebook:` prefix is never shown as meaningful text, so keeping it costs nothing at the product surface.
5. **Polymorphic resolution still works.** `ObjectModel.get()` (`open_notebook/domain/base.py`) resolves the subclass from the ID prefix via `_get_class_by_table_name("notebook")`. With `Project.table_name = "notebook"`, `notebook:` IDs resolve to `Project` — no breakage.

Net: the only *irreducible* churn is (a) one additive migration, (b) a Python class rename, (c) an API path rename + new schemas, (d) the frontend feature rename. Everything downstream of the table (sources/notes/chat/insights/search) keeps working untouched because the table, its IDs, and its relations are unchanged.

## Data model changes (SurrealDB migration 21)

Register in `open_notebook/database/async_migrate.py` (`AsyncMigrationManager.up_migrations` / `down_migrations`) — migrations are hard-coded, not auto-discovered.

`open_notebook/database/migrations/21.surrealql`:
```surql
-- Migration 21: Repurpose notebook as company-owned project + project_member.
-- The notebook table and its relations (reference/artifact/refers_to) are kept;
-- we only ADD governance columns and a member join table.

-- New columns on the repurposed notebook(=project) table.
DEFINE FIELD IF NOT EXISTS company            ON TABLE notebook TYPE option<record<company>>;
DEFINE FIELD IF NOT EXISTS owner              ON TABLE notebook TYPE option<record<user>>;
DEFINE FIELD IF NOT EXISTS default_visibility ON TABLE notebook TYPE string
    ASSERT $value INSIDE ["private", "project"] DEFAULT "private";

-- Query path: list projects for the active company, newest first.
DEFINE INDEX IF NOT EXISTS idx_notebook_company ON TABLE notebook FIELDS company;

-- project_member: user <-> project (= notebook) with a project-level role.
DEFINE TABLE IF NOT EXISTS project_member SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS project  ON TABLE project_member TYPE record<notebook>;
DEFINE FIELD IF NOT EXISTS user     ON TABLE project_member TYPE record<user>;
DEFINE FIELD IF NOT EXISTS role     ON TABLE project_member TYPE string
    ASSERT $value INSIDE ["admin", "member"] DEFAULT "member";
DEFINE FIELD IF NOT EXISTS status   ON TABLE project_member TYPE string
    ASSERT $value INSIDE ["active", "invited", "revoked"] DEFAULT "active";
DEFINE FIELD IF NOT EXISTS created  ON project_member DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated  ON project_member DEFAULT time::now() VALUE time::now();
-- One membership row per (user, project).
DEFINE INDEX IF NOT EXISTS idx_project_member_unique ON TABLE project_member FIELDS user, project UNIQUE;

-- Backfill (runs only when pre-auth notebooks exist): P3 OWNS this seed — the
-- Default Company is created HERE, in migration 21, NOT by P2. P2's migration (20)
-- only defines the empty company/membership tables; it seeds no data. This keeps
-- the backfill self-contained and removes the P2↔P3 record-id coupling.
-- Owner = the first existing user (the first admin/user to have registered). If no
-- user exists yet at migration time (pure pre-auth data), owner/membership stay
-- NONE and are claimed by the first user to register (P2 onboarding, documented
-- handoff); the Default Company + notebook.company assignment still happen here so
-- no project is ever orphaned once queries become company-scoped.
LET $legacy = (SELECT VALUE id FROM notebook WHERE company = NONE);
IF array::len($legacy) > 0 {
    LET $owner = (SELECT VALUE id FROM user ORDER BY created ASC LIMIT 1)[0];
    -- deterministic ids so re-running the migration is idempotent
    UPSERT company:default SET
        name = "Default Company", slug = "default-company", owner = $owner;
    IF $owner != NONE {
        UPSERT membership:default_owner SET
            user = $owner, company = company:default, role = "owner", status = "active";
    };
    UPDATE notebook SET
        company = company:default, owner = $owner, default_visibility = "private"
    WHERE company = NONE;
    -- Seed the owner as the sole admin member of each backfilled project.
    FOR $nb IN (SELECT id, owner FROM notebook WHERE owner != NONE) {
        IF (SELECT id FROM project_member WHERE project = $nb.id AND user = $nb.owner) = [] {
            CREATE project_member SET project = $nb.id, user = $nb.owner, role = "admin", status = "active";
        };
    };
};
```

`open_notebook/database/migrations/21_down.surrealql`:
```surql
-- Remove the seed this migration created (safe: only touches the default ids).
DELETE membership:default_owner;
DELETE company:default;
REMOVE INDEX IF EXISTS idx_project_member_unique ON TABLE project_member;
REMOVE TABLE IF EXISTS project_member;
REMOVE INDEX IF EXISTS idx_notebook_company ON TABLE notebook;
REMOVE FIELD IF EXISTS default_visibility ON TABLE notebook;
REMOVE FIELD IF EXISTS owner ON TABLE notebook;
REMOVE FIELD IF EXISTS company ON TABLE notebook;
```

> Backfill note: the Default Company (`company:default`) and its owner membership (`membership:default_owner`) are created **by this migration (21)**, not by P2. There is therefore no record-id handshake to reconcile with P2 — P3 is self-contained. The only soft edge remaining: if no `user` row exists at migration time (pure pre-auth data with zero registered users), the default company's `owner` is left `NONE` and the first user to complete P2 onboarding claims it; existing notebooks are still assigned to `company:default` so nothing is orphaned.

## Backend: endpoints, services, domain models (file paths)

### Domain — `open_notebook/domain/notebook.py`
- Rename class `Notebook` → `Project`, keep `table_name: ClassVar[str] = "notebook"`. Add fields: `company: Optional[str]`, `owner: Optional[str]`, `default_visibility: Literal["private","project"] = "private"`. Keep `name`, `description`, `archived`, `last_viewed_at` and every existing method (`get_sources`, `get_notes`, `get_context`, `get_chat_sessions`, `get_delete_preview`, `delete`) unchanged — they operate on the same relations.
- Update the internal method names that read "notebook" only for clarity if cheap (`Source.add_to_notebook`, `Note.add_to_notebook`, `ChatSession.relate_to_notebook`); functionally they still `relate("reference"|"artifact"|"refers_to", project_id)`. **Keep them as-is in P3** to bound churn — they already take an opaque id.
- Add `ProjectMember(ObjectModel)` with `table_name = "project_member"`, fields `project`, `user`, `role`, `status`, plus `@classmethod get_for_project(project_id)` and `@classmethod get_for_user(user_id)` helpers (mirror `SourceInsight.get_for_sources` query shape).
- Keep a module-level alias `Notebook = Project` **only if** a lighter-touch rollout is wanted; the checklist below assumes a clean rename of importers, which is preferred for clarity in P5/P6.

### Schemas — `api/models.py`
- Add `ProjectCreate` (`name`, `description`, optional `default_visibility`), `ProjectUpdate` (`name?`, `description?`, `archived?`, `default_visibility?`), `ProjectResponse` (existing NotebookResponse fields + `company`, `owner`, `default_visibility`), `ProjectMemberResponse`. Keep the old `Notebook*` schemas until every importer moves, or replace them and update `context.py`/`chat.py`/`notes.py`/`sources.py` imports (they mostly don't import these — verify).
- `RecentlyViewedResponse.type` Literal currently `["notebook","source"]` → add `"project"` (or switch the notebook branch to emit `"project"`); update `_recently_viewed_notebook`.

### Router — `api/routers/projects.py` (new, replaces `notebooks.py` at `/api`)
All endpoints take the P2 auth dependency and scope by `company_id` from the token. Reuse the existing query bodies from `notebooks.py`, adding a `WHERE company = $company_id` filter and, on create, stamping `company`/`owner`/`default_visibility` + seeding a `project_member` admin row.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/projects` | any active member | `SELECT ... FROM notebook WHERE company = $company_id ORDER BY ...` + source/note counts (keep the `order_by` allowlist). |
| POST | `/projects` | `require_role("owner","admin")` | create `Project(company=company_id, owner=user_id, default_visibility=...)`, then `CREATE project_member` (owner, role `admin`). |
| GET | `/projects/{id}` | member of project OR company owner/admin | 404 if not in company; stamp `last_viewed_at` (existing `_stamp_notebook_view`). |
| PUT | `/projects/{id}` | project admin OR company owner/admin | reuse update body; guard company match first. |
| DELETE | `/projects/{id}` | project admin OR company owner/admin | reuse cascade `delete(delete_exclusive_sources=...)`; also `DELETE project_member WHERE project = $id`. |
| GET | `/projects/{id}/delete-preview` | as DELETE | unchanged logic. |
| POST | `/projects/{id}/sources/{source_id}` | project admin/member | unchanged relate logic. |
| DELETE | `/projects/{id}/sources/{source_id}` | project admin/member | unchanged. |
| GET | `/recently-viewed` | any active member | filter notebooks by `company = $company_id`. |

- Register in `api/main.py` (`from api.routers import projects`; `app.include_router(projects.router, prefix="/api", tags=["projects"])`) and drop the `notebooks` include (or keep it temporarily as a deprecated alias — recommend dropping to avoid an unscoped surface, since it currently has NO company filter and would be a tenant-leak hole).
- `api/notebook_service.py`: rename to `project_service.py` / `ProjectService` (used by the API-client shim); update `api/client.py` `get_notebooks`/`get_notebook` accessors if they hit `/notebooks`.

### Company-scoping enforcement (P3-local, generalized in P6)
Every project query filters on the token's `company_id`; every `{id}` route first confirms the target row's `company == company_id` (404 otherwise, to avoid leaking existence). Project-level role checks read `project_member` (owner/admin of the company bypass, per the RBAC table below).

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

Rename the `notebooks` feature to `projects`. All HTTP stays on the single `apiClient`; hooks keep the TanStack Query shape (invalidate + sonner toast).

- **Routes:** `frontend/src/app/(dashboard)/notebooks/` → `.../projects/` (`page.tsx`, `[id]/page.tsx`, and the `components/` folder — `NotebookList`, `NotebookCard`, `NotebookRow`, `NotebookHeader`, `NotebookDeleteDialog`, `SourcesColumn`, `NotesColumn`, `ChatColumn`, `RecentlyViewed`, `NoteEditorDialog`, `ChatColumn.test.tsx`). Rename components to `Project*` (mechanical).
- **API client:** `frontend/src/lib/api/notebooks.ts` → `projects.ts` — point at `/projects`, rename `notebooksApi`→`projectsApi`, methods keep signatures.
- **Hooks:** `frontend/src/lib/hooks/use-notebooks.ts` → `use-projects.ts` (`useProjects`, `useProject`, `useCreateProject`, `useUpdateProject`, `useProjectDeletePreview`, `useDeleteProject`). Toast keys move to `projects.*`.
- **Query keys:** `frontend/src/lib/api/query-client.ts` — add `projects` / `project(id)` keys (keep child keys `notes(notebookId)`, `sources(notebookId)`, `notebookChatSessions(...)` as-is since their params still carry project ids; renaming them is optional cleanup).
- **Types:** `frontend/src/lib/types/api.ts` — add `ProjectResponse` (with `company`, `owner`, `default_visibility`), `CreateProjectRequest`, `UpdateProjectRequest`, `ProjectDeletePreview`, `ProjectDeleteResponse`, `ProjectMemberResponse`.
- **Stores:** `frontend/src/lib/stores/notebook-view-store.ts` → `project-view-store.ts`, `notebook-columns-store.ts` → `project-columns-store.ts` (rename persisted `name` keys — localStorage collision rule). `frontend/src/lib/hooks/useNotebookChat.ts` → `useProjectChat.ts`. `frontend/src/lib/types/notebook-context.ts` → `project-context.ts`.
- **Nav:** `frontend/src/components/layout/AppSidebar.tsx` line ~56 — `href: '/notebooks'` → `'/projects'`, label `t('navigation.notebooks')` → `t('navigation.projects')`; update `AppSidebar.test.tsx`.
- **Cross-feature consumers (update imports + labels):** `frontend/src/components/notebooks/CreateNotebookDialog.tsx` → `projects/CreateProjectDialog.tsx`; `frontend/src/components/sources/steps/NotebooksStep.tsx`, `SourceTypeStep.tsx`, `ProcessingStep.tsx`, `AddSourceDialog.tsx`, `SourceCard.tsx`; `frontend/src/components/source/NotebookAssociations.tsx`, `SourceDetailContent.tsx`; `frontend/src/components/search/SaveToNotebooksDialog.tsx`; `frontend/src/components/podcasts/GeneratePodcastDialog.tsx`; `frontend/src/components/common/ContextToggle.tsx`, `CommandPalette.tsx`; `frontend/src/components/providers/ModalProvider.tsx`. These import `useNotebooks`/labels — repoint to `use-projects` and `projects.*` strings.
- **Active company scope:** `useProjects` reads the active company from the P2 context (the company-scoped token already carries `company_id`, auto-injected by `apiClient`); switching company must invalidate `QUERY_KEYS.projects`. Wire the invalidation into P2's switch-company mutation (cross-phase note).
- **i18n (all 7 enforced locales — en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN — in `frontend/src/lib/locales/`):** add a `projects.*` section mirroring today's `notebooks.*` (`title`, `create`, `createSuccess`, `updateSuccess`, `deleteSuccess`, `empty`, `namePlaceholder`, `defaultVisibility.private`, `defaultVisibility.project`, delete-dialog strings) and `navigation.projects`. Keep `notebooks.*` only if any un-migrated string remains; goal is full replacement.

## Permissions / RBAC rules (explicit)

Company roles from P2: `owner|admin|member`. Project roles from `project_member`: `admin|member`. Enforced at the application layer (no SurrealDB RLS).

| Action | Company owner | Company admin | Company member (project admin) | Company member (project member) | Company member (no project row) |
|---|---|---|---|---|---|
| List projects (own company) | ✅ | ✅ | ✅ (sees projects they belong to) | ✅ (sees projects they belong to) | ✅ (sees none) |
| **Create project** | ✅ | ✅ | ❌ | ❌ | ❌ |
| View a project | ✅ | ✅ | ✅ | ✅ | ❌ (403) |
| Update project (name/desc/visibility/archive) | ✅ | ✅ | ✅ | ❌ | ❌ |
| Delete project | ✅ | ✅ | ✅ | ❌ | ❌ |
| Add/remove source ↔ project | ✅ | ✅ | ✅ | ✅ | ❌ |
| Manage project members | ✅ | ✅ | ✅ | ❌ | ❌ | (populate flow = P4) |
| Any project in another company | ❌ 404 | ❌ 404 | ❌ 404 | ❌ 404 | ❌ 404 |

Stated defaults (from the brief, user may flip later): **project creation is limited to company owner/admin — members are invited into projects.** `default_visibility` defaults to `private`. (Source-level `private` visibility semantics — visible to owner + company owner/admin + the project's admins — are defined and enforced in **P5**; P3 only stores `default_visibility` on the project.)

## Error handling (per the shared contract)
- 401 unauthenticated → frontend clears `auth-storage`, redirect `/login`.
- 403 wrong role (non owner/admin creating a project; project member editing/deleting) → `{ "detail": "..." }`.
- 404 project not found **or in another company** (existence hidden across tenants).
- 400 invalid input (empty name — reuse `Project.name` validator; bad `order_by`; bad `default_visibility`).
- 409 duplicate `project_member` (unique `(user, project)` index) — relevant when P4 writes members; P3's create-seed guards with an existence check first.
- Backend raises typed exceptions from `open_notebook.exceptions` (mapped by global handlers); `require_role` raises the P2 403. Consistent `{ "detail": "..." }` body.

## Testing (concrete)
Backend (`uv run pytest tests/`):
1. `test_migration_21_backfill`: existing companyless notebook gets `company:default` + `owner` + a seeded `admin` project_member; `default_visibility` defaults `private`; down-migration removes columns/table cleanly.
2. `test_project_create_requires_owner_admin`: company `member` token → 403; `admin`/`owner` → 201 and a `project_member(admin, active)` row for the creator.
3. `test_project_list_company_scoped`: user in company A cannot see company B's projects (tenant-leakage test, mirrors `test_X3_suite1_tenant_leakage.py`).
4. `test_project_get_cross_company_404`: fetching another company's project id → 404 (not 403 — existence hidden).
5. `test_project_update_delete_role_gate`: project `member` → 403 on PUT/DELETE; project `admin` / company admin → success.
6. `test_project_source_relations_intact`: add/remove source, get_sources/get_notes/get_context, delete-cascade still work (proves the kept `reference`/`artifact` relations are unaffected).
7. `test_recently_viewed_company_scoped`: only the active company's projects appear.

Frontend (`npm run test` / `lint` / `build`):
8. `use-projects` hooks hit `/projects`, invalidate `QUERY_KEYS.projects`, toast on success/error.
9. Renamed `ChatColumn.test.tsx` + `AppSidebar.test.tsx` pass with `navigation.projects`.
10. i18n guard: every new `projects.*` / `navigation.projects` key exists in all 7 enforced locales (missing-key check).
11. Switching active company refetches the projects list (invalidation wired to P2 switch-company).

## Full blast radius — files touched (checklist)

**Backend — migrations**
- [ ] `open_notebook/database/migrations/21.surrealql` (new)
- [ ] `open_notebook/database/migrations/21_down.surrealql` (new)
- [ ] `open_notebook/database/async_migrate.py` (register 21 in up/down lists)

**Backend — domain / schemas / routers / services**
- [ ] `open_notebook/domain/notebook.py` (`Notebook`→`Project` + fields; add `ProjectMember`)
- [ ] `api/models.py` (`Project*` schemas; `RecentlyViewedResponse.type` += `"project"`)
- [ ] `api/routers/projects.py` (new, company-scoped; replaces notebooks router)
- [ ] `api/routers/notebooks.py` (delete, or keep as deprecated alias — recommend delete)
- [ ] `api/main.py` (imports + `include_router`; drop `notebooks`)
- [ ] `api/notebook_service.py` → `api/project_service.py`
- [ ] `api/client.py` (any `get_notebooks`/`/notebooks` accessors → `/projects`)
- [ ] Import-only updates (class rename `Notebook`→`Project`): `api/routers/context.py`, `api/routers/chat.py`, `api/routers/notes.py`, `api/routers/sources.py`, `api/routers/search.py` (imports `text_search`/`vector_search` — unaffected but verify), plus any `commands/` or `open_notebook/` modules importing `Notebook` (grep `from open_notebook.domain.notebook import`). **`notebook_id` params in these routers stay named as-is (out of scope).**

**Frontend — routes / components**
- [ ] `frontend/src/app/(dashboard)/notebooks/` → `.../projects/` (page.tsx, [id]/page.tsx, all `components/*`, `ChatColumn.test.tsx`)
- [ ] `frontend/src/components/notebooks/CreateNotebookDialog.tsx` → `projects/CreateProjectDialog.tsx`
- [ ] `frontend/src/components/layout/AppSidebar.tsx` + `AppSidebar.test.tsx`
- [ ] Cross-feature consumers: `frontend/src/components/sources/steps/{NotebooksStep,SourceTypeStep,ProcessingStep}.tsx`, `sources/{AddSourceDialog,SourceCard}.tsx`, `source/{NotebookAssociations,SourceDetailContent}.tsx`, `search/SaveToNotebooksDialog.tsx`, `podcasts/GeneratePodcastDialog.tsx`, `common/{ContextToggle,CommandPalette}.tsx`, `providers/ModalProvider.tsx`

**Frontend — lib**
- [ ] `frontend/src/lib/api/notebooks.ts` → `projects.ts`
- [ ] `frontend/src/lib/hooks/use-notebooks.ts` → `use-projects.ts`
- [ ] `frontend/src/lib/hooks/useNotebookChat.ts` → `useProjectChat.ts`
- [ ] `frontend/src/lib/api/query-client.ts` (`projects`/`project(id)` keys)
- [ ] `frontend/src/lib/types/api.ts` (`Project*` types + `company`/`owner`/`default_visibility`)
- [ ] `frontend/src/lib/types/notebook-context.ts` → `project-context.ts`
- [ ] `frontend/src/lib/stores/notebook-view-store.ts` → `project-view-store.ts`
- [ ] `frontend/src/lib/stores/notebook-columns-store.ts` → `project-columns-store.ts`
- [ ] Active-company invalidation hook (coordinate with P2 switch-company mutation)

**Frontend — i18n**
- [ ] `frontend/src/lib/locales/{en-US,pt-BR,zh-CN,zh-TW,ja-JP,ru-RU,bn-IN}/` — add `projects.*` + `navigation.projects` (7 enforced locales; repo has 16 files — update the enforced 7 at minimum per AGENTS.md)

## Open questions / risks
- **Default-company backfill (resolved):** the previously-flagged "highest-risk cross-phase dependency" — who creates the default company — is now settled: **migration 21 creates `company:default` + `membership:default_owner` itself** (P2 seeds nothing). Owner = the first existing `user`. The only residual edge is the zero-users-at-migration-time case (owner left `NONE`, claimed on first P2 onboarding), which orphans nothing because notebooks are still assigned to `company:default`. P5's source backfill (migration 23) leans on the same mechanism: legacy sources inherit their company via their (now-backfilled) notebook.
- **`default_visibility` field type:** declared non-optional with `DEFAULT "private"` so every project has a value; existing rows are set by the backfill. If any project can precede the backfill in a live system, keep it `option<string>` and default in the domain model instead. Recommend the migration-default shown.
- **Alias vs clean rename of the `Notebook` class:** a `Notebook = Project` alias reduces the immediate import churn but leaves stale vocabulary that P5/P6 will trip over. Recommend the clean rename (checklist assumes it); the alias is a fallback if the rename destabilizes the build.
- **Child-router param naming debt:** `notebook_id` params persist in `sources.py`/`notes.py`/`chat.py`/`context.py` and carry project ids. This is intentional scope-bounding but is a readability smell; schedule a cosmetic `notebook_id`→`project_id` rename as a post-P6 cleanup once the tenant model is stable.
- **`refers_to` overload:** `ChatSession.relate_to_source` and `relate_to_notebook` both use the `refers_to` relation. Re-anchoring chat to project is free (same table), but any future project-vs-source disambiguation on `refers_to` must not assume the target table — it currently distinguishes by traversal direction only.
