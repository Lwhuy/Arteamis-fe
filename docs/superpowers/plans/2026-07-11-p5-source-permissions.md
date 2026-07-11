# P5 — Source Permissions (owner + visibility) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `owner` + `visibility` (`private`|`project`) to the `source` table and enforce a view/mutate permission check on every source-touching endpoint (sources, insights, source-chat, embedding, search/RAG, context) so a private source is never listed, read, downloaded, chatted-over, or surfaced in search to a user who may not see it.

**Architecture:** A new predicate module `api/source_permissions.py` owns all authorization logic (routers stay thin per `api/AGENTS.md`). It consumes a `PermissionContext` (user_id + company_id + company_role + async `project_role()`), which P5 ships as a concrete, working class and P6 later formalizes/relocates. Search leakage is closed at two layers: migration-23 rewrites `fn::text_search`/`fn::vector_search` to take a `$viewer_source_ids` allow-list, and the app layer computes that list from the caller's context. A `source` carries **no** denormalized `company` column — it inherits company through the `notebook` (project) it is referenced by via the `reference` edge.

**Tech Stack:** FastAPI, SurrealDB (hand-written SurrealQL migrations), Pydantic, LangGraph (ask RAG graph), Next.js 16 App Router, TanStack Query, react-hook-form + zod, i18next.

**Spec:** docs/superpowers/specs/2026-07-11-p5-source-permissions-design.md
**Depends on:** P1 (auth/users + `api/security.py:AuthContext`), P2 (company/membership/roles + `api/deps.py:get_auth_context`), P3 (`notebook`→`project` rename: domain class `Project` in `open_notebook/domain/notebook.py` with `table_name="notebook"`, `notebook.company`/`owner`, and the `project_member` table). **Branch:** feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB/AI call is awaited (no sync DB access).
- All frontend HTTP goes through the single axios `apiClient` (frontend/src/lib/api/client.ts) — never a 2nd instance.
- i18n MANDATORY: every UI string via `t('section.key')`; add the key to ALL 14 locales in the `resources` map under frontend/src/lib/locales/. The parity test (`frontend/src/lib/locales/index.test.ts`) iterates EVERY locale in `resources` and fails on any missing/extra key, and its unused-key test fails on any key not referenced by `t('...')` in source. The 7 enforced locales (en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN) get real translations; the other 7 (it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR) get English fallback values so `npm run test` stays green.
- New SurrealDB schema = new migration pair `open_notebook/database/migrations/23.surrealql` + `23_down.surrealql`, registered in `AsyncMigrationManager` (`open_notebook/database/async_migrate.py`). P5 = migration **23**. **Migration SQL comments must be on their own lines starting with `--`** — `AsyncMigration.from_file()` strips whole `--` lines but joins the rest with spaces, so an inline trailing `-- comment` would comment out the remainder of the joined single-line query.
- Physical SurrealDB table stays `notebook` (exposed as "project"); domain class `Project`; the `reference` edge is `RELATE source->reference->notebook` (`in`=source, `out`=notebook). Unchanged by P5.
- Backend tests: `uv run pytest tests/`. Frontend (in `frontend/`): `npm run lint`, `npm run test`, `npm run build`.

> **P3-rename note (read once):** This plan targets the **post-P3** codebase: the domain class is `Project` (file still `open_notebook/domain/notebook.py`, `table_name="notebook"`), and `api/routers/sources.py`/`context.py` import `Project` (not `Notebook`). The `Source`, `SourceInsight`, `SourceEmbedding`, `ChatSession` classes and the `reference`/`refers_to` edges are unchanged by P3. If your P3 kept a `Notebook = Project` alias instead of a clean rename, substitute `Notebook` for `Project` in the import lines below; nothing else changes.

> **PermissionContext ownership (read once):** P5 declares AND ships a concrete `PermissionContext` (Task 3) so P5 is independently runnable and testable **before P6 exists**. P6's spec ("Provides") formalizes/relocates the exact same interface — `user_id`, `company_id`, `company_role`, `async project_role(project_id) -> "admin"|"member"|None` with company-owner/admin→project-admin escalation. Keep the two in sync. There is no blank here: the working class lives in `api/source_permissions.py` until P6 moves it.

---

## Reference: role × visibility × action matrix

Roles (all relative to **the source's** company/projects): **Owner** = `source.owner` (uploader). **Company owner/admin** = `membership.role ∈ {owner,admin}` on the source's company. **Project admin** = `project_member.role='admin'` on a project referencing the source (company owner/admin escalate to project admin). **Project member** = `project_member.role='member'` on such a project. **Outsider** = authenticated user with no membership in the source's company / projects.

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
- Any project **member+** (member, project admin, company owner/admin) of a project in the active company may create a source there. On create: `owner = ctx.user_id`, `visibility =` chosen (wizard default `project`).
- A user with **no** membership in the target project → **403**.

### Deny-code rule (avoids existence leaks)
- **View/list/read/download/chat deny → 404** (`{"detail":"Source not found"}`) — a private source is indistinguishable from "doesn't exist".
- **Mutate deny where the caller CAN view → 403** (`{"detail":"You do not have permission to modify this source"}`).
- **Mutate deny where the caller CANNOT even view → 404**.
- Search/list simply omit non-visible rows (no error).
- Insights and embeddings have no independent permission — they inherit their parent source's rules.
- Chat sessions require **view** on the source; a member may create/read/delete their own chat sessions over a `project` source without mutate rights.

---

### Task 1: Migration 23 — `source.owner` + `source.visibility` + indexes + backfill + visibility-aware search functions

**Files:**
- Create: `open_notebook/database/migrations/23.surrealql`
- Create: `open_notebook/database/migrations/23_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py:98-189` (register 23 in `up_migrations` + `down_migrations`)
- Test: `tests/test_p5_migration_23.py`

**Interfaces:**
- Produces: `source.owner` (`option<record<user>>`), `source.visibility` (`string`, `'private'|'project'`, default `'project'`); rewritten `fn::text_search($query_text,$match_count,$sources,$show_notes,$viewer_source_ids)` and `fn::vector_search($query,$match_count,$sources,$show_notes,$min_similarity,$viewer_source_ids)`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_migration_23.py`:
```python
"""Migration 23 registration + content guards (P5 source permissions)."""
from pathlib import Path

from open_notebook.database.async_migrate import AsyncMigrationManager

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_23_registered():
    mgr = AsyncMigrationManager()
    # P5 is migration 23 → 23 up + 23 down migrations registered.
    assert len(mgr.up_migrations) == 23
    assert len(mgr.down_migrations) == 23


def test_migration_23_up_defines_owner_visibility_and_search_fns():
    sql = (MIGRATIONS / "23.surrealql").read_text()
    assert "DEFINE FIELD IF NOT EXISTS owner ON TABLE source" in sql
    assert "DEFINE FIELD IF NOT EXISTS visibility ON TABLE source" in sql
    assert "idx_source_visibility" in sql
    assert "idx_source_owner" in sql
    # search functions gain the $viewer_source_ids allow-list param
    assert "$viewer_source_ids: array<record<source>>" in sql
    assert sql.count("DEFINE FUNCTION IF NOT EXISTS fn::text_search") == 1
    assert sql.count("DEFINE FUNCTION IF NOT EXISTS fn::vector_search") == 1


def test_migration_23_down_removes_fields_and_restores_legacy_fns():
    sql = (MIGRATIONS / "23_down.surrealql").read_text()
    assert "REMOVE FIELD IF EXISTS visibility ON TABLE source" in sql
    assert "REMOVE FIELD IF EXISTS owner ON TABLE source" in sql
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

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_migration_23.py -q` — Expected: FAIL (`23.surrealql` missing → `FileNotFoundError`; `len(up_migrations) == 18`).

- [ ] **Step 3: Write minimal implementation** — Create `open_notebook/database/migrations/23.surrealql` (all comments on their own `--` lines; the `fn::` bodies are migration 4's `fn::text_search` and migration 9's `fn::vector_search`, each with `AND` filters added to the source-derived branches):
```surql
-- Migration 23: Source ownership + visibility (P5 source permissions)
-- owner = uploader; NONE for legacy/backfilled sources (no user existed pre-auth).
DEFINE FIELD IF NOT EXISTS owner ON TABLE source TYPE option<record<user>>;
-- visibility gate. 'private' = owner + company owner/admin + project admins only.
-- 'project' = all members of any project the source is referenced by.
DEFINE FIELD IF NOT EXISTS visibility ON TABLE source TYPE string ASSERT $value IN ['private', 'project'] DEFAULT 'project';
-- Backfill existing rows: pre-auth sources default to 'project', owner stays NONE.
-- A source inherits its company from its notebook (project) via the reference edge;
-- P3's migration 21 already backfilled every notebook to a company, so every legacy
-- source resolves to a company through its notebook.
UPDATE source SET visibility = 'project' WHERE visibility = NONE;
-- Indexes backing the visibility/owner filter used by list + search.
DEFINE INDEX IF NOT EXISTS idx_source_visibility ON TABLE source FIELDS visibility CONCURRENTLY;
DEFINE INDEX IF NOT EXISTS idx_source_owner ON TABLE source FIELDS owner CONCURRENTLY;
-- Visibility-aware search functions. $viewer_source_ids is the pre-computed set of
-- source ids the caller may see (owner/admin escalation resolved in Python). Every
-- source-derived branch is filtered by it; note branches are untouched (notes have
-- no per-source visibility in P5).
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
REMOVE INDEX IF EXISTS idx_source_visibility ON TABLE source;
REMOVE INDEX IF EXISTS idx_source_owner ON TABLE source;
REMOVE FIELD IF EXISTS visibility ON TABLE source;
REMOVE FIELD IF EXISTS owner ON TABLE source;
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
Then register both in `open_notebook/database/async_migrate.py`. Append to `self.up_migrations` (after the line loading `18.surrealql`, before the closing `]`):
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/19.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/21.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/22.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/23.surrealql"
            ),
```
and the matching `_down` entries appended to `self.down_migrations`:
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/19_down.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20_down.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/21_down.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/22_down.surrealql"
            ),
            AsyncMigration.from_file(
                "open_notebook/database/migrations/23_down.surrealql"
            ),
```
> **Ordering note:** 19–22 are registered by P1/P2/P3/P4. If those phases already added their entries, only append the two `23` lines. The test asserts exactly 23 entries — reconcile with what P1–P4 already registered.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_migration_23.py -q` — Expected: PASS (4 passed). Then boot once against a dev DB to confirm the SQL applies cleanly: `make database && make api` and check logs for `Migration successful. New version: 23` with no SurrealDB error.

- [ ] **Step 5: Commit** — `git add open_notebook/database/migrations/23.surrealql open_notebook/database/migrations/23_down.surrealql open_notebook/database/async_migrate.py tests/test_p5_migration_23.py && git commit -m "P5: migration 23 — source owner/visibility + visibility-aware search fns"`

---

### Task 2: `Source` domain model — `owner` + `visibility` fields + `get_project_ids()`

**Files:**
- Modify: `open_notebook/domain/notebook.py` (class `Source`, ~lines 391-431 for fields/validators, ~621-629 for `_prepare_save_data`; add `get_project_ids` method)
- Test: `tests/test_p5_source_model.py`

**Interfaces:**
- Produces: `Source.owner: Optional[Union[str, RecordID]]`, `Source.visibility: Literal["private","project"]`, `async Source.get_project_ids() -> List[str]`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_source_model.py`:
```python
"""Source owner/visibility fields + get_project_ids (P5)."""
from unittest.mock import AsyncMock, patch

import pytest
from surrealdb import RecordID

from open_notebook.domain.notebook import Source


def test_visibility_defaults_to_project():
    s = Source(title="t")
    assert s.visibility == "project"
    assert s.owner is None


def test_visibility_accepts_private():
    s = Source(title="t", visibility="private")
    assert s.visibility == "private"


def test_owner_string_coerced_to_record_id():
    s = Source(title="t", owner="user:abc")
    assert isinstance(s.owner, RecordID)
    assert str(s.owner) == "user:abc"


def test_owner_none_passthrough():
    s = Source(title="t", owner=None)
    assert s.owner is None


def test_prepare_save_data_coerces_owner_and_keeps_visibility():
    s = Source(title="t", owner="user:abc", visibility="private")
    data = s._prepare_save_data()
    assert isinstance(data["owner"], RecordID)
    assert data["visibility"] == "private"


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

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_source_model.py -q` — Expected: FAIL (`Source` has no `visibility`/`owner` field; `get_project_ids` missing).

- [ ] **Step 3: Write minimal implementation** — In `open_notebook/domain/notebook.py`, class `Source`, add the two fields after the existing `command` field (after line 402) and an `owner` validator after `parse_command` (after line 410). First ensure `Literal` is imported (it already is, line 5). Add fields:
```python
    command: Optional[Union[str, RecordID]] = Field(
        default=None, description="Link to surreal-commands processing job"
    )
    owner: Optional[Union[str, RecordID]] = Field(
        default=None, description="Uploader user; NONE for legacy pre-auth sources"
    )
    visibility: Literal["private", "project"] = "project"
```
Add the `owner` validator (mirrors `parse_command`) right after the `parse_command` method:
```python
    @field_validator("owner", mode="before")
    @classmethod
    def parse_owner(cls, value):
        """Coerce a str owner id to RecordID; pass through None."""
        if isinstance(value, str) and value:
            return ensure_record_id(value)
        return value
```
Extend `_prepare_save_data` (currently lines 621-629) to coerce `owner`:
```python
    def _prepare_save_data(self) -> dict:
        """Override to ensure command/owner fields are RecordID format for the DB."""
        data = super()._prepare_save_data()
        if data.get("command") is not None:
            data["command"] = ensure_record_id(data["command"])
        if data.get("owner") is not None:
            data["owner"] = ensure_record_id(data["owner"])
        return data
```
Add `get_project_ids` as a method on `Source` (e.g. after `get_insights`):
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
> `owner` is not None-only-saved: `ObjectModel._prepare_save_data` drops keys whose value is `None` unless listed in `nullable_fields`. `owner=None` (legacy) is therefore simply omitted on save, which is correct — the DB field is `option<record<user>>`.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_source_model.py -q` — Expected: PASS (6 passed).

- [ ] **Step 5: Commit** — `git add open_notebook/domain/notebook.py tests/test_p5_source_model.py && git commit -m "P5: Source model owner/visibility fields + get_project_ids"`

---

### Task 3: `PermissionContext` + `get_permission_context` + `can_view_source` / `can_mutate_source`

**Files:**
- Create: `api/source_permissions.py`
- Test: `tests/test_p5_predicate.py`

**Interfaces:**
- Consumes: `Source.get_project_ids()` (Task 2); `api.deps.get_auth_context -> AuthContext(user_id, company_id, role)` (P2); `api.security.AuthContext` (P1).
- Produces: `class PermissionContext(user_id, company_id, company_role)` with `async project_role(project_id) -> Optional[str]`; `async get_permission_context(auth) -> PermissionContext`; `async can_view_source(source, ctx) -> bool`; `async can_mutate_source(source, ctx) -> bool`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_predicate.py`:
```python
"""Permission predicate logic (P5). Uses a hand-built PermissionContext; the
source's project ids, company resolution, and project_role are mocked."""
from unittest.mock import AsyncMock, patch

import pytest

from api.source_permissions import (
    PermissionContext,
    can_mutate_source,
    can_view_source,
)
from open_notebook.domain.notebook import Source


def _ctx(user="user:u1", company="company:c1", role="member"):
    return PermissionContext(user_id=user, company_id=company, company_role=role)


def _source(owner=None, visibility="project", sid="source:s1"):
    return Source(id=sid, title="t", owner=owner, visibility=visibility)


@pytest.fixture
def in_company():
    # every predicate first resolves the source's company via the reference edge
    with patch(
        "api.source_permissions.repo_query",
        new=AsyncMock(return_value=["company:c1"]),
    ) as m:
        yield m


@pytest.mark.asyncio
async def test_owner_can_view_and_mutate_private(in_company):
    ctx = _ctx()
    src = _source(owner="user:u1", visibility="private")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value=None)
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_company_admin_can_view_and_mutate_others_private(in_company):
    ctx = _ctx(user="user:u2", role="admin")
    src = _source(owner="user:u1", visibility="private")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="admin")
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_project_admin_can_view_and_mutate_private(in_company):
    ctx = _ctx(user="user:u2", role="member")
    src = _source(owner="user:u1", visibility="private")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="admin")
        assert await can_view_source(src, ctx) is True
        assert await can_mutate_source(src, ctx) is True


@pytest.mark.asyncio
async def test_member_view_project_but_not_private_and_never_mutate(in_company):
    ctx = _ctx(user="user:u2", role="member")
    with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
        ctx.project_role = AsyncMock(return_value="member")
        assert await can_view_source(_source(owner="user:u1", visibility="project"), ctx) is True
        assert await can_view_source(_source(owner="user:u1", visibility="private"), ctx) is False
        assert await can_mutate_source(_source(owner="user:u1", visibility="project"), ctx) is False


@pytest.mark.asyncio
async def test_outsider_other_company_denied():
    ctx = _ctx(user="user:x", company="company:OTHER", role="member")
    src = _source(owner="user:u1", visibility="project")
    with patch("api.source_permissions.repo_query", new=AsyncMock(return_value=["company:c1"])):
        with patch.object(Source, "get_project_ids", new=AsyncMock(return_value=["notebook:p1"])):
            ctx.project_role = AsyncMock(return_value=None)
            assert await can_view_source(src, ctx) is False
            assert await can_mutate_source(src, ctx) is False
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_predicate.py -q` — Expected: FAIL (`ModuleNotFoundError: api.source_permissions`).

- [ ] **Step 3: Write minimal implementation** — Create `api/source_permissions.py`:
```python
"""Source visibility/permission predicate (P5).

All source authorization lives here so routers stay thin (api/AGENTS.md).

PermissionContext is shipped concrete by P5 so this module is runnable/testable
before P6 exists. P6 formalizes/relocates the SAME interface (user_id,
company_id, company_role, async project_role) — keep them in sync.
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
    but not its shape."""

    def __init__(self, user_id: str, company_id: str, company_role: str):
        self.user_id = user_id
        self.company_id = company_id
        self.company_role = company_role

    async def project_role(self, project_id: str) -> Optional[str]:
        """Caller's role on a project: 'admin'|'member'|None. Company owner/admin
        escalate to project admin everywhere in their company."""
        if self.company_role in ("owner", "admin"):
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
        company_id=str(auth.company_id),
        company_role=str(auth.role),
    )


async def _source_companies(source: Source) -> List[str]:
    """Company ids owning this source, resolved via its referencing projects."""
    rows = await repo_query(
        "SELECT VALUE out.company FROM reference WHERE in = $source",
        {"source": ensure_record_id(source.id)},
    )
    return [str(c) for c in rows if c is not None]


async def _in_active_company(source: Source, ctx: PermissionContext) -> bool:
    return ctx.company_id in await _source_companies(source)


async def can_view_source(source: Source, ctx: PermissionContext) -> bool:
    # Company isolation (belt-and-braces with P6): must be referenced by a project
    # in the caller's active company, else treat as not-found.
    if not await _in_active_company(source, ctx):
        return False
    # Owner always sees their own source.
    if source.owner is not None and str(source.owner) == ctx.user_id:
        return True
    # Company owner/admin sees everything in the company, including private.
    if ctx.company_role in ("owner", "admin"):
        return True
    project_ids = await source.get_project_ids()
    # Project admin of any referencing project sees everything in it.
    for pid in project_ids:
        if await ctx.project_role(pid) == "admin":
            return True
    # 'project' visibility: any member (admin/member) of a referencing project.
    if source.visibility == "project":
        for pid in project_ids:
            if await ctx.project_role(pid) in ("admin", "member"):
                return True
    return False


async def can_mutate_source(source: Source, ctx: PermissionContext) -> bool:
    if not await _in_active_company(source, ctx):
        return False
    if source.owner is not None and str(source.owner) == ctx.user_id:
        return True
    if ctx.company_role in ("owner", "admin"):
        return True
    for pid in await source.get_project_ids():
        if await ctx.project_role(pid) == "admin":
            return True
    return False
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_predicate.py -q` — Expected: PASS (5 passed).

- [ ] **Step 5: Commit** — `git add api/source_permissions.py tests/test_p5_predicate.py && git commit -m "P5: PermissionContext + can_view_source/can_mutate_source predicate"`

---

### Task 4: `require_view_source` / `require_mutate_source` + `visible_source_ids`

**Files:**
- Modify: `api/source_permissions.py` (append the three functions)
- Test: `tests/test_p5_require_and_visible.py`

**Interfaces:**
- Produces: `async require_view_source(source_id, ctx) -> Source` (404 on view-deny/missing); `async require_mutate_source(source_id, ctx) -> Source` (404 if not viewable, 403 if viewable-but-not-mutable); `async visible_source_ids(ctx, project_id=None) -> List[str]` (deduped source ids, single parameterized query, backs list + search filtering).

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
    return PermissionContext(user_id="user:u1", company_id="company:c1", company_role=role)


@pytest.mark.asyncio
async def test_require_view_missing_is_404():
    with patch.object(Source, "get", new=AsyncMock(side_effect=NotFoundError("x"))):
        with pytest.raises(HTTPException) as e:
            await require_view_source("source:missing", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_require_view_deny_is_404():
    src = Source(id="source:1", title="t", owner="user:z", visibility="private")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as e:
                await require_view_source("source:1", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_require_mutate_viewable_but_not_mutable_is_403():
    src = Source(id="source:1", title="t", owner="user:z", visibility="project")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=True)):
            with patch.object(sp, "can_mutate_source", new=AsyncMock(return_value=False)):
                with pytest.raises(HTTPException) as e:
                    await require_mutate_source("source:1", _ctx())
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_require_mutate_not_viewable_is_404():
    src = Source(id="source:1", title="t", owner="user:z", visibility="private")
    with patch.object(Source, "get", new=AsyncMock(return_value=src)):
        with patch.object(sp, "can_view_source", new=AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as e:
                await require_mutate_source("source:1", _ctx())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_visible_source_ids_admin_branch_is_company_wide_and_deduped():
    ctx = _ctx(role="admin")
    with patch(
        "api.source_permissions.repo_query",
        new=AsyncMock(return_value=["source:a", "source:a", "source:b"]),
    ) as m:
        ids = await visible_source_ids(ctx)
    assert ids == ["source:a", "source:b"]
    assert "in.owner" not in m.call_args.args[0]  # admin branch = no per-user predicate


@pytest.mark.asyncio
async def test_visible_source_ids_member_branch_has_visibility_predicate():
    ctx = _ctx(role="member")
    with patch(
        "api.source_permissions.repo_query", new=AsyncMock(return_value=[])
    ) as m:
        await visible_source_ids(ctx, project_id="notebook:p1")
    q = m.call_args.args[0]
    assert "in.owner = $user" in q
    assert "in.visibility = 'project'" in q
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
    """Source ids in the caller's company (optionally one project) the caller may
    VIEW. Single parameterized query (no N+1); backs GET /sources + search filters.

    Company owner/admin: every source in the company. Otherwise: owner's sources,
    plus 'project' sources of any project they belong to, plus every source of any
    project they admin.
    """
    params = {
        "company": ensure_record_id(ctx.company_id),
        "user": ensure_record_id(ctx.user_id),
    }
    project_filter = ""
    if project_id is not None:
        params["project"] = ensure_record_id(project_id)
        project_filter = " AND out = $project"

    if ctx.company_role in ("owner", "admin"):
        query = (
            "SELECT VALUE in FROM reference "
            "WHERE out.company = $company" + project_filter
        )
    else:
        query = (
            "SELECT VALUE in FROM reference "
            "WHERE out.company = $company" + project_filter + " AND ("
            "in.owner = $user "
            "OR out IN (SELECT VALUE project FROM project_member "
            "WHERE user = $user AND role = 'admin' AND status = 'active') "
            "OR (in.visibility = 'project' AND out IN (SELECT VALUE project "
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

- [ ] **Step 5: Commit** — `git add api/source_permissions.py tests/test_p5_require_and_visible.py && git commit -m "P5: require_view/mutate_source + visible_source_ids"`

---

### Task 5: Pydantic schemas — visibility on create/update/response + form parsing

**Files:**
- Modify: `api/models.py` (`SourceCreate` ~297, `SourceUpdate` ~348, `SourceResponse` ~353, `SourceListResponse` ~372)
- Modify: `api/routers/sources.py` (`parse_source_form_data` ~141-209)
- Test: `tests/test_p5_models.py`

**Interfaces:**
- Produces: `SourceCreate.visibility: Literal["private","project"]="project"`; `SourceUpdate.visibility: Optional[Literal["private","project"]]=None`; `SourceResponse`/`SourceListResponse` gain `visibility: str = "project"` and `owner: Optional[str] = None`.

- [ ] **Step 1: Write the failing test** — `tests/test_p5_models.py`:
```python
import pytest
from pydantic import ValidationError

from api.models import SourceCreate, SourceListResponse, SourceResponse, SourceUpdate


def test_source_create_default_visibility():
    assert SourceCreate(type="text", content="x").visibility == "project"


def test_source_create_rejects_bad_visibility():
    with pytest.raises(ValidationError):
        SourceCreate(type="text", content="x", visibility="secret")


def test_source_update_visibility_optional():
    assert SourceUpdate().visibility is None
    assert SourceUpdate(visibility="private").visibility == "private"


def test_responses_carry_visibility_and_owner():
    r = SourceResponse(
        id="source:1", title="t", topics=[], asset=None, full_text=None,
        embedded=False, embedded_chunks=0, created="c", updated="u",
        visibility="private", owner="user:u1",
    )
    assert r.visibility == "private" and r.owner == "user:u1"
    lr = SourceListResponse(
        id="source:1", title="t", topics=[], asset=None, embedded=False,
        embedded_chunks=0, insights_count=0, created="c", updated="u",
    )
    assert lr.visibility == "project" and lr.owner is None
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p5_models.py -q` — Expected: FAIL (`SourceCreate` has no `visibility`).

- [ ] **Step 3: Write minimal implementation** — In `api/models.py`:
  - `SourceCreate`: add after the `async_processing` field (line 326):
```python
    visibility: Literal["private", "project"] = Field(
        "project", description="Source visibility: private or project"
    )
```
  - `SourceUpdate`: add after `topics` (line 350):
```python
    visibility: Optional[Literal["private", "project"]] = Field(
        None, description="Source visibility: private or project"
    )
```
  - `SourceResponse`: add after `notebooks` (line 369):
```python
    visibility: str = "project"
    owner: Optional[str] = None
```
  - `SourceListResponse`: add after `processing_info` (line 386):
```python
    visibility: str = "project"
    owner: Optional[str] = None
```
  (`Literal` and `Optional` are already imported in `api/models.py`.)
  - In `api/routers/sources.py`, `parse_source_form_data`: add a `visibility` form param and pass it into `SourceCreate`. Change the signature (add after `async_processing`, line 151):
```python
    async_processing: str = Form("false"),  # Accept as string, convert to bool
    visibility: str = Form("project"),
    file: Optional[UploadFile] = File(None),
```
  and in the `SourceCreate(...)` construction (after `async_processing=async_processing_bool,`, line 199) add:
```python
            async_processing=async_processing_bool,
            visibility=visibility,
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_models.py -q` — Expected: PASS (4 passed).

- [ ] **Step 5: Commit** — `git add api/models.py api/routers/sources.py tests/test_p5_models.py && git commit -m "P5: visibility on Source create/update/response schemas + form parsing"`

---

### Task 6: Wire the predicate into `api/routers/sources.py` (create, list, get, download, status, update, retry, delete, insights)

**Files:**
- Modify: `api/routers/sources.py` (imports; every endpoint)
- Test: `tests/test_p5_sources_router.py`

**Interfaces:**
- Consumes: `get_permission_context`, `require_view_source`, `require_mutate_source`, `visible_source_ids` (Tasks 3-4); `PermissionContext.project_role` (Task 3).

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
    return PermissionContext(user_id="user:u1", company_id="company:c1", company_role="member")


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
    # visible_source_ids returns an empty allow-list → no rows, and the id filter
    # param is threaded into the query.
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
    # ctx.project_role returns None → caller is not a member of the target project → 403
    ctx.project_role = AsyncMock(return_value=None)
    resp = client.post(
        "/api/sources",
        data={"type": "text", "content": "hi", "notebooks": '["notebook:p1"]', "visibility": "private"},
    )
    assert resp.status_code == 403
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

        # Allow-list of source ids the caller may view (scopes to active company).
        visible = await visible_source_ids(ctx, notebook_id)
        visible_ids = [ensure_record_id(s) for s in visible]

        if notebook_id:
            notebook = await Project.get(notebook_id)
            if not notebook:
                raise HTTPException(status_code=404, detail="Notebook not found")
            query = f"""
                SELECT id, asset, created, title, updated, topics, command, visibility, owner,
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
                SELECT id, asset, created, title, updated, topics, command, visibility, owner,
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
        # SourceListResponse(...): visibility=row.get("visibility") or "project",
        # owner=str(row["owner"]) if row.get("owner") else None,
```
  In the `SourceListResponse(...)` constructor inside the loop, add the two fields:
```python
                    processing_info=processing_info,
                    visibility=row.get("visibility") or "project",
                    owner=str(row["owner"]) if row.get("owner") else None,
```

  **`create_source`** — add `ctx` param and enforce project membership + stamp owner/visibility on both paths. Change signature:
```python
async def create_source(
    form_data: tuple[SourceCreate, Optional[UploadFile]] = Depends(parse_source_form_data),
    ctx: PermissionContext = Depends(get_permission_context),
):
```
  Replace the notebook-existence loop (lines 364-370) with a membership+company check:
```python
        # Verify target projects exist AND the caller is a member (member+) of each,
        # in the active company. Non-member → 403; wrong company / missing → 404.
        for notebook_id in source_data.notebooks or []:
            project = await Project.get(notebook_id)
            if not project:
                raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
            if str(getattr(project, "company", None)) != ctx.company_id:
                raise HTTPException(status_code=404, detail=f"Notebook {notebook_id} not found")
            if await ctx.project_role(notebook_id) not in ("admin", "member"):
                raise HTTPException(status_code=403, detail="You are not a member of this project")
```
  In the ASYNC path `Source(...)` construction (line 448) and the SYNC path `Source(...)` (line 528), stamp owner + visibility before `await source.save()`:
```python
            source = Source(
                title=source_data.title or "Processing...",
                topics=[],
                asset=source_asset,
                owner=ctx.user_id,
                visibility=source_data.visibility,
            )
```
  (sync path is identical minus `asset=source_asset`; add `owner=ctx.user_id, visibility=source_data.visibility` there too.) Add `visibility`/`owner` to the async-path `SourceResponse(...)` (line 487) and the sync-path `SourceResponse(...)` (line 587):
```python
                    processing_info={"async": True, "queued": True},
                    visibility=source_data.visibility,
                    owner=ctx.user_id,
```
```python
                    updated=str(processed_source.updated),
                    visibility=processed_source.visibility,
                    owner=str(processed_source.owner) if processed_source.owner else None,
```
  `create_source_json` (line 646) — add `ctx` and forward it:
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
  `check_source_file` (line 757) and `download_source_file` (line 770) — add `ctx: PermissionContext = Depends(get_permission_context)` and pass it: `await _resolve_source_file(source_id, ctx)`.

  **`get_source`** (line 693) — add `ctx` and replace the load+null-check (lines 697-699) with the predicate:
```python
async def get_source(source_id: str, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        source = await require_view_source(source_id, ctx)
        await _stamp_source_view(source.id or source_id)
        # ... existing status/embedded/notebooks logic unchanged ...
```
  Add to the returned `SourceResponse(...)` (line 725): `visibility=source.visibility, owner=str(source.owner) if source.owner else None,`.

  **`get_source_status`** (line 787) — add `ctx` and replace the load (lines 792-794): `source = await require_view_source(source_id, ctx)`.

  **`update_source`** (line 847) — add `ctx`, replace the load (lines 851-853) with `source = await require_mutate_source(source_id, ctx)`, and apply visibility:
```python
async def update_source(source_id: str, source_update: SourceUpdate, ctx: PermissionContext = Depends(get_permission_context)):
    try:
        source = await require_mutate_source(source_id, ctx)
        if source_update.title is not None:
            source.title = source_update.title
        if source_update.topics is not None:
            source.topics = source_update.topics
        if source_update.visibility is not None:
            source.visibility = source_update.visibility
        await source.save()
        # ... existing response build ...
```
  Add to the returned `SourceResponse(...)` (line 864): `visibility=source.visibility, owner=str(source.owner) if source.owner else None,`.

  **`retry_source_processing`** (line 889) — add `ctx`, replace the load (lines 894-896) with `source = await require_mutate_source(source_id, ctx)`. Add `visibility=source.visibility, owner=str(source.owner) if source.owner else None,` to its `SourceResponse(...)` (line 983).

  **`delete_source`** (line 1018) — add `ctx`, replace the load (lines 1022-1024) with `source = await require_mutate_source(source_id, ctx)`.

  **`get_source_insights`** (line 1036) — add `ctx`, replace the load (lines 1040-1042) with `source = await require_view_source(source_id, ctx)`.

  **`create_source_insight`** (line 1068) — add `ctx`, replace the load (lines 1078-1080) with `source = await require_mutate_source(source_id, ctx)` (generating insights writes to the source).

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_sources_router.py tests/test_sources_api.py -q` — Expected: PASS. (Existing `tests/test_sources_api.py` mocks `Notebook.get`/`Source.get` — update those patches to `Project.get` and add `app.dependency_overrides[get_permission_context]` in its `client` fixture if it exercises the now-ctx-dependent endpoints; adjust as the failures direct.)

- [ ] **Step 5: Commit** — `git add api/routers/sources.py tests/test_p5_sources_router.py tests/test_sources_api.py && git commit -m "P5: enforce view/mutate on all sources.py endpoints + owner/visibility on create"`

---

### Task 7: Wire the predicate into `api/routers/insights.py`

**Files:**
- Modify: `api/routers/insights.py`
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
    ctx = PermissionContext(user_id="user:u1", company_id="company:c1", company_role="member")
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
  `get_insight` — add `ctx`, and after `source = await insight.get_source()`, view-check:
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
  `delete_insight` — add `ctx`, resolve source and mutate-check before delete:
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
  `save_insight_as_note` — add `ctx`, view-check the insight's source before reading it into a note:
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

- [ ] **Step 5: Commit** — `git add api/routers/insights.py tests/test_p5_insights_router.py && git commit -m "P5: enforce source visibility on insights endpoints"`

---

### Task 8: Wire the predicate into `api/routers/source_chat.py`

**Files:**
- Modify: `api/routers/source_chat.py` (all 6 endpoints replace `Source.get(full_source_id)` load with `require_view_source`)
- Test: `tests/test_p5_source_chat_router.py`

**Interfaces:**
- Consumes: `get_permission_context`, `require_view_source`. All chat endpoints require **view** on the source (a member may manage their own sessions over a `project` source without mutate rights).

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
    ctx = PermissionContext(user_id="user:u1", company_id="company:c1", company_role="member")
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
  In each of the 6 endpoints (`create_source_chat_session`, `get_source_chat_sessions`, `get_source_chat_session`, `update_source_chat_session`, `delete_source_chat_session`, `send_message_to_source_chat`) add `ctx: PermissionContext = Depends(get_permission_context)` to the signature and replace the block:
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
- Modify: `api/routers/embedding.py` (`embed_content`, `item_type == "source"` branches — both async and domain paths)
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
    ctx = PermissionContext(user_id="user:u1", company_id="company:c1", company_role="member")
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
  Add `ctx: PermissionContext = Depends(get_permission_context)` to `embed_content`. In the async path, before submitting the `embed_source` command (inside `if item_type == "source":`, line 43), add the check; and in the domain path before `source_item.vectorize()` (line 81). Simplest: check once at the top, right after `item_type` is validated (after line 31):
```python
        # Source embedding writes derived data → require mutate on the source.
        if item_type == "source":
            await require_mutate_source(item_id, ctx)
```
  Place this immediately after the `if item_type not in ["source", "note"]:` guard so it covers both the async and domain branches. The `note` branch is untouched.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p5_embedding_router.py -q` — Expected: PASS (1 passed).

- [ ] **Step 5: Commit** — `git add api/routers/embedding.py tests/test_p5_embedding_router.py && git commit -m "P5: require mutate on POST /embed for sources"`

---

### Task 10: Search-leakage fix — thread `viewer_source_ids` through domain search + `search.py` + ask RAG graph

**Files:**
- Modify: `open_notebook/domain/notebook.py` (`text_search` ~756, `vector_search` ~798 — add `viewer_source_ids` param + pass to `fn::`)
- Modify: `api/routers/search.py` (3 endpoints get `ctx`; compute + pass `viewer_source_ids`; thread into ask-graph `configurable`)
- Modify: `open_notebook/graphs/ask.py` (`provide_answer` reads `viewer_source_ids` from `config.configurable`)
- Test: `tests/test_p5_search_leakage.py`

**Interfaces:**
- Consumes: `visible_source_ids(ctx, None)` (Task 4), `get_permission_context`.
- Produces: `text_search(..., viewer_source_ids=None)`, `vector_search(..., viewer_source_ids=None)` — both normalize ids to `RecordID` and forward to the migration-23 `fn::` allow-list param.

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
    ctx = PermissionContext(user_id="user:u1", company_id="company:c1", company_role="member")
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
  In `open_notebook/domain/notebook.py`, update `text_search` (line 756) and `vector_search` (line 798):
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
  `search_knowledge_base` (line 17) — add `ctx`, compute allow-list, pass to both search calls:
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
  `ask_knowledge_base` (line 113) and `ask_knowledge_base_simple` (line 165) — add `ctx`, compute `viewer_ids`, and add it to the graph `configurable` dict. For the streaming endpoint, pass `viewer_ids` into `stream_ask_response` and its `configurable`; for the simple endpoint add it to the inline `configurable`:
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
  Update `stream_ask_response` (line 61) to accept and forward `viewer_source_ids`:
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
  In `open_notebook/graphs/ask.py`, `provide_answer` (line 98) — read the allow-list from config and pass to `vector_search`:
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

- [ ] **Step 5: Commit** — `git add open_notebook/domain/notebook.py api/routers/search.py open_notebook/graphs/ask.py tests/test_p5_search_leakage.py tests/test_search_api.py && git commit -m "P5: thread viewer_source_ids through search + ask RAG graph (leakage fix)"`

---

### Task 11: Visibility-filtered project context — `context.py` + `Project.get_sources()`

**Files:**
- Modify: `open_notebook/domain/notebook.py` (`Project.get_sources` ~31 — add optional `viewer_source_ids` filter)
- Modify: `api/routers/context.py` (`get_notebook_context` — compute allow-list, pass to `get_sources`; view-check per-source in the explicit-config branch)
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

- [ ] **Step 3: Write minimal implementation** — In `open_notebook/domain/notebook.py`, class `Project`, update `get_sources` (line 31):
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
  In `api/routers/context.py`, add imports and enforce visibility:
```python
from fastapi import APIRouter, Depends, HTTPException

from api.source_permissions import (
    PermissionContext, get_permission_context, require_view_source, visible_source_ids,
)
from open_notebook.domain.notebook import Note, Project, Source, SourceInsight
```
  `get_notebook_context` (line 12) — add `ctx`, replace `Notebook.get` with `Project.get`, compute the allow-list once, and use it in both branches:
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

- [ ] **Step 5: Commit** — `git add open_notebook/domain/notebook.py api/routers/context.py tests/test_p5_context_router.py && git commit -m "P5: filter project context assembly by source visibility"`

---

### Task 12: Frontend — types + API client + hook plumbing for `visibility`

**Files:**
- Modify: `frontend/src/lib/types/api.ts` (`SourceListResponse` ~21, `SourceDetailResponse` ~41, `CreateSourceRequest` ~96, `UpdateSourceRequest` ~120)
- Modify: `frontend/src/lib/api/sources.ts` (`create` ~32, `update` ~71)
- Test: `frontend/src/lib/api/sources.visibility.test.ts`

**Interfaces:**
- Produces: `visibility?: 'private' | 'project'` on create/update requests; `visibility: 'private' | 'project'` + `owner?: string | null` on list/detail responses; `sourcesApi.create` appends `visibility` to `FormData`; `sourcesApi.update` includes `visibility` in its JSON body.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/api/sources.visibility.test.ts`:
```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { sourcesApi } from './sources'
import { apiClient } from './client'

vi.mock('./client', () => ({
  apiClient: { post: vi.fn().mockResolvedValue({ data: {} }), put: vi.fn().mockResolvedValue({ data: {} }) },
}))

describe('sourcesApi visibility', () => {
  beforeEach(() => vi.clearAllMocks())

  it('appends visibility to create FormData (default project)', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi', visibility: 'private' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('visibility')).toBe('private')
  })

  it('defaults create visibility to project when omitted', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('visibility')).toBe('project')
  })

  it('includes visibility in update body', async () => {
    await sourcesApi.update('source:1', { visibility: 'project' })
    expect(apiClient.put).toHaveBeenCalledWith('/sources/source:1', { visibility: 'project' })
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (in `frontend/`): `npm run test -- sources.visibility` — Expected: FAIL (type error / `visibility` not appended).

- [ ] **Step 3: Write minimal implementation** —
  In `frontend/src/lib/types/api.ts`:
  - `SourceListResponse` — add after `processing_info?` (line 38): `visibility: 'private' | 'project'` and `owner?: string | null`.
  - `CreateSourceRequest` — add after `async_processing?` (line 111): `visibility?: 'private' | 'project'`.
  - `UpdateSourceRequest` — add after `content?` (line 124): `visibility?: 'private' | 'project'`.
  - `SourceDetailResponse extends SourceListResponse`, and `SourceResponse = SourceDetailResponse`, so both inherit `visibility`/`owner` automatically — no separate edit.
  In `frontend/src/lib/api/sources.ts`, `create` — after the `async_processing` append (line 65) add:
```ts
    formData.append('visibility', data.visibility ?? 'project')
```
  `update` already sends `data` verbatim as the JSON body (`apiClient.put('/sources/${id}', data)`), so `visibility` flows through with no change — the test asserts this.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- sources.visibility` — Expected: PASS (3 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/types/api.ts frontend/src/lib/api/sources.ts frontend/src/lib/api/sources.visibility.test.ts && git commit -m "P5 fe: visibility on source types + api client"`

---

### Task 13: Frontend — visibility selector in the add-source wizard

**Files:**
- Modify: `frontend/src/components/sources/AddSourceDialog.tsx` (`createSourceSchema` ~30, `defaultValues` ~132, `submitSingleSource` ~301, `submitBatch` ~353)
- Modify: `frontend/src/components/sources/steps/ProcessingStep.tsx` (local `CreateSourceFormData` ~11, add a Visibility `FormSection`)
- Test: `frontend/src/components/sources/AddSourceDialog.visibility.test.tsx`

**Interfaces:**
- Produces: `visibility` field on the wizard form (default `'project'`), threaded into every `createRequest`; a two-option segmented control rendered in `ProcessingStep`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/sources/AddSourceDialog.visibility.test.tsx`:
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

describe('AddSourceDialog visibility', () => {
  it('submits a text source with the selected visibility', async () => {
    render(<AddSourceDialog open onOpenChange={() => {}} defaultNotebookId="notebook:p1" />)
    // fill the text content, advance to the Processing step, pick Private, submit.
    fireEvent.change(screen.getByPlaceholderText(/text/i), { target: { value: 'hello world' } })
    // (navigate wizard to step 3 — helper clicks Next twice; adapt selectors to the dialog)
    fireEvent.click(await screen.findByRole('radio', { name: /private/i }))
    fireEvent.click(screen.getByRole('button', { name: /add source/i }))
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ visibility: 'private' })
  })
})
```
> If the multi-step navigation makes a full render brittle, assert instead on `submitSingleSource`'s output by exporting a small pure builder, or keep this as a focused test of the `ProcessingStep` control (below). The load-bearing assertion is: **`createRequest.visibility` equals the form value, defaulting to `'project'`.**

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- AddSourceDialog.visibility` — Expected: FAIL (no radio named "Private"; `visibility` absent from the request).

- [ ] **Step 3: Write minimal implementation** —
  In `AddSourceDialog.tsx`:
  - `createSourceSchema` (line 30) — add to the `z.object({...})`: `visibility: z.enum(['private', 'project']),`.
  - `defaultValues` (line 134) — add `visibility: 'project',`.
  - `submitSingleSource` (line 301) — add `visibility: data.visibility,` to the `createRequest` object literal.
  - `submitBatch` (line 353) — add `visibility: data.visibility,` to the per-item `createRequest`.
  In `ProcessingStep.tsx`:
  - Add to the local `CreateSourceFormData` interface (line 11): `visibility: 'private' | 'project'`.
  - Add imports at the top: `import { Lock, Users } from 'lucide-react'` and `import { cn } from '@/lib/utils'`.
  - Add a new `FormSection` right after the transformations section (before the "Settings" section, ~line 61):
```tsx
      <FormSection title={t('sources.visibility')} description={t('sources.visibilityLabel')}>
        <Controller
          control={control}
          name="visibility"
          render={({ field }) => (
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label={t('sources.visibilityLabel')}>
              {(['project', 'private'] as const).map((value) => (
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
                    {value === 'private' ? <Lock className="h-4 w-4" /> : <Users className="h-4 w-4" />}
                    {value === 'private' ? t('sources.visibilityPrivate') : t('sources.visibilityProject')}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {value === 'private' ? t('sources.visibilityPrivateDesc') : t('sources.visibilityProjectDesc')}
                  </span>
                </button>
              ))}
            </div>
          )}
        />
      </FormSection>
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- AddSourceDialog.visibility` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add frontend/src/components/sources/AddSourceDialog.tsx frontend/src/components/sources/steps/ProcessingStep.tsx frontend/src/components/sources/AddSourceDialog.visibility.test.tsx && git commit -m "P5 fe: visibility selector in add-source wizard"`

---

### Task 14: Frontend — visibility badge on the source card

**Files:**
- Modify: `frontend/src/components/sources/SourceCard.tsx` (metadata badges row ~276-302; `areEqual` comparator ~450-471; lucide imports ~15)
- Test: `frontend/src/components/sources/SourceCard.visibility.test.tsx`

**Interfaces:**
- Consumes: `source.visibility` (Task 12).

- [ ] **Step 1: Write the failing test** — `frontend/src/components/sources/SourceCard.visibility.test.tsx`:
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

describe('SourceCard visibility badge', () => {
  it('renders the private badge', () => {
    render(<SourceCard source={{ ...base, visibility: 'private' }} />)
    expect(screen.getByText('sources.visibilityPrivate')).toBeInTheDocument()
  })
  it('renders the project badge', () => {
    render(<SourceCard source={{ ...base, visibility: 'project' }} />)
    expect(screen.getByText('sources.visibilityProject')).toBeInTheDocument()
  })
})
```
> Adapt the `SourceCard` props shape/wrappers (it may need a router or query provider) to match how `SourceCard` is tested elsewhere in the repo; the load-bearing assertion is the badge text keyed off `source.visibility`.

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- SourceCard.visibility` — Expected: FAIL (no badge text).

- [ ] **Step 3: Write minimal implementation** — In `SourceCard.tsx`:
  - Ensure `Lock` and `Users` are imported from `lucide-react` (add to the existing lucide import block, line 15).
  - In the "Metadata badges" row (after the source-type `Badge`, ~line 281) add:
```tsx
            <Badge variant="outline" className="text-xs flex items-center gap-1">
              {source.visibility === 'private' ? <Lock className="h-3 w-3" /> : <Users className="h-3 w-3" />}
              {source.visibility === 'private' ? t('sources.visibilityPrivate') : t('sources.visibilityProject')}
            </Badge>
```
  - In the `areEqual` memo comparator (line ~450) add a clause so a visibility change re-renders the card:
```tsx
    prev.source.visibility === next.source.visibility &&
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- SourceCard.visibility` — Expected: PASS (2 passed).

- [ ] **Step 5: Commit** — `git add frontend/src/components/sources/SourceCard.tsx frontend/src/components/sources/SourceCard.visibility.test.tsx && git commit -m "P5 fe: visibility badge on source card"`

---

### Task 15: Frontend — editable visibility control on source detail

**Files:**
- Modify: `frontend/src/components/source/SourceDetailContent.tsx` (imports; header ~418-422; add `handleUpdateVisibility`)
- Test: `frontend/src/components/source/SourceDetailContent.visibility.test.tsx`

**Interfaces:**
- Consumes: `useUpdateSource` (invalidates `['sources']` + toasts, per Task 12 hook); `source.owner`; the current user id from the P1 auth store (`useAuthStore((s) => s.userId)`), a best-effort UI gate — the server (Task 6) is the real gate.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/source/SourceDetailContent.visibility.test.tsx`:
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
      id: 'source:1', title: 'T', visibility: 'project', owner: 'user:me',
      topics: [], asset: null, full_text: '', embedded: false, embedded_chunks: 0,
      insights_count: 0, created: 'c', updated: 'u',
    }),
  },
}))

describe('SourceDetailContent visibility control', () => {
  it('owner can change visibility and it calls useUpdateSource', async () => {
    render(<SourceDetailContent sourceId="source:1" />)
    const control = await screen.findByRole('radio', { name: /private/i })
    fireEvent.click(control)
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ id: 'source:1', data: { visibility: 'private' } }),
    )
  })
})
```
> Adapt the mock surface (SourceDetailContent has many collaborators). The load-bearing assertions: (a) an owner sees an **enabled** visibility control that calls `useUpdateSource({ id, data: { visibility } })`; (b) a non-owner sees a **read-only** badge (add a second test toggling the mocked `owner`/`userId`).

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- SourceDetailContent.visibility` — Expected: FAIL (no visibility control).

- [ ] **Step 3: Write minimal implementation** — In `SourceDetailContent.tsx`:
  - Add imports: `import { useUpdateSource } from '@/lib/hooks/use-sources'`, `import { useAuthStore } from '@/lib/stores/auth-store'`, `import { Lock, Users } from 'lucide-react'`, `import { cn } from '@/lib/utils'`.
  - Inside the component: `const updateSource = useUpdateSource()` and `const currentUserId = useAuthStore((s) => s.userId)`.
  - Derive the gate + handler:
```tsx
  const canEditVisibility = !!currentUserId && source?.owner === currentUserId
  const handleUpdateVisibility = async (visibility: 'private' | 'project') => {
    if (!source || source.visibility === visibility) return
    try {
      await updateSource.mutateAsync({ id: sourceId, data: { visibility } })
      setSource({ ...source, visibility })
      toast.success(t('sources.visibilityChanged'))
    } catch (err) {
      console.error('Failed to update source visibility:', err)
      toast.error(t('sources.visibilityForbidden'))
      await fetchSource()
    }
  }
```
  - In the header cluster (right side, after the source-type `Badge`, ~line 422), render an editable segmented control for the owner, else a read-only badge:
```tsx
            {canEditVisibility ? (
              <div className="flex items-center gap-1" role="radiogroup" aria-label={t('sources.visibilityLabel')}>
                {(['project', 'private'] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={source.visibility === value}
                    onClick={() => handleUpdateVisibility(value)}
                    className={cn(
                      'flex items-center gap-1 rounded-md border px-2 py-1 text-xs',
                      source.visibility === value ? 'border-primary bg-primary/5' : 'border-input hover:bg-muted',
                    )}
                  >
                    {value === 'private' ? <Lock className="h-3 w-3" /> : <Users className="h-3 w-3" />}
                    {value === 'private' ? t('sources.visibilityPrivate') : t('sources.visibilityProject')}
                  </button>
                ))}
              </div>
            ) : (
              <Badge variant="outline" className="text-sm flex items-center gap-1">
                {source.visibility === 'private' ? <Lock className="h-3 w-3" /> : <Users className="h-3 w-3" />}
                {source.visibility === 'private' ? t('sources.visibilityPrivate') : t('sources.visibilityProject')}
              </Badge>
            )}
```
  > `visibilityChanged` and `visibilityForbidden` keys are referenced here so the locale unused-key test passes. `useAuthStore((s) => s.userId)` assumes P1's auth store exposes `userId`; if P1 named the field differently, adjust the selector. Non-admins/non-owners get the read-only badge (admins still succeed server-side; this UI gate is best-effort per spec).

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- SourceDetailContent.visibility` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add frontend/src/components/source/SourceDetailContent.tsx frontend/src/components/source/SourceDetailContent.visibility.test.tsx && git commit -m "P5 fe: editable visibility control on source detail"`

---

### Task 16: i18n — 8 visibility keys in all 14 locales + parity test

**Files:**
- Modify (real translations): `frontend/src/lib/locales/en-US/index.ts` (add to `sources` section)
- Modify (real translations): `frontend/src/lib/locales/{pt-BR,zh-CN,zh-TW,ja-JP,ru-RU,bn-IN}/index.ts` (same keys)
- Modify (English fallback — same keys, English values): `frontend/src/lib/locales/{it-IT,fr-FR,ca-ES,es-ES,de-DE,pl-PL,tr-TR}/index.ts`
- Test: `frontend/src/lib/locales/index.test.ts` (existing parity + unused-key tests — no code change needed; they now must pass with the new keys)

**Interfaces:**
- Produces: `sources.visibility`, `sources.visibilityPrivate`, `sources.visibilityProject`, `sources.visibilityPrivateDesc`, `sources.visibilityProjectDesc`, `sources.visibilityLabel`, `sources.visibilityChanged`, `sources.visibilityForbidden` in all 14 locales (real translations in the 7 enforced, English fallback in the other 7). Every key is already referenced by `t('...')` in Tasks 13-15 (satisfies the unused-key test).

- [ ] **Step 1: Write the failing test** — No new test file; the existing `frontend/src/lib/locales/index.test.ts` is the gate. Run it now to confirm it currently fails once the keys are referenced in code but missing from locales: Run: `npm run test -- locales/index` — Expected at this point: FAIL (unused-key test would fail if keys were referenced but absent; parity fails if added to only en-US).

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- locales/index` — Expected: FAIL with "Missing keys in <locale>: sources.visibility, ..." (after Step 3 adds them to en-US only) OR passes only once all 14 locales have them.

- [ ] **Step 3: Write minimal implementation** — Add the 8 keys inside the `sources: { ... }` object of each locale. **en-US** (`frontend/src/lib/locales/en-US/index.ts`):
```ts
    visibility: "Visibility",
    visibilityPrivate: "Private",
    visibilityProject: "Project",
    visibilityPrivateDesc: "Only you and workspace/project admins can see this source.",
    visibilityProjectDesc: "All members of this project can see this source.",
    visibilityLabel: "Who can see this source?",
    visibilityChanged: "Source visibility updated",
    visibilityForbidden: "You don't have permission to change this source's visibility.",
```
  **pt-BR:**
```ts
    visibility: "Visibilidade",
    visibilityPrivate: "Privado",
    visibilityProject: "Projeto",
    visibilityPrivateDesc: "Apenas você e os administradores do espaço/projeto podem ver esta fonte.",
    visibilityProjectDesc: "Todos os membros deste projeto podem ver esta fonte.",
    visibilityLabel: "Quem pode ver esta fonte?",
    visibilityChanged: "Visibilidade da fonte atualizada",
    visibilityForbidden: "Você não tem permissão para alterar a visibilidade desta fonte.",
```
  **zh-CN:**
```ts
    visibility: "可见性",
    visibilityPrivate: "私密",
    visibilityProject: "项目",
    visibilityPrivateDesc: "只有您和工作区/项目管理员可以查看此来源。",
    visibilityProjectDesc: "此项目的所有成员都可以查看此来源。",
    visibilityLabel: "谁可以查看此来源？",
    visibilityChanged: "来源可见性已更新",
    visibilityForbidden: "您无权更改此来源的可见性。",
```
  **zh-TW:**
```ts
    visibility: "可見性",
    visibilityPrivate: "私密",
    visibilityProject: "專案",
    visibilityPrivateDesc: "只有您和工作區/專案管理員可以檢視此來源。",
    visibilityProjectDesc: "此專案的所有成員都可以檢視此來源。",
    visibilityLabel: "誰可以檢視此來源？",
    visibilityChanged: "來源可見性已更新",
    visibilityForbidden: "您無權變更此來源的可見性。",
```
  **ja-JP:**
```ts
    visibility: "公開範囲",
    visibilityPrivate: "非公開",
    visibilityProject: "プロジェクト",
    visibilityPrivateDesc: "あなたとワークスペース/プロジェクトの管理者のみがこのソースを表示できます。",
    visibilityProjectDesc: "このプロジェクトのすべてのメンバーがこのソースを表示できます。",
    visibilityLabel: "このソースを誰が閲覧できますか？",
    visibilityChanged: "ソースの公開範囲を更新しました",
    visibilityForbidden: "このソースの公開範囲を変更する権限がありません。",
```
  **ru-RU:**
```ts
    visibility: "Видимость",
    visibilityPrivate: "Приватный",
    visibilityProject: "Проект",
    visibilityPrivateDesc: "Только вы и администраторы рабочего пространства/проекта могут видеть этот источник.",
    visibilityProjectDesc: "Все участники этого проекта могут видеть этот источник.",
    visibilityLabel: "Кто может видеть этот источник?",
    visibilityChanged: "Видимость источника обновлена",
    visibilityForbidden: "У вас нет прав на изменение видимости этого источника.",
```
  **bn-IN:**
```ts
    visibility: "দৃশ্যমানতা",
    visibilityPrivate: "ব্যক্তিগত",
    visibilityProject: "প্রকল্প",
    visibilityPrivateDesc: "শুধুমাত্র আপনি এবং ওয়ার্কস্পেস/প্রকল্প অ্যাডমিনরা এই উৎসটি দেখতে পারেন।",
    visibilityProjectDesc: "এই প্রকল্পের সকল সদস্য এই উৎসটি দেখতে পারেন।",
    visibilityLabel: "এই উৎসটি কে দেখতে পারবে?",
    visibilityChanged: "উৎসের দৃশ্যমানতা আপডেট হয়েছে",
    visibilityForbidden: "এই উৎসের দৃশ্যমানতা পরিবর্তন করার অনুমতি আপনার নেই।",
```
- [ ] **Step 3b: Add the same keys (English fallback) to the 7 non-enforced locales** — the parity test iterates EVERY entry of `resources` except `en-US`, so the 7 non-enforced locales `it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR` MUST also carry the 8 `sources.visibility*` keys or `npm run test` fails on them. Add the exact same 8 keys to each of these 7 files' `sources` object using the **en-US English values** (silent en-US fallback is acceptable for non-enforced locales; a native pass can follow).

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- locales/index && npm run lint && npm run build` — Expected: PASS (parity: no missing/extra keys in any of the 14 locales; unused-key: all 8 keys referenced in Tasks 13-15; lint + build clean).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/locales && git commit -m "P5 fe: visibility i18n keys in all 14 locales"`

---

## Final verification (run before opening the PR)
- [ ] Backend: `uv run pytest tests/ -q` — all P5 tests + the existing suite pass (fix any `Notebook.get`→`Project.get` / ctx-override fallout in `test_sources_api.py`, `test_search_api.py` as the failures direct).
- [ ] Backend lint/type: `ruff check . --fix` · `uv run python -m mypy .`
- [ ] Frontend: `cd frontend && npm run test && npm run lint && npm run build`.
- [ ] Manual smoke (real DB + worker): `make start-all`, then as user A create a `private` source in a project, and as user B (same company, project member, non-owner) confirm: it is absent from `GET /sources`, `GET /sources/{id}` → 404, `POST /search` for a token unique to that source → 0 source results, `/search/ask/simple` answer omits the token. As a `project` source, all of these succeed for B.

## Self-review (done — gaps closed inline)
1. **Spec coverage.** Every spec section maps to a task: migration 23 + backfill + search-fn rewrite (Task 1); `Source` model owner/visibility + `get_project_ids` (Task 2); `PermissionContext` concrete shape + predicate (Tasks 3-4); Pydantic schemas + form parsing (Task 5); **every enumerated source-touching endpoint** — sources (Task 6), insights (7), source_chat (8), embedding (9), search + RAG leakage (10), context + `get_sources` filter (11); frontend types/api/hook (12), wizard selector (13), card badge (14), detail control (15), i18n ×14 (16). The role×visibility×action matrix is included as a reference block. Search leakage is closed at both the DB layer ($viewer_source_ids in migration 23) and the app layer (visible_source_ids threaded through `/search`, `/search/ask*`, and the ask graph).
2. **Placeholder scan.** No TBD/"handle edge cases"/"similar to Task N": every code step shows complete, runnable code or an exact, located edit; the ask-graph threading is fully specified (no interim "gate to project-only" fallback needed — the graph reads `viewer_source_ids` from `configurable`).
3. **Type consistency.** `PermissionContext(user_id, company_id, company_role)` + `async project_role()` used identically in Tasks 3, 4, 6-11 (and matches P6's declared shape). `visible_source_ids(ctx, project_id=None) -> List[str]`; routers convert to `RecordID` at the `id IN $visible_ids` / `$viewer_source_ids` boundary. `require_view_source`/`require_mutate_source` return a `Source`; response constructors add `visibility` + `owner` consistently. Frontend `visibility: 'private' | 'project'` is identical across types, api client, hooks, and all three components.
4. **Stated assumptions (no blanks).** Domain class is post-P3 `Project` (substitute `Notebook` if P3 kept an alias); `get_auth_context`/`AuthContext` come from P1/P2; the frontend owner-gate reads `useAuthStore((s) => s.userId)` from P1's auth store. Background podcast/context jobs intentionally run unfiltered (project-owner-initiated) — documented in Task 11.
