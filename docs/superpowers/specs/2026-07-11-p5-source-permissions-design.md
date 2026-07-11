# P5 — Source permissions (owner + visibility) — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft

## Goal (2-4 sentences)
Add `owner` (uploader user) and `visibility` (`private` | `project`) to the `source` table so every source read/list/mutate operation is filtered by who is allowed to see it. When adding a source the user picks a visibility: **private** (only me, plus company/project admins) or **project** (all project members). Every endpoint that lists, reads, mutates, downloads, chats over, embeds, or searches a source (or its insights/embeddings) must apply the visibility check; search in particular must never surface a private source the caller cannot see. This is the last content-plane permission layer before P6 wires up app-layer tenant scoping.

## Depends on / Provides

**Depends on:**
- **P1 (auth+users)** — a real authenticated `user` record; `owner` links to `user`.
- **P2 (company+membership+roles)** — company-level roles `owner|admin|member` via `membership`; needed for the "company owner/admin can see private sources" rule.
- **P3 (project, repurposed from `notebook`)** — sources attach to a `project` (the current `notebook` table); the migration and enforcement assume `project` + `project.company` + `project.owner` exist.
- **P4 (invitation)** — not a hard dependency; `project_member` rows it produces are consumed here.
- **P6 (tenant scoping helper)** — this spec assumes a request context object providing `(current_user, active_company, company_role, project_role_resolver)` is available as a FastAPI dependency. **P5 does not build that helper**; it declares the shape it needs (see "Permission context dependency" below) and P6 provides the concrete implementation. Until P6 lands, P5's check functions can be unit-tested against a hand-built context.

**Provides:**
- `source.owner` + `source.visibility` schema (migration 23) and a reusable permission predicate `can_view_source` / `can_mutate_source` (new `api/source_permissions.py`) that all source-touching routers call.
- A visibility-aware replacement for the `fn::text_search` / `fn::vector_search` SurrealQL functions (migration 23) so search results are pre-filtered at the DB layer.
- Frontend: a private/project visibility selector in the add-source wizard, a visibility badge on source cards, and an editable visibility control on the source detail view, with i18n keys in all 7 enforced locales.

## Scope (in) / Out of scope

**In scope:**
- Migration adding `owner` + `visibility` to `source`, with backfill (existing sources → `visibility = 'project'`, `owner = NONE`).
- Setting `owner` = current user and `visibility` = chosen value on source creation.
- A permission predicate module and its wiring into **every** source-touching endpoint enumerated below (sources, source_chat, insights, embedding, search, context, notebook get_context).
- Visibility-aware search functions (both text and vector).
- Frontend visibility selector (add wizard), badge (card), and edit control (detail), plus hooks/types/i18n.

**Out of scope:**
- The generic company_id tenant-scoping helper and role-gating guards — **P6**.
- Per-source ACLs / sharing with specific users, link-based sharing, or "team" visibility beyond `private`/`project` (only the two values are in scope; the enum is defined so a 3rd value could be added later).
- Note / chat_session visibility (notes have no owner/visibility in this phase; they inherit project membership only). Only `source` gets owner+visibility here.
- Changing the `reference` graph edge model (source↔project relation stays as-is).

## Data model changes (SurrealDB migration 23.surrealql + _down)

New migration pair `open_notebook/database/migrations/23.surrealql` and `23_down.surrealql`, registered in `open_notebook/database/async_migrate.py` (append `AsyncMigration.from_file("open_notebook/database/migrations/23.surrealql")` to `self.up_migrations` and the matching `23_down.surrealql` to `self.down_migrations` — migrations are hard-coded, not auto-discovered; current highest is 18).

**`23.surrealql`:**
```surrealql
-- Migration 23: Source ownership + visibility (P5 source permissions)

-- owner = the user who uploaded/created the source. NONE for legacy/backfilled
-- sources (no user existed pre-auth). Nullable on purpose.
DEFINE FIELD IF NOT EXISTS owner ON TABLE source TYPE option<record<user>>;

-- visibility gate. 'private' = owner + company owner/admin + project admins only.
-- 'project' = all members of any project the source is referenced by.
DEFINE FIELD IF NOT EXISTS visibility ON TABLE source
    TYPE string
    ASSERT $value IN ['private', 'project']
    DEFAULT 'project';

-- Backfill existing rows: pre-existing sources predate multi-tenancy, so they
-- default to 'project' (visible to all project members) and owner stays NONE.
-- NOTE: source carries NO denormalized `company` column — a source inherits its
-- company from the project (physical `notebook` table) it is referenced by via the
-- `reference` edge. By the time this migration (23) runs, P3's migration (21) has
-- already backfilled every notebook to `company:default`, so every legacy source
-- resolves to a company through its notebook. `can_view_source` derives the
-- company this way (SELECT VALUE company FROM $project).
UPDATE source SET visibility = 'project' WHERE visibility = NONE;

-- Indexes backing the visibility filter used by list/search so it does not
-- degrade to a full scan as data grows.
DEFINE INDEX IF NOT EXISTS idx_source_visibility ON TABLE source FIELDS visibility CONCURRENTLY;
DEFINE INDEX IF NOT EXISTS idx_source_owner ON TABLE source FIELDS owner CONCURRENTLY;

-- Replace the search functions with visibility-aware variants. They take an
-- extra $viewer_source_ids param: the pre-computed set of source ids the caller
-- may see (owner/admin escalation is resolved in Python, then passed down). Any
-- source not in that set is filtered out of every result branch.
REMOVE FUNCTION IF EXISTS fn::text_search;
DEFINE FUNCTION IF NOT EXISTS fn::text_search(
    $query_text: string, $match_count: int, $sources: bool, $show_notes: bool,
    $viewer_source_ids: array<record<source>>
) {
    -- identical body to migration 4's fn::text_search, EXCEPT every source /
    -- source_embedding / source_insight sub-select gains:
    --     AND (source.id IN $viewer_source_ids)   -- (or `id IN ...` on the source table)
    -- Notes are unaffected (notes have no visibility in P5).
    -- (Full body reproduced from migrations/4.surrealql with the added WHERE clauses.)
};

REMOVE FUNCTION IF EXISTS fn::vector_search;
DEFINE FUNCTION IF NOT EXISTS fn::vector_search(
    $query: array<float>, $match_count: int, $sources: bool, $show_notes: bool,
    $min_similarity: float, $viewer_source_ids: array<record<source>>
) {
    -- identical body to migration 9's fn::vector_search, EXCEPT the
    -- source_embedding and source_insight branches gain:
    --     AND (source.id IN $viewer_source_ids)
    -- Note branch unchanged.
};
```

**`23_down.surrealql`:**
```surrealql
-- Migration 23 rollback

REMOVE INDEX IF EXISTS idx_source_visibility ON TABLE source;
REMOVE INDEX IF EXISTS idx_source_owner ON TABLE source;
REMOVE FIELD IF EXISTS visibility ON TABLE source;
REMOVE FIELD IF EXISTS owner ON TABLE source;

-- Restore the pre-P5 search functions (copy the DEFINE FUNCTION bodies verbatim
-- from migrations/4.surrealql (fn::text_search) and migrations/9.surrealql
-- (fn::vector_search) — the 4-arg / 5-arg signatures without $viewer_source_ids).
REMOVE FUNCTION IF EXISTS fn::text_search;
-- <re-DEFINE fn::text_search from migration 4>
REMOVE FUNCTION IF EXISTS fn::vector_search;
-- <re-DEFINE fn::vector_search from migration 9>
```

**Domain model change — `open_notebook/domain/notebook.py`, class `Source`:**
Add two fields to `Source` (subclass of `ObjectModel`):
```python
owner: Optional[Union[str, RecordID]] = None      # link to user
visibility: Literal["private", "project"] = "project"
```
Add an `owner` `field_validator(mode="before")` mirroring the existing `command` validator (coerce a str to `RecordID` via `ensure_record_id`, pass through `None`). `visibility` needs no special handling. `Source._prepare_save_data()` already exists — extend it to coerce `owner` to `RecordID` when not `None`, same pattern as `command`.

Add helper query methods on `Source` (used by the permission predicate):
- `async def get_project_ids(self) -> List[str]` — `SELECT VALUE out FROM reference WHERE in = $id` (the source→project references; identical query already inline in `get_source` and `retry_source_processing`).

## Backend: endpoints, services, domain models (file paths)

### New: permission context dependency (shape only; P6 implements)
P5 assumes a FastAPI dependency yielding a context object, referenced here as `ctx: PermissionContext`:
```
ctx.user_id: str                      # current authenticated user record id
ctx.company_id: str                   # active company record id
ctx.company_role: "owner"|"admin"|"member"
async ctx.project_role(project_id) -> "admin"|"member"|None   # via project_member + company_role escalation
```
Until P6, P5 ships a minimal stub of this dependency in `api/source_permissions.py` (reads the JWT claims that P1/P2 already put on the request) so P5 endpoints and tests are runnable; P6 replaces the stub body with the real tenant-scoping helper. This dependency is added to every source-touching route via `Depends`.

### New: `api/source_permissions.py` (the predicate module — the heart of P5)
Pure functions + two query helpers, called by all routers. Business logic lives here (routers stay thin, per `api/AGENTS.md`).

```
async def can_view_source(source: Source, ctx: PermissionContext) -> bool
async def can_mutate_source(source: Source, ctx: PermissionContext) -> bool
async def visible_source_ids(ctx: PermissionContext, project_id: str | None) -> list[str]
async def require_view_source(source_id: str, ctx) -> Source   # loads, checks, raises 404/403
async def require_mutate_source(source_id: str, ctx) -> Source # loads, checks, raises 404/403
```

Logic of `can_view_source`:
1. Resolve the source's project ids (`source.get_project_ids()`) and, from the first/any, its owning company (`SELECT VALUE company FROM $project`). If the source is not referenced by any project in `ctx.company_id`, treat as not-found (404) — enforces company isolation (belt-and-braces with P6).
2. If `source.owner == ctx.user_id` → **allow**.
3. If `ctx.company_role in ('owner','admin')` (for the source's company) → **allow** (company owner/admin sees everything, including private).
4. If any of the source's projects has `ctx.project_role(project_id) == 'admin'` → **allow**.
5. If `source.visibility == 'project'` **and** the caller is a member (`ctx.project_role(project_id) in ('admin','member')`) of any project the source is referenced by → **allow**.
6. Otherwise **deny**.

Logic of `can_mutate_source` (edit/delete): steps 2–4 above only (owner + company owner/admin + project admin). A plain `project` member who is not the owner may **view** a project source but may **not** edit/delete it.

`require_view_source` / `require_mutate_source`: load via `Source.get(source_id)` (404 if missing), run the predicate, raise `HTTPException(403, detail="You do not have access to this source")` on deny (or 404 to avoid leaking existence for private sources the caller can't see — **use 404 on view-deny, 403 on mutate-deny**; see Error handling). Return the `Source` so the caller reuses it.

### Endpoint-by-endpoint changes

**`api/routers/sources.py`** (all take `ctx = Depends(get_permission_context)`):
| Endpoint | Change |
|---|---|
| `GET /sources` (`get_sources`) | Constrain the list query to visible sources. Compute `visible_source_ids(ctx, notebook_id)` and add `AND id IN $visible_ids` to both the notebook-scoped and all-sources `SELECT ... FROM source` queries. Prefer an in-query predicate over post-filtering so `LIMIT`/`START` paging stays correct. Also scope the no-`notebook_id` branch to the active company's projects. |
| `POST /sources` + `POST /sources/json` (`create_source`) | Accept new form/JSON fields `visibility` (default `'project'`). Set `source.owner = ctx.user_id` and `source.visibility = source_data.visibility` on both async and sync paths before `source.save()`. Validate each `notebooks[]` project belongs to `ctx.company_id` and the caller may add sources to it (member+). Reject `visibility` not in `{private, project}` with 400. |
| `GET /sources/{id}` (`get_source`) | Replace `Source.get` + null check with `await require_view_source(source_id, ctx)`. |
| `HEAD/GET /sources/{id}/download` (`check_source_file`, `download_source_file` → `_resolve_source_file`) | Add `require_view_source` before returning the file. Private file must not be downloadable by a non-viewer. |
| `GET /sources/{id}/status` (`get_source_status`) | `require_view_source`. |
| `PUT /sources/{id}` (`update_source`) | `require_mutate_source`. Also allow updating `visibility` here: extend `SourceUpdate` with `visibility: Optional[Literal['private','project']]`; only owner/admins (already enforced by mutate check) may flip it. |
| `POST /sources/{id}/retry` (`retry_source_processing`) | `require_mutate_source` (re-processing is a mutation). |
| `DELETE /sources/{id}` (`delete_source`) | `require_mutate_source`. |
| `GET /sources/{id}/insights` (`get_source_insights`) | `require_view_source` (insights inherit the source's visibility). |
| `POST /sources/{id}/insights` (`create_source_insight`) | `require_mutate_source` (generating insights writes to the source). |

**`api/routers/insights.py`** (insights reference a source; resolve it and check):
| Endpoint | Change |
|---|---|
| `GET /insights/{id}` (`get_insight`) | After `insight.get_source()`, `require_view_source(source.id, ctx)`. |
| `DELETE /insights/{id}` (`delete_insight`) | Resolve source via `insight.get_source()`, then `require_mutate_source`. |
| `POST /insights/{id}/save-as-note` (`save_insight_as_note`) | `require_view_source` on the insight's source (reading it into a note). |

**`api/routers/source_chat.py`** — every endpoint already loads the source via `Source.get(full_source_id)`; replace that load with the predicate:
| Endpoint | Change |
|---|---|
| `POST /sources/{id}/chat/sessions` | `require_view_source` (must see the source to chat about it). |
| `GET /sources/{id}/chat/sessions` | `require_view_source`. |
| `GET /sources/{id}/chat/sessions/{sid}` | `require_view_source`. |
| `PUT /sources/{id}/chat/sessions/{sid}` | `require_view_source`. |
| `DELETE /sources/{id}/chat/sessions/{sid}` | `require_view_source` (chat sessions are per-user reads; deleting your own session over a source you can view is allowed — this is not a source mutation). |
| `POST /sources/{id}/chat/sessions/{sid}/messages` | `require_view_source`. |

**`api/routers/embedding.py`** (`POST /embed`) — when `item_type == 'source'`, load and `require_mutate_source(item_id, ctx)` before `source.vectorize()` (embedding writes derived data for the source). Note branch unchanged.

**`api/routers/search.py`** (`POST /search`, `POST /search/ask`, `POST /search/ask/simple`) — the leakage-critical path. See dedicated section below.

**`api/routers/context.py`** and `Notebook.get_context()` / `Notebook.get_sources()` (`open_notebook/domain/notebook.py`) — context assembly for chat/podcast pulls **all** sources of a project (`get_sources`) with no visibility filter. Add an optional `viewer_source_ids: set[str] | None` param to `Notebook.get_sources()` and filter the `reference`-joined result to that set; the context router computes it from `ctx` and passes it. Rationale: a company member chatting with a project must not have another user's *private* source silently injected into the LLM context. (Podcast/background jobs that build context without a user context use the unfiltered path — document that they run with full project scope, which is acceptable because they are project-owner-initiated.)

### Search-leakage concern (explicit)
`fn::text_search` and `fn::vector_search` (defined in migrations 4 and 9, called from `text_search()`/`vector_search()` in `open_notebook/domain/notebook.py`, invoked by `api/routers/search.py`) currently scan `source`, `source_embedding`, and `source_insight` **globally with no owner/visibility/company filter**. Without a change, a text or vector search — and the `/search/ask` RAG flow that embeds source content into answers — would surface titles, highlighted snippets, and full-text chunks of **private sources belonging to other users, and sources in other companies**. This is the primary data-leak risk of the whole feature.

Fix (two layers):
1. **DB layer:** the migration-23 search functions gain a `$viewer_source_ids` parameter and filter every source-derived branch (`source`, `source_embedding`, `source_insight`) with `AND source.id IN $viewer_source_ids`. Note branches are untouched (notes are project-membership scoped, not per-source private, in P5).
2. **App layer:** `text_search()` and `vector_search()` in `open_notebook/domain/notebook.py` gain a `viewer_source_ids: list[str]` param passed straight into the SurrealQL call. `search.py` computes it via `visible_source_ids(ctx, project_id=None)` (all sources across the caller's company that the caller may view) and passes it down. The RAG `ask_graph` retrieval path (`open_notebook/graphs/ask/`) is invoked from `/search/ask*`; it must be given the same `viewer_source_ids` filter so retrieved chunks feeding the LLM answer are also scoped — thread the id set through the graph config (same mechanism as the model ids already in `configurable`). If the graph cannot yet accept the filter, gate `/search/ask*` to `visibility='project'` sources only as an interim safe default and note it as a follow-up.

Computing `visible_source_ids`: a single SurrealQL query returning source ids in the caller's company projects where `visibility = 'project' AND caller is a member` OR `owner = caller` OR `caller is company owner/admin` OR `caller is admin of the source's project`. Implement as one parameterized query in `source_permissions.py` (avoid N+1). This same helper backs `GET /sources` list filtering.

### Pydantic model changes — `api/models.py`
- `SourceCreate`: add `visibility: Literal["private", "project"] = "project"`.
- `SourceUpdate`: add `visibility: Optional[Literal["private", "project"]] = None`.
- `SourceResponse` and `SourceListResponse`: add `visibility: str` and `owner: Optional[str] = None` (so the frontend can render badge + gate the edit control). Populate them in every response constructor in `sources.py` (list, get, create sync/async, update, retry).
- `parse_source_form_data` (`sources.py`): add `visibility: str = Form("project")` and pass into `SourceCreate`.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

**Types — `frontend/src/lib/types/api.ts`:**
- `CreateSourceRequest`: add `visibility?: 'private' | 'project'`.
- `UpdateSourceRequest`: add `visibility?: 'private' | 'project'`.
- `SourceListResponse` / `SourceResponse` / `SourceDetailResponse`: add `visibility: 'private' | 'project'` and `owner?: string | null`.

**API client — `frontend/src/lib/api/sources.ts`:**
- `create`: `formData.append('visibility', data.visibility ?? 'project')`.
- `update`: already sends JSON body — include `visibility` when present.

**Hook — `frontend/src/lib/hooks/use-sources.ts`:** no signature change; `useCreateSource`/`useUpdateSource` pass `visibility` through the existing request objects. A new `useUpdateSourceVisibility` is unnecessary — reuse `useUpdateSource`. Mutations already invalidate `['sources']` and toast (keep as-is).

**Add-source wizard — `frontend/src/components/sources/AddSourceDialog.tsx` + `steps/ProcessingStep.tsx`:**
- Add `visibility: z.enum(['private','project'])` to `createSourceSchema` (default `'project'`), thread through `defaultValues` and `submitSingleSource` / `submitBatch` (`createRequest.visibility = data.visibility`).
- Render the selector in **`ProcessingStep.tsx`** inside the existing "Settings" `FormSection` (it already holds the embed toggle), as a `Controller`-wrapped radio group / segmented control with two options: private and project, each with a short description. This keeps visibility next to the other per-source processing settings and out of the type/notebook steps.

**Source card — `frontend/src/components/sources/SourceCard.tsx`:** render a small badge (lock icon for `private`, users icon for `project`) from `source.visibility`. Owner-only / admin affordances (edit visibility, delete) can key off `source.owner` vs the current user id from the auth store, but the authoritative check is server-side (403/404).

**Source detail — `frontend/src/components/source/SourceDetailContent.tsx`:** add a visibility control (same segmented control) that calls `useUpdateSource` with `{ visibility }`; only enabled when the current user is the owner or a company/project admin (best-effort UI gate; server enforces). Show a read-only badge otherwise.

**i18n — add to ALL 7 enforced locales** (`en-US`, `pt-BR`, `zh-CN`, `zh-TW`, `ja-JP`, `ru-RU`, `bn-IN`) under `frontend/src/lib/locales/<locale>/index.ts`, in the existing `sources` section (missing keys silently fall back to en-US, so all 7 must be filled). New keys (en-US values shown):
```
sources.visibility: "Visibility"
sources.visibilityPrivate: "Private"
sources.visibilityProject: "Project"
sources.visibilityPrivateDesc: "Only you and workspace/project admins can see this source."
sources.visibilityProjectDesc: "All members of this project can see this source."
sources.visibilityLabel: "Who can see this source?"
sources.visibilityChanged: "Source visibility updated"
sources.visibilityForbidden: "You don't have permission to change this source's visibility."
```
(The repo ships 16 locale directories; only the 7 above are the enforced set per `AGENTS.md`. Filling the other 9 is optional but they'll fall back to en-US.)

## Permissions / RBAC rules (explicit table: who can do what)

Roles: **Owner** = source.owner (uploader). **CoOwn/CoAdmin** = company `owner` or `admin` (from `membership` on the source's company). **ProjAdmin** = `project_member.role = 'admin'` on a project the source is referenced by (company owner/admin escalate to project admin). **ProjMember** = `project_member.role = 'member'` on such a project. **Outsider** = authenticated user with no membership in the source's company / no membership in any project referencing it.

### View / list / read / download / chat / search-surface

| Role \ visibility | `private` | `project` |
|---|---|---|
| Owner | ✅ allow | ✅ allow |
| Company owner/admin | ✅ allow | ✅ allow |
| Project admin | ✅ allow | ✅ allow |
| Project member (not owner) | ❌ deny (404) | ✅ allow |
| Outsider (other company / no project) | ❌ deny (404) | ❌ deny (404) |

### Mutate (edit metadata, edit visibility, delete, retry, (re)embed, generate insights)

| Role \ visibility | `private` | `project` |
|---|---|---|
| Owner | ✅ allow | ✅ allow |
| Company owner/admin | ✅ allow | ✅ allow |
| Project admin | ✅ allow | ✅ allow |
| Project member (not owner) | ❌ deny (403) | ❌ deny (403) |
| Outsider | ❌ deny (404) | ❌ deny (404) |

### Create
- Any project **member+** (member, project admin, company owner/admin) of a project in the active company may create a source and add it to that project. On create, `owner` = current user; `visibility` = chosen (`private` default-safe is `project` per product decision; the wizard defaults to `project`).
- A user with **no** project membership in the target project → 403 (cannot add sources to a project they're not in).

Notes on the matrix:
- **Deny code differs by action to avoid existence leaks:** a *view/list* deny returns **404** (a private source must be indistinguishable from "doesn't exist" for someone who can't see it). A *mutate* deny on a source the caller *can view* returns **403** (they know it exists but lack permission); a mutate deny on a source they *can't even view* returns **404**. Search/list simply omit non-visible rows (no error).
- Insights and embeddings have **no independent permission** — they inherit their parent source's visibility (view) / mutate rules.
- Chat sessions over a source require **view** on the source; a member may create/read/delete *their own* chat sessions over a `project` source without needing mutate rights on the source itself.

## Error handling
Follows the brief's contract + `open_notebook/AGENTS.md` (raise typed exceptions where handlers exist; routers here already raise `HTTPException` for source flows, so keep that pattern but with the correct codes):
- **401** — unauthenticated (no/invalid token): handled upstream by P1 middleware; frontend clears `auth-storage` and redirects `/login`.
- **403** — authenticated but not allowed to **mutate** a source the caller can view (edit/delete/retry/embed/generate-insight/change-visibility); or creating a source in a project the caller isn't a member of. Body `{"detail": "You do not have permission to modify this source"}` / visibility variant uses `sources.visibilityForbidden` client-side.
- **404** — source not found, **or** view-denied (private source the caller can't see, or a source outside the caller's company). Same `{"detail": "Source not found"}` body for both so existence isn't leaked.
- **400** — invalid `visibility` value (not in `{private, project}`), or invalid create payload (unchanged existing validations).
- **409 / 410** — not applicable to P5.
- Consistent JSON `{"detail": "..."}` (FastAPI default). Frontend surfaces via existing `getApiErrorMessage` + sonner toast; mutations already invalidate `['sources']`.

## Testing (concrete test cases)

**Backend — `tests/` (mirror `test_X3_suite1_tenant_leakage.py` style), e.g. `tests/test_p5_source_visibility.py`:**
1. `create_source` sets `owner = current_user` and persists chosen `visibility`; default is `'project'` when omitted.
2. Owner can GET / download / update / delete their own `private` source.
3. Company owner and company admin can view **and** mutate another member's `private` source.
4. Project admin (non-owner, non-company-admin) can view + mutate a `private` source in their project.
5. Project **member** (non-owner) gets **404** on GET of a `private` source, **403** on PUT/DELETE of a `project` source, and **200** on GET of a `project` source.
6. Outsider (member of a different company) gets **404** on GET/PUT/DELETE and the source never appears in their `GET /sources` list.
7. `GET /sources` (both notebook-scoped and all-sources) omits private sources the caller can't see and omits other companies' sources; paging (`limit`/`offset`) counts only visible rows.
8. **Search leakage:** user A creates a `private` source with a distinctive token in title + body + an insight; user B (same company, project member, non-owner) runs `POST /search` (text and vector) for that token → **0 source results**; a `project` source with the token **is** returned. Repeat for `/search/ask/simple` → answer does not contain the private token.
9. Insight endpoints: view/delete/save-as-note inherit source visibility (member 404 on private insight's source; owner OK).
10. Source chat: member cannot create a chat session over a private source (404); can over a project source.
11. `POST /embed` on a source the caller can't mutate → 403/404; owner → 200.
12. `PUT /sources/{id}` with `visibility` flips private↔project only for owner/admins; member → 403.
13. Migration 23 backfill: a source row created before the migration ends up `visibility='project'`, `owner=NONE`, and remains visible to project members.

**Frontend — `npm run test` (vitest) + `npm run lint` + `npm run build`:**
14. `AddSourceDialog` submits `visibility` in the create request; default `'project'`; batch mode applies the same visibility to all items.
15. `SourceCard` renders the private vs project badge from `source.visibility`.
16. `SourceDetailContent` visibility control is disabled for a non-owner/non-admin and enabled for the owner; changing it calls `useUpdateSource` and invalidates `['sources']`.
17. All 8 new i18n keys exist in all 7 enforced locales (extend the existing locale-key parity test in `frontend/src/lib/locales/index.test.ts`).

## Open questions / risks
- **`/search/ask` RAG threading:** confirming the `ask_graph` retrieval node can accept and honor `viewer_source_ids`. Risk: if it retrieves embeddings directly rather than via `fn::vector_search`, the filter must be added there too. Interim mitigation: restrict `/search/ask*` to `visibility='project'` sources until the graph is threaded. **Needs a quick check of `open_notebook/graphs/ask/`.**
- **Background context (podcasts):** `Notebook.get_context()` / `get_sources()` run in worker jobs with no user context; they currently see all project sources including private ones. Decision taken here: background jobs run with full project scope (the project owner initiated them). Flag if product wants private sources excluded from podcasts by default.
- **Company resolution from source:** a source can be referenced by multiple projects (potentially — though in practice one). The predicate resolves company/visibility across *all* referencing projects (allow if any qualifies). Confirm sources are never referenced across two companies' projects; P6's tenant scoping should make cross-company references impossible, but P5's `can_view_source` guards against it defensively (404 if no referencing project is in `ctx.company_id`).
- **Performance:** `visible_source_ids` runs on every list and search. It must be a single parameterized SurrealQL query (not N+1 over projects); the new `idx_source_visibility` / `idx_source_owner` indexes back it. Validate query plan on a large dataset.
- **Owner nullability:** legacy sources have `owner = NONE`; they're only mutable by company/project admins (no owner match). Acceptable, but means a pre-auth source can't be edited by a plain member even if they "uploaded" it before auth existed.
- **P6 dependency:** the `PermissionContext` dependency shape is defined here but implemented in P6. P5 ships a JWT-claims-reading stub so it's independently testable; the two specs must keep the context interface in sync.
