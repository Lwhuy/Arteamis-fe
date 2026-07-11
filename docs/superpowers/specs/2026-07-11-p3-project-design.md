# P3 — Project (repurpose Notebook) — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft (v2 — workspace model)

## Goal
Repurpose Open Notebook's `notebook` concept as a **project** that belongs to a `workspace` — either a personal workspace (`kind="personal"`, exactly one member, the owner) or a company workspace (`kind="company"`, `owner|admin|member` roles). A project has an `owner` (user), a `default_source_scope` (`personal|project|company`), and a `promoted_from` provenance hook (schema-only in this phase). Sources, notes, chat sessions, and insights re-anchor from notebook→project (unchanged relations). Backend CRUD becomes workspace-scoped: in a company workspace, project creation is restricted to workspace `owner`/`admin`; in a personal workspace the (sole) owner creates freely. The existing notebooks UI becomes the projects UI (routes/labels/hooks), scoped to the active workspace. This phase also introduces the `project_member` table (user↔project, role `admin|member`) — meaningful only for company-workspace projects (a personal project's only "member" is implicitly its owner); the invite flow that populates it for company projects lands in P4.

## Depends on / Provides
- **Depends on:**
  - P1 (auth): real JWT identity, `user` table, an auth dependency exposing the current user.
  - P2 (workspace + membership + roles): `workspace` (`kind` personal|company), `membership`, the workspace-scoped access token (`sub`, `workspace_id`, `role`), the `require_role(...)` FastAPI dependency in `api/deps.py`, and the frontend active-workspace context (`AuthContext(workspace_id)`). Signup auto-provisions a personal workspace, so a logged-in user always has an active workspace. P3 consumes these — it does NOT define them.
- **Provides:**
  - `project` (the repurposed `notebook` table) with `workspace`/`owner`/`default_source_scope`/`promoted_from`, and a workspace-scoped `/api/projects` CRUD surface.
  - `project_member` table + domain model — the join table P4's invitation-accept flow writes into (for company-workspace projects) and P5's source-visibility check reads from.
  - Frontend `projects` feature (routes, hooks, API client, i18n) scoped to the active workspace, working identically for personal and company workspaces.

## Scope (in)
- Additive SurrealDB migration: add `workspace`, `owner`, `default_source_scope`, `promoted_from` to the `notebook` table; create `project_member`; backfill existing (pre-tenancy) notebooks into the **first existing user's PERSONAL workspace**, self-seeding that personal workspace (and its owner membership) if P2's auto-provisioning hasn't already created one for that user.
- Rename the Python domain class `Notebook`→`Project` (keeping `table_name = "notebook"`).
- New `api/routers/projects.py` (workspace-scoped CRUD) replacing `api/routers/notebooks.py` as the canonical top-level surface, wired through `require_role`/`get_auth_context` (both from P2's `api/deps.py`).
- New `Project` Pydantic schemas in `api/models.py`; `ProjectMember` domain model.
- Frontend: rename the `notebooks` feature to `projects` (route folder, API module, hooks, query keys, nav label, i18n), reading the active workspace from the P2 context.

## Out of scope
- **Do NOT rename the SurrealDB table `notebook`, nor the relation tables `reference` / `artifact` / `refers_to`.** They stay; only columns are added (see Decision).
- **Do NOT rename the `notebook_id` path/query/body params in the child routers** (`sources.py`, `notes.py`, `chat.py`, `context.py`, `search.py`). Those params keep their name in P3 and now simply carry project IDs (same table, same IDs). A cosmetic `notebook_id`→`project_id` param rename is a later, optional cleanup — pulling it into P3 would multiply the blast radius for zero behavioural gain.
- Source `owner`/`scope` columns and enforcement — that is **P5** (source scope has 3 levels: `personal|project|company`; P3 only stores `default_source_scope` on the project).
- The invitation lifecycle that populates `project_member` — that is **P4**. P3 only creates the table + model and lets a project owner see themselves as the sole `admin` member (seeded at create time), regardless of workspace kind.
- The governed promotion review flow (moving a project/source between workspaces) — **not built in this phase**. P3 only adds the `promoted_from` schema hook (an optional self-link) with no read/write logic beyond persisting it.
- Tenant-leakage hardening / app-layer `workspace_id` scoping helper and frontend role-gating — that is **P6**. P3 scopes queries by `workspace` directly; P6 generalizes the pattern.

## Decision: keep table `notebook`, expose "project" everywhere else

**Recommendation: repurpose in place. Keep the SurrealDB table named `notebook` and the three relation tables (`reference`, `artifact`, `refers_to`) exactly as defined in `1.surrealql`. Add columns via an additive migration. Rename only the Python domain class (`Notebook`→`Project`, `table_name` stays `"notebook"`), the API path (`/notebooks`→`/projects`), and the frontend feature.**

Justification (lower-risk path):
1. **Relations are typed to the table.** `1.surrealql` defines `reference TYPE RELATION FROM source TO notebook`, `artifact TYPE RELATION FROM note TO notebook`, and `refers_to` (chat_session→notebook). Renaming the table forces redefining all three relation tables and every graph query in `open_notebook/domain/notebook.py` (`<-reference.in`, `<-artifact.in`, `->reference`, `refers_to` traversals).
2. **Record IDs are the table name.** Every existing record is `notebook:<ulid>` and every edge in `reference`/`artifact`/`refers_to` stores those IDs in `in`/`out`. A table rename in SurrealDB is not a metadata op — it means copying every record to a new table and rewriting every edge, with real risk of dangling edges. Additive column changes carry none of that risk.
3. **Fixed migration history.** Migrations 1–19 are hard-coded and already applied in every existing deployment (`AsyncMigrationManager` in `open_notebook/database/async_migrate.py`). A rename would have to reconcile with that immutable history; an additive migration 21 is clean.
4. **IDs are already opaque at the boundary.** `api/routers/notebooks.py` returns `str(nb["id"])` and the frontend treats it as an opaque string in URLs (`/notebooks/[id]`). The `notebook:` prefix is never shown as meaningful text, so keeping it costs nothing at the product surface.
5. **Polymorphic resolution still works.** `ObjectModel.get()` (`open_notebook/domain/base.py`) resolves the subclass from the ID prefix via `_get_class_by_table_name("notebook")`. With `Project.table_name = "notebook"`, `notebook:` IDs resolve to `Project` — no breakage.

Net: the only *irreducible* churn is (a) one additive migration, (b) a Python class rename, (c) an API path rename + new schemas, (d) the frontend feature rename. Everything downstream of the table (sources/notes/chat/insights/search) keeps working untouched because the table, its IDs, and its relations are unchanged.

## Data model changes (SurrealDB migration 21)

Register in `open_notebook/database/async_migrate.py` (`AsyncMigrationManager.up_migrations` / `down_migrations`) — migrations are hard-coded, not auto-discovered.

`open_notebook/database/migrations/21.surrealql`:
```surql
-- Migration 21: Repurpose notebook as workspace-owned project + project_member.
-- The notebook table and its relations (reference/artifact/refers_to) are kept;
-- we only ADD governance columns and a member join table. A project belongs to
-- a workspace (personal or company, per P2's workspace.kind); project_member is
-- only functionally consulted for company-workspace projects.

DEFINE FIELD IF NOT EXISTS workspace ON TABLE notebook TYPE option<record<workspace>>;
DEFINE FIELD IF NOT EXISTS owner ON TABLE notebook TYPE option<record<user>>;
DEFINE FIELD IF NOT EXISTS default_source_scope ON TABLE notebook TYPE string
    ASSERT $value INSIDE ["personal", "project", "company"] DEFAULT "personal";
DEFINE FIELD IF NOT EXISTS promoted_from ON TABLE notebook TYPE option<record<notebook>>;

-- Query path: list projects for the active workspace, newest first.
DEFINE INDEX IF NOT EXISTS idx_notebook_workspace ON TABLE notebook FIELDS workspace;

-- project_member: user <-> project (= notebook) with a project-level role.
DEFINE TABLE IF NOT EXISTS project_member SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS project ON TABLE project_member TYPE record<notebook>;
DEFINE FIELD IF NOT EXISTS user ON TABLE project_member TYPE record<user>;
DEFINE FIELD IF NOT EXISTS role ON TABLE project_member TYPE string
    ASSERT $value INSIDE ["admin", "member"] DEFAULT "member";
DEFINE FIELD IF NOT EXISTS status ON TABLE project_member TYPE string
    ASSERT $value INSIDE ["active", "invited", "revoked"] DEFAULT "active";
DEFINE FIELD IF NOT EXISTS created ON project_member DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON project_member DEFAULT time::now() VALUE time::now();
-- One membership row per (user, project).
DEFINE INDEX IF NOT EXISTS idx_project_member_unique ON TABLE project_member FIELDS user, project UNIQUE;

-- Backfill (runs only when pre-tenancy notebooks exist): assign every legacy
-- notebook to the FIRST existing user's PERSONAL workspace. P2 auto-provisions
-- a personal workspace on signup/first-login going forward, but a user who
-- registered before P2 shipped may not have one yet, so this migration
-- self-seeds one (idempotent: reuses whichever personal workspace already
-- exists for that user, whether self-seeded on a prior run or auto-provisioned
-- by P2 in the meantime).
LET $legacy = (SELECT VALUE id FROM notebook WHERE workspace = NONE);
IF array::len($legacy) > 0 {
    LET $owner = (SELECT VALUE id FROM user ORDER BY created ASC LIMIT 1)[0];
    IF $owner != NONE {
        LET $found_personal = (SELECT VALUE id FROM workspace WHERE owner = $owner AND kind = "personal" LIMIT 1)[0];
        LET $personal_workspace = $found_personal ?? workspace:personal_default;
        IF $found_personal = NONE {
            UPSERT workspace:personal_default SET
                name = "Personal", slug = "personal-default", kind = "personal", owner = $owner;
            UPSERT membership:personal_default_owner SET
                user = $owner, workspace = workspace:personal_default, role = "owner", status = "active";
        };
        UPDATE notebook SET
            workspace = $personal_workspace, owner = $owner, default_source_scope = "personal"
        WHERE workspace = NONE;
        -- Seed the owner as the sole admin member of each backfilled project
        -- (a no-op for enforcement purposes while the project stays personal,
        -- but keeps project_member populated uniformly for every project).
        FOR $nb IN (SELECT id, owner FROM notebook WHERE owner != NONE) {
            IF (SELECT id FROM project_member WHERE project = $nb.id AND user = $nb.owner) = [] {
                CREATE project_member SET project = $nb.id, user = $nb.owner, role = "admin", status = "active";
            };
        };
    };
};
```

`open_notebook/database/migrations/21_down.surrealql`:
```surql
-- Remove only the seed this migration created (safe: deterministic ids, never
-- touches a personal workspace P2 auto-provisioned for another user).
DELETE membership:personal_default_owner;
DELETE workspace:personal_default;
REMOVE INDEX IF EXISTS idx_project_member_unique ON TABLE project_member;
REMOVE TABLE IF EXISTS project_member;
REMOVE INDEX IF EXISTS idx_notebook_workspace ON TABLE notebook;
REMOVE FIELD IF EXISTS promoted_from ON TABLE notebook;
REMOVE FIELD IF EXISTS default_source_scope ON TABLE notebook;
REMOVE FIELD IF EXISTS owner ON TABLE notebook;
REMOVE FIELD IF EXISTS workspace ON TABLE notebook;
```

> Backfill note: `workspace:personal_default` and `membership:personal_default_owner` are created **by this migration (21)**, not by P2 — P2's migration (20) only defines the empty `workspace`/`membership` tables; it seeds no data. The self-seed only fires when (a) legacy company-less/workspace-less notebooks exist AND (b) the first existing user has no personal workspace yet. If a personal workspace for that user already exists (P2's onboarding got there first), the backfill reuses it instead of creating a duplicate — there is deliberately no hard dependency on migration *ordering* between P2's auto-provisioning code path and P3's migration. **Cross-phase note (P3 ↔ P2):** the reverse also holds — P2's `ensure_personal_workspace(user_id)` (`docs/superpowers/specs/2026-07-11-p2-company-membership-onboarding-design.md`) looks up by `SELECT * FROM workspace WHERE owner = $user AND kind = 'personal'`, never by a hardcoded id, so if this migration runs first and self-seeds `workspace:personal_default` for that first user, the next time that user logs in `ensure_personal_workspace` finds and reuses it rather than creating a second personal workspace. Both sides key on `(owner, kind='personal')`, so whichever runs first "wins" and the other is a no-op. The only soft edge remaining: if no `user` row exists at migration time (pure pre-auth data with zero registered users), legacy notebooks are left `workspace = NONE`; the first user to complete registration and P2 onboarding is expected to claim them via a documented handoff (out of scope to automate here — no orphaning occurs because the app-layer scoping added in P6 filters by `workspace`, and a `workspace = NONE` project simply will not appear in any workspace's list until claimed).

## Backend: endpoints, services, domain models (file paths)

### Domain — `open_notebook/domain/notebook.py`
- Rename class `Notebook` → `Project`, keep `table_name: ClassVar[str] = "notebook"`. Add fields: `workspace: Optional[str]`, `owner: Optional[str]`, `default_source_scope: Literal["personal","project","company"] = "personal"`, `promoted_from: Optional[str]` (schema hook only — nothing reads/writes it beyond persistence in P3). Keep `name`, `description`, `archived`, `last_viewed_at` and every existing method (`get_sources`, `get_notes`, `get_context`, `get_chat_sessions`, `get_delete_preview`, `delete`) unchanged — they operate on the same relations.
- Update the internal method names that read "notebook" only for clarity if cheap (`Source.add_to_notebook`, `Note.add_to_notebook`, `ChatSession.relate_to_notebook`); functionally they still `relate("reference"|"artifact"|"refers_to", project_id)`. **Keep them as-is in P3** to bound churn — they already take an opaque id.
- Add `ProjectMember(ObjectModel)` with `table_name = "project_member"`, fields `project`, `user`, `role`, `status`, plus `@classmethod get_for_project(project_id)` and `@classmethod get_for_user(user_id)` helpers (mirror `SourceInsight.get_for_sources` query shape). `ProjectMember` rows exist for every project (seeded at create/backfill time) but are only *consulted* for authorization when the project's workspace is `kind="company"` — a personal project's owner already passes the `ctx.role == "owner"` fast path (see RBAC below), so the table is never queried for personal projects in practice.
- Keep a module-level alias `Notebook = Project` **only if** a lighter-touch rollout is wanted; the checklist below assumes a clean rename of importers, which is preferred for clarity in P5/P6.

### Schemas — `api/models.py`
- Add `ProjectCreate` (`name`, `description`, optional `default_source_scope`), `ProjectUpdate` (`name?`, `description?`, `archived?`, `default_source_scope?`), `ProjectResponse` (existing `NotebookResponse` fields + `workspace`, `owner`, `default_source_scope`, `promoted_from`), `ProjectMemberResponse`. Keep the old `Notebook*` schemas until every importer moves, or replace them and update `context.py`/`chat.py`/`notes.py`/`sources.py` imports (they mostly don't import these — verify).
- `RecentlyViewedResponse.type` Literal currently `["notebook","source"]` → add `"project"` (or switch the notebook branch to emit `"project"`); update `_recently_viewed_notebook`.

### Router — `api/routers/projects.py` (new, replaces `notebooks.py` at `/api`)
All endpoints take P2's `get_auth_context`/`require_role` (from `api/deps.py`) and scope by `workspace_id` from the token (`AuthContext.workspace_id`). Reuse the existing query bodies from `notebooks.py`, adding a `WHERE workspace = $workspace_id` filter and, on create, stamping `workspace`/`owner`/`default_source_scope` + seeding a `project_member` admin row.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/projects` | any active workspace member | `SELECT ... FROM notebook WHERE workspace = $workspace_id ORDER BY ...` + source/note counts (keep the `order_by` allowlist). Works identically for personal (single-project-owner) and company workspaces. |
| POST | `/projects` | `require_role("owner","admin")` | create `Project(workspace=workspace_id, owner=user_id, default_source_scope=...)`, then `CREATE project_member` (owner, role `admin`). In a **personal** workspace the caller's role is always `"owner"` (P2 invariant: a personal workspace has exactly one member, the owner), so this same gate naturally lets the personal owner create freely without a separate code path — **in a company workspace it correctly excludes plain members**. |
| GET | `/projects/{id}` | member of project OR workspace owner/admin | 404 if not in workspace; stamp `last_viewed_at` (existing `_stamp_notebook_view`). |
| PUT | `/projects/{id}` | project admin OR workspace owner/admin | reuse update body; guard workspace match first. |
| DELETE | `/projects/{id}` | project admin OR workspace owner/admin | reuse cascade `delete(delete_exclusive_sources=...)`; also `DELETE project_member WHERE project = $id`. |
| GET | `/projects/{id}/delete-preview` | as DELETE | unchanged logic. |
| POST | `/projects/{id}/sources/{source_id}` | project admin/member | unchanged relate logic. |
| DELETE | `/projects/{id}/sources/{source_id}` | project admin/member | unchanged. |
| GET | `/recently-viewed` | any active workspace member | filter notebooks by `workspace = $workspace_id`. |

- Register in `api/main.py` (`from api.routers import projects`; `app.include_router(projects.router, prefix="/api", tags=["projects"])`) and drop the `notebooks` include (recommend dropping to avoid an unscoped surface, since it currently has NO workspace filter and would be a tenant-leak hole).
- `api/notebook_service.py`: dead code (nothing imports it) → delete. `api/client.py` `get_notebooks`/`get_notebook` accessors, if they hit `/notebooks`, repoint to `/projects`.

### Workspace-scoping enforcement (P3-local, generalized in P6)
Every project query filters on the token's `workspace_id`; every `{id}` route first confirms the target row's `workspace == workspace_id` (404 otherwise, to avoid leaking existence). Project-level role checks read `project_member` (workspace owner/admin bypass, per the RBAC table below) — this bypass and the seeded `project_member` row are both harmless-but-unused when the workspace is personal, since the personal owner already satisfies `ctx.role in {"owner","admin"}`.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

Rename the `notebooks` feature to `projects`. All HTTP stays on the single `apiClient`; hooks keep the TanStack Query shape (invalidate + sonner toast).

- **Routes:** `frontend/src/app/(dashboard)/notebooks/` → `.../projects/` (`page.tsx`, `[id]/page.tsx`, and the `components/` folder — `NotebookList`, `NotebookCard`, `NotebookRow`, `NotebookHeader`, `NotebookDeleteDialog`, `SourcesColumn`, `NotesColumn`, `ChatColumn`, `RecentlyViewed`, `NoteEditorDialog`, `ChatColumn.test.tsx`). Rename components to `Project*` (mechanical).
- **API client:** `frontend/src/lib/api/notebooks.ts` → `projects.ts` — point at `/projects`, rename `notebooksApi`→`projectsApi`, methods keep signatures.
- **Hooks:** `frontend/src/lib/hooks/use-notebooks.ts` → `use-projects.ts` (`useProjects`, `useProject`, `useCreateProject`, `useUpdateProject`, `useProjectDeletePreview`, `useDeleteProject`). Toast keys move to `projects.*`.
- **Query keys:** `frontend/src/lib/api/query-client.ts` — add `projects` / `project(id)` keys (keep child keys `notes(notebookId)`, `sources(notebookId)`, `notebookChatSessions(...)` as-is since their params still carry project ids; renaming them is optional cleanup).
- **Types:** `frontend/src/lib/types/api.ts` — add `ProjectResponse` (with `workspace`, `owner`, `default_source_scope`, `promoted_from`), `CreateProjectRequest`, `UpdateProjectRequest`, `ProjectDeletePreview`, `ProjectDeleteResponse`, `ProjectMemberResponse`.
- **Stores:** `frontend/src/lib/stores/notebook-view-store.ts` → `project-view-store.ts`, `notebook-columns-store.ts` → `project-columns-store.ts` (rename persisted `name` keys — localStorage collision rule). `frontend/src/lib/hooks/useNotebookChat.ts` → `useProjectChat.ts`. `frontend/src/lib/types/notebook-context.ts` → `project-context.ts`.
- **Nav:** `frontend/src/components/layout/AppSidebar.tsx` line ~56 — `href: '/notebooks'` → `'/projects'`, label `t('navigation.notebooks')` → `t('navigation.projects')`; update `AppSidebar.test.tsx`.
- **Cross-feature consumers (update imports + labels):** `frontend/src/components/notebooks/CreateNotebookDialog.tsx` → `projects/CreateProjectDialog.tsx`; `frontend/src/components/sources/steps/NotebooksStep.tsx`, `SourceTypeStep.tsx`, `ProcessingStep.tsx`, `AddSourceDialog.tsx`, `SourceCard.tsx`; `frontend/src/components/source/NotebookAssociations.tsx`, `SourceDetailContent.tsx`; `frontend/src/components/search/SaveToNotebooksDialog.tsx`; `frontend/src/components/podcasts/GeneratePodcastDialog.tsx`; `frontend/src/components/common/ContextToggle.tsx`, `CommandPalette.tsx`; `frontend/src/components/providers/ModalProvider.tsx`. These import `useNotebooks`/labels — repoint to `use-projects` and `projects.*` strings.
- **Active workspace scope:** `useProjects` reads the active workspace from the P2 context (the workspace-scoped token already carries `workspace_id`, auto-injected by `apiClient`); switching the active workspace (personal ↔ any company, or between companies) must invalidate `QUERY_KEYS.projects`. Wire the invalidation into P2's switch-workspace mutation (cross-phase note).
- **i18n (all 7 enforced locales — en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN — in `frontend/src/lib/locales/`):** add a `projects.*` section mirroring today's `notebooks.*` (`title`, `create`, `createSuccess`, `updateSuccess`, `deleteSuccess`, `empty`, `namePlaceholder`, `defaultSourceScope.personal`, `defaultSourceScope.project`, `defaultSourceScope.company`, delete-dialog strings) and `navigation.projects`. Keep `notebooks.*` only if any un-migrated string remains; goal is full replacement. No "company"-worded strings are introduced elsewhere by P3 — the `defaultSourceScope.company` value's UI label uses the product word "company" deliberately (it names a source-scope level, not the workspace entity).

## Permissions / RBAC rules (explicit)

Workspace roles from P2: `owner|admin|member` — but a **personal** workspace always has exactly one membership row and it is always `role="owner"` (P2 invariant; you cannot invite into a personal workspace). Project roles from `project_member`: `admin|member`, populated for every project but only *checked* when the workspace is `kind="company"` (a personal-workspace request already short-circuits on `ctx.role == "owner"`). Enforced at the application layer (no SurrealDB RLS).

| Action | Workspace owner (company or personal) | Workspace admin (company only) | Workspace member (project admin) | Workspace member (project member) | Workspace member (no project row) |
|---|---|---|---|---|---|
| List projects (own workspace) | ✅ | ✅ | ✅ (sees projects they belong to) | ✅ (sees projects they belong to) | ✅ (sees none) |
| **Create project** | ✅ | ✅ | ❌ | ❌ | ❌ |
| View a project | ✅ | ✅ | ✅ | ✅ | ❌ (403) |
| Update project (name/desc/scope/archive) | ✅ | ✅ | ✅ | ❌ | ❌ |
| Delete project | ✅ | ✅ | ✅ | ❌ | ❌ |
| Add/remove source ↔ project | ✅ | ✅ | ✅ | ✅ | ❌ |
| Manage project members | ✅ | ✅ | ✅ | ❌ | ❌ (populate flow = P4; N/A in a personal workspace) |
| Any project in another workspace | ❌ 404 | ❌ 404 | ❌ 404 | ❌ 404 | ❌ 404 |

Stated defaults (from the brief, user may flip later): **in a company workspace, project creation is limited to owner/admin — members are invited into projects; in a personal workspace the owner creates freely** (mechanically the same `require_role("owner","admin")` gate, since a personal workspace's sole member is always `owner`). `default_source_scope` defaults to `personal`. (Source-scope enforcement across `personal|project|company` is defined in **P5**; P3 only stores `default_source_scope` on the project, plus the `promoted_from` schema hook with no enforcement logic.)

## Error handling (per the shared contract)
- 401 unauthenticated → frontend clears `auth-storage`, redirect `/login`.
- 403 wrong role (non owner/admin creating a company-workspace project; project member editing/deleting) → `{ "detail": "..." }`.
- 404 project not found **or in another workspace** (existence hidden across tenants).
- 400 invalid input (empty name — reuse `Project.name` validator; bad `order_by`; bad `default_source_scope`).
- 409 duplicate `project_member` (unique `(user, project)` index) — relevant when P4 writes members; P3's create-seed guards with an existence check first.
- Backend raises typed exceptions from `open_notebook.exceptions` (mapped by global handlers); `require_role` raises the P2 403. Consistent `{ "detail": "..." }` body.

## Testing (concrete)
Backend (`uv run pytest tests/`):
1. `test_migration_21_backfill`: existing workspace-less notebook gets assigned to the first user's personal workspace (self-seeded `workspace:personal_default` + `membership:personal_default_owner` if none existed) + `owner` + a seeded `admin` project_member; `default_source_scope` defaults `personal`; down-migration removes columns/table/self-seed cleanly.
2. `test_project_create_requires_owner_admin`: company-workspace `member` token → 403; `admin`/`owner` → 201 and a `project_member(admin, active)` row for the creator. Personal-workspace `owner` token → 201 (same gate, different workspace kind).
3. `test_project_list_workspace_scoped`: user in workspace A cannot see workspace B's projects (tenant-leakage test, mirrors `test_X3_suite1_tenant_leakage.py`); a company workspace's projects never leak into a personal workspace's list and vice versa.
4. `test_project_get_cross_workspace_404`: fetching another workspace's project id → 404 (not 403 — existence hidden).
5. `test_project_update_delete_role_gate`: project `member` → 403 on PUT/DELETE; project `admin` / workspace admin → success.
6. `test_project_source_relations_intact`: add/remove source, get_sources/get_notes/get_context, delete-cascade still work (proves the kept `reference`/`artifact` relations are unaffected).
7. `test_recently_viewed_workspace_scoped`: only the active workspace's projects appear.
8. `test_project_personal_workspace_create_and_scope`: a personal-workspace owner creates a project without any explicit admin/member distinction; `default_source_scope` still stored and returned; `project_member` seeded but irrelevant to the (single-user) authorization path.

Frontend (`npm run test` / `lint` / `build`):
9. `use-projects` hooks hit `/projects`, invalidate `QUERY_KEYS.projects`, toast on success/error.
10. Renamed `ChatColumn.test.tsx` + `AppSidebar.test.tsx` pass with `navigation.projects`.
11. i18n guard: every new `projects.*` / `navigation.projects` key exists in all 14 locales (missing-key + unused-key parity test).
12. Switching the active workspace (personal ↔ company, or company ↔ company) refetches the projects list (invalidation wired to P2 switch-workspace).

## Full blast radius — files touched (checklist)

**Backend — migrations**
- [ ] `open_notebook/database/migrations/21.surrealql` (new)
- [ ] `open_notebook/database/migrations/21_down.surrealql` (new)
- [ ] `open_notebook/database/async_migrate.py` (register 21 in up/down lists)

**Backend — domain / schemas / routers / services**
- [ ] `open_notebook/domain/notebook.py` (`Notebook`→`Project` + fields; add `ProjectMember`)
- [ ] `api/models.py` (`Project*` schemas; `RecentlyViewedResponse.type` += `"project"`)
- [ ] `api/routers/projects.py` (new, workspace-scoped; replaces notebooks router)
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
- [ ] `frontend/src/lib/types/api.ts` (`Project*` types + `workspace`/`owner`/`default_source_scope`/`promoted_from`)
- [ ] `frontend/src/lib/types/notebook-context.ts` → `project-context.ts`
- [ ] `frontend/src/lib/stores/notebook-view-store.ts` → `project-view-store.ts`
- [ ] `frontend/src/lib/stores/notebook-columns-store.ts` → `project-columns-store.ts`
- [ ] Active-workspace invalidation hook (coordinate with P2 switch-workspace mutation)

**Frontend — i18n**
- [ ] `frontend/src/lib/locales/{en-US,pt-BR,zh-CN,zh-TW,ja-JP,ru-RU,bn-IN}/` — add `projects.*` + `navigation.projects` (7 enforced locales, real translations)
- [ ] `frontend/src/lib/locales/{it-IT,fr-FR,ca-ES,es-ES,de-DE,pl-PL,tr-TR}/` — same keys, English-fallback values (repo has 14 locales total registered in the `resources` map; the parity test fails on any missing/extra key across ALL of them)

## Open questions / risks
- **Personal-workspace backfill (resolved):** the previously-flagged "highest-risk cross-phase dependency" (who creates the tenant a legacy notebook belongs to) is now settled: **migration 21 assigns legacy notebooks to the first existing user's personal workspace**, self-seeding `workspace:personal_default` + `membership:personal_default_owner` only if that user has no personal workspace yet (reusing one if P2's auto-provisioning already created it). The only residual edge is the zero-users-at-migration-time case (notebooks left `workspace = NONE`, claimed on first registration + P2 onboarding), which orphans nothing because P6's workspace-scoping simply excludes an unassigned project from every workspace's list until claimed. P5's source backfill (migration 23) leans on the same mechanism: legacy sources inherit their workspace via their (now-backfilled) notebook.
- **`default_source_scope` field type:** declared non-optional with `DEFAULT "personal"` so every project has a value; existing rows are set by the backfill. If any project can precede the backfill in a live system, keep it `option<string>` and default in the domain model instead. Recommend the migration-default shown.
- **`promoted_from` is a pure schema hook in P3.** No endpoint reads or writes it beyond accepting it as an optional field on the domain model; the governed promotion review flow (PRD §4.3) is explicitly deferred past this phase. Do not build UI or enforcement around it here.
- **Alias vs clean rename of the `Notebook` class:** a `Notebook = Project` alias reduces the immediate import churn but leaves stale vocabulary that P5/P6 will trip over. Recommend the clean rename (checklist assumes it); the alias is a fallback if the rename destabilizes the build.
- **Child-router param naming debt:** `notebook_id` params persist in `sources.py`/`notes.py`/`chat.py`/`context.py` and carry project ids. This is intentional scope-bounding but is a readability smell; schedule a cosmetic `notebook_id`→`project_id` rename as a post-P6 cleanup once the tenant model is stable.
- **`refers_to` overload:** `ChatSession.relate_to_source` and `relate_to_notebook` both use the `refers_to` relation. Re-anchoring chat to project is free (same table), but any future project-vs-source disambiguation on `refers_to` must not assume the target table — it currently distinguishes by traversal direction only.
- **`AuthContext` field naming assumption:** this spec assumes P2 exposes `AuthContext.workspace_id`/`AuthContext.role` (per the shared architecture brief). If P2's actual implementation names the claim differently, reconcile the router's `ctx.*` reads before building against this spec (see the plan's "Consumed interfaces" section for the exact contract this phase relies on).
