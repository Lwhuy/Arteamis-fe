# P5 — Source Permissions (owner + scope) Implementation Plan
Version: v2 — 3-level scope (`personal|project|company`), workspace-named context

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `owner` + `scope` (`personal|project|company`) + a `promoted_from` schema hook to the `source` table and enforce a view/mutate permission check on every source-touching endpoint (sources, insights, source-chat, embedding, search/RAG, context) so a `personal`- or `project`-scope source is never listed, read, downloaded, chatted-over, or surfaced in search to a user who may not see it, and a `company`-scope source is visible workspace-wide but mutable only by its owner/admins.

**v2 revision note:** This plan supersedes the earlier 2-level (`private|project`) draft. Every occurrence of `visibility` is renamed `scope`; every occurrence of `company_id`/`company_role` (the request-context fields) is renamed `workspace_id`/`workspace_role`; a third scope value `company` (visible to every member of the active workspace, across all projects) is added; a `promoted_from` schema-only field is added alongside `owner`/`scope`. "Company" now means two different things depending on context — the **product word for a `kind="company"` workspace** (unchanged, per `ARCHITECTURE_BRIEF.md`), and the **new widest source `scope` value** — both are used below; the code never has a literal `company_id` field.

**Architecture:** A new predicate module `api/source_permissions.py` owns all authorization logic (routers stay thin per `api/AGENTS.md`). It consumes a `PermissionContext` (user_id + workspace_id + workspace_role + async `project_role()`), which P5 ships as a concrete, working class and P6 later formalizes/relocates (P6 has been revised to the v2 workspace model and already names its `PermissionContext` fields `workspace_id`/`workspace_role` — matching this plan's shape verbatim; no rename is pending on either side). Search leakage is closed at two layers: migration-23 rewrites `fn::text_search`/`fn::vector_search` to take a `$viewer_source_ids` allow-list, and the app layer computes that list from the caller's context using the 3-scope rule. A `source` carries **no** denormalized `workspace` column — it inherits workspace through the `notebook` (project) it is referenced by via the `reference` edge.

**Tech Stack:** FastAPI, SurrealDB (hand-written SurrealQL migrations), Pydantic, LangGraph (ask RAG graph), Next.js 16 App Router, TanStack Query, react-hook-form + zod, i18next.

**Spec:** docs/superpowers/specs/2026-07-11-p5-source-permissions-design.md
**Depends on:** P1 (auth/users + `api/security.py:AuthContext`), P2 (workspace/membership/roles + `api/deps.py:get_auth_context`), P3 (`notebook`→`project` rename: domain class `Project` in `open_notebook/domain/notebook.py` with `table_name="notebook"`, `notebook.workspace`/`owner`/`default_source_scope`, and the `project_member` table — company-workspace projects only). **Branch:** feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB/AI call is awaited (no sync DB access).
- All frontend HTTP goes through the single axios `apiClient` (frontend/src/lib/api/client.ts) — never a 2nd instance.
- i18n MANDATORY: every UI string via `t('section.key')`; add the key to ALL 14 locales in the `resources` map under frontend/src/lib/locales/ (`en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN, it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR` — confirmed exactly 14 entries in `frontend/src/lib/locales/index.ts`). The parity test (`frontend/src/lib/locales/index.test.ts`) iterates EVERY locale in `resources` and fails on any missing/extra key, and its unused-key test fails on any key not referenced by `t('...')` in source. The 7 enforced locales (en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN) get real translations; the other 7 (it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR) get English fallback values so `npm run test` stays green.
- New SurrealDB schema = new migration pair `open_notebook/database/migrations/23.surrealql` + `23_down.surrealql`, registered in `AsyncMigrationManager` (`open_notebook/database/async_migrate.py`). P5 = migration **23**. Confirmed current state: `up_migrations`/`down_migrations` are hard-coded Python lists, highest registered is **19** (lines ~130-135 up / ~189-194 down); P2/P3/P4 add 20/21/22 before P5 appends 23. **Migration SQL comments must be on their own lines starting with `--`** — `AsyncMigration.from_file()` strips whole `--` lines but joins the rest with spaces, so an inline trailing `-- comment` would comment out the remainder of the joined single-line query.
- Physical SurrealDB table stays `notebook` (exposed as "project"); domain class `Project`; the `reference` edge is `RELATE source->reference->notebook` (`in`=source, `out`=notebook). Unchanged by P5. Confirmed: today's pre-P3 file still names the class `Notebook` (`open_notebook/domain/notebook.py:17`) — see the P3-rename note below.
- Backend tests: `uv run pytest tests/`. Frontend (in `frontend/`): `npm run lint`, `npm run test`, `npm run build`.

> **P3-rename note (read once):** This plan targets the **post-P3** codebase: the domain class is `Project` (file still `open_notebook/domain/notebook.py`, `table_name="notebook"`), and `api/routers/sources.py`/`context.py` import `Project` (not `Notebook`). The `Source`, `SourceInsight`, `SourceEmbedding`, `ChatSession` classes and the `reference`/`refers_to` edges are unchanged by P3. If your P3 kept a `Notebook = Project` alias instead of a clean rename, substitute `Notebook` for `Project` in the import lines below; nothing else changes. As of writing this plan, the actual repo is still pre-P3 (`class Notebook(ObjectModel)` at `open_notebook/domain/notebook.py:17`, no `workspace`/`company` field anywhere) — line numbers cited throughout are taken from that current file and from `api/routers/sources.py`, `insights.py`, `source_chat.py`, `embedding.py`, `search.py`, `context.py`, `api/models.py` as they exist today; P3's own rename may shift a handful of lines, in which case match by function name.

> **PermissionContext ownership (read once):** P5 declares AND ships a concrete `PermissionContext` (Task 3) so P5 is independently runnable and testable **before P6 exists**. P6's spec ("Provides") formalizes/relocates the exact same interface — `user_id`, `workspace_id`, `workspace_role`, `async project_role(project_id) -> "admin"|"member"|None` with workspace-owner/admin→project-admin escalation. The two are already in sync: P6's revised (v2, workspace-model) draft defines `PermissionContext(user_id, workspace_id, workspace_role)` with the identical field names used here — verified against `docs/superpowers/specs/2026-07-11-p6-tenant-scoping-frontend-gating-design.md` and `docs/superpowers/plans/2026-07-11-p6-tenant-scoping.md` Task 2, neither of which redefines the shape with `company_id`/`company_role`. There is no blank here: the working class lives in `api/source_permissions.py` until P6 moves it.

---

## Reference: role × scope × action matrix

Roles (all relative to **the source's** workspace/projects): **Owner** = `source.owner` (uploader). **Workspace owner/admin** = `membership.role ∈ {owner,admin}` on the source's workspace (always `owner`, and the sole member, in a `kind="personal"` workspace). **Project admin** = `project_member.role='admin'` on a project referencing the source (workspace owner/admin escalate to project admin everywhere in their workspace). **Project member** = `project_member.role='member'` on such a project. **Workspace member (other project)** = a member of the source's workspace with no membership in any project referencing the source. **Outsider** = an authenticated user with no membership in the source's workspace at all.

### View / list / read / download / chat / search-surface
| Role \ scope | `personal` | `project` | `company` |
|---|---|---|---|
| Owner | ✅ allow | ✅ allow | ✅ allow |
| Workspace owner/admin | ✅ allow | ✅ allow | ✅ allow |
| Project admin | ✅ allow | ✅ allow | ✅ allow |
| Project member (not owner) | ❌ deny (404) | ✅ allow | ✅ allow |
| Workspace member (not in that project) | ❌ deny (404) | ❌ deny (404) | ✅ allow |
| Outsider (other workspace / no membership) | ❌ deny (404) | ❌ deny (404) | ❌ deny (404) |

**Personal-workspace collapse:** in a `kind="personal"` workspace there is exactly one member (the owner), so the "Project member", "Workspace member", and "Outsider" rows never apply *within that workspace* — all three scope columns collapse to owner-only as a structural consequence, not a special-cased `if kind == "personal"` branch.

### Mutate (edit metadata, edit scope, delete, retry, (re)embed, generate insights)
| Role \ scope | `personal` | `project` | `company` |
|---|---|---|---|
| Owner | ✅ allow | ✅ allow | ✅ allow |
| Workspace owner/admin | ✅ allow | ✅ allow | ✅ allow |
| Project admin | ✅ allow | ✅ allow | ✅ allow |
| Project member (not owner) | ❌ deny (403) | ❌ deny (403) | ❌ deny (403) |
| Workspace member (not in that project) | ❌ deny (404) | ❌ deny (404) | ❌ deny (403 — can view `company`, cannot mutate) |
| Outsider | ❌ deny (404) | ❌ deny (404) | ❌ deny (404) |

### Create
- Any project **member+** (member, project admin, workspace owner/admin) of a project in the active workspace may create a source there, choosing any of the 3 scopes. On create: `owner = ctx.user_id`; `scope =` the request value, or — if omitted — the target project's `default_source_scope` (P3 field), falling back to `"project"`.
- A user with **no** membership in the target project → **403**.
- In a `kind="personal"` workspace the sole owner creates freely; the stored `scope` is inert (collapses to owner-only per the tables above).

### Deny-code rule (avoids existence leaks)
- **View/list/read/download/chat deny → 404** (`{"detail":"Source not found"}`) — a source the caller can't see is indistinguishable from "doesn't exist".
- **Mutate deny where the caller CAN view → 403** (`{"detail":"You do not have permission to modify this source"}`) — this is exactly the `company`-scope / workspace-member row above.
- **Mutate deny where the caller CANNOT even view → 404**.
- Search/list simply omit non-visible rows (no error).
- Insights and embeddings have no independent permission — they inherit their parent source's rules.
- Chat sessions require **view** on the source; a member may create/read/delete their own chat sessions over a `project`- or `company`-scope source without mutate rights.
- `company` scope requires **no extra membership subquery**: holding a `PermissionContext` for `ctx.workspace_id` already proves workspace membership (P6 mints workspace-scoped contexts only for active members), so "same workspace as the source" is sufficient for a `company`-scope view-allow.

---

### Task 1: Migration 23 — `source.owner` + `source.scope` + `source.promoted_from` + indexes + backfill + scope-aware search functions

**Files:**
- Create: `open_notebook/database/migrations/23.surrealql`
- Create: `open_notebook/database/migrations/23_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (register 23 in `up_migrations` + `down_migrations`, appended after 19/20/21/22)
- Test: `tests/test_p5_migration_23.py`

**Interfaces:**
- Produces: `source.owner` (`option<record<user>>`), `source.scope` (`string`, `'personal'|'project'|'company'`, default `'project'`), `source.promoted_from` (`option<record<source>>`, schema hook only); rewritten `fn::text_search($query_text,$match_count,$sources,$show_notes,$viewer_source_ids)` and `fn::vector_search($query,$match_count,$sources,$show_notes,$min_similarity,$viewer_source_ids)`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_migration_23.py`:
```python
"""Migration 23 registration + content guards (P5 source permissions, v2 3-scope)."""
from pathlib import Path

from open_notebook.database.async_migrate import AsyncMigrationManager

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_23_registered():
    mgr = AsyncMigrationManager()
    # P5 is migration 23 -> 23 up + 23 down migrations registered.
    assert len(mgr.up_migrations) == 23
    assert len(mgr.down_migrations) == 23


def test_migration_23_up_defines_owner_scope_promoted_from_and_search_fns():
    sql = (MIGRATIONS / "23.surrealql").read_text()
    assert "DEFINE FIELD IF NOT EXISTS owner ON TABLE source" in sql
    assert "DEFINE FIELD IF NOT EXISTS scope ON TABLE source" in sql
    assert "DEFINE FIELD IF NOT EXISTS promoted_from ON TABLE source" in sql
    assert "'personal', 'project', 'company'" in sql
    assert "idx_source_scope" in sql
    assert "idx_source_owner" in sql
    # search functions gain the $viewer_source_ids allow-list param
    assert "$viewer_source_ids: array<record<source>>" in sql
    assert sql.count("DEFINE FUNCTION IF NOT EXISTS fn::text_search") == 1
    assert sql.count("DEFINE FUNCTION IF NOT EXISTS fn::vector_search") == 1


def test_migration_23_down_removes_fields_and_restores_legacy_fns():
    sql = (MIGRATIONS / "23_down.surrealql").read_text()
    assert "REMOVE FIELD IF EXISTS scope ON TABLE source" in sql
    assert "REMOVE FIELD IF EXISTS owner ON TABLE source" in sql
    assert "REMOVE FIELD IF EXISTS promoted_from ON TABLE source" in sql
    # down restores the pre-P5 4-arg / 5-arg signatures (no $viewer_source_ids)
    assert "$viewer_source_ids" not in sql
    assert "DEFINE FUNCTION IF NOT EXISTS fn::text_search" in sql
    assert "DEFINE FUNCTION IF NOT EXISTS fn::vector_search" in sql


def test_no_inline_comments_in_migration_23():
    # AsyncMigration.from_file() joins non-comment lines with spaces; an inline
    # trailing `-- comment` would comment out the rest of the single-line query.
    for name in ("23.surrealql", "23_down.surrealql"):
        for line in (MIGRATIONS / name).read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                assert "--" not in stripped, f"inline comment in {name}: {line!r}"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_migration_23.py -q` — Expected: FAIL (`23.surrealql` missing → `FileNotFoundError`; `len(up_migrations) == 19` pre-P2/P3/P4, or `22` once those land).

- [ ] **Step 3: Write minimal implementation** — Create `open_notebook/database/migrations/23.surrealql` (all comments on their own `--` lines; the `fn::` bodies are migration 4's `fn::text_search` and migration 9's `fn::vector_search` verbatim — those bodies are agnostic to the `owner`/`scope` rename, they only gain the `$viewer_source_ids` allow-list filter, which is computed in Python by `visible_source_ids()` using the 3-scope rule BEFORE this function ever runs):
```surql
-- Migration 23: Source ownership + scope (P5 source permissions, v2 3-level scope)
-- owner = uploader; NONE for legacy/backfilled sources (no user existed pre-auth).
DEFINE FIELD IF NOT EXISTS owner ON TABLE source TYPE option<record<user>>;
-- scope gate (v2: THREE levels, not two).
-- 'personal' = owner + workspace owner/admin + the project's admins only.
-- 'project'  = all members of any project the source is referenced by.
-- 'company'  = every member of the active workspace, across every project.
DEFINE FIELD IF NOT EXISTS scope ON TABLE source TYPE string ASSERT $value IN ['personal', 'project', 'company'] DEFAULT 'project';
-- Schema hook only (P5 does NOT build the promotion flow): the source this row
-- was promoted from. Mirrors project.promoted_from (P3, migration 21).
DEFINE FIELD IF NOT EXISTS promoted_from ON TABLE source TYPE option<record<source>>;
-- Backfill existing rows: pre-auth sources default to 'project', owner stays NONE.
-- A source inherits its workspace from its notebook (project) via the reference
-- edge; P3's migration 21 already backfilled every notebook/project to a
-- workspace, so every legacy source resolves to a workspace through its notebook.
UPDATE source SET scope = 'project' WHERE scope = NONE;
-- Indexes backing the scope/owner filter used by list + search.
DEFINE INDEX IF NOT EXISTS idx_source_scope ON TABLE source FIELDS scope CONCURRENTLY;
DEFINE INDEX IF NOT EXISTS idx_source_owner ON TABLE source FIELDS owner CONCURRENTLY;
-- Scope-aware search functions. $viewer_source_ids is the pre-computed set of
-- source ids the caller may see (owner/admin escalation AND the 3-scope rule
-- both resolved in Python by visible_source_ids()). Every source-derived branch
-- is filtered by it; note branches are untouched (notes have no per-source
-- scope in P5).
REMOVE FUNCTION IF EXISTS fn::text_search;
DEFINE FUNCTION IF NOT EXISTS fn::text_search($query_text: string, $match_count: int, $sources: bool, $show_notes: bool, $viewer_source_ids: array<record<source>>) {
    let $source_title_search =
        IF $sources {(
            SELECT id, title,
            search::highlight('`', '`', 1) as content,
            id as parent_id,
            math::max(search::score(1)) AS relevance
            FROM source
            WHERE title @1@ $query_text AND id IN $viewer_source_ids
            GROUP BY id)}
        ELSE { [] };
    let $source_embedding_search =
         IF $sources {(
            SELECT source.id as id, source.title as title, search::highlight('`', '`', 1) as content, source.id as parent_id, math::max(search::score(1)) AS relevance
            FROM source_embedding
            WHERE content @1@ $query_text AND source.id IN $viewer_source_ids
            GROUP BY id)}
        ELSE { [] };
    let $source_full_search =
         IF $sources {(
            SELECT id, title, search::highlight('`', '`', 1) as content, id as parent_id, math::max(search::score(1)) AS relevance
            FROM source
            WHERE full_text @1@ $query_text AND id IN $viewer_source_ids
            GROUP BY id)}
        ELSE { [] };
    let $source_insight_search =
         IF $sources {(
             SELECT id, insight_type + " - " + (source.title OR '') as title, search::highlight('`', '`', 1) as content, id as parent_id,  math::max(search::score(1)) AS relevance
            FROM source_insight
            WHERE content @1@ $query_text AND source.id IN $viewer_source_ids
            GROUP BY id)}
        ELSE { [] };
    let $note_title_search =
         IF $show_notes {(
             SELECT id, title, search::highlight('`', '`', 1) as content,  id as parent_id, math::max(search::score(1)) AS relevance
            FROM note
            WHERE title @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
     let $note_content_search =
         IF $show_notes {(
             SELECT id, title, search::highlight('`', '`', 1) as content,  id as parent_id, math::max(search::score(1)) AS relevance
            FROM note
            WHERE content @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
    let $source_chunk_results = array::union($source_embedding_search, $source_full_search);
    let $source_asset_results = array::union($source_title_search, $source_insight_search);
    let $source_results = array::union($source_chunk_results, $source_asset_results );
    let $note_results = array::union($note_title_search, $note_content_search );
    let $final_results = array::union($source_results, $note_results );
        RETURN (select id, parent_id, title, math::max(relevance) as relevance
        from $final_results where id is not None
        group by id, parent_id, title ORDER BY relevance DESC LIMIT $match_count);
};
REMOVE FUNCTION IF EXISTS fn::vector_search;
DEFINE FUNCTION IF NOT EXISTS fn::vector_search($query: array<float>, $match_count: int, $sources: bool, $show_notes: bool, $min_similarity: float, $viewer_source_ids: array<record<source>>) {
    let $source_embedding_search =
        IF $sources {(
            SELECT
                source.id as id,
                source.title as title,
                content,
                source.id as parent_id,
                vector::similarity::cosine(embedding, $query) as similarity
            FROM source_embedding
            WHERE embedding != none and array::len(embedding)=array::len($query) AND source.id IN $viewer_source_ids AND
                 vector::similarity::cosine(embedding, $query) >= $min_similarity
            ORDER BY similarity DESC
            LIMIT $match_count
        )}
        ELSE { [] };
    let $source_insight_search =
        IF $sources {(
            SELECT
                id,
                insight_type + ' - ' + (source.title OR '') as title,
                content,
                source.id as parent_id,
                vector::similarity::cosine(embedding, $query) as similarity
            FROM source_insight
             WHERE embedding != none and array::len(embedding)=array::len($query) AND source.id IN $viewer_source_ids AND
            vector::similarity::cosine(embedding, $query) >= $min_similarity
            ORDER BY similarity DESC
            LIMIT $match_count
        )}
        ELSE { [] };
    let $note_content_search =
        IF $show_notes {(
            SELECT
                id,
                title,
                content,
                id as parent_id,
                vector::similarity::cosine(embedding, $query) as similarity
            FROM note
            WHERE embedding != none and array::len(embedding)=array::len($query) AND
            vector::similarity::cosine(embedding, $query) >= $min_similarity
            ORDER BY similarity DESC
            LIMIT $match_count
        )}
        ELSE { [] };
    let $all_results = array::union(
        array::union($source_embedding_search, $source_insight_search),
        $note_content_search
    );
    RETURN (select id, parent_id, title, math::max(similarity) as similarity,
    array::flatten(content) as matches
    from $all_results where id is not None
    group by id, parent_id, title ORDER BY similarity DESC LIMIT $match_count);
};
```
Create `open_notebook/database/migrations/23_down.surrealql` (restores the exact pre-P5 signatures — migration 4's `fn::text_search` and migration 9's `fn::vector_search`, no `$viewer_source_ids`):
```surql
-- Migration 23 rollback
REMOVE INDEX IF EXISTS idx_source_scope ON TABLE source;
REMOVE INDEX IF EXISTS idx_source_owner ON TABLE source;
REMOVE FIELD IF EXISTS scope ON TABLE source;
REMOVE FIELD IF EXISTS owner ON TABLE source;
REMOVE FIELD IF EXISTS promoted_from ON TABLE source;
REMOVE FUNCTION IF EXISTS fn::text_search;
DEFINE FUNCTION IF NOT EXISTS fn::text_search($query_text: string, $match_count: int, $sources:bool, $show_notes:bool) {
    let $source_title_search =
        IF $sources {(
            SELECT id, title,
            search::highlight('`', '`', 1) as content,
            id as parent_id,
            math::max(search::score(1)) AS relevance
            FROM source
            WHERE title @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
    let $source_embedding_search =
         IF $sources {(
            SELECT source.id as id, source.title as title, search::highlight('`', '`', 1) as content, source.id as parent_id, math::max(search::score(1)) AS relevance
            FROM source_embedding
            WHERE content @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
    let $source_full_search =
         IF $sources {(
            SELECT id, title, search::highlight('`', '`', 1) as content, id as parent_id, math::max(search::score(1)) AS relevance
            FROM source
            WHERE full_text @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
    let $source_insight_search =
         IF $sources {(
             SELECT id, insight_type + " - " + (source.title OR '') as title, search::highlight('`', '`', 1) as content, id as parent_id,  math::max(search::score(1)) AS relevance
            FROM source_insight
            WHERE content @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
    let $note_title_search =
         IF $show_notes {(
             SELECT id, title, search::highlight('`', '`', 1) as content,  id as parent_id, math::max(search::score(1)) AS relevance
            FROM note
            WHERE title @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
     let $note_content_search =
         IF $show_notes {(
             SELECT id, title, search::highlight('`', '`', 1) as content,  id as parent_id, math::max(search::score(1)) AS relevance
            FROM note
            WHERE content @1@ $query_text
            GROUP BY id)}
        ELSE { [] };
    let $source_chunk_results = array::union($source_embedding_search, $source_full_search);
    let $source_asset_results = array::union($source_title_search, $source_insight_search);
    let $source_results = array::union($source_chunk_results, $source_asset_results );
    let $note_results = array::union($note_title_search, $note_content_search );
    let $final_results = array::union($source_results, $note_results );
        RETURN (select id, parent_id, title, math::max(relevance) as relevance
        from $final_results where id is not None
        group by id, parent_id, title ORDER BY relevance DESC LIMIT $match_count);
};
REMOVE FUNCTION IF EXISTS fn::vector_search;
DEFINE FUNCTION IF NOT EXISTS fn::vector_search($query: array<float>, $match_count: int, $sources: bool, $show_notes: bool, $min_similarity: float) {
    let $source_embedding_search =
        IF $sources {(
            SELECT
                source.id as id,
                source.title as title,
                content,
                source.id as parent_id,
                vector::similarity::cosine(embedding, $query) as similarity
            FROM source_embedding
            WHERE embedding != none and array::len(embedding)=array::len($query) AND
                 vector::similarity::cosine(embedding, $query) >= $min_similarity
            ORDER BY similarity DESC
            LIMIT $match_count
        )}
        ELSE { [] };
    let $source_insight_search =
        IF $sources {(
            SELECT
                id,
                insight_type + ' - ' + (source.title OR '') as title,
                content,
                source.id as parent_id,
                vector::similarity::cosine(embedding, $query) as similarity
            FROM source_insight
             WHERE embedding != none and array::len(embedding)=array::len($query) AND
            vector::similarity::cosine(embedding, $query) >= $min_similarity
            ORDER BY similarity DESC
            LIMIT $match_count
        )}
        ELSE { [] };
    let $note_content_search =
        IF $show_notes {(
            SELECT
                id,
                title,
                content,
                id as parent_id,
                vector::similarity::cosine(embedding, $query) as similarity
            FROM note
            WHERE embedding != none and array::len(embedding)=array::len($query) AND
            vector::similarity::cosine(embedding, $query) >= $min_similarity
            ORDER BY similarity DESC
            LIMIT $match_count
        )}
        ELSE { [] };
    let $all_results = array::union(
        array::union($source_embedding_search, $source_insight_search),
        $note_content_search
    );
    RETURN (select id, parent_id, title, math::max(similarity) as similarity,
    array::flatten(content) as matches
    from $all_results where id is not None
    group by id, parent_id, title ORDER BY similarity DESC LIMIT $match_count);
};
```
Then register both in `open_notebook/database/async_migrate.py`. Append to `self.up_migrations` (after P2/P3/P4's 20/21/22 entries, before the closing `]`):
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/23.surrealql"
            ),
```
and the matching `_down` entry appended to `self.down_migrations`:
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/23_down.surrealql"
            ),
```
> **Ordering note:** as of this plan the repo only has migrations through **19** (P1). 20/21/22 are P2/P3/P4's job; only append the two `23` lines here, after whatever P2-P4 already registered. The registration test asserts exactly 23 entries — reconcile with what P1-P4 have actually registered by the time this task runs.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_migration_23.py -q` — Expected: PASS (4 passed). Then boot once against a dev DB to confirm the SQL applies cleanly: `make database && make api` and check logs for `Migration successful. New version: 23` with no SurrealDB error.

- [ ] **Step 5: Commit** — `git add open_notebook/database/migrations/23.surrealql open_notebook/database/migrations/23_down.surrealql open_notebook/database/async_migrate.py tests/test_p5_migration_23.py && git commit -m "P5: migration 23 — source owner/scope/promoted_from + scope-aware search fns"`

---

### Task 2: `Source` domain model — `owner` + `scope` + `promoted_from` fields + `get_project_ids()`

**Files:**
- Modify: `open_notebook/domain/notebook.py` (class `Source`, fields at lines 391-402, `command` validator at 404-410, `_prepare_save_data` at 621-629 — confirmed current locations; add `get_project_ids` method)
- Test: `tests/test_p5_source_model.py`

**Interfaces:**
- Produces: `Source.owner: Optional[Union[str, RecordID]]`, `Source.scope: Literal["personal","project","company"]`, `Source.promoted_from: Optional[Union[str, RecordID]]`, `async Source.get_project_ids() -> List[str]`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_source_model.py`:
```python
"""Source owner/scope/promoted_from fields + get_project_ids (P5, v2 3-scope)."""
from unittest.mock import AsyncMock, patch

import pytest
from surrealdb import RecordID

from open_notebook.domain.notebook import Source


def test_scope_defaults_to_project():
    s = Source(title="t")
    assert s.scope == "project"
    assert s.owner is None
    assert s.promoted_from is None


def test_scope_accepts_personal_and_company():
    assert Source(title="t", scope="personal").scope == "personal"
    assert Source(title="t", scope="company").scope == "company"


def test_owner_string_coerced_to_record_id():
    s = Source(title="t", owner="user:abc")
    assert isinstance(s.owner, RecordID)
    assert str(s.owner) == "user:abc"


def test_owner_none_passthrough():
    s = Source(title="t", owner=None)
    assert s.owner is None


def test_promoted_from_string_coerced_to_record_id():
    s = Source(title="t", promoted_from="source:old")
    assert isinstance(s.promoted_from, RecordID)
    assert str(s.promoted_from) == "source:old"


def test_prepare_save_data_coerces_owner_promoted_from_and_keeps_scope():
    s = Source(title="t", owner="user:abc", scope="company", promoted_from="source:old")
    data = s._prepare_save_data()
    assert isinstance(data["owner"], RecordID)
    assert isinstance(data["promoted_from"], RecordID)
    assert data["scope"] == "company"


@pytest.mark.asyncio
async def test_get_project_ids_queries_reference_edge():
    s = Source(title="t", id="source:1")
    with patch(
        "open_notebook.domain.notebook.repo_query",
        new=AsyncMock(return_value=[RecordID.parse("notebook:p1"), RecordID.parse("notebook:p2")]),
    ) as mock_q:
        ids = await s.get_project_ids()
    assert ids == ["notebook:p1", "notebook:p2"]
    query = mock_q.call_args.args[0]
    assert "reference" in query and "in = $id" in query
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_source_model.py -q` — Expected: FAIL (`Source` has no `scope`/`owner`/`promoted_from` field; `get_project_ids` missing).

- [ ] **Step 3: Write minimal implementation** — In `open_notebook/domain/notebook.py`, class `Source`, add the three fields after the existing `command` field (after line 402) and a combined `owner`/`promoted_from` validator after `parse_command` (after line 410). `Literal`, `RecordID`, `ensure_record_id` are already imported at module top (lines 5, 10, 12). Add fields:
```python
    command: Optional[Union[str, RecordID]] = Field(
        default=None, description="Link to surreal-commands processing job"
    )
    owner: Optional[Union[str, RecordID]] = Field(
        default=None, description="Uploader user; NONE for legacy pre-auth sources"
    )
    scope: Literal["personal", "project", "company"] = "project"
    promoted_from: Optional[Union[str, RecordID]] = Field(
        default=None,
        description="Schema hook only (P5 does not implement promotion): the "
        "source this row was promoted from",
    )
```
Add the combined `owner`/`promoted_from` validator (mirrors `parse_command`) right after the `parse_command` method:
```python
    @field_validator("owner", "promoted_from", mode="before")
    @classmethod
    def parse_record_link(cls, value):
        """Coerce a str record id (owner or promoted_from) to RecordID; pass
        through None."""
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value
```
Extend `_prepare_save_data` (currently lines 621-629) to coerce `owner` and `promoted_from`:
```python
    def _prepare_save_data(self) -> dict:
        """Override to ensure command/owner/promoted_from fields are RecordID
        format for the DB."""
        data = super()._prepare_save_data()
        if data.get("command") is not None:
            data["command"] = ensure_record_id(data["command"])
        if data.get("owner") is not None:
            data["owner"] = ensure_record_id(data["owner"])
        if data.get("promoted_from") is not None:
            data["promoted_from"] = ensure_record_id(data["promoted_from"])
        return data
```
Add `get_project_ids` as a method on `Source` (e.g. after `get_insights`), reusing the same `reference`-edge query pattern already inlined in `api/routers/sources.py`'s `get_source` (~717-720) and `retry_source_processing` (~913-921):
```python
    async def get_project_ids(self) -> List[str]:
        """Project (notebook) ids this source is referenced by, via the reference edge.
        `reference` is RELATE source->reference->notebook (in=source, out=notebook)."""
        result = await repo_query(
            "SELECT VALUE out FROM reference WHERE in = $id",
            {"id": ensure_record_id(self.id)},
        )
        return [str(pid) for pid in result] if result else []
```
> `owner`/`promoted_from` are not-None-only-saved: `ObjectModel._prepare_save_data` drops keys whose value is `None` unless listed in `nullable_fields`. `owner=None` (legacy) / `promoted_from=None` (always, this phase) are therefore simply omitted on save, which is correct — both DB fields are `option<record<...>>`.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_source_model.py -q` — Expected: PASS (7 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/domain/notebook.py tests/test_p5_source_model.py && git commit -m "P5: Source model owner/scope/promoted_from fields + get_project_ids"`

---

### Task 3: `PermissionContext` + `get_permission_context` + `can_view_source` / `can_mutate_source`

**Files:**
- Create: `api/source_permissions.py`
- Test: `tests/test_p5_predicate.py`

**Interfaces:**
- Consumes: `Source.get_project_ids()` (Task 2); `api.deps.get_auth_context -> AuthContext(user_id, workspace_id, role)` (P2); `api.security.AuthContext` (P1).
- Produces: `class PermissionContext(user_id, workspace_id, workspace_role)` with `async project_role(project_id) -> Optional[str]`; `async get_permission_context(auth) -> PermissionContext`; `async can_view_source(source, ctx) -> bool`; `async can_mutate_source(source, ctx) -> bool`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_predicate.py`:
```python
"""Permission predicate logic (P5, v2 3-scope). Uses a hand-built
PermissionContext; the source's project ids, workspace resolution, and
project_role are mocked."""
from unittest.mock import AsyncMock, patch

import pytest

from api.source_permissions import (
    PermissionContext,
    can_mutate_source,
    can_view_source,
)
from open_notebook.domain.notebook import Source


def _ctx(user="user:u1", workspace="workspace:w1", role="member"):
    return PermissionContext(user_id=user, workspace_id=workspace, workspace_role=role)


def _source(owner=None, scope="project", sid="source:s1"):
    return Source(id=sid, title="t", owner=owner, scope=scope)


@pytest.fixture
def in_workspace():
    # every predicate first resolves the source's workspace via the reference edge
    with patch(
        "api.source_permissions.repo_query",
        new=AsyncMock(return_value=["workspace:w1"]),
    ) as m:
        yield m


@pytest.mark.asyncio
async def test_owner_can_view_and_mutate_personal(in_workspace):
    ctx = _ctx()
    src = _source(owner="user:u1", scope="personal")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value=None)
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_workspace_admin_can_view_and_mutate_others_personal(in_workspace):
    ctx = _ctx(user="user:u2", role="admin")
    src = _source(owner="user:u1", scope="personal")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="admin")
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_project_admin_can_view_and_mutate_personal(in_workspace):
    ctx = _ctx(user="user:u2", role="member")
    src = _source(owner="user:u1", scope="personal")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="admin")
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_member_view_project_but_not_personal_and_never_mutate(in_workspace):
    ctx = _ctx(user="user:u2", role="member")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="member")
        assert await can_view_source(_source(owner="user:u1", scope="project"), ctx) is True
        assert await can_view_source(_source(owner="user:u1", scope="personal"), ctx) is False
        assert await can_mutate_source(_source(owner="user:u1", scope="project"), ctx) is False


@pytest.mark.asyncio
async def test_workspace_member_outside_project_sees_only_company_scope(in_workspace):
    # Same workspace, but NOT a member of the project the source is referenced by.
    ctx = _ctx(user="user:u3", role="member")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value=None)
        assert await can_view_source(_source(owner="user:u1", scope="company"), ctx) is True
        assert await can_view_source(_source(owner="user:u1", scope="project"), ctx) is False
        assert await can_view_source(_source(owner="user:u1", scope="personal"), ctx) is False
        # Can view company scope, but cannot mutate it (not owner/admin).
        assert await can_mutate_source(_source(owner="user:u1", scope="company"), ctx) is False


@pytest.mark.asyncio
async def test_outsider_other_workspace_denied():
    ctx = _ctx(user="user:x", workspace="workspace:OTHER", role="member")
    src = _source(owner="user:u1", scope="company")
    with patch("api.source_permissions.repo_query", new=AsyncMock(return_value=["workspace:w1"])):
        with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
            ctx.project_role = AsyncMock(return_value=None)
            assert await can_view_source(src, ctx) is False
            assert await can_mutate_source(src, ctx) is False


@pytest.mark.asyncio
async def test_personal_workspace_solo_owner_sees_all_scopes(in_workspace):
    # A kind="personal" workspace's sole member is always "owner" -> the
    # workspace_role escalation branch (step 3) allows every scope for the
    # solo owner, with no kind-conditional code needed.
    ctx = _ctx(user="user:solo", role="owner")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value=None)
        for scope in ("personal", "project", "company"):
            src = _source(owner="user:solo", scope=scope)
            assert await can_view_source(src, ctx) is True
            assert await can_mutate_source(src, ctx) is True
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_predicate.py -q` — Expected: FAIL (`ModuleNotFoundError: api.source_permissions`).

- [ ] **Step 3: Write minimal implementation** — Create `api/source_permissions.py`:
```python
"""Source scope/permission predicate (P5, v2 3-level scope).

All source authorization lives here so routers stay thin (api/AGENTS.md).

PermissionContext is shipped concrete by P5 so this module is runnable/testable
before P6 exists. P6 formalizes/relocates the SAME interface (user_id,
workspace_id, workspace_role, async project_role) — keep them in sync.
"""
from typing import List, Optional

from fastapi import Depends, HTTPException

from api.deps import get_auth_context  # P2
from api.security import AuthContext  # P1
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import NotFoundError


class PermissionContext:
    """Request-scoped auth context P5 needs. P6 replaces the class body's origin
    but not its shape. `workspace_role` is always "owner" in a kind="personal"
    workspace (the sole member)."""

    def __init__(self, user_id: str, workspace_id: str, workspace_role: str):
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.workspace_role = workspace_role

    async def project_role(self, project_id: str) -> Optional[str]:
        """Caller's role on a project: 'admin'|'member'|None. Workspace
        owner/admin escalate to project admin everywhere in their workspace
        (this also covers personal-workspace projects, which have no
        project_member rows at all — the escalation short-circuits before the
        query below ever runs)."""
        if self.workspace_role in ("owner", "admin"):
            return "admin"
        rows = await repo_query(
            "SELECT VALUE role FROM project_member "
            "WHERE user = $user AND project = $project AND status = 'active'",
            {
                "user": ensure_record_id(self.user_id),
                "project": ensure_record_id(project_id),
            },
        )
        return rows[0] if rows else None


async def get_permission_context(
    auth: AuthContext = Depends(get_auth_context),
) -> PermissionContext:
    """FastAPI dependency injected into every source-touching route."""
    return PermissionContext(
        user_id=str(auth.user_id),
        workspace_id=str(auth.workspace_id),
        workspace_role=str(auth.role),
    )


async def _source_workspaces(source: Source) -> List[str]:
    """Workspace ids owning this source, resolved via its referencing projects."""
    rows = await repo_query(
        "SELECT VALUE out.workspace FROM reference WHERE in = $source",
        {"source": ensure_record_id(source.id)},
    )
    return [str(w) for w in rows if w is not None]


async def _in_active_workspace(source: Source, ctx: PermissionContext) -> bool:
    return ctx.workspace_id in await _source_workspaces(source)


async def can_view_source(source: Source, ctx: PermissionContext) -> bool:
    # Workspace isolation (belt-and-braces with P6): must be referenced by a
    # project in the caller's active workspace, else treat as not-found.
    if not await _in_active_workspace(source, ctx):
        return False
    # Owner always sees their own source.
    if source.owner is not None and str(source.owner) == ctx.user_id:
        return True
    # Workspace owner/admin sees everything in the workspace, including
    # 'personal'-scope sources. In a kind="personal" workspace the sole member
    # is always "owner", so this branch alone makes the collapse-to-owner-only
    # behavior fall out naturally, with no kind-conditional code.
    if ctx.workspace_role in ("owner", "admin"):
        return True
    project_ids = await source.get_project_ids()
    # Project admin of any referencing project sees everything in it.
    for pid in project_ids:
        if await ctx.project_role(pid) == "admin":
            return True
    # 'company' scope: visible to every member of the active workspace, across
    # every project. No extra membership lookup needed — _in_active_workspace
    # already proved same-workspace, and holding a PermissionContext for this
    # workspace_id already proves active membership in it.
    if source.scope == "company":
        return True
    # 'project' scope: any member (admin/member) of a referencing project.
    if source.scope == "project":
        for pid in project_ids:
            if await ctx.project_role(pid) in ("admin", "member"):
                return True
    return False


async def can_mutate_source(source: Source, ctx: PermissionContext) -> bool:
    if not await _in_active_workspace(source, ctx):
        return False
    if source.owner is not None and str(source.owner) == ctx.user_id:
        return True
    if ctx.workspace_role in ("owner", "admin"):
        return True
    for pid in await source.get_project_ids():
        if await ctx.project_role(pid) == "admin":
            return True
    return False
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_predicate.py -q` — Expected: PASS (7 passed).

- [ ] **Step 5: Commit** — `git add api/source_permissions.py tests/test_p5_predicate.py && git commit -m "P5: PermissionContext + can_view_source/can_mutate_source predicate (3-scope)"`

---

### Task 4: `require_view_source` / `require_mutate_source` + `visible_source_ids`

**Files:**
- Modify: `api/source_permissions.py` (append the three functions)
- Test: `tests/test_p5_require_and_visible.py`

**Interfaces:**
- Produces: `async require_view_source(source_id, ctx) -> Source` (404 on view-deny/missing); `async require_mutate_source(source_id, ctx) -> Source` (404 if not viewable, 403 if viewable-but-not-mutable); `async visible_source_ids(ctx, project_id=None) -> List[str]` (deduped source ids, single parameterized query, backs list + search filtering across all 3 scopes).

- [ ] **Step 1: Write the failing test** — `tests/test_p5_require_and_visible.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api import source_permissions as sp
from api.source_permissions import (
    PermissionContext,
    require_mutate_source,
    require_view_source,
    visible_source_ids,
)
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import NotFoundError


def _ctx(role="member"):
    return PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role=role)


@pytest.mark.asyncio
async def test_require_view_missing_is_404():
    with patch.object(Source, "get", new=AsyncMock(side_effect=NotFoundError("x"))):
        with pytest.raises(HTTPException) as e:
            await require_view_source("source:missing", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_require_view_deny_is_404():
    src = Source(id="source:1", title="t", owner="user:z", scope="personal")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as e:
                await require_view_source("source:1", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_require_mutate_viewable_but_not_mutable_is_403():
    src = Source(id="source:1", title="t", owner="user:z", scope="company")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=True)):
            with patch.object(sp, "can_mutate_source", new=AsyncMock(return_value=False)):
                with pytest.raises(HTTPException) as e:
                    await require_mutate_source("source:1", _ctx())
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_require_mutate_not_viewable_is_404():
    src = Source(id="source:1", title="t", owner="user:z", scope="personal")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as e:
                await require_mutate_source("source:1", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_visible_source_ids_admin_branch_is_workspace_wide_and_deduped():
    ctx = _ctx(role="admin")
    with patch(
        "api.source_permissions.repo_query",
        new=AsyncMock(return_value=["source:a", "source:a", "source:b"]),
    ) as m:
        ids = await visible_source_ids(ctx)
    assert ids == ["source:a", "source:b"]
    assert "in.owner" not in m.call_args.args[0]  # admin branch = no per-user predicate


@pytest.mark.asyncio
async def test_visible_source_ids_member_branch_has_all_three_scope_predicates():
    ctx = _ctx(role="member")
    with patch(
        "api.source_permissions.repo_query", new=AsyncMock(return_value=[])
    ) as m:
        await visible_source_ids(ctx, project_id="notebook:p1")
    q = m.call_args.args[0]
    assert "in.owner = $user" in q
    assert "in.scope = 'company'" in q
    assert "in.scope = 'project'" in q
    assert "out = $project" in q
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_require_and_visible.py -q` — Expected: FAIL (`ImportError: cannot import name 'require_view_source'`).

- [ ] **Step 3: Write minimal implementation** — Append to `api/source_permissions.py`:
```python
async def require_view_source(source_id: str, ctx: PermissionContext) -> Source:
    """Load + view-check. 404 if missing OR view-denied (no existence oracle)."""
    try:
        source = await Source.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    if not await can_view_source(source, ctx):
        raise HTTPException(status_code=404, detail="Source not found")
    return source


async def require_mutate_source(source_id: str, ctx: PermissionContext) -> Source:
    """Load + mutate-check. 404 if not even viewable; 403 if viewable but not mutable."""
    try:
        source = await Source.get(source_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Source not found")
    if not await can_view_source(source, ctx):
        raise HTTPException(status_code=404, detail="Source not found")
    if not await can_mutate_source(source, ctx):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to modify this source",
        )
    return source


async def visible_source_ids(
    ctx: PermissionContext, project_id: Optional[str] = None
) -> List[str]:
    """Source ids in the caller's workspace (optionally one project) the caller
    may VIEW, across all three scopes. Single parameterized query (no N+1);
    backs GET /sources + search filters.

    Workspace owner/admin: every source in the workspace (any scope).
    Otherwise: owner's own sources, plus every 'company'-scope source in the
    workspace (no membership predicate needed — same-workspace is sufficient),
    plus every source of any project they admin, plus 'project'-scope sources
    of any project they are a plain member of.
    """
    params = {
        "workspace": ensure_record_id(ctx.workspace_id),
        "user": ensure_record_id(ctx.user_id),
    }
    project_filter = ""
    if project_id is not None:
        params["project"] = ensure_record_id(project_id)
        project_filter = " AND out = $project"

    if ctx.workspace_role in ("owner", "admin"):
        query = (
            "SELECT VALUE in FROM reference "
            "WHERE out.workspace = $workspace" + project_filter
        )
    else:
        query = (
            "SELECT VALUE in FROM reference "
            "WHERE out.workspace = $workspace" + project_filter + " AND ("
            "in.owner = $user "
            "OR in.scope = 'company' "
            "OR out IN (SELECT VALUE project FROM project_member "
            "WHERE user = $user AND role = 'admin' AND status = 'active') "
            "OR (in.scope = 'project' AND out IN (SELECT VALUE project "
            "FROM project_member WHERE user = $user AND status = 'active'))"
            ")"
        )
    rows = await repo_query(query, params)
    seen: List[str] = []
    for r in rows:
        s = str(r)
        if s not in seen:
            seen.append(s)
    return seen
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_require_and_visible.py -q` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add api/source_permissions.py tests/test_p5_require_and_visible.py && git commit -m "P5: require_view/mutate_source + visible_source_ids (3-scope)"`

---

### Task 5: Pydantic schemas — scope on create/update/response + form parsing

**Files:**
- Modify: `api/models.py` (`SourceCreate` 297-345, `SourceUpdate` 348-350, `SourceResponse` 353-369, `SourceListResponse` 372-386)
- Modify: `api/routers/sources.py` (`parse_source_form_data` 141-209)
- Test: `tests/test_p5_models.py`

**Interfaces:**
- Produces: `SourceCreate.scope: Optional[Literal["personal","project","company"]]=None` (resolved server-side, Task 6); `SourceUpdate.scope: Optional[Literal["personal","project","company"]]=None`; `SourceResponse`/`SourceListResponse` gain `scope: str = "project"` and `owner: Optional[str] = None`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_models.py`:
```python
import pytest
from pydantic import ValidationError

from api.models import SourceCreate, SourceListResponse, SourceResponse, SourceUpdate


def test_source_create_scope_optional_and_unset_by_default():
    assert SourceCreate(type="text", content="x").scope is None


def test_source_create_accepts_all_three_scopes():
    for scope in ("personal", "project", "company"):
        assert SourceCreate(type="text", content="x", scope=scope).scope == scope


def test_source_create_rejects_bad_scope():
    with pytest.raises(ValidationError):
        SourceCreate(type="text", content="x", scope="secret")


def test_source_update_scope_optional():
    assert SourceUpdate().scope is None
    assert SourceUpdate(scope="company").scope == "company"


def test_responses_carry_scope_and_owner():
    r = SourceResponse(
        id="source:1", title="t", topics=[], asset=None, full_text=None,
        embedded=False, embedded_chunks=0, created="c", updated="u",
        scope="personal", owner="user:u1",
    )
    assert r.scope == "personal" and r.owner == "user:u1"
    lr = SourceListResponse(
        id="source:1", title="t", topics=[], asset=None, embedded=False,
        embedded_chunks=0, insights_count=0, created="c", updated="u",
    )
    assert lr.scope == "project" and lr.owner is None
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_models.py -q` — Expected: FAIL (`SourceCreate` has no `scope`).

- [ ] **Step 3: Write minimal implementation** — In `api/models.py`:
  - `SourceCreate`: add after the `async_processing` field (line 326):
```python
    scope: Optional[Literal["personal", "project", "company"]] = Field(
        None,
        description="Source scope: personal, project, or company. Omitted -> "
        "resolved server-side from the target project's default_source_scope, "
        "falling back to 'project'.",
    )
```
  - `SourceUpdate`: add after `topics` (line 350):
```python
    scope: Optional[Literal["personal", "project", "company"]] = Field(
        None, description="Source scope: personal, project, or company"
    )
```
  - `SourceResponse`: add after `notebooks` (line 369):
```python
    scope: str = "project"
    owner: Optional[str] = None
```
  - `SourceListResponse`: add after `processing_info` (line 386):
```python
    scope: str = "project"
    owner: Optional[str] = None
```
  (`Literal` and `Optional` are already imported in `api/models.py`, line 1.)
  - In `api/routers/sources.py`, `parse_source_form_data`: add a `scope` form param and pass it into `SourceCreate`. Change the signature (add after `async_processing`, line 151):
```python
    async_processing: str = Form("false"),  # Accept as string, convert to bool
    scope: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
```
  and in the `SourceCreate(...)` construction (after `async_processing=async_processing_bool,`, line 199) add:
```python
            async_processing=async_processing_bool,
            scope=scope,
```
  > `parse_source_form_data` already wraps its JSON-decode and construction steps in `try`/`except` blocks that raise `HTTPException(422, ...)` for malformed `notebooks`/`transformations` JSON (lines 166-184); a `pydantic.ValidationError` from an invalid `scope` literal propagates the same way through FastAPI's existing exception handling for this dependency — no new error-handling code is required, only the field addition.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_models.py -q` — Expected: PASS (5 passed).

- [ ] **Step 5: Commit** — `git add api/models.py api/routers/sources.py tests/test_p5_models.py && git commit -m "P5: scope on Source create/update/response schemas + form parsing"`

---

### Task 6: Wire the predicate into `api/routers/sources.py` (create, list, get, download, status, update, retry, delete, insights)

**Files:**
- Modify: `api/routers/sources.py` (imports line 36; every endpoint: `get_sources` 213-348, `create_source` 352-643, `create_source_json` 647-651, `_resolve_source_file` 654-676, `get_source` 694-754, `check_source_file` 758-767, `download_source_file` 771-784, `get_source_status` 788-844, `update_source` 848-886, `retry_source_processing` 890-1015, `delete_source` 1019-1033, `get_source_insights` 1037-1060, `create_source_insight` 1068-1113)
- Test: `tests/test_p5_sources_router.py`

**Interfaces:**
- Consumes: `get_permission_context`, `require_view_source`, `require_mutate_source`, `visible_source_ids` (Tasks 3-4); `PermissionContext.project_role` (Task 3); `Project.default_source_scope` (P3).

- [ ] **Step 1: Write the failing test** — `tests/test_p5_sources_router.py` (TestClient + `dependency_overrides` for ctx; predicate seams patched):
```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context
from open_notebook.domain.notebook import Source


@pytest.fixture
def ctx():
    return PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")


@pytest.fixture
def client(ctx):
    from api.main import app
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_source_view_denied_returns_404(client):
    with patch(
        "api.routers.sources.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret")
    assert resp.status_code == 404


def test_update_source_mutate_denied_returns_403(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="You do not have permission to modify this source")),
    ):
        resp = client.put("/api/sources/source:x", json={"title": "new"})
    assert resp.status_code == 403


def test_delete_source_mutate_denied_returns_403(client):
    with patch(
        "api.routers.sources.require_mutate_source",
        new=AsyncMock(side_effect=HTTPException(status_code=403, detail="nope")),
    ):
        resp = client.delete("/api/sources/source:x")
    assert resp.status_code == 403


def test_list_sources_filters_by_visible_ids(client):
    # visible_source_ids returns an empty allow-list -> no rows, and the id
    # filter param is threaded into the query.
    captured = {}

    async def fake_repo_query(q, params=None):
        captured["query"] = q
        captured["params"] = params or {}
        return []

    with patch("api.routers.sources.visible_source_ids", new=AsyncMock(return_value=[])):
        with patch("api.routers.sources.repo_query", new=fake_repo_query):
            resp = client.get("/api/sources")
    assert resp.status_code == 200
    assert resp.json() == []
    assert "visible_ids" in captured["params"]
    assert "id IN $visible_ids" in captured["query"]


def test_create_source_rejects_non_member_project(client, ctx):
    # ctx.project_role returns None -> caller is not a member of the target project -> 403
    ctx.project_role = AsyncMock(return_value=None)
    resp = client.post(
        "/api/sources",
        data={"type": "text", "content": "hi", "notebooks": '["notebook:p1"]', "scope": "personal"},
    )
    assert resp.status_code == 403


def test_create_source_resolves_scope_from_project_default(client, ctx):
    # scope omitted entirely -> falls back to the target project's
    # default_source_scope ("company" in this fixture project).
    ctx.project_role = AsyncMock(return_value="member")
    captured = {}

    class _FakeProject:
        id = "notebook:p1"
        workspace = "workspace:w1"
        default_source_scope = "company"

    async def fake_project_get(pid):
        return _FakeProject()

    async def fake_save(self):
        captured["scope"] = self.scope
        return self

    with patch("api.routers.sources.Project.get", new=AsyncMock(side_effect=fake_project_get)):
        with patch.object(Source, "save", new=fake_save):
            resp = client.post(
                "/api/sources",
                data={"type": "text", "content": "hi", "notebooks": '["notebook:p1"]'},
            )
    assert resp.status_code in (200, 201, 202)
    assert captured.get("scope") == "company"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_sources_router.py -q` — Expected: FAIL (endpoints don't depend on ctx / predicate not wired; e.g. `test_get_source_view_denied` returns 500/404 for the wrong reason, `test_create_source_rejects_non_member_project` returns 200/404).

- [ ] **Step 3: Write minimal implementation** — Edit `api/routers/sources.py`:

  **Imports** — replace the domain import line (line 36) and add the predicate imports:
```python
from open_notebook.domain.notebook import Asset, Project, Source
```
```python
from api.source_permissions import (
    PermissionContext,
    get_permission_context,
    require_mutate_source,
    require_view_source,
    visible_source_ids,
)
```
  (Every `Notebook.get(...)` in this file becomes `Project.get(...)`.)

  **`get_sources`** — add `ctx` param and scope the query with the visible-id allow-list. Change the signature to accept `ctx: PermissionContext = Depends(get_permission_context)`, then compute `visible_ids` and inject the filter into BOTH query branches:
```python
async def get_sources(
    notebook_id: Optional[str] = Query(None, description="Filter by notebook ID"),
    limit: int = Query(50, ge=1, le=100, description="Number of sources to return (1-100)"),
    offset: int = Query(0, ge=0, description="Number of sources to skip"),
    sort_by: str = Query("updated", description="Field to sort by (...)"),
    sort_order: str = Query("desc", description="Sort order (asc or desc)"),
    ctx: PermissionContext = Depends(get_permission_context),
):
    """Get sources with pagination and sorting, scoped to sources the caller may view."""
    try:
        if sort_by not in SOURCE_SORT_FIELDS:
            raise HTTPException(status_code=400, detail="sort_by must be one of: type, title, created, updated, insights_count, embedded")
        if sort_order.lower() not in ["asc", "desc"]:
            raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")
        order_clause = f"ORDER BY {SOURCE_SORT_FIELDS[sort_by]} {sort_order.upper()}, id ASC"

        # Allow-list of source ids the caller may view (scopes to active workspace).
        visible = await visible_source_ids(ctx, notebook_id)
        visible_ids = [ensure_record_id(s) for s in visible]

        if notebook_id:
            notebook = await Project.get(notebook_id)
            if not notebook:
                raise HTTPException(status_code=404, detail="Notebook not found")
            query = f"""
                SELECT id, asset, created, title, updated, topics, command, scope, owner,
                string::lowercase(title OR '') AS title_sort,
                ({SOURCE_TYPE_EXPRESSION}) AS type,
                (SELECT VALUE count() FROM source_insight WHERE source = $parent.id GROUP ALL)[0].count OR 0 AS insights_count,
                (SELECT VALUE id FROM source_embedding WHERE source = $parent.id LIMIT 1) != [] AS embedded
                FROM (select value in from reference where out=$notebook_id)
                WHERE id IN $visible_ids
                {order_clause}
                LIMIT $limit START $offset
                FETCH command
            """
            result = await repo_query(query, {"notebook_id": ensure_record_id(notebook_id), "visible_ids": visible_ids, "limit": limit, "offset": offset})
        else:
            query = f"""
                SELECT id, asset, created, title, updated, topics, command, scope, owner,
                string::lowercase(title OR '') AS title_sort,
                ({SOURCE_TYPE_EXPRESSION}) AS type,
                (SELECT VALUE count() FROM source_insight WHERE source = $parent.id GROUP ALL)[0].count OR 0 AS insights_count,
                (SELECT VALUE id FROM source_embedding WHERE source = $parent.id LIMIT 1) != [] AS embedded
                FROM source
                WHERE id IN $visible_ids
                {order_clause}
                LIMIT $limit START $offset
                FETCH command
            """
            result = await repo_query(query, {"visible_ids": visible_ids, "limit": limit, "offset": offset})
        # ... existing response_list building loop unchanged, EXCEPT add to each
        # SourceListResponse(...): scope=row.get("scope") or "project",
        # owner=str(row["owner"]) if row.get("owner") else None,
```
  In the `SourceListResponse(...)` constructor inside the loop, add the two fields:
```python
                    processing_info=processing_info,
                    scope=row.get("scope") or "project",
                    owner=str(row["owner"]) if row.get("owner") else None,
```

  **`create_source`** — add `ctx` param, enforce project membership, and resolve+stamp `owner`/`scope` on both paths. Change signature:
```python
async def create_source(
    form_data: tuple[SourceCreate, Optional[UploadFile]] = Depends(parse_source_form_data),
    ctx: PermissionContext = Depends(get_permission_context),
):
```
  Replace the notebook-existence loop (lines 364-370) with a membership+workspace check that also resolves the effective scope from the first target project's `default_source_scope` when the caller omitted `scope`:
```python
        # Verify target projects exist AND the caller is a member (member+) of
        # each, in the active workspace. Non-member -> 403; wrong workspace /
        # missing -> 404. Resolve the effective scope from the FIRST target
        # project's default_source_scope when the caller didn't pick one.
        resolved_scope = source_data.scope
        for i, notebook_id in enumerate(source_data.notebooks or []):
            project = await Project.get(notebook_id)
            if not project:
                raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
            if str(getattr(project, "workspace", None)) != ctx.workspace_id:
                raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
            if await ctx.project_role(notebook_id) not in ("admin", "member"):
                raise HTTPException(status_code=403, detail="You are not a member of this project")
            if i == 0 and resolved_scope is None:
                resolved_scope = getattr(project, "default_source_scope", None)
        resolved_scope = resolved_scope or "project"
```
  In the ASYNC path `Source(...)` construction (line 448) and the SYNC path `Source(...)` (line 528), stamp owner + the resolved scope before `await source.save()`:
```python
            source = Source(
                title=source_data.title or "Processing...",
                topics=[],
                asset=source_asset,
                owner=ctx.user_id,
                scope=resolved_scope,
            )
```
  (sync path is identical minus `asset=source_asset`; add `owner=ctx.user_id, scope=resolved_scope,` there too.) Add `scope`/`owner` to the async-path `SourceResponse(...)` (line 487) and the sync-path `SourceResponse(...)` (line 587):
```python
                    processing_info={"async": True, "queued": True},
                    scope=resolved_scope,
                    owner=ctx.user_id,
```
```python
                    updated=str(processed_source.updated),
                    scope=processed_source.scope,
                    owner=str(processed_source.owner) if processed_source.owner else None,
```
  `create_source_json` (line 647) — add `ctx` and forward it:
```python
async def create_source_json(
    source_data: SourceCreate,
    ctx: PermissionContext = Depends(get_permission_context),
):
    form_data = (source_data, None)
    return await create_source(form_data, ctx)
```

  **`_resolve_source_file`** — add a `ctx` param and view-check before returning the path:
```python
async def _resolve_source_file(source_id: str, ctx: PermissionContext) -> tuple[str, str]:
    source = await require_view_source(source_id, ctx)
    file_path = source.asset.file_path if source.asset else None
    if not file_path:
        raise HTTPException(status_code=404, detail="Source has no file to download")
    # ... rest of the existing path-containment logic unchanged ...
```
  `check_source_file` (line 758) and `download_source_file` (line 771) — add `ctx: PermissionContext = Depends(get_permission_context)` and pass it: `await _resolve_source_file(source_id, ctx)`.

  **`get_source`** (line 694) — add `ctx` and replace the load+null-check with the predicate:
```python
async def get_source(source_id: str, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        source = await require_view_source(source_id, ctx)
        await _stamp_source_view(source.id or source_id)
        # ... existing status/embedded/notebooks logic unchanged ...
```
  Add to the returned `SourceResponse(...)` (line 725): `scope=source.scope, owner=str(source.owner) if source.owner else None,`.

  **`get_source_status`** (line 788) — add `ctx` and replace the load: `source = await require_view_source(source_id, ctx)`.

  **`update_source`** (line 848) — add `ctx`, replace the load with `source = await require_mutate_source(source_id, ctx)`, and apply scope:
```python
async def update_source(source_id: str, source_update: SourceUpdate, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        source = await require_mutate_source(source_id, ctx)
        if source_update.title is not None:
            source.title = source_update.title
        if source_update.topics is not None:
            source.topics = source_update.topics
        if source_update.scope is not None:
            source.scope = source_update.scope
        await source.save()
        # ... existing response build ...
```
  Add to the returned `SourceResponse(...)` (line 864): `scope=source.scope, owner=str(source.owner) if source.owner else None,`.

  **`retry_source_processing`** (line 890) — add `ctx`, replace the load with `source = await require_mutate_source(source_id, ctx)`. Add `scope=source.scope, owner=str(source.owner) if source.owner else None,` to its `SourceResponse(...)` (line 983).

  **`delete_source`** (line 1019) — add `ctx`, replace the load with `source = await require_mutate_source(source_id, ctx)`.

  **`get_source_insights`** (line 1037) — add `ctx`, replace the load with `source = await require_view_source(source_id, ctx)`.

  **`create_source_insight`** (line 1068) — add `ctx`, replace the load with `source = await require_mutate_source(source_id, ctx)` (generating insights writes to the source).

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_sources_router.py tests/test_sources_api.py -q` — Expected: PASS. (Existing `tests/test_sources_api.py` mocks `Notebook.get`/`Source.get` — update those patches to `Project.get` and add `app.dependency_overrides[get_permission_context]` in its `client` fixture if it exercises the now-ctx-dependent endpoints; adjust as the failures direct.)

- [ ] **Step 5: Commit** — `git add api/routers/sources.py tests/test_p5_sources_router.py tests/test_sources_api.py && git commit -m "P5: enforce view/mutate on all sources.py endpoints + owner/scope on create (3-scope, default_source_scope fallback)"`

---

### Task 7: Wire the predicate into `api/routers/insights.py`

**Files:**
- Modify: `api/routers/insights.py` (`get_insight` 11-34, `delete_insight` 37-52, `save_insight_as_note` 55-84)
- Test: `tests/test_p5_insights_router.py`

**Interfaces:**
- Consumes: `get_permission_context`, `require_view_source`, `require_mutate_source`; `SourceInsight.get_source()` (existing, returns the parent `Source`).

- [ ] **Step 1: Write the failing test** — `tests/test_p5_insights_router.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context
from open_notebook.domain.notebook import Source, SourceInsight


@pytest.fixture
def client():
    from api.main import app
    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def _insight():
    ins = SourceInsight(id="source_insight:1", insight_type="x", content="c")
    ins.get_source = AsyncMock(return_value=Source(id="source:1", title="t"))
    return ins


def test_get_insight_view_denied_404(client):
    with patch.object(SourceInsight, "get", new=AsyncMock(return_value=_insight())):
        with patch(
            "api.routers.insights.require_view_source",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
        ):
            resp = client.get("/api/insights/source_insight:1")
    assert resp.status_code == 404


def test_delete_insight_mutate_denied_403(client):
    with patch.object(SourceInsight, "get", new=AsyncMock(return_value=_insight())):
        with patch(
            "api.routers.insights.require_mutate_source",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="nope")),
        ):
            resp = client.delete("/api/insights/source_insight:1")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_insights_router.py -q` — Expected: FAIL (endpoints don't call the predicate).

- [ ] **Step 3: Write minimal implementation** — In `api/routers/insights.py` add imports and wire each endpoint:
```python
from fastapi import APIRouter, Depends, HTTPException

from api.source_permissions import (
    PermissionContext,
    get_permission_context,
    require_mutate_source,
    require_view_source,
)
```
  `get_insight` (11-34) — add `ctx`, and after `source = await insight.get_source()`, view-check:
```python
async def get_insight(insight_id: str, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        insight = await SourceInsight.get(insight_id)
        if not insight:
            raise HTTPException(status_code=404, detail="Insight not found")
        source = await insight.get_source()
        await require_view_source(source.id, ctx)
        return SourceInsightResponse(...)  # unchanged body
```
  `delete_insight` (37-52) — add `ctx`, resolve source and mutate-check before delete:
```python
async def delete_insight(insight_id: str, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        insight = await SourceInsight.get(insight_id)
        if not insight:
            raise HTTPException(status_code=404, detail="Insight not found")
        source = await insight.get_source()
        await require_mutate_source(source.id, ctx)
        await insight.delete()
        return {"message": "Insight deleted successfully"}
```
  `save_insight_as_note` (55-84) — add `ctx`, view-check the insight's source before reading it into a note:
```python
async def save_insight_as_note(insight_id: str, request: SaveAsNoteRequest, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        insight = await SourceInsight.get(insight_id)
        if not insight:
            raise HTTPException(status_code=404, detail="Insight not found")
        source = await insight.get_source()
        await require_view_source(source.id, ctx)
        note = await insight.save_as_note(request.notebook_id)
        return NoteResponse(...)  # unchanged body
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_insights_router.py -q` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add api/routers/insights.py tests/test_p5_insights_router.py && git commit -m "P5: enforce source scope on insights endpoints"`

---

### Task 8: Wire the predicate into `api/routers/source_chat.py`

**Files:**
- Modify: `api/routers/source_chat.py` (all 6 endpoints replace the repeated `Source.get(full_source_id)` load with `require_view_source`: `create_source_chat_session` 87-129, `get_source_chat_sessions` 132-190, `get_source_chat_session` 193-287, `update_source_chat_session` 290-359, `delete_source_chat_session` 362-414, `send_message_to_source_chat` 487-558)
- Test: `tests/test_p5_source_chat_router.py`

**Interfaces:**
- Consumes: `get_permission_context`, `require_view_source`. All chat endpoints require **view** on the source (a member may manage their own sessions over a `project`/`company` source without mutate rights).

- [ ] **Step 1: Write the failing test** — `tests/test_p5_source_chat_router.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context


@pytest.fixture
def client():
    from api.main import app
    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_create_session_view_denied_404(client):
    with patch(
        "api.routers.source_chat.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.post("/api/sources/source:secret/chat/sessions", json={"source_id": "source:secret"})
    assert resp.status_code == 404


def test_list_sessions_view_denied_404(client):
    with patch(
        "api.routers.source_chat.require_view_source",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Source not found")),
    ):
        resp = client.get("/api/sources/source:secret/chat/sessions")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_source_chat_router.py -q` — Expected: FAIL.

- [ ] **Step 3: Write minimal implementation** — In `api/routers/source_chat.py` add imports:
```python
from fastapi import APIRouter, Depends, HTTPException, Path

from api.source_permissions import (
    PermissionContext,
    get_permission_context,
    require_view_source,
)
```
  In each of the 6 endpoints add `ctx: PermissionContext = Depends(get_permission_context)` to the signature and replace the repeated block:
```python
        full_source_id = (
            source_id if source_id.startswith("source:") else f"source:{source_id}"
        )
        source = await Source.get(full_source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
```
  with:
```python
        full_source_id = (
            source_id if source_id.startswith("source:") else f"source:{source_id}"
        )
        await require_view_source(full_source_id, ctx)
```
  (The `Source` import may become unused in this file — remove it from the import if lint flags it, or keep if still referenced. `ChatSession` import stays.)

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_source_chat_router.py -q` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add api/routers/source_chat.py tests/test_p5_source_chat_router.py && git commit -m "P5: require source view on all source-chat endpoints"`

---

### Task 9: Wire the predicate into `api/routers/embedding.py`

**Files:**
- Modify: `api/routers/embedding.py` (`embed_content` 13-124 — `item_type not in ["source","note"]` guard ~line 31, async branch ~34-70, domain-model branch ~72-110)
- Test: `tests/test_p5_embedding_router.py`

**Interfaces:**
- Consumes: `get_permission_context`, `require_mutate_source`. Embedding a source writes derived data → mutate check. The `note` branch is unchanged.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_embedding_router.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context


@pytest.fixture
def client():
    from api.main import app
    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_embed_source_mutate_denied_403(client):
    with patch("api.routers.embedding.model_manager.get_embedding_model", new=AsyncMock(return_value=object())):
        with patch(
            "api.routers.embedding.require_mutate_source",
            new=AsyncMock(side_effect=HTTPException(status_code=403, detail="nope")),
        ):
            resp = client.post("/api/embed", json={"item_id": "source:x", "item_type": "source"})
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_embedding_router.py -q` — Expected: FAIL (no mutate check).

- [ ] **Step 3: Write minimal implementation** — In `api/routers/embedding.py`:
```python
from fastapi import APIRouter, Depends, HTTPException

from api.source_permissions import (
    PermissionContext,
    get_permission_context,
    require_mutate_source,
)
```
  Add `ctx: PermissionContext = Depends(get_permission_context)` to `embed_content`. Place the check once, right after the `if item_type not in ["source", "note"]:` guard (~line 31), so it covers both the async-submit branch and the domain-model branch:
```python
        # Source embedding writes derived data -> require mutate on the source.
        if item_type == "source":
            await require_mutate_source(item_id, ctx)
```
  The `note` branch is untouched.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_embedding_router.py -q` — Expected: PASS (1 passed).

- [ ] **Step 5: Commit** — `git add api/routers/embedding.py tests/test_p5_embedding_router.py && git commit -m "P5: require mutate on POST /embed for sources"`

---

### Task 10: Search-leakage fix — thread `viewer_source_ids` through domain search + `search.py` + ask RAG graph

**Files:**
- Modify: `open_notebook/domain/notebook.py` (`text_search` 756-795, `vector_search` 798-828 — add `viewer_source_ids` param + pass to `fn::`)
- Modify: `api/routers/search.py` (`search_knowledge_base` 17-58, `ask_knowledge_base` 113-162 + its `stream_ask_response` helper 61-110, `ask_knowledge_base_simple` 165-222 — all get `ctx`; compute + pass `viewer_source_ids`; thread into ask-graph `configurable`)
- Modify: `open_notebook/graphs/ask.py` (a single module file, not a package; `provide_answer` reads `viewer_source_ids` from `config.configurable`)
- Test: `tests/test_p5_search_leakage.py`

**Interfaces:**
- Consumes: `visible_source_ids(ctx, None)` (Task 4), `get_permission_context`.
- Produces: `text_search(..., viewer_source_ids=None)`, `vector_search(..., viewer_source_ids=None)` — both normalize ids to `RecordID` and forward to the migration-23 `fn::` allow-list param, which is scope-agnostic (it only filters an already-3-scope-resolved id set).

- [ ] **Step 1: Write the failing test** — `tests/test_p5_search_leakage.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from surrealdb import RecordID
from fastapi.testclient import TestClient

from api.source_permissions import PermissionContext, get_permission_context


@pytest.mark.asyncio
async def test_text_search_passes_viewer_source_ids_to_fn():
    captured = {}

    async def fake_repo_query(q, params=None):
        captured["q"] = q
        captured["params"] = params or {}
        return []

    from open_notebook.domain.notebook import text_search
    with patch("open_notebook.domain.notebook.repo_query", new=fake_repo_query):
        await text_search("hello", 10, True, True, viewer_source_ids=["source:a"])
    assert "fn::text_search" in captured["q"]
    assert "$viewer_source_ids" in captured["q"]
    assert isinstance(captured["params"]["viewer_source_ids"][0], RecordID)


@pytest.mark.asyncio
async def test_vector_search_passes_viewer_source_ids_to_fn():
    captured = {}

    async def fake_repo_query(q, params=None):
        captured["params"] = params or {}
        return []

    from open_notebook.domain import notebook as nb
    with patch("open_notebook.domain.notebook.repo_query", new=fake_repo_query):
        with patch("open_notebook.utils.embedding.generate_embedding", new=AsyncMock(return_value=[0.1, 0.2])):
            await nb.vector_search("hello", 10, True, True, viewer_source_ids=["source:b"])
    assert "viewer_source_ids" in captured["params"]
    assert str(captured["params"]["viewer_source_ids"][0]) == "source:b"


def test_search_endpoint_computes_and_forwards_viewer_ids():
    from api.main import app
    ctx = PermissionContext(user_id="user:u1", workspace_id="workspace:w1", workspace_role="member")
    app.dependency_overrides[get_permission_context] = lambda: ctx
    try:
        client = TestClient(app)
        with patch("api.routers.search.visible_source_ids", new=AsyncMock(return_value=["source:a"])) as vsi:
            with patch("api.routers.search.text_search", new=AsyncMock(return_value=[])) as ts:
                resp = client.post("/api/search", json={"query": "q", "type": "text", "limit": 5, "search_sources": True, "search_notes": True})
        assert resp.status_code == 200
        vsi.assert_awaited()
        assert ts.await_args.kwargs["viewer_source_ids"] == ["source:a"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ask_graph_provide_answer_uses_configurable_viewer_ids():
    from open_notebook.graphs.ask import provide_answer
    captured = {}

    async def fake_vector_search(term, n, s, note, **kw):
        captured["kw"] = kw
        return []

    with patch("open_notebook.graphs.ask.vector_search", new=fake_vector_search):
        await provide_answer(
            {"question": "q", "term": "t", "instructions": "i"},
            {"configurable": {"answer_model": "m", "viewer_source_ids": ["source:a"]}},
        )
    assert captured["kw"]["viewer_source_ids"] == ["source:a"]
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_search_leakage.py -q` — Expected: FAIL (`text_search()` got an unexpected keyword argument `viewer_source_ids`).

- [ ] **Step 3: Write minimal implementation** —
  In `open_notebook/domain/notebook.py`, update `text_search` (756) and `vector_search` (798):
```python
async def text_search(
    keyword: str, results: int, source: bool = True, note: bool = True,
    viewer_source_ids: Optional[List[str]] = None,
):
    if not keyword:
        raise InvalidInputError("Search keyword cannot be empty")
    viewer_rids = [ensure_record_id(s) for s in (viewer_source_ids or [])]
    try:
        search_results = await repo_query(
            """
            select *
            from fn::text_search($keyword, $results, $source, $note, $viewer_source_ids)
            """,
            {"keyword": keyword, "results": results, "source": source, "note": note,
             "viewer_source_ids": viewer_rids},
        )
        return search_results
    except RuntimeError as e:
        if "position overflow" in str(e):
            logger.warning(f"Highlight position overflow, falling back to vector search: {str(e)}")
            try:
                return await vector_search(keyword, results, source, note, viewer_source_ids=viewer_source_ids)
            except Exception as ve:
                logger.error(f"Vector search fallback also failed: {str(ve)}")
                logger.exception(ve)
                raise DatabaseOperationError(ve)
        logger.error(f"Error performing text search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)
    except Exception as e:
        logger.error(f"Error performing text search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)


async def vector_search(
    keyword: str, results: int, source: bool = True, note: bool = True,
    minimum_score=0.2, viewer_source_ids: Optional[List[str]] = None,
):
    if not keyword:
        raise InvalidInputError("Search keyword cannot be empty")
    viewer_rids = [ensure_record_id(s) for s in (viewer_source_ids or [])]
    try:
        from open_notebook.utils.embedding import generate_embedding
        embed = await generate_embedding(keyword)
        search_results = await repo_query(
            """
            SELECT * FROM fn::vector_search($embed, $results, $source, $note, $minimum_score, $viewer_source_ids);
            """,
            {"embed": embed, "results": results, "source": source, "note": note,
             "minimum_score": minimum_score, "viewer_source_ids": viewer_rids},
        )
        return search_results
    except Exception as e:
        logger.error(f"Error performing vector search: {str(e)}")
        logger.exception(e)
        raise DatabaseOperationError(e)
```
  In `api/routers/search.py`, add imports and thread the allow-list. Imports:
```python
from fastapi import APIRouter, Depends, HTTPException

from api.source_permissions import (
    PermissionContext, get_permission_context, visible_source_ids,
)
from open_notebook.database.repository import ensure_record_id
```
  `search_knowledge_base` (17) — add `ctx`, compute allow-list, pass to both search calls:
```python
async def search_knowledge_base(
    search_request: SearchRequest,
    ctx: PermissionContext = Depends(get_permission_context),
):
    try:
        viewer_ids = await visible_source_ids(ctx, None)
        if search_request.type == "vector":
            if not await model_manager.get_embedding_model():
                raise HTTPException(status_code=400, detail="Vector search requires an embedding model. Please configure one in the Models section.")
            results = await vector_search(
                keyword=search_request.query, results=search_request.limit,
                source=search_request.search_sources, note=search_request.search_notes,
                minimum_score=search_request.minimum_score, viewer_source_ids=viewer_ids,
            )
        else:
            results = await text_search(
                keyword=search_request.query, results=search_request.limit,
                source=search_request.search_sources, note=search_request.search_notes,
                viewer_source_ids=viewer_ids,
            )
        return SearchResponse(results=results or [], total_count=len(results) if results else 0, search_type=search_request.type)
    # ... existing except blocks unchanged ...
```
  `ask_knowledge_base` (113) and `ask_knowledge_base_simple` (165) — add `ctx`, compute `viewer_ids`, and add it to the graph `configurable` dict:
```python
async def ask_knowledge_base(ask_request: AskRequest, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        # ... model validation unchanged ...
        viewer_ids = await visible_source_ids(ctx, None)
        return StreamingResponse(
            stream_ask_response(ask_request.question, strategy_model, answer_model, final_answer_model, viewer_ids),
            media_type="text/event-stream",
            headers={...},  # unchanged
        )
```
  Update `stream_ask_response` (61) to accept and forward `viewer_source_ids`:
```python
async def stream_ask_response(question, strategy_model, answer_model, final_answer_model, viewer_source_ids):
    ...
    async for chunk in ask_graph.astream(
        input=dict(question=question),
        config=dict(configurable=dict(
            strategy_model=strategy_model.id,
            answer_model=answer_model.id,
            final_answer_model=final_answer_model.id,
            viewer_source_ids=viewer_source_ids,
        )),
        stream_mode="updates",
    ):
        ...
```
  In `ask_knowledge_base_simple`, compute `viewer_ids = await visible_source_ids(ctx, None)` and add `viewer_source_ids=viewer_ids` to the inline `configurable=dict(...)` (line 202).
  In `open_notebook/graphs/ask.py`, `provide_answer` (98) — read the allow-list from config and pass to `vector_search`:
```python
async def provide_answer(state: SubGraphState, config: RunnableConfig) -> dict:
    try:
        payload = state
        viewer_source_ids = config.get("configurable", {}).get("viewer_source_ids") or []
        results = await vector_search(state["term"], 10, True, True, viewer_source_ids=viewer_source_ids)
        if len(results) == 0:
            return {"answers": []}
        # ... rest unchanged ...
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_search_leakage.py tests/test_search_api.py -q` — Expected: PASS. (If `tests/test_search_api.py` calls the endpoints without a ctx override, add `app.dependency_overrides[get_permission_context]` in its client fixture.)

- [ ] **Step 5: Commit** — `git add open_notebook/domain/notebook.py api/routers/search.py open_notebook/graphs/ask.py tests/test_p5_search_leakage.py tests/test_search_api.py && git commit -m "P5: thread viewer_source_ids through search + ask RAG graph (leakage fix, 3-scope)"`

---

### Task 11: Scope-filtered project context — `context.py` + `Project.get_sources()`

**Files:**
- Modify: `open_notebook/domain/notebook.py` (`Project.get_sources` — pre-P3 today this is `Notebook.get_sources`, lines 31-47 — add optional `viewer_source_ids` filter)
- Modify: `api/routers/context.py` (`get_notebook_context` 12-127 — `context_config` branch ~25-76, default branch ~77-109 — compute allow-list, pass to `get_sources`; view-check per-source in the explicit-config branch)
- Test: `tests/test_p5_context_router.py`

**Interfaces:**
- Consumes: `visible_source_ids(ctx, notebook_id)`, `get_permission_context`.
- Produces: `Project.get_sources(include_full_text=False, viewer_source_ids=None)` — when the set is provided, only sources whose id is in it are returned.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_context_router.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.notebook import Project, Source


@pytest.mark.asyncio
async def test_get_sources_filters_to_viewer_set():
    p = Project(id="notebook:p1", name="P", description="")
    rows = [
        {"source": {"id": "source:a", "title": "A"}},
        {"source": {"id": "source:b", "title": "B"}},
    ]
    with patch("open_notebook.domain.notebook.repo_query", new=AsyncMock(return_value=rows)):
        got = await p.get_sources(viewer_source_ids={"source:a"})
    assert [s.id for s in got] == ["source:a"]


@pytest.mark.asyncio
async def test_get_sources_no_filter_returns_all():
    p = Project(id="notebook:p1", name="P", description="")
    rows = [{"source": {"id": "source:a", "title": "A"}}]
    with patch("open_notebook.domain.notebook.repo_query", new=AsyncMock(return_value=rows)):
        got = await p.get_sources()
    assert [s.id for s in got] == ["source:a"]
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_context_router.py -q` — Expected: FAIL (`get_sources()` got an unexpected keyword argument `viewer_source_ids`).

- [ ] **Step 3: Write minimal implementation** — In `open_notebook/domain/notebook.py`, class `Project`, update `get_sources` (currently lines 31-47 as `Notebook.get_sources`):
```python
    async def get_sources(
        self,
        include_full_text: bool = False,
        viewer_source_ids: Optional[set] = None,
    ) -> List["Source"]:
        try:
            source_projection = "" if include_full_text else " omit source.full_text"
            srcs = await repo_query(
                f"""
                select *{source_projection} from (
                select in as source from reference where out=$id
                fetch source
            ) order by source.updated desc
            """,
                {"id": ensure_record_id(self.id)},
            )
            sources = [Source(**src["source"]) for src in srcs] if srcs else []
            if viewer_source_ids is not None:
                allowed = {str(s) for s in viewer_source_ids}
                sources = [s for s in sources if str(s.id) in allowed]
            return sources
        except Exception as e:
            logger.error(f"Error fetching sources for notebook {self.id}: {str(e)}")
            logger.exception(e)
            raise DatabaseOperationError(e)
```
  In `api/routers/context.py`, add imports and enforce scope:
```python
from fastapi import APIRouter, Depends, HTTPException

from api.source_permissions import (
    PermissionContext, get_permission_context, require_view_source, visible_source_ids,
)
from open_notebook.domain.notebook import Note, Project, Source, SourceInsight
```
  `get_notebook_context` (12) — add `ctx`, replace `Notebook.get` with `Project.get`, compute the allow-list once, and use it in both branches:
```python
async def get_notebook_context(
    notebook_id: str,
    context_request: ContextRequest,
    ctx: PermissionContext = Depends(get_permission_context),
):
    try:
        notebook = await Project.get(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        visible = set(await visible_source_ids(ctx, notebook_id))
        context_data: dict[str, list[dict[str, str]]] = {"note": [], "source": []}
        total_content = ""
        if context_request.context_config:
            for source_id, status in context_request.context_config.sources.items():
                if "not in" in status:
                    continue
                try:
                    full_source_id = source_id if source_id.startswith("source:") else f"source:{source_id}"
                    # Skip sources the caller may not view (belt-and-braces with the set filter).
                    if full_source_id not in visible:
                        continue
                    try:
                        source = await Source.get(full_source_id)
                    except Exception:
                        continue
                    # ... existing insights/full-content branch unchanged ...
```
  In the default (no-config) branch, pass the set into `get_sources`:
```python
            sources = await notebook.get_sources(viewer_source_ids=visible)
```
  > **Background jobs note (documented decision, not a code change):** `Project.get_context()` / `get_sources()` run without a user context in worker jobs (podcasts) — those keep the unfiltered path and run with full project scope, which is acceptable because they are project-owner-initiated (see spec "Open questions"). Only the request-scoped `context.py` path filters.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_context_router.py -q` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/domain/notebook.py api/routers/context.py tests/test_p5_context_router.py && git commit -m "P5: filter project context assembly by source scope"`

---

### Task 12: Frontend — types + API client + hook plumbing for `scope`

**Files:**
- Modify: `frontend/src/lib/types/api.ts` (`SourceListResponse` 21-39, `SourceDetailResponse` 41-44, `CreateSourceRequest` 96-112, `UpdateSourceRequest` 120-125)
- Modify: `frontend/src/lib/api/sources.ts` (`create` 32-69)
- Test: `frontend/src/lib/api/sources.scope.test.ts`

**Interfaces:**
- Produces: `scope?: 'personal' | 'project' | 'company'` on create/update requests; `scope: 'personal' | 'project' | 'company'` + `owner?: string | null` on list/detail responses; `sourcesApi.create` appends `scope` to `FormData`; `sourcesApi.update` includes `scope` in its JSON body.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/api/sources.scope.test.ts`:
```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { sourcesApi } from './sources'
import { apiClient } from './client'

vi.mock('./client', () => ({
  apiClient: { post: vi.fn().mockResolvedValue({ data: {} }), put: vi.fn().mockResolvedValue({ data: {} }) },
}))

describe('sourcesApi scope', () => {
  beforeEach(() => vi.clearAllMocks())

  it('appends scope to create FormData', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi', scope: 'personal' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('scope')).toBe('personal')
  })

  it('defaults create scope to project when omitted', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('scope')).toBe('project')
  })

  it('supports the company scope value', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi', scope: 'company' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('scope')).toBe('company')
  })

  it('includes scope in update body', async () => {
    await sourcesApi.update('source:1', { scope: 'company' })
    expect(apiClient.put).toHaveBeenCalledWith('/sources/source:1', { scope: 'company' })
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (in `frontend/`): `npm run test -- sources.scope` — Expected: FAIL (type error / `scope` not appended).

- [ ] **Step 3: Write minimal implementation** —
  In `frontend/src/lib/types/api.ts`:
  - `SourceListResponse` (21-39) — add after `processing_info?`: `scope: 'personal' | 'project' | 'company'` and `owner?: string | null`.
  - `CreateSourceRequest` (96-112) — add after `async_processing?`: `scope?: 'personal' | 'project' | 'company'`.
  - `UpdateSourceRequest` (120-125) — add after `content?`: `scope?: 'personal' | 'project' | 'company'`.
  - `SourceDetailResponse extends SourceListResponse` (41-44), and `SourceResponse = SourceDetailResponse` (46), so both inherit `scope`/`owner` automatically — no separate edit.
  In `frontend/src/lib/api/sources.ts`, `create` (32-69) — after the `async_processing` append add:
```ts
    formData.append('scope', data.scope ?? 'project')
```
  `update` already sends `data` verbatim as the JSON body (`apiClient.put('/sources/${id}', data)`), so `scope` flows through with no change — the test asserts this.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- sources.scope` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/types/api.ts frontend/src/lib/api/sources.ts frontend/src/lib/api/sources.scope.test.ts && git commit -m "P5 fe: scope on source types + api client (3-scope)"`

---

### Task 13: Frontend — 3-option scope selector in the add-source wizard

**Files:**
- Modify: `frontend/src/components/sources/AddSourceDialog.tsx` (`createSourceSchema` 30-66, `defaultValues`, `submitSingleSource` 300-320, `submitBatch` 323-383)
- Modify: `frontend/src/components/sources/steps/ProcessingStep.tsx` (local `CreateSourceFormData` interface, add a Visibility `FormSection`)
- Test: `frontend/src/components/sources/AddSourceDialog.scope.test.tsx`

**Interfaces:**
- Produces: `scope` field on the wizard form (default `'project'`), threaded into every `createRequest`; a three-option segmented control rendered in `ProcessingStep`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/sources/AddSourceDialog.scope.test.tsx`:
```tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { AddSourceDialog } from './AddSourceDialog'

const mutateAsync = vi.fn().mockResolvedValue({ id: 'source:1' })
vi.mock('@/lib/hooks/use-sources', () => ({
  useCreateSource: () => ({ mutateAsync, isPending: false }),
  useFileUpload: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('@/lib/hooks/use-settings', () => ({ useSettings: () => ({ data: { default_embedding_option: 'ask' } }) }))
vi.mock('@/lib/hooks/use-transformations', () => ({ useTransformations: () => ({ data: [] }) }))

describe('AddSourceDialog scope', () => {
  it('submits a text source with the selected scope', async () => {
    render(<AddSourceDialog open onOpenChange={() => {}} defaultNotebookId="notebook:p1" />)
    fireEvent.change(screen.getByPlaceholderText(/text/i), { target: { value: 'hello world' } })
    fireEvent.click(await screen.findByRole('radio', { name: /personal/i }))
    fireEvent.click(screen.getByRole('button', { name: /add source/i }))
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ scope: 'personal' })
  })

  it('offers all three scope options', async () => {
    render(<AddSourceDialog open onOpenChange={() => {}} defaultNotebookId="notebook:p1" />)
    expect(await screen.findByRole('radio', { name: /personal/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /project/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /company/i })).toBeInTheDocument()
  })
})
```
> If the multi-step navigation makes a full render brittle, assert instead on `submitSingleSource`'s output by exporting a small pure builder, or keep this as a focused test of the `ProcessingStep` control. The load-bearing assertion is: **`createRequest.scope` equals the form value, defaulting to `'project'`, and all three options are selectable.**

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- AddSourceDialog.scope` — Expected: FAIL (no radio named "Personal"/"Company"; `scope` absent from the request).

- [ ] **Step 3: Write minimal implementation** —
  In `AddSourceDialog.tsx`:
  - `createSourceSchema` (30-66) — add to the `z.object({...})`: `scope: z.enum(['personal', 'project', 'company']),`.
  - `defaultValues` — add `scope: 'project',`.
  - `submitSingleSource` (300-320) — add `scope: data.scope,` to the `createRequest` object literal.
  - `submitBatch` (323-383) — add `scope: data.scope,` to the per-item `createRequest`.
  In `ProcessingStep.tsx`:
  - Add to the local `CreateSourceFormData` interface: `scope: 'personal' | 'project' | 'company'`.
  - Add imports at the top: `import { Lock, Users, Building2 } from 'lucide-react'` and `import { cn } from '@/lib/utils'`.
  - Add a new `FormSection` right after the transformations section (before the "Settings" section):
```tsx
      <FormSection title={t('sources.visibility')} description={t('sources.visibilityLabel')}>
        <Controller
          control={control}
          name="scope"
          render={({ field }) => (
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label={t('sources.visibilityLabel')}>
              {(['personal', 'project', 'company'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={field.value === value}
                  onClick={() => field.onChange(value)}
                  className={cn(
                    'flex flex-col items-start gap-1 rounded-md border p-3 text-left transition-colors',
                    field.value === value ? 'border-primary bg-primary/5' : 'border-input hover:bg-muted',
                  )}
                >
                  <span className="flex items-center gap-2 text-sm font-medium">
                    {value === 'personal' && <Lock className="h-4 w-4" />}
                    {value === 'project' && <Users className="h-4 w-4" />}
                    {value === 'company' && <Building2 className="h-4 w-4" />}
                    {value === 'personal' && t('sources.visibilityPersonal')}
                    {value === 'project' && t('sources.visibilityProject')}
                    {value === 'company' && t('sources.visibilityCompany')}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {value === 'personal' && t('sources.visibilityPersonalDesc')}
                    {value === 'project' && t('sources.visibilityProjectDesc')}
                    {value === 'company' && t('sources.visibilityCompanyDesc')}
                  </span>
                </button>
              ))}
            </div>
          )}
        />
      </FormSection>
```
  - Nicety (not required for correctness — the server already collapses all three scopes to owner-only in a `kind="personal"` workspace): if a `useActiveWorkspace()`-style hook from P2/P6 is available, pass an `isPersonalWorkspace` prop down to `ProcessingStep` and render the control `disabled`, force `field.value` to `'personal'`, and show `t('sources.visibilityPersonalWorkspaceHint')` under the control instead of the three options being independently clickable. Skip this if the workspace hook isn't available yet — the backend rule is authoritative either way.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- AddSourceDialog.scope` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add frontend/src/components/sources/AddSourceDialog.tsx frontend/src/components/sources/steps/ProcessingStep.tsx frontend/src/components/sources/AddSourceDialog.scope.test.tsx && git commit -m "P5 fe: 3-option scope selector in add-source wizard"`

---

### Task 14: Frontend — scope badge on the source card

**Files:**
- Modify: `frontend/src/components/sources/SourceCard.tsx` (metadata badges row, `areEqual` comparator 450-471; lucide imports)
- Test: `frontend/src/components/sources/SourceCard.scope.test.tsx`

**Interfaces:**
- Consumes: `source.scope` (Task 12).

- [ ] **Step 1: Write the failing test** — `frontend/src/components/sources/SourceCard.scope.test.tsx`:
```tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SourceCard } from './SourceCard'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const base = {
  id: 'source:1', title: 'T', topics: [], asset: null, embedded: true,
  embedded_chunks: 1, insights_count: 0, created: 'c', updated: 'u',
  status: 'completed',
}

describe('SourceCard scope badge', () => {
  it('renders the personal badge', () => {
    render(<SourceCard source={{ ...base, scope: 'personal' }} />)
    expect(screen.getByText('sources.visibilityPersonal')).toBeInTheDocument()
  })
  it('renders the project badge', () => {
    render(<SourceCard source={{ ...base, scope: 'project' }} />)
    expect(screen.getByText('sources.visibilityProject')).toBeInTheDocument()
  })
  it('renders the company badge', () => {
    render(<SourceCard source={{ ...base, scope: 'company' }} />)
    expect(screen.getByText('sources.visibilityCompany')).toBeInTheDocument()
  })
})
```
> Adapt the `SourceCard` props shape/wrappers (it may need a router or query provider) to match how `SourceCard` is tested elsewhere in the repo; the load-bearing assertion is the badge text keyed off `source.scope`.

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- SourceCard.scope` — Expected: FAIL (no badge text).

- [ ] **Step 3: Write minimal implementation** — In `SourceCard.tsx`:
  - Ensure `Lock`, `Users`, `Building2` are imported from `lucide-react` (add to the existing lucide import block).
  - In the "Metadata badges" row (after the source-type `Badge`) add:
```tsx
            <Badge variant="outline" className="text-xs flex items-center gap-1">
              {source.scope === 'personal' && <Lock className="h-3 w-3" />}
              {source.scope === 'project' && <Users className="h-3 w-3" />}
              {source.scope === 'company' && <Building2 className="h-3 w-3" />}
              {source.scope === 'personal' && t('sources.visibilityPersonal')}
              {source.scope === 'project' && t('sources.visibilityProject')}
              {source.scope === 'company' && t('sources.visibilityCompany')}
            </Badge>
```
  - In the `areEqual` memo comparator (450-471) add a clause so a scope change re-renders the card:
```tsx
    prev.source.scope === next.source.scope &&
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- SourceCard.scope` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/sources/SourceCard.tsx frontend/src/components/sources/SourceCard.scope.test.tsx && git commit -m "P5 fe: scope badge on source card (3-scope)"`

---

### Task 15: Frontend — editable scope control on source detail

**Files:**
- Modify: `frontend/src/components/source/SourceDetailContent.tsx` (imports; header cluster; add `handleUpdateScope`)
- Test: `frontend/src/components/source/SourceDetailContent.scope.test.tsx`

**Interfaces:**
- Consumes: `useUpdateSource` (invalidates `['sources']` + toasts, per Task 12 hook); `source.owner`; the current user id from the P1 auth store (`useAuthStore((s) => s.userId)`), a best-effort UI gate — the server (Task 6) is the real gate.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/source/SourceDetailContent.scope.test.tsx`:
```tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { SourceDetailContent } from './SourceDetailContent'

const mutateAsync = vi.fn().mockResolvedValue({})
vi.mock('@/lib/hooks/use-sources', () => ({ useUpdateSource: () => ({ mutateAsync, isPending: false }) }))
vi.mock('@/lib/stores/auth-store', () => ({ useAuthStore: (sel: (s: { userId: string }) => unknown) => sel({ userId: 'user:me' }) }))
vi.mock('@/lib/api/sources', () => ({
  sourcesApi: {
    get: vi.fn().mockResolvedValue({
      id: 'source:1', title: 'T', scope: 'project', owner: 'user:me',
      topics: [], asset: null, full_text: '', embedded: false, embedded_chunks: 0,
      insights_count: 0, created: 'c', updated: 'u',
    }),
  },
}))

describe('SourceDetailContent scope control', () => {
  it('owner can change scope to company and it calls useUpdateSource', async () => {
    render(<SourceDetailContent sourceId="source:1" />)
    const control = await screen.findByRole('radio', { name: /company/i })
    fireEvent.click(control)
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ id: 'source:1', data: { scope: 'company' } }),
    )
  })
})
```
> Adapt the mock surface (SourceDetailContent has many collaborators). The load-bearing assertions: (a) an owner sees an **enabled** 3-option control that calls `useUpdateSource({ id, data: { scope } })`; (b) a non-owner sees a **read-only** badge (add a second test toggling the mocked `owner`/`userId`).

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- SourceDetailContent.scope` — Expected: FAIL (no scope control).

- [ ] **Step 3: Write minimal implementation** — In `SourceDetailContent.tsx`:
  - Add imports: `import { useUpdateSource } from '@/lib/hooks/use-sources'`, `import { useAuthStore } from '@/lib/stores/auth-store'`, `import { Lock, Users, Building2 } from 'lucide-react'`, `import { cn } from '@/lib/utils'`.
  - Inside the component: `const updateSource = useUpdateSource()` and `const currentUserId = useAuthStore((s) => s.userId)`.
  - Derive the gate + handler:
```tsx
  const canEditScope = !!currentUserId && source?.owner === currentUserId
  const handleUpdateScope = async (scope: 'personal' | 'project' | 'company') => {
    if (!source || source.scope === scope) return
    try {
      await updateSource.mutateAsync({ id: sourceId, data: { scope } })
      setSource({ ...source, scope })
      toast.success(t('sources.visibilityChanged'))
    } catch (err) {
      console.error('Failed to update source scope:', err)
      toast.error(t('sources.visibilityForbidden'))
      await fetchSource()
    }
  }
```
  - In the header cluster (right side, after the source-type `Badge`), render an editable 3-option control for the owner, else a read-only badge:
```tsx
            {canEditScope ? (
              <div className="flex items-center gap-1" role="radiogroup" aria-label={t('sources.visibilityLabel')}>
                {(['personal', 'project', 'company'] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={source.scope === value}
                    onClick={() => handleUpdateScope(value)}
                    className={cn(
                      'flex items-center gap-1 rounded-md border px-2 py-1 text-xs',
                      source.scope === value ? 'border-primary bg-primary/5' : 'border-input hover:bg-muted',
                    )}
                  >
                    {value === 'personal' && <Lock className="h-3 w-3" />}
                    {value === 'project' && <Users className="h-3 w-3" />}
                    {value === 'company' && <Building2 className="h-3 w-3" />}
                    {value === 'personal' && t('sources.visibilityPersonal')}
                    {value === 'project' && t('sources.visibilityProject')}
                    {value === 'company' && t('sources.visibilityCompany')}
                  </button>
                ))}
              </div>
            ) : (
              <Badge variant="outline" className="text-sm flex items-center gap-1">
                {source.scope === 'personal' && <Lock className="h-3 w-3" />}
                {source.scope === 'project' && <Users className="h-3 w-3" />}
                {source.scope === 'company' && <Building2 className="h-3 w-3" />}
                {source.scope === 'personal' && t('sources.visibilityPersonal')}
                {source.scope === 'project' && t('sources.visibilityProject')}
                {source.scope === 'company' && t('sources.visibilityCompany')}
              </Badge>
            )}
```
  > `visibilityChanged`/`visibilityForbidden` keys are referenced here so the locale unused-key test passes. `useAuthStore((s) => s.userId)` assumes P1's auth store exposes `userId`; if P1 named the field differently, adjust the selector. This is a best-effort **owner-only** UI gate; workspace/project admins also succeed server-side even though this simplified UI gate doesn't grant them the control — acceptable for P5, refine in a follow-up if admins need the in-page control too.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- SourceDetailContent.scope` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add frontend/src/components/source/SourceDetailContent.tsx frontend/src/components/source/SourceDetailContent.scope.test.tsx && git commit -m "P5 fe: editable 3-option scope control on source detail"`

---

### Task 16: i18n — visibility keys (3-scope) in all 14 locales + parity test

**Files:**
- Modify (real translations): `frontend/src/lib/locales/en-US/index.ts` (add to `sources` section)
- Modify (real translations): `frontend/src/lib/locales/{pt-BR,zh-CN,zh-TW,ja-JP,ru-RU,bn-IN}/index.ts` (same keys)
- Modify (English fallback — same keys, English values): `frontend/src/lib/locales/{it-IT,fr-FR,ca-ES,es-ES,de-DE,pl-PL,tr-TR}/index.ts`
- Test: `frontend/src/lib/locales/index.test.ts` (existing parity + unused-key tests — no code change needed; they now must pass with the new/renamed keys)

**Interfaces:**
- Produces: `sources.visibility`, `sources.visibilityPersonal`, `sources.visibilityProject`, `sources.visibilityCompany`, `sources.visibilityPersonalDesc`, `sources.visibilityProjectDesc`, `sources.visibilityCompanyDesc`, `sources.visibilityLabel`, `sources.visibilityChanged`, `sources.visibilityForbidden` in all 14 locales (real translations in the 7 enforced, English fallback in the other 7). Every key is already referenced by `t('...')` in Tasks 13-15 (satisfies the unused-key test). This supersedes the earlier 2-scope key set (`visibilityPrivate`/`visibilityPrivateDesc` are renamed to `visibilityPersonal`/`visibilityPersonalDesc`; `visibilityCompany`/`visibilityCompanyDesc` are new).

- [ ] **Step 1: Write the failing test** — No new test file; the existing `frontend/src/lib/locales/index.test.ts` is the gate. Run it now to confirm its current state.

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- locales/index` — Expected: FAIL with "Missing keys in <locale>: sources.visibilityPersonal, sources.visibilityCompany, ..." once the keys are referenced in Tasks 13-15's code but not yet present in every locale.

- [ ] **Step 3: Write minimal implementation** — Add the 10 keys inside the `sources: { ... }` object of each locale. **en-US** (`frontend/src/lib/locales/en-US/index.ts`):
```ts
    visibility: "Visibility",
    visibilityPersonal: "Personal",
    visibilityProject: "Project",
    visibilityCompany: "Company",
    visibilityPersonalDesc: "Only you, workspace owners/admins, and this project's admins can see this source.",
    visibilityProjectDesc: "All members of this project can see this source.",
    visibilityCompanyDesc: "All members of this workspace can see this source, across every project.",
    visibilityLabel: "Who can see this source?",
    visibilityChanged: "Source visibility updated",
    visibilityForbidden: "You don't have permission to change this source's visibility.",
```
  **pt-BR:**
```ts
    visibility: "Visibilidade",
    visibilityPersonal: "Pessoal",
    visibilityProject: "Projeto",
    visibilityCompany: "Empresa",
    visibilityPersonalDesc: "Somente você, os proprietários/administradores do espaço de trabalho e os administradores deste projeto podem ver esta fonte.",
    visibilityProjectDesc: "Todos os membros deste projeto podem ver esta fonte.",
    visibilityCompanyDesc: "Todos os membros deste espaço de trabalho podem ver esta fonte, em todos os projetos.",
    visibilityLabel: "Quem pode ver esta fonte?",
    visibilityChanged: "Visibilidade da fonte atualizada",
    visibilityForbidden: "Você não tem permissão para alterar a visibilidade desta fonte.",
```
  **zh-CN:**
```ts
    visibility: "可见性",
    visibilityPersonal: "个人",
    visibilityProject: "项目",
    visibilityCompany: "公司",
    visibilityPersonalDesc: "只有您、工作区所有者/管理员以及此项目的管理员可以查看此来源。",
    visibilityProjectDesc: "此项目的所有成员都可以查看此来源。",
    visibilityCompanyDesc: "此工作区的所有成员都可以查看此来源，涵盖所有项目。",
    visibilityLabel: "谁可以查看此来源？",
    visibilityChanged: "来源可见性已更新",
    visibilityForbidden: "您无权更改此来源的可见性。",
```
  **zh-TW:**
```ts
    visibility: "可見性",
    visibilityPersonal: "個人",
    visibilityProject: "專案",
    visibilityCompany: "公司",
    visibilityPersonalDesc: "只有您、工作區擁有者/管理員以及此專案的管理員可以檢視此來源。",
    visibilityProjectDesc: "此專案的所有成員都可以檢視此來源。",
    visibilityCompanyDesc: "此工作區的所有成員都可以檢視此來源，涵蓋所有專案。",
    visibilityLabel: "誰可以檢視此來源？",
    visibilityChanged: "來源可見性已更新",
    visibilityForbidden: "您無權變更此來源的可見性。",
```
  **ja-JP:**
```ts
    visibility: "公開範囲",
    visibilityPersonal: "個人",
    visibilityProject: "プロジェクト",
    visibilityCompany: "会社",
    visibilityPersonalDesc: "あなた、ワークスペースのオーナー/管理者、およびこのプロジェクトの管理者のみがこのソースを表示できます。",
    visibilityProjectDesc: "このプロジェクトのすべてのメンバーがこのソースを表示できます。",
    visibilityCompanyDesc: "このワークスペースのすべてのメンバーが、すべてのプロジェクトを横断してこのソースを表示できます。",
    visibilityLabel: "このソースを誰が閲覧できますか？",
    visibilityChanged: "ソースの公開範囲を更新しました",
    visibilityForbidden: "このソースの公開範囲を変更する権限がありません。",
```
  **ru-RU:**
```ts
    visibility: "Видимость",
    visibilityPersonal: "Личный",
    visibilityProject: "Проект",
    visibilityCompany: "Компания",
    visibilityPersonalDesc: "Только вы, владельцы/администраторы рабочего пространства и администраторы этого проекта могут видеть этот источник.",
    visibilityProjectDesc: "Все участники этого проекта могут видеть этот источник.",
    visibilityCompanyDesc: "Все участники этого рабочего пространства могут видеть этот источник, во всех проектах.",
    visibilityLabel: "Кто может видеть этот источник?",
    visibilityChanged: "Видимость источника обновлена",
    visibilityForbidden: "У вас нет прав на изменение видимости этого источника.",
```
  **bn-IN:**
```ts
    visibility: "দৃশ্যমানতা",
    visibilityPersonal: "ব্যক্তিগত",
    visibilityProject: "প্রকল্প",
    visibilityCompany: "কোম্পানি",
    visibilityPersonalDesc: "শুধুমাত্র আপনি, ওয়ার্কস্পেসের মালিক/অ্যাডমিনরা এবং এই প্রকল্পের অ্যাডমিনরা এই উৎসটি দেখতে পারেন।",
    visibilityProjectDesc: "এই প্রকল্পের সকল সদস্য এই উৎসটি দেখতে পারেন।",
    visibilityCompanyDesc: "এই ওয়ার্কস্পেসের সকল সদস্য, সকল প্রকল্প জুড়ে, এই উৎসটি দেখতে পারেন।",
    visibilityLabel: "এই উৎসটি কে দেখতে পারবে?",
    visibilityChanged: "উৎসের দৃশ্যমানতা আপডেট হয়েছে",
    visibilityForbidden: "এই উৎসের দৃশ্যমানতা পরিবর্তন করার অনুমতি আপনার নেই।",
```
- [ ] **Step 3b: Add the same keys (English fallback) to the 7 non-enforced locales** — the parity test iterates EVERY entry of `resources` except `en-US`, so the 7 non-enforced locales `it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR` MUST also carry all 10 `sources.visibility*` keys or `npm run test` fails on them. Add the exact same 10 keys to each of these 7 files' `sources` object using the **en-US English values** (silent en-US fallback is acceptable for non-enforced locales; a native pass can follow).

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- locales/index && npm run lint && npm run build` — Expected: PASS (parity: no missing/extra keys in any of the 14 locales; unused-key: all 10 keys referenced in Tasks 13-15; lint + build clean).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/locales && git commit -m "P5 fe: 3-scope visibility i18n keys in all 14 locales"`

---

## Final verification (run before opening the PR)
- [ ] Backend: `uv run pytest tests/ -q` — all P5 tests + the existing suite pass (fix any `Notebook.get`→`Project.get` / ctx-override fallout in `test_sources_api.py`, `test_search_api.py` as the failures direct).
- [ ] Backend lint/type: `ruff check . --fix` · `uv run python -m mypy .`
- [ ] Frontend: `cd frontend && npm run test && npm run lint && npm run build`.
- [ ] Manual smoke (real DB + worker): `make start-all`, then as user A create a `personal`-scope source in a project, and as user B (same workspace, project member, non-owner) confirm: it is absent from `GET /sources`, `GET /sources/{id}` → 404, `POST /search` for a token unique to that source → 0 source results, `/search/ask/simple` answer omits the token. As a `project`-scope source, all of these succeed for B. As a `company`-scope source, B can view it (including from a different project) but gets 403 attempting to PUT/DELETE it.

## Self-review (done — gaps closed inline)
1. **Spec coverage.** Every spec section maps to a task: migration 23 + backfill + search-fn rewrite (Task 1); `Source` model owner/scope/promoted_from + `get_project_ids` (Task 2); `PermissionContext` concrete shape (workspace-named) + 3-scope predicate (Tasks 3-4); Pydantic schemas + form parsing + `default_source_scope` fallback (Task 5); **every enumerated source-touching endpoint** — sources (Task 6), insights (7), source_chat (8), embedding (9), search + RAG leakage (10), context + `get_sources` filter (11); frontend types/api/hook (12), 3-option wizard selector (13), card badge (14), detail control (15), i18n ×14 (16). The role×scope×action matrix (3 columns now) is included as a reference block. Search leakage is closed at both the DB layer ($viewer_source_ids in migration 23) and the app layer (visible_source_ids threaded through `/search`, `/search/ask*`, and the ask graph), with the 3-scope resolution happening entirely in Python before the DB-layer allow-list is ever built.
2. **Placeholder scan.** No TBD/"handle edge cases"/"similar to Task N": every code step shows complete, runnable code or an exact, located edit; the ask-graph threading is fully specified; the `company`-scope "no extra membership lookup needed" simplification is explicitly justified (same-workspace ⟹ membership, because P6 only mints a workspace-scoped context for active members) rather than left as an assumption.
3. **Type consistency.** `PermissionContext(user_id, workspace_id, workspace_role)` + `async project_role()` used identically in Tasks 3, 4, 6-11 (and matches the v2-named shape P6's own revised draft already ships, per `ARCHITECTURE_BRIEF.md`). `visible_source_ids(ctx, project_id=None) -> List[str]` covers all 3 scopes in one query; routers convert to `RecordID` at the `id IN $visible_ids` / `$viewer_source_ids` boundary. `require_view_source`/`require_mutate_source` return a `Source`; response constructors add `scope` + `owner` consistently. Frontend `scope: 'personal' | 'project' | 'company'` is identical across types, api client, hooks, and all three components.
4. **Stated assumptions (no blanks).** Domain class is post-P3 `Project` (substitute `Notebook` if P3 kept an alias — confirmed the actual repo is still pre-P3 as of writing, so line numbers are cited against the current `Notebook`-named file); `get_auth_context`/`AuthContext` come from P1/P2 and are expected to carry `workspace_id`/`role` per the v2 brief (P2's own revision is out of scope here); the frontend owner-gate reads `useAuthStore((s) => s.userId)` from P1's auth store. Background podcast/context jobs intentionally run unfiltered (project-owner-initiated) — documented in Task 11. `promoted_from` is a schema-only hook (Task 2), never read/written by any endpoint or UI control in this phase — consistent with the spec's "Out of scope" section and `ARCHITECTURE_BRIEF.md`'s "build the SCHEMA HOOK only now."
5. **v2 rename completeness (self-check against the brief).** Grepped this plan's own vocabulary: no remaining `visibility` field name (renamed to `scope`, with "Visibility" kept only as the product-facing i18n label, matching how "Company" stays the UI word for a `kind="company"` workspace); no remaining `company_id`/`company_role` context fields (renamed `workspace_id`/`workspace_role`); `private` scope value renamed to `personal` everywhere; `company` added as the third scope value with its own row in both matrices and its own "no extra membership lookup" simplification; personal-workspace collapse is stated as a structural consequence (Task 3 test `test_personal_workspace_solo_owner_sees_all_scopes`) rather than special-cased code.
