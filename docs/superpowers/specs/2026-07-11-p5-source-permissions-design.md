# P5 — Source permissions (owner + scope) — Design Spec
Date: 2026-07-11 · Branch: feat/auth-multitenancy · Status: Draft (v2 — 3-level scope)

## Goal (2-4 sentences)
Add `owner` (uploader user), `scope` (`personal | project | company`), and a `promoted_from` schema hook to the `source` table so every source read/list/mutate operation is filtered by who is allowed to see it, within the active **workspace** (P6). When adding a source the user picks a scope: **personal** (only me, plus workspace owner/admin, plus the project's admins), **project** (all members of the project it belongs to), or **company** (every member of the workspace, across every project). Every endpoint that lists, reads, mutates, downloads, chats over, embeds, or searches a source (or its insights/embeddings) must apply the scope check; search in particular must never surface a source the caller cannot see. In a `kind="personal"` workspace (solo — one member, always the owner) all three scopes collapse to owner-only, as a structural consequence of the workspace having no other members, not as special-cased code. This is the last content-plane permission layer before P6 wires up app-layer workspace scoping.

## v2 revision note
This spec supersedes the earlier 2-level (`private|project`) draft per the shared `ARCHITECTURE_BRIEF.md` v2 revision: source scope is **THREE** levels (`personal|project|company`), the tenant is a **`workspace`** (`kind = personal|company`, NOT `company`), and the request context field is **`workspace_id`** (NOT `company_id`). All "company visibility" wording below refers to the new **`company` scope value** (workspace-wide visibility), not the tenant. "Workspace" is the DB/API/token word for the tenant; "Company" stays a product/UI word for a `kind="company"` workspace and, separately, the name of the new widest source scope.

## Depends on / Provides

**Depends on:**
- **P1 (auth+users)** — a real authenticated `user` record; `owner` links to `user`.
- **P2 (workspace+membership+roles)** — workspace-level roles `owner|admin|member` via `membership`; needed for "workspace owner/admin sees everything" and for "`company` scope = every member of the workspace."
- **P3 (project, repurposed from `notebook`)** — sources attach to a `project` (the current `notebook` table); the migration and enforcement assume `project` + `project.workspace` + `project.owner` + `project.default_source_scope` exist (P3's migration 21).
- **P4 (invitation)** — not a hard dependency; `project_member` rows it produces are consumed here.
- **P6 (tenant/workspace scoping helper)** — this spec assumes a request context object providing `(user_id, workspace_id, workspace_role, async project_role())` is available as a FastAPI dependency. **P5 does not build that helper**; it declares the shape it needs (see "Permission context dependency" below) and P6 provides the concrete implementation. Until P6 lands, P5's check functions can be unit-tested against a hand-built context. (P6's revised (v2, workspace-model) draft already names its concrete `PermissionContext` with these exact `workspace_id`/`workspace_role` field names — the two specs are in sync; no `company_id`/`company_role` remains on either side.)

**Provides:**
- `source.owner` + `source.scope` + `source.promoted_from` schema (migration 23) and a reusable permission predicate `can_view_source` / `can_mutate_source` (new `api/source_permissions.py`) that all source-touching routers call.
- A scope-aware replacement for the `fn::text_search` / `fn::vector_search` SurrealQL functions (migration 23) so search results are pre-filtered at the DB layer.
- Frontend: a personal/project/company scope selector in the add-source wizard, a scope badge on source cards, and an editable scope control on the source detail view, with i18n keys in all 14 locales.

## Scope (in) / Out of scope

**In scope:**
- Migration adding `owner` + `scope` + `promoted_from` (schema hook only) to `source`, with backfill (existing sources → `scope = 'project'`, `owner = NONE`).
- Setting `owner` = current user and `scope` = chosen value (or the target project's `default_source_scope`, falling back to `'project'`) on source creation.
- A permission predicate module and its wiring into **every** source-touching endpoint enumerated below (sources, source_chat, insights, embedding, search, context, notebook/project `get_context`).
- Scope-aware search functions (both text and vector).
- Frontend scope selector (add wizard), badge (card), and edit control (detail), plus hooks/types/i18n.

**Out of scope:**
- The generic `workspace_id` tenant-scoping helper and role-gating guards — **P6**.
- Per-source ACLs / sharing with specific users, link-based sharing, or scopes beyond the three defined here.
- `promoted_from` is a **schema hook only** — no promotion/move flow, no read/write of it via any P5 endpoint or frontend field this phase (mirrors `project.promoted_from` from P3).
- Note / chat_session scope (notes have no owner/scope in this phase; they inherit project membership only). Only `source` gets owner+scope here.
- Changing the `reference` graph edge model (source↔project relation stays as-is: `RELATE source->reference->notebook`, `in`=source, `out`=notebook/project).

## Data model changes (SurrealDB migration 23.surrealql + _down)

New migration pair `open_notebook/database/migrations/23.surrealql` and `23_down.surrealql`, registered in `open_notebook/database/async_migrate.py` (append `AsyncMigration.from_file("open_notebook/database/migrations/23.surrealql")` to `self.up_migrations` and the matching `23_down.surrealql` to `self.down_migrations` — migrations are hard-coded, not auto-discovered; current highest registered is **19**, at lines ~130-135 (up) / ~189-194 (down) of `async_migrate.py`. P2/P3/P4's migrations 20/21/22 land before this one; 23 is appended after them).

**`23.surrealql`:**
```surrealql
-- Migration 23: Source ownership + scope (P5 source permissions, v2 3-level scope)

-- owner = the user who uploaded/created the source. NONE for legacy/backfilled
-- sources (no user existed pre-auth). Nullable on purpose.
DEFINE FIELD IF NOT EXISTS owner ON TABLE source TYPE option<record<user>>;

-- scope gate (v2: THREE levels, not two).
-- 'personal' = owner + workspace owner/admin + the project's admins only.
-- 'project'  = all members of any project the source is referenced by.
-- 'company'  = every member of the active workspace, across every project.
DEFINE FIELD IF NOT EXISTS scope ON TABLE source
    TYPE string
    ASSERT $value IN ['personal', 'project', 'company']
    DEFAULT 'project';

-- Schema hook only (P5 does NOT build the promotion flow): the source this row
-- was promoted from, for a later phase that moves/copies a source between
-- workspaces or scopes. Mirrors project.promoted_from (P3, migration 21).
DEFINE FIELD IF NOT EXISTS promoted_from ON TABLE source TYPE option<record<source>>;

-- Backfill existing rows: pre-existing sources predate multi-tenancy, so they
-- default to 'project' (visible to all project members) and owner stays NONE.
-- NOTE: source carries NO denormalized `workspace` column — a source inherits
-- its workspace from the project (physical `notebook` table) it is referenced
-- by via the `reference` edge. By the time this migration (23) runs, P3's
-- migration (21) has already backfilled every notebook/project into a
-- workspace, so every legacy source resolves to a workspace through its
-- project. `can_view_source` derives the workspace this way
-- (SELECT VALUE out.workspace FROM reference WHERE in = $source).
UPDATE source SET scope = 'project' WHERE scope = NONE;

-- Indexes backing the scope filter used by list/search so it does not degrade
-- to a full scan as data grows.
DEFINE INDEX IF NOT EXISTS idx_source_scope ON TABLE source FIELDS scope CONCURRENTLY;
DEFINE INDEX IF NOT EXISTS idx_source_owner ON TABLE source FIELDS owner CONCURRENTLY;

-- Replace the search functions with scope-aware variants. They take an extra
-- $viewer_source_ids param: the pre-computed set of source ids the caller may
-- see (owner/admin escalation AND the 3-scope resolution are both resolved in
-- Python by visible_source_ids(), then passed down as a flat allow-list). Any
-- source not in that set is filtered out of every result branch. The fn body
-- itself does not need to know about 'personal'/'project'/'company' — it only
-- filters by the precomputed id set.
REMOVE FUNCTION IF EXISTS fn::text_search;
DEFINE FUNCTION IF NOT EXISTS fn::text_search(
    $query_text: string, $match_count: int, $sources: bool, $show_notes: bool,
    $viewer_source_ids: array<record<source>>
) {
    -- identical body to migration 4's fn::text_search, EXCEPT every source /
    -- source_embedding / source_insight sub-select gains:
    --     AND (source.id IN $viewer_source_ids)   -- (or `id IN ...` on the source table)
    -- Notes are unaffected (notes have no scope in P5).
    -- (Full body reproduced from migrations/4.surrealql with the added WHERE clauses.)
};

REMOVE FUNCTION IF EXISTS fn::vector_search;
DEFINE FUNCTION IF NOT EXISTS fn::vector_search(
    $query: array<float>, $match_count: int, $sources: bool, $show_notes: bool,
    $min_similarity: float, $viewer_source_ids: array<record<source>>
) {
    -- identical body to migration 9's fn::vector_search (the dimension-guard
    -- fixed version), EXCEPT the source_embedding and source_insight branches
    -- gain: AND source.id IN $viewer_source_ids
    -- Note branch unchanged.
};
```

**`23_down.surrealql`:**
```surrealql
-- Migration 23 rollback

REMOVE INDEX IF EXISTS idx_source_scope ON TABLE source;
REMOVE INDEX IF EXISTS idx_source_owner ON TABLE source;
REMOVE FIELD IF EXISTS scope ON TABLE source;
REMOVE FIELD IF EXISTS owner ON TABLE source;
REMOVE FIELD IF EXISTS promoted_from ON TABLE source;

-- Restore the pre-P5 search functions (copy the DEFINE FUNCTION bodies verbatim
-- from migrations/4.surrealql (fn::text_search) and migrations/9.surrealql
-- (fn::vector_search) — the 4-arg / 5-arg signatures without $viewer_source_ids).
REMOVE FUNCTION IF EXISTS fn::text_search;
-- <re-DEFINE fn::text_search from migration 4>
REMOVE FUNCTION IF EXISTS fn::vector_search;
-- <re-DEFINE fn::vector_search from migration 9>
```

**Domain model change — `open_notebook/domain/notebook.py`, class `Source` (fields currently at lines 391-402, `command` validator at 404-410, `_prepare_save_data` at 621-629 — confirmed against the current pre-P5 file):**
Add three fields to `Source` (subclass of `ObjectModel`; `Literal`, `RecordID`, `ensure_record_id`, `repo_query` are already imported at module top):
```python
owner: Optional[Union[str, RecordID]] = None      # link to user
scope: Literal["personal", "project", "company"] = "project"
promoted_from: Optional[Union[str, RecordID]] = None   # schema hook only, unused in P5
```
Add a combined `field_validator(mode="before")` for `owner` and `promoted_from` mirroring the existing `command` validator (coerce a str to `RecordID` via `ensure_record_id`, pass through `None`). `scope` needs no special handling (plain `Literal`). `Source._prepare_save_data()` already exists — extend it to coerce `owner` and `promoted_from` to `RecordID` when not `None`, same pattern as `command`.

Add a helper query method on `Source` (used by the permission predicate) — the same `reference`-edge query already used inline in `api/routers/sources.py`'s `get_source` (~lines 717-720) and `retry_source_processing` (~lines 913-921):
- `async def get_project_ids(self) -> List[str]` — `SELECT VALUE out FROM reference WHERE in = $id`.

## Backend: endpoints, services, domain models (file paths)

### New: permission context dependency (shape only; P6 implements)
P5 assumes a FastAPI dependency yielding a context object, referenced here as `ctx: PermissionContext`:
```
ctx.user_id: str                      # current authenticated user record id
ctx.workspace_id: str                 # active workspace record id (personal or company)
ctx.workspace_role: "owner"|"admin"|"member"   # role in ctx.workspace_id (always "owner" in a personal workspace)
async ctx.project_role(project_id) -> "admin"|"member"|None   # via project_member + workspace_role escalation
```
Until P6, P5 ships a minimal stub of this dependency in `api/source_permissions.py` (reads the JWT claims that P1/P2 already put on the request: `sub`, `workspace_id`, `role`) so P5 endpoints and tests are runnable; P6 replaces the stub body with the real tenant-scoping helper, keeping the same field names. This dependency is added to every source-touching route via `Depends`.

Note: `project_member` rows only exist for **company-workspace** projects (P3's guardrail: personal-workspace projects have no `project_member` rows, since a personal workspace has exactly one member). `project_role()` still works correctly for personal-workspace projects because `workspace_role` is always `"owner"` there, which the resolver escalates to `"admin"` before ever querying `project_member`.

### New: `api/source_permissions.py` (the predicate module — the heart of P5)
Pure functions + two query helpers, called by all routers. Business logic lives here (routers stay thin, per `api/AGENTS.md`).

```
async def can_view_source(source: Source, ctx: PermissionContext) -> bool
async def can_mutate_source(source: Source, ctx: PermissionContext) -> bool
async def visible_source_ids(ctx: PermissionContext, project_id: str | None) -> list[str]
async def require_view_source(source_id: str, ctx) -> Source   # loads, checks, raises 404/403
async def require_mutate_source(source_id: str, ctx) -> Source # loads, checks, raises 404/403
```

Logic of `can_view_source` (all checks are relative to `ctx.workspace_id`, the active workspace):
1. Resolve the source's project ids (`source.get_project_ids()`) and, from any of them, the workspace(s) that own it (`SELECT VALUE out.workspace FROM reference WHERE in = $source`). If the source is not referenced by any project in `ctx.workspace_id`, treat as not-found (404) — enforces workspace isolation (belt-and-braces with P6).
2. If `source.owner == ctx.user_id` → **allow**.
3. If `ctx.workspace_role in ('owner','admin')` → **allow** (workspace owner/admin sees everything, including `personal`-scope; this branch alone is what makes a personal workspace's sole owner see all of their own sources regardless of stored scope — no special-casing needed).
4. If any of the source's projects has `ctx.project_role(project_id) == 'admin'` → **allow**.
5. If `source.scope == 'company'` → **allow**. No further membership lookup is needed: step 1 already proved the source's workspace equals `ctx.workspace_id`, and holding a valid `PermissionContext` for that workspace already proves the caller is an active member of it (P6 only mints a workspace-scoped token/context for active members). `company` scope is therefore "visible to everyone already known to be in this workspace."
6. If `source.scope == 'project'` **and** the caller is a member (`ctx.project_role(project_id) in ('admin','member')`) of any project the source is referenced by → **allow**.
7. Otherwise **deny** (this is the only branch a plain `personal`-scope source falls through to for a non-owner, non-admin project member or a workspace member outside the project).

Logic of `can_mutate_source` (edit/delete/retry/(re)embed/generate-insight/change-scope): steps 2–4 above only (owner + workspace owner/admin + project admin). A plain `project`- or `company`-scope viewer who is not the owner/admin may **view** the source but may **not** edit/delete it.

`require_view_source` / `require_mutate_source`: load via `Source.get(source_id)` (404 if missing), run the predicate, raise `HTTPException(403, detail="You do not have permission to modify this source")` on mutate-deny where the caller CAN view, or `HTTPException(404, detail="Source not found")` on view-deny / mutate-deny-where-caller-cannot-even-view (no existence leak). Return the `Source` so the caller reuses it.

### Endpoint-by-endpoint changes

**`api/routers/sources.py`** (imports currently line 36: `from open_notebook.domain.notebook import Asset, Notebook, Source` — becomes `Asset, Project, Source` post-P3, plus the new predicate imports; all endpoints take `ctx = Depends(get_permission_context)`):
| Endpoint | Change |
|---|---|
| `GET /sources` (`get_sources`, currently 213-348) | Constrain the list query to visible sources. Compute `visible_source_ids(ctx, notebook_id)` and add `AND id IN $visible_ids` to both the notebook-scoped and all-sources `SELECT ... FROM source` queries. Prefer an in-query predicate over post-filtering so `LIMIT`/`START` paging stays correct. Also scope the no-`notebook_id` branch to the active workspace's projects. |
| `POST /sources` + `POST /sources/json` (`create_source` 351-643, `create_source_json` 646-651) | Accept a new form/JSON field `scope` (optional — `Optional[Literal["personal","project","company"]] = None`). Resolve the effective scope: `source_data.scope or primary_project.default_source_scope or "project"` (primary project = the first entry of `notebooks[]`). Set `source.owner = ctx.user_id` and `source.scope = resolved_scope` on both async and sync paths before `source.save()`. Validate each `notebooks[]` project belongs to `ctx.workspace_id` and the caller may add sources to it (member+). Reject a `scope` value outside `{personal, project, company}` with 400 (parse_source_form_data already wraps the `SourceCreate(...)` constructor and converts a `ValidationError` to a 400, the same existing pattern used for the other `Literal`/enum fields on this model — the new `scope` field reuses it, no new error-handling code required). |
| `GET /sources/{id}` (`get_source`, 694-754) | Replace `Source.get` + null check with `await require_view_source(source_id, ctx)`. |
| `HEAD/GET /sources/{id}/download` (`check_source_file` 758-767, `download_source_file` 771-784 → `_resolve_source_file` 654-676) | Add `require_view_source` before returning the file. A `personal`-scope file must not be downloadable by a non-viewer. |
| `GET /sources/{id}/status` (`get_source_status`, 788-844) | `require_view_source`. |
| `PUT /sources/{id}` (`update_source`, 848-886) | `require_mutate_source`. Also allow updating `scope` here: extend `SourceUpdate` with `scope: Optional[Literal['personal','project','company']]`; only owner/admins (already enforced by mutate check) may flip it. |
| `POST /sources/{id}/retry` (`retry_source_processing`, 890-1015) | `require_mutate_source` (re-processing is a mutation). |
| `DELETE /sources/{id}` (`delete_source`, 1019-1033) | `require_mutate_source`. |
| `GET /sources/{id}/insights` (`get_source_insights`, 1037-1060) | `require_view_source` (insights inherit the source's scope). |
| `POST /sources/{id}/insights` (`create_source_insight`, 1068-1113) | `require_mutate_source` (generating insights writes to the source). |

**`api/routers/insights.py`** (insights reference a source via `SourceInsight.get_source()`, currently lines 11-84; resolve it and check):
| Endpoint | Change |
|---|---|
| `GET /insights/{id}` (`get_insight`, 11-34) | After `source = await insight.get_source()`, `require_view_source(source.id, ctx)`. |
| `DELETE /insights/{id}` (`delete_insight`, 37-52) | Resolve source via `insight.get_source()`, then `require_mutate_source`. |
| `POST /insights/{id}/save-as-note` (`save_insight_as_note`, 55-84) | `require_view_source` on the insight's source (reading it into a note). |

**`api/routers/source_chat.py`** — every endpoint currently loads the source via the repeated block `full_source_id = ...; source = await Source.get(full_source_id); if not source: raise HTTPException(404, ...)`; replace that block with the predicate:
| Endpoint | Change |
|---|---|
| `POST /sources/{id}/chat/sessions` (`create_source_chat_session`, 87-129) | `require_view_source` (must see the source to chat about it). |
| `GET /sources/{id}/chat/sessions` (`get_source_chat_sessions`, 132-190) | `require_view_source`. |
| `GET /sources/{id}/chat/sessions/{sid}` (`get_source_chat_session`, 193-287) | `require_view_source`. |
| `PUT /sources/{id}/chat/sessions/{sid}` (`update_source_chat_session`, 290-359) | `require_view_source`. |
| `DELETE /sources/{id}/chat/sessions/{sid}` (`delete_source_chat_session`, 362-414) | `require_view_source` (chat sessions are per-user reads; deleting your own session over a source you can view is allowed — this is not a source mutation). |
| `POST /sources/{id}/chat/sessions/{sid}/messages` (`send_message_to_source_chat`, 487-558) | `require_view_source`. |

**`api/routers/embedding.py`** (`POST /embed`, `embed_content` 13-124) — when `item_type == 'source'` (both the async-submit branch ~34-70 and the domain-model branch ~72-110), `require_mutate_source(item_id, ctx)` before dispatching `embed_source` / `source_item.vectorize()` (embedding writes derived data for the source). `note` branch unchanged.

**`api/routers/search.py`** (`POST /search` 17-58, `POST /search/ask` 113-162, `POST /search/ask/simple` 165-222) — the leakage-critical path. See dedicated section below.

**`api/routers/context.py`** (`get_notebook_context`, 12-127) and `Project.get_sources()` (`open_notebook/domain/notebook.py`, currently `Notebook.get_sources` 31-47) — context assembly for chat/podcast pulls **all** sources of a project with no scope filter, in two places: the `context_config`-driven per-source loop (lines ~25-76, calling `Source.get(full_source_id)` directly) and the default no-config branch (lines ~77-109, calling `notebook.get_sources()`). Add an optional `viewer_source_ids: set[str] | None` param to `Project.get_sources()` and filter the `reference`-joined result to that set; skip any `context_config` source id not in the set. The context router computes the allow-list once from `ctx` and passes it to both branches. Rationale: a company member chatting with a project must not have another user's *personal*-scope source silently injected into the LLM context. (Podcast/background jobs that build context via `Project.get_context()` without a user context use the unfiltered path — document that they run with full project scope, which is acceptable because they are project-owner-initiated.)

### Search-leakage concern (explicit)
`fn::text_search` and `fn::vector_search` (defined in migrations 4 and 9, called from `text_search()`/`vector_search()` module-level functions in `open_notebook/domain/notebook.py` at ~lines 756-828, invoked by `api/routers/search.py`) currently scan `source`, `source_embedding`, and `source_insight` **globally with no owner/scope/workspace filter**. Without a change, a text or vector search — and the `/search/ask` RAG flow that embeds source content into answers — would surface titles, highlighted snippets, and full-text chunks of **personal-scope sources belonging to other users, and sources in other workspaces**. This is the primary data-leak risk of the whole feature.

Fix (two layers):
1. **DB layer:** the migration-23 search functions gain a `$viewer_source_ids` parameter and filter every source-derived branch (`source`, `source_embedding`, `source_insight`) with `AND source.id IN $viewer_source_ids`. Note branches are untouched (notes are project-membership scoped, not per-source scoped, in P5).
2. **App layer:** `text_search()` and `vector_search()` in `open_notebook/domain/notebook.py` gain a `viewer_source_ids: list[str]` param passed straight into the SurrealQL call. `search.py` computes it via `visible_source_ids(ctx, project_id=None)` (all sources across the caller's active workspace that the caller may view — `personal` owned by them, `project` where they're a member, `company` unconditionally since `company` scope is workspace-wide) and passes it down. The RAG `ask_graph` retrieval path (`open_notebook/graphs/ask.py`, a single module, not a package) is invoked from `/search/ask*`; it must be given the same `viewer_source_ids` filter so retrieved chunks feeding the LLM answer are also scoped — thread the id set through the graph config (same mechanism as the model ids already in `configurable`).

Computing `visible_source_ids`: a single SurrealQL query returning source ids in the caller's workspace's projects where (workspace owner/admin → every source unconditionally) OR (`owner = caller`) OR (`scope = 'company'`) OR (caller is admin of the source's project) OR (`scope = 'project' AND` caller is a member of the source's project). Implement as one parameterized query in `source_permissions.py` (avoid N+1). This same helper backs `GET /sources` list filtering.

## Pydantic model changes — `api/models.py`
- `SourceCreate` (currently 297-345, fields end at `async_processing` 324-326): add `scope: Optional[Literal["personal", "project", "company"]] = None` (omitted → resolved server-side from `project.default_source_scope`, falling back to `"project"`).
- `SourceUpdate` (currently 348-350, `title`/`topics` only): add `scope: Optional[Literal["personal", "project", "company"]] = None`.
- `SourceResponse` (353-369) and `SourceListResponse` (372-386): add `scope: str = "project"` and `owner: Optional[str] = None` (so the frontend can render badge + gate the edit control). Populate them in every response constructor in `sources.py` (list, get, create sync/async, update, retry).
- `parse_source_form_data` (`sources.py`, 141-209): add `scope: Optional[str] = Form(None)` and pass into `SourceCreate`.

## Frontend: routes, components, hooks, stores, i18n keys (file paths)

**Types — `frontend/src/lib/types/api.ts`:**
- `CreateSourceRequest` (currently 96-112): add `scope?: 'personal' | 'project' | 'company'`.
- `UpdateSourceRequest` (currently 120-125, note: this frontend type already carries `title`/`type`/`url`/`content` even though the backend `SourceUpdate` only accepts `title`/`topics` — a pre-existing mismatch, not introduced by P5, not fixed here): add `scope?: 'personal' | 'project' | 'company'`.
- `SourceListResponse` (21-39) / `SourceDetailResponse extends SourceListResponse` (41-44) / `SourceResponse = SourceDetailResponse` (46, alias): add `scope: 'personal' | 'project' | 'company'` and `owner?: string | null` to `SourceListResponse` (the other two inherit it).

**API client — `frontend/src/lib/api/sources.ts`:**
- `create` (32-69, always builds `FormData`): `formData.append('scope', data.scope ?? 'project')`.
- `update` (sends the JSON body as-is): include `scope` when present — no code change needed beyond the type addition.

**Hook — `frontend/src/lib/hooks/use-sources.ts`:** no signature change; `useCreateSource`/`useUpdateSource` pass `scope` through the existing request objects. A new `useUpdateSourceScope` is unnecessary — reuse `useUpdateSource`. Mutations already invalidate `['sources']` and toast (keep as-is).

**Add-source wizard — `frontend/src/components/sources/AddSourceDialog.tsx` (`createSourceSchema` 30-66, `submitSingleSource` 300-320, `submitBatch` 323-383) + `steps/ProcessingStep.tsx`:**
- Add `scope: z.enum(['personal','project','company'])` to `createSourceSchema` (default `'project'`), thread through `defaultValues` and `submitSingleSource` / `submitBatch` (`createRequest.scope = data.scope`).
- Render the selector in **`ProcessingStep.tsx`** inside the existing "Settings" `FormSection` (it already holds the embed toggle), as a `Controller`-wrapped 3-option segmented control (personal / project / company), each with a short description. This keeps the scope choice next to the other per-source processing settings and out of the type/notebook steps.
- When the active workspace's `kind` is `"personal"` (read from the P2/P6 workspace store), the three scopes are behaviorally identical (owner-only) — render the control disabled, pinned to `personal`, with a one-line hint (`sources.visibilityPersonalWorkspaceHint`) instead of hiding it outright, so the UI never implies a choice that has no effect. This is a UX nicety layered on top of a server-side rule that already collapses the values; it is not required for correctness.

**Source card — `frontend/src/components/sources/SourceCard.tsx` (metadata badges ~line 281, `areEqual` comparator 450-471):** render a small badge (lock icon for `personal`, users icon for `project`, building/globe icon for `company`) from `source.scope`. Add `prev.source.scope === next.source.scope` to the `areEqual` comparator so a scope change re-renders the card. Owner-only / admin affordances (edit scope, delete) can key off `source.owner` vs the current user id from the auth store, but the authoritative check is server-side (403/404).

**Source detail — `frontend/src/components/source/SourceDetailContent.tsx`:** add a 3-option scope control (same segmented control) that calls `useUpdateSource` with `{ scope }`; only enabled when the current user is the owner (best-effort UI gate; server enforces the full owner/workspace-admin/project-admin rule). Show a read-only badge otherwise.

**i18n — add to ALL 14 locales** (`frontend/src/lib/locales/index.ts` registers exactly 14: `en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN, it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR`; the 7 enforced ones — `en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN` — get real translations, the other 7 get English-fallback values) under `frontend/src/lib/locales/<locale>/index.ts`, in the existing `sources` section (missing keys silently fall back to en-US but the parity test still requires every key to exist in every locale). New keys (en-US values shown; renamed/expanded from the 2-scope draft):
```
sources.visibility: "Visibility"
sources.visibilityPersonal: "Personal"
sources.visibilityProject: "Project"
sources.visibilityCompany: "Company"
sources.visibilityPersonalDesc: "Only you, workspace owners/admins, and this project's admins can see this source."
sources.visibilityProjectDesc: "All members of this project can see this source."
sources.visibilityCompanyDesc: "All members of this workspace can see this source, across every project."
sources.visibilityLabel: "Who can see this source?"
sources.visibilityChanged: "Source visibility updated"
sources.visibilityForbidden: "You don't have permission to change this source's visibility."
```
(The product-facing label stays "Visibility" even though the DB/API field is named `scope` — same convention as "Company" staying the UI word for a `kind="company"` workspace while the DB field is `workspace`.)

## Permissions / RBAC rules (explicit table: who can do what)

Roles (all relative to **the source's** workspace/projects): **Owner** = `source.owner` (uploader). **Workspace owner/admin** = `membership.role ∈ {owner,admin}` on the source's workspace (always `owner`, and the sole member, in a `kind="personal"` workspace). **Project admin** = `project_member.role = 'admin'` on a project the source is referenced by (workspace owner/admin escalate to project admin everywhere in their workspace). **Project member** = `project_member.role = 'member'` on such a project. **Workspace member (other project)** = a member of the source's workspace who is **not** a member of any project the source is referenced by. **Outsider** = an authenticated user who is not a member of the source's workspace at all.

### View / list / read / download / chat / search-surface

| Role \ scope | `personal` | `project` | `company` |
|---|---|---|---|
| Owner | ✅ allow | ✅ allow | ✅ allow |
| Workspace owner/admin | ✅ allow | ✅ allow | ✅ allow |
| Project admin (of the source's project) | ✅ allow | ✅ allow | ✅ allow |
| Project member (of the source's project, not owner) | ❌ deny (404) | ✅ allow | ✅ allow |
| Workspace member (not in that project) | ❌ deny (404) | ❌ deny (404) | ✅ allow |
| Outsider (not a member of this workspace) | ❌ deny (404) | ❌ deny (404) | ❌ deny (404) |

**In a `kind="personal"` workspace** (solo, one member = owner) every row except "Owner" is structurally impossible — there is no second member, project-admin, or outsider *within that workspace* — so all three scope columns collapse to owner-only. This falls out of the predicate's existing "workspace owner/admin → allow" branch (step 3) plus the workspace's own membership invariant; no `kind`-conditional code is needed in `can_view_source`.

### Mutate (edit metadata, edit scope, delete, retry, (re)embed, generate insights)

| Role \ scope | `personal` | `project` | `company` |
|---|---|---|---|
| Owner | ✅ allow | ✅ allow | ✅ allow |
| Workspace owner/admin | ✅ allow | ✅ allow | ✅ allow |
| Project admin | ✅ allow | ✅ allow | ✅ allow |
| Project member (not owner) | ❌ deny (403) | ❌ deny (403) | ❌ deny (403) |
| Workspace member (not in that project) | ❌ deny (404 — cannot even view) | ❌ deny (404 — cannot even view) | ❌ deny (403 — can view `company`, cannot mutate) |
| Outsider | ❌ deny (404) | ❌ deny (404) | ❌ deny (404) |

### Create
- Any project **member+** (member, project admin, workspace owner/admin) of a project in the active workspace may create a source and add it to that project. On create, `owner` = current user; `scope` = the value the user chose, or — if omitted — the target project's `default_source_scope` (P3 field), falling back to `"project"` if that isn't set. The wizard's UI default is `"project"`.
- A user with **no** project membership in the target project → 403 (cannot add sources to a project they're not in).
- In a `kind="personal"` workspace the sole owner always creates freely; whatever `scope` is stored is inert (collapses to owner-only per the table above).

Notes on the matrix:
- **Deny code differs by action to avoid existence leaks:** a *view/list* deny returns **404** (a source the caller can't see must be indistinguishable from "doesn't exist"). A *mutate* deny on a source the caller *can view* returns **403** (they know it exists but lack permission — this is the `company`-scope workspace-member row); a mutate deny on a source they *can't even view* returns **404**. Search/list simply omit non-visible rows (no error).
- Insights and embeddings have **no independent permission** — they inherit their parent source's scope (view) / mutate rules.
- Chat sessions over a source require **view** on the source; a member may create/read/delete *their own* chat sessions over a `project`- or `company`-scope source without needing mutate rights on the source itself.
- `company` scope needs no per-request membership subquery beyond "same workspace as the source" — holding a `PermissionContext` for `ctx.workspace_id` already proves workspace membership (P6 only mints a workspace-scoped context for active members).

## Error handling
Follows the brief's contract + `open_notebook/AGENTS.md` (raise typed exceptions where handlers exist; routers here already raise `HTTPException` for source flows, so keep that pattern but with the correct codes):
- **401** — unauthenticated (no/invalid token): handled upstream by P1 middleware; frontend clears `auth-storage` and redirects `/login`.
- **403** — authenticated but not allowed to **mutate** a source the caller can view (edit/delete/retry/embed/generate-insight/change-scope); or creating a source in a project the caller isn't a member of; or inviting into a personal workspace (P4, not P5). Body `{"detail": "You do not have permission to modify this source"}` / scope variant uses `sources.visibilityForbidden` client-side.
- **404** — source not found, **or** view-denied (a `personal`- or `project`-scope source the caller can't see, or a source outside the caller's active workspace). Same `{"detail": "Source not found"}` body for both so existence isn't leaked.
- **400** — invalid `scope` value (not in `{personal, project, company}`), or invalid create payload (unchanged existing validations).
- **409 / 410** — not applicable to P5.
- Consistent JSON `{"detail": "..."}` (FastAPI default). Frontend surfaces via existing `getApiErrorMessage` + sonner toast; mutations already invalidate `['sources']`.

## Testing (concrete test cases)

**Backend — `tests/` (mirror the tenant-leakage-style suites), e.g. `tests/test_p5_source_scope.py`:**
1. `create_source` sets `owner = current_user` and persists the chosen `scope`; when `scope` is omitted, it resolves from the target project's `default_source_scope`, falling back to `'project'`.
2. Owner can GET / download / update / delete their own `personal`-scope source.
3. Workspace owner and workspace admin can view **and** mutate another member's `personal`-scope source.
4. Project admin (non-owner, non-workspace-admin) can view + mutate a `personal`-scope source in their project.
5. Project **member** (non-owner) gets **404** on GET of a `personal`-scope source, **403** on PUT/DELETE of a `project`-scope source, and **200** on GET of a `project`-scope source.
6. **`company`-scope visibility:** a workspace member with no membership in the source's project can GET a `company`-scope source (**200**) but gets **403** on PUT/DELETE of it, and still gets **404** on a `personal`- or `project`-scope source in a project they're not in.
7. Outsider (not a member of this workspace at all) gets **404** on GET/PUT/DELETE for all three scopes, and the source never appears in their `GET /sources` list.
8. `GET /sources` (both notebook-scoped and all-sources) omits sources the caller can't see per the 3-scope rule and omits other workspaces' sources; paging (`limit`/`offset`) counts only visible rows.
9. **Search leakage:** user A creates a `personal`-scope source with a distinctive token in title + body + an insight; user B (same workspace, project member, non-owner) runs `POST /search` (text and vector) for that token → **0 source results**; a `project`- or `company`-scope source with the token **is** returned to a qualifying viewer. Repeat for `/search/ask/simple` → answer does not contain the personal-scope token.
10. Insight endpoints: view/delete/save-as-note inherit source scope (member 404 on a personal-scope insight's source; owner OK).
11. Source chat: member cannot create a chat session over a `personal`-scope source they don't own/admin (404); can over a `project`- or `company`-scope source they're entitled to view.
12. `POST /embed` on a source the caller can't mutate → 403/404; owner → 200.
13. `PUT /sources/{id}` with `scope` flips between all three values only for owner/workspace-admins/project-admins; plain member → 403.
14. Migration 23 backfill: a source row created before the migration ends up `scope='project'`, `owner=NONE`, `promoted_from=NONE`, and remains visible to project members.
15. **Personal-workspace collapse:** in a `kind="personal"` workspace, the sole owner can view/mutate their own sources regardless of stored `scope` value (no second user exists to probe the "deny" branches — assert via the predicate directly with `workspace_role="owner"`).

**Frontend — `npm run test` (vitest) + `npm run lint` + `npm run build`:**
16. `AddSourceDialog` submits `scope` in the create request; default `'project'`; batch mode applies the same scope to all items; the control is disabled (pinned to `personal`) when the active workspace `kind` is `personal`.
17. `SourceCard` renders the personal/project/company badge from `source.scope`.
18. `SourceDetailContent` scope control is disabled for a non-owner and enabled for the owner; changing it calls `useUpdateSource` and invalidates `['sources']`.
19. All new i18n keys exist in all 14 locales (extend the existing locale-key parity test in `frontend/src/lib/locales/index.test.ts`).

## Open questions / risks
- **`/search/ask` RAG threading:** confirming the `ask_graph` retrieval node (`open_notebook/graphs/ask.py`) can accept and honor `viewer_source_ids` via `config["configurable"]`. Risk: if it retrieves embeddings directly rather than via `fn::vector_search`, the filter must be added there too.
- **Background context (podcasts):** `Project.get_context()` / `get_sources()` run in worker jobs with no user context; they currently see all project sources including `personal`-scope ones. Decision taken here: background jobs run with full project scope (the project owner initiated them). Flag if product wants `personal`-scope sources excluded from podcasts by default.
- **Workspace resolution from source:** a source can be referenced by multiple projects (potentially — though in practice one). The predicate resolves workspace/scope across *all* referencing projects (allow if any qualifies). Confirm sources are never referenced across two workspaces' projects; P6's tenant scoping should make cross-workspace references impossible, but P5's `can_view_source` guards against it defensively (404 if no referencing project is in `ctx.workspace_id`).
- **`default_source_scope` conflicts:** if a source is created against multiple `notebooks[]` whose projects have different `default_source_scope` values and the caller omits `scope`, P5 resolves from the *first* listed project only — document this as the rule rather than erroring, since requiring an explicit `scope` whenever `notebooks[]` has length > 1 would be a bigger UX change than this phase should make.
- **Performance:** `visible_source_ids` runs on every list and search. It must be a single parameterized SurrealQL query (not N+1 over projects); the new `idx_source_scope` / `idx_source_owner` indexes back it. Validate query plan on a large dataset.
- **Owner nullability:** legacy sources have `owner = NONE`; they're only mutable by workspace/project admins (no owner match). Acceptable, but means a pre-auth source can't be edited by a plain member even if they "uploaded" it before auth existed.
- **P6 dependency:** the `PermissionContext` dependency shape (`user_id`, `workspace_id`, `workspace_role`, `project_role()`) is defined here but implemented in P6. P6's revised (v2, workspace-model) draft already names its concrete `PermissionContext` with these exact field names (`docs/superpowers/specs/2026-07-11-p6-tenant-scoping-frontend-gating-design.md`, `docs/superpowers/plans/2026-07-11-p6-tenant-scoping.md` Task 2) — the two specs are in sync; no `company_id`/`company_role` remains on either side. P5 ships a JWT-claims-reading stub so it's independently testable in the meantime.
