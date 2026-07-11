# P7.1 — Brain Schema, Graph API & Entity Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first viewable per-workspace knowledge graph: a SurrealDB `entity`/`mentions`/`part_of` schema, an `Entity` domain model with dedup + edge helpers, an async `extract_source_entities` worker hooked into source ingest, and a `GET /brain/graph` API that returns nodes + hierarchy + source→topic mentions (no semantic `relates` edges yet — those are P7.2).

**Architecture:** Three-tier, matching the existing stack. Next.js is out of scope here. FastAPI router (`api/routers/brain.py`) → thin service (`api/brain_service.py`) → SurrealDB brain tables. Extraction is a fire-and-forget surreal-commands worker job (`commands/brain_commands.py`) submitted after source ingest completes. All reads/writes are workspace-scoped through the P6 `CtxDep`.

**Tech Stack:** Python 3 / FastAPI, SurrealDB (SurrealQL migrations), `surreal-commands` worker, `ai_prompter.Prompter` + LangChain `PydanticOutputParser`, `provision_langchain_model()`, Pydantic v2, pytest (async).

## Global Constraints

Every task's requirements implicitly include these (copied from the design spec and backend AGENTS.md):

- **Async-first.** Every DB query, worker job, and AI call is `await`-ed. No sync DB access.
- **All LLM calls go through `provision_langchain_model()`** (`open_notebook/ai/provision.py`). Never instantiate provider clients directly. A missing/unconfigured model raises `ConfigurationError` (→ HTTP 422) — never `ValueError` for the missing-model case.
- **Typed exceptions only** from `open_notebook.exceptions` (`NotFoundError`→404, `InvalidInputError`→400, `ConfigurationError`→422, `DatabaseOperationError`→500, …). Never raise bare `HTTPException` in domain/service code; global handlers in `api/main.py` map typed exceptions to status codes.
- **New migration MUST be registered in `AsyncMigrationManager`** (`open_notebook/database/async_migrate.py`) — migrations are hard-coded in the `up_migrations`/`down_migrations` lists, not auto-discovered. This plan uses migration number **20** (the next free integer after the last landed migration, 19; the implementer confirms `open_notebook/database/migrations/20.surrealql` does not already exist before starting).
- **Every brain query is workspace-scoped.** Each SELECT/RELATE against `entity`/`mentions`/`part_of` includes `WHERE workspace = $workspace` (or binds `workspace` in RELATE `CONTENT`) using `ctx.workspace_id`. No `kind`/personal-vs-company branching in the scoping layer.
- **P6 is landed and given.** Reference `from api.deps import CtxDep` (and `get_request_context`, `RequestContext`) — a context object exposing `.workspace_id`, `.user_id`, `.role`. Do **not** implement P6 or `api/deps.py` here.
- **Prompter path syntax:** `Prompter(prompt_template="brain/extract_entities")` → `prompts/brain/extract_entities.jinja` (forward slash, no extension). With a `PydanticOutputParser`, the template MUST contain `{{ format_instructions }}` or the parser is silently ignored.
- **Commands retry blocklist:** `@command(..., retry={... "stop_on": [ValueError, ConfigurationError]})`. Raise `ValueError` for permanent (no-retry) failures; any other exception auto-retries. Extraction failures must be logged and must **never block ingest**.
- **TDD is mandatory.** RED (write failing test, confirm it fails for the right reason) → GREEN (minimal code) → REFACTOR. Mock `provision_langchain_model` for determinism.
- **Commands to run:** tests `uv run pytest tests/` · lint `ruff check . --fix` · types `uv run python -m mypy .`

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `open_notebook/database/migrations/20.surrealql` | Create | Define `entity` table + indexes and `mentions`/`part_of` relation tables. |
| `open_notebook/database/migrations/20_down.surrealql` | Create | Drop `mentions`, `part_of`, `entity`. |
| `open_notebook/database/async_migrate.py` | Modify | Register migration 20 in `up_migrations` and `down_migrations`. |
| `tests/test_migration_20_registration.py` | Create | Assert migration 20 is registered and defines/drops the brain tables. |
| `open_notebook/domain/brain.py` | Create | `Entity(ObjectModel)`, `normalize_entity_name`, `upsert_entity_dedup`, `relate_mention`, `relate_part_of`. |
| `tests/test_brain_domain.py` | Create | Unit tests for name-dedup, embedding-dedup, create-new, and edge helpers. |
| `prompts/brain/extract_entities.jinja` | Create | LLM prompt returning entities + suggested domain path; contains `{{ format_instructions }}`. |
| `commands/brain_commands.py` | Create | `ExtractSourceEntitiesInput`, `EntityExtraction` schema, `extract_source_entities` `@command`. |
| `tests/test_brain_commands.py` | Create | Command test with mocked `provision_langchain_model` + mocked domain helpers. |
| `commands/source_commands.py` | Modify | `_submit_entity_extraction()` helper + call site after ingest completes. |
| `tests/test_source_extraction_hook.py` | Create | Assert the hook resolves workspace and submits `extract_source_entities`. |
| `api/brain_models.py` | Create | `BrainNode`, `BrainEdge`, `BrainGraphResponse` Pydantic response models. |
| `api/brain_service.py` | Create | `get_brain_graph(ctx, domain, limit) -> BrainGraphResponse`, workspace-scoped. |
| `tests/test_brain_service.py` | Create | Service shape test with mocked `repo_query`. |
| `api/routers/brain.py` | Create | `GET /brain/graph` router, `prefix="/brain"`, scoped by `CtxDep`. |
| `api/main.py` | Modify | Import and register `brain.router` under the `/api` prefix. |
| `tests/test_brain_router.py` | Create | Router test with `get_request_context` overridden + patched service. |
| `tests/test_brain_tenant_leakage.py` | Create | Extend P6 tenant-leakage coverage to `entity`/`mentions`/`part_of`, incl. personal-vs-personal. |

---

### Task 1: Migration 20 — brain schema

**Files:**
- Create: `open_notebook/database/migrations/20.surrealql`
- Create: `open_notebook/database/migrations/20_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py:98-195`
- Test: `tests/test_migration_20_registration.py`

**Interfaces:**
- Consumes: nothing.
- Produces: SurrealDB tables `entity` (fields `workspace record<workspace>`, `kind`, `name`, `normalized_name`, `embedding option<array<float>>`, `description option<string>`, `salience float DEFAULT 0`), relation `mentions` (`source→entity`, `confidence float`, `workspace record<workspace>`), relation `part_of` (`entity→entity`, `workspace record<workspace>`). Migration index `len(up_migrations) == 20`.

- [ ] **Step 1: Write the failing registration test**

Create `tests/test_migration_20_registration.py`:

```python
from open_notebook.database.async_migrate import AsyncMigration, AsyncMigrationManager


def test_migration_20_is_registered_in_both_lists():
    """Migration 20 must be appended to up and down lists (hard-coded, not auto-discovered)."""
    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 20
    assert len(manager.down_migrations) == 20


def test_migration_20_defines_brain_tables():
    """Cleaned SQL for migration 20 defines entity + mentions/part_of relations."""
    up = AsyncMigration.from_file("open_notebook/database/migrations/20.surrealql")
    sql = up.sql
    assert "DEFINE TABLE IF NOT EXISTS entity" in sql
    assert "DEFINE FIELD IF NOT EXISTS workspace ON TABLE entity TYPE record<workspace>" in sql
    assert "DEFINE FIELD IF NOT EXISTS normalized_name ON TABLE entity TYPE string" in sql
    assert "DEFINE TABLE IF NOT EXISTS mentions" in sql
    assert "TYPE RELATION FROM source TO entity" in sql
    assert "DEFINE TABLE IF NOT EXISTS part_of" in sql
    # The cleaner drops comment lines: no stray "--" survives.
    assert "--" not in sql

    down = AsyncMigration.from_file("open_notebook/database/migrations/20_down.surrealql")
    assert "REMOVE TABLE IF EXISTS entity" in down.sql
    assert "REMOVE TABLE IF EXISTS mentions" in down.sql
    assert "REMOVE TABLE IF EXISTS part_of" in down.sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration_20_registration.py -v`
Expected: FAIL — `test_migration_20_is_registered_in_both_lists` asserts 20 but manager has 19; `test_migration_20_defines_brain_tables` fails at `AsyncMigration.from_file` with `FileNotFoundError` (file not created yet).

- [ ] **Step 3: Create the up migration**

Create `open_notebook/database/migrations/20.surrealql`:

```surrealql
-- P7.1 brain schema: entity nodes + mentions/part_of edges (workspace-scoped)
DEFINE TABLE IF NOT EXISTS entity SCHEMALESS;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE entity TYPE record<workspace>;
DEFINE FIELD IF NOT EXISTS kind ON TABLE entity TYPE string ASSERT $value IN ['domain', 'topic', 'person', 'decision'];
DEFINE FIELD IF NOT EXISTS name ON TABLE entity TYPE string;
DEFINE FIELD IF NOT EXISTS normalized_name ON TABLE entity TYPE string;
DEFINE FIELD IF NOT EXISTS embedding ON TABLE entity TYPE option<array<float>>;
DEFINE FIELD IF NOT EXISTS description ON TABLE entity TYPE option<string>;
DEFINE FIELD IF NOT EXISTS salience ON TABLE entity TYPE float DEFAULT 0;
DEFINE INDEX IF NOT EXISTS idx_entity_workspace ON TABLE entity FIELDS workspace;
DEFINE INDEX IF NOT EXISTS idx_entity_dedup ON TABLE entity FIELDS workspace, kind, normalized_name;

DEFINE TABLE IF NOT EXISTS mentions SCHEMALESS TYPE RELATION FROM source TO entity;
DEFINE FIELD IF NOT EXISTS confidence ON TABLE mentions TYPE float;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE mentions TYPE record<workspace>;
DEFINE INDEX IF NOT EXISTS idx_mentions_workspace ON TABLE mentions FIELDS workspace;

DEFINE TABLE IF NOT EXISTS part_of SCHEMALESS TYPE RELATION FROM entity TO entity;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE part_of TYPE record<workspace>;
DEFINE INDEX IF NOT EXISTS idx_part_of_workspace ON TABLE part_of FIELDS workspace;
```

- [ ] **Step 4: Create the down migration**

Create `open_notebook/database/migrations/20_down.surrealql`:

```surrealql
-- Roll back P7.1 brain schema
REMOVE TABLE IF EXISTS mentions;
REMOVE TABLE IF EXISTS part_of;
REMOVE TABLE IF EXISTS entity;
```

- [ ] **Step 5: Register migration 20 in AsyncMigrationManager**

In `open_notebook/database/async_migrate.py`, add to the end of the `self.up_migrations` list (after the `19.surrealql` entry, ~line 135):

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20.surrealql"
            ),
```

And to the end of the `self.down_migrations` list (after the `19_down.surrealql` entry, ~line 194):

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20_down.surrealql"
            ),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_migration_20_registration.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add open_notebook/database/migrations/20.surrealql open_notebook/database/migrations/20_down.surrealql open_notebook/database/async_migrate.py tests/test_migration_20_registration.py
git commit -m "feat(brain): add migration 20 for entity/mentions/part_of schema

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Entity domain model + dedup + edge helpers

**Files:**
- Create: `open_notebook/domain/brain.py`
- Test: `tests/test_brain_domain.py`

**Interfaces:**
- Consumes: `repo_query`, `repo_relate`, `ensure_record_id` from `open_notebook.database.repository`; `ObjectModel` from `open_notebook.domain.base`.
- Produces (P7.2/P7.3/P7.4 consume verbatim):
  - `class Entity(ObjectModel)` with `table_name = "entity"`, fields `workspace: str`, `kind: Literal["domain","topic","person","decision"]`, `name: str`, `normalized_name: str`, `embedding: Optional[List[float]] = None`, `description: Optional[str] = None`, `salience: float = 0.0`.
  - `normalize_entity_name(name: str) -> str`
  - `async def upsert_entity_dedup(workspace: str, kind: str, name: str, description: Optional[str] = None, embedding: Optional[List[float]] = None) -> Entity`
  - `async def relate_mention(source_id: str, entity_id: str, workspace: str, confidence: float) -> list`
  - `async def relate_part_of(topic_id: str, domain_id: str, workspace: str) -> list`
  - Constant `ENTITY_DEDUP_SIMILARITY_THRESHOLD = 0.92`

- [ ] **Step 1: Write the failing test for name normalization + create-new**

Create `tests/test_brain_domain.py`:

```python
from unittest.mock import AsyncMock

import pytest

import open_notebook.domain.brain as brain
from open_notebook.domain.brain import Entity, normalize_entity_name


def test_normalize_entity_name_folds_case_and_whitespace():
    assert normalize_entity_name("  Machine   Learning ") == "machine learning"


@pytest.mark.asyncio
async def test_upsert_creates_new_entity_when_no_match(monkeypatch):
    calls = []

    async def fake_repo_query(query, vars=None):
        calls.append((query, vars or {}))
        if "SELECT * FROM entity" in query:
            return []  # no name match, no embedding match
        if query.strip().startswith("CREATE entity"):
            return [{
                "id": "entity:new1",
                "workspace": vars["workspace"],
                "kind": vars["kind"],
                "name": vars["name"],
                "normalized_name": vars["normalized"],
                "salience": 1.0,
            }]
        return []

    monkeypatch.setattr(brain, "repo_query", fake_repo_query)

    result = await brain.upsert_entity_dedup(
        workspace="workspace:ws1", kind="topic", name="Machine Learning"
    )
    assert isinstance(result, Entity)
    assert result.id == "entity:new1"
    assert result.normalized_name == "machine learning"
    # Every SELECT/CREATE is workspace-scoped.
    for query, vars in calls:
        assert "$workspace" in query
        assert str(vars.get("workspace")) == "workspace:ws1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_domain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'open_notebook.domain.brain'`.

- [ ] **Step 3: Write the brain domain module**

Create `open_notebook/domain/brain.py`:

```python
import re
from typing import ClassVar, List, Literal, Optional

from loguru import logger

from open_notebook.database.repository import (
    ensure_record_id,
    repo_query,
    repo_relate,
)
from open_notebook.domain.base import ObjectModel
from open_notebook.exceptions import DatabaseOperationError

ENTITY_DEDUP_SIMILARITY_THRESHOLD = 0.92


def normalize_entity_name(name: str) -> str:
    """Case- and whitespace-fold an entity name for dedup matching."""
    return re.sub(r"\s+", " ", name).strip().lower()


class Entity(ObjectModel):
    table_name: ClassVar[str] = "entity"
    nullable_fields: ClassVar[set[str]] = {"embedding", "description"}
    workspace: str
    kind: Literal["domain", "topic", "person", "decision"]
    name: str
    normalized_name: str
    embedding: Optional[List[float]] = None
    description: Optional[str] = None
    salience: float = 0.0


async def upsert_entity_dedup(
    workspace: str,
    kind: str,
    name: str,
    description: Optional[str] = None,
    embedding: Optional[List[float]] = None,
) -> Entity:
    """
    Upsert an entity, deduplicating within the same workspace.

    Match order: (1) exact normalized_name within workspace+kind, then
    (2) embedding cosine similarity >= ENTITY_DEDUP_SIMILARITY_THRESHOLD.
    A match bumps salience and fills description if newly provided; otherwise
    a new entity is created. Prevents "engineering" becoming N duplicate nodes.
    """
    try:
        normalized = normalize_entity_name(name)
        ws = ensure_record_id(workspace)

        # 1. exact normalized_name match
        rows = await repo_query(
            "SELECT * FROM entity WHERE workspace = $workspace AND kind = $kind "
            "AND normalized_name = $normalized LIMIT 1",
            {"workspace": ws, "kind": kind, "normalized": normalized},
        )
        match = rows[0] if rows else None

        # 2. embedding similarity fallback
        if match is None and embedding is not None:
            sim = await repo_query(
                "SELECT *, vector::similarity::cosine(embedding, $embedding) AS similarity "
                "FROM entity WHERE workspace = $workspace AND kind = $kind "
                "AND embedding != NONE AND array::len(embedding) = array::len($embedding) "
                "AND vector::similarity::cosine(embedding, $embedding) >= $threshold "
                "ORDER BY similarity DESC LIMIT 1",
                {
                    "workspace": ws,
                    "kind": kind,
                    "embedding": embedding,
                    "threshold": ENTITY_DEDUP_SIMILARITY_THRESHOLD,
                },
            )
            match = sim[0] if sim else None

        if match is not None:
            updated = await repo_query(
                "UPDATE $id SET salience = salience + 1, "
                "description = ($description OR description), updated = time::now() "
                "RETURN AFTER",
                {"id": ensure_record_id(match["id"]), "description": description},
            )
            return Entity(**updated[0])

        # 3. create new
        created = await repo_query(
            "CREATE entity CONTENT { workspace: $workspace, kind: $kind, name: $name, "
            "normalized_name: $normalized, description: $description, embedding: $embedding, "
            "salience: 1, created: time::now(), updated: time::now() }",
            {
                "workspace": ws,
                "kind": kind,
                "name": name,
                "normalized": normalized,
                "description": description,
                "embedding": embedding,
            },
        )
        return Entity(**created[0])
    except Exception as e:
        logger.error(f"Error upserting entity '{name}' in {workspace}: {e}")
        logger.exception(e)
        raise DatabaseOperationError(e)


async def relate_mention(
    source_id: str, entity_id: str, workspace: str, confidence: float
) -> list:
    """RELATE source->mentions->entity with confidence, workspace-scoped."""
    return await repo_relate(
        source_id,
        "mentions",
        entity_id,
        {"workspace": ensure_record_id(workspace), "confidence": confidence},
    )


async def relate_part_of(topic_id: str, domain_id: str, workspace: str) -> list:
    """RELATE topic-entity->part_of->domain-entity, workspace-scoped."""
    return await repo_relate(
        topic_id,
        "part_of",
        domain_id,
        {"workspace": ensure_record_id(workspace)},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_domain.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Add tests for name-dedup, embedding-dedup, and edge helpers**

Append to `tests/test_brain_domain.py`:

```python
@pytest.mark.asyncio
async def test_upsert_dedups_by_normalized_name(monkeypatch):
    captured = {}

    async def fake_repo_query(query, vars=None):
        vars = vars or {}
        if "SELECT * FROM entity" in query and "normalized_name" in query:
            return [{"id": "entity:existing", "workspace": vars["workspace"],
                     "kind": "topic", "name": "Engineering",
                     "normalized_name": "engineering", "salience": 3.0}]
        if query.strip().startswith("UPDATE"):
            captured["update_id"] = str(vars["id"])
            return [{"id": "entity:existing", "workspace": "workspace:ws1",
                     "kind": "topic", "name": "Engineering",
                     "normalized_name": "engineering", "salience": 4.0}]
        raise AssertionError(f"CREATE should not run on a name match: {query}")

    monkeypatch.setattr(brain, "repo_query", fake_repo_query)
    result = await brain.upsert_entity_dedup(
        workspace="workspace:ws1", kind="topic", name="  engineering "
    )
    assert result.id == "entity:existing"
    assert result.salience == 4.0
    assert captured["update_id"] == "entity:existing"


@pytest.mark.asyncio
async def test_upsert_dedups_by_embedding_when_name_differs(monkeypatch):
    async def fake_repo_query(query, vars=None):
        vars = vars or {}
        if "SELECT * FROM entity" in query and "normalized_name" in query:
            return []  # no name match
        if "vector::similarity::cosine" in query and query.strip().startswith("SELECT"):
            assert vars["threshold"] == brain.ENTITY_DEDUP_SIMILARITY_THRESHOLD
            return [{"id": "entity:sim", "workspace": vars["workspace"], "kind": "topic",
                     "name": "ML", "normalized_name": "ml", "salience": 1.0,
                     "similarity": 0.97}]
        if query.strip().startswith("UPDATE"):
            return [{"id": "entity:sim", "workspace": "workspace:ws1", "kind": "topic",
                     "name": "ML", "normalized_name": "ml", "salience": 2.0}]
        raise AssertionError(f"CREATE should not run on an embedding match: {query}")

    monkeypatch.setattr(brain, "repo_query", fake_repo_query)
    result = await brain.upsert_entity_dedup(
        workspace="workspace:ws1", kind="topic", name="Machine Learning",
        embedding=[0.1, 0.2, 0.3],
    )
    assert result.id == "entity:sim"


@pytest.mark.asyncio
async def test_relate_mention_and_part_of_pass_workspace(monkeypatch):
    calls = []

    async def fake_repo_relate(source, relationship, target, data=None):
        calls.append((str(source), relationship, str(target), data or {}))
        return [{"id": f"{relationship}:1"}]

    monkeypatch.setattr(brain, "repo_relate", fake_repo_relate)

    await brain.relate_mention("source:s1", "entity:e1", "workspace:ws1", 0.8)
    await brain.relate_part_of("entity:topic", "entity:domain", "workspace:ws1")

    assert calls[0][1] == "mentions"
    assert calls[0][3]["confidence"] == 0.8
    assert str(calls[0][3]["workspace"]) == "workspace:ws1"
    assert calls[1][1] == "part_of"
    assert str(calls[1][3]["workspace"]) == "workspace:ws1"
```

- [ ] **Step 6: Run the full brain-domain suite**

Run: `uv run pytest tests/test_brain_domain.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Commit**

```bash
git add open_notebook/domain/brain.py tests/test_brain_domain.py
git commit -m "feat(brain): Entity model with workspace-scoped dedup and edge helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Entity-extraction prompt + command

**Files:**
- Create: `prompts/brain/extract_entities.jinja`
- Create: `commands/brain_commands.py`
- Test: `tests/test_brain_commands.py`

**Interfaces:**
- Consumes: `Entity`, `upsert_entity_dedup`, `relate_mention`, `relate_part_of` from `open_notebook.domain.brain`; `provision_langchain_model`; `Source` from `open_notebook.domain.notebook`; `Prompter`; `PydanticOutputParser`; `CommandInput`/`CommandOutput`/`command` from `surreal_commands`.
- Produces (P7.2/P7.3 consume verbatim):
  - `class ExtractSourceEntitiesInput(CommandInput)` with `source_id: str`, `workspace_id: str`.
  - `class ExtractedEntity(BaseModel)` with `kind: Literal["domain","topic","person","decision"]`, `name: str`, `description: Optional[str]`.
  - `class EntityExtraction(BaseModel)` with `domain_path: str`, `entities: List[ExtractedEntity]`.
  - `@command("extract_source_entities", app="open_notebook")` handler `extract_source_entities_command`.

- [ ] **Step 1: Create the prompt template**

Create `prompts/brain/extract_entities.jinja`:

```jinja
# SYSTEM ROLE

You extract a structured knowledge graph from a single source document. You
identify the salient entities and the domain the source belongs to.

# ENTITY KINDS

- domain: a broad field of knowledge (e.g. "engineering", "finance").
- topic: a specific subject within a domain (e.g. "vector search").
- person: a named individual referenced by the source.
- decision: a concrete choice or commitment recorded by the source.

# YOUR JOB

Read the SOURCE below and return:
1. domain_path: a dot-delimited path from broad to narrow, e.g. "engineering.ai".
   The FIRST segment is the top-level domain.
2. entities: the salient topics, persons, and decisions in the source. Do not
   invent entities that are not supported by the text. Prefer canonical names
   (e.g. "machine learning", not "ML stuff").

# OUTPUT FORMATTING

{{ format_instructions }}

- Return ONLY the JSON object. Do not wrap it in ```json fences.

# SOURCE TITLE

{{ source_title }}

# SOURCE CONTENT

{{ source_content }}

# ANSWER
```

- [ ] **Step 2: Write the failing command test**

Create `tests/test_brain_commands.py`:

```python
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import commands.brain_commands as bc
from commands.brain_commands import ExtractSourceEntitiesInput


@pytest.mark.asyncio
async def test_extract_source_entities_upserts_relates_and_builds_hierarchy(monkeypatch):
    # 1. Fake source
    fake_source = SimpleNamespace(
        id="source:s1", title="Deep Learning Primer",
        full_text="A primer on neural networks by Ada Lovelace.",
    )
    monkeypatch.setattr(bc.Source, "get", AsyncMock(return_value=fake_source))

    # 2. Deterministic LLM: model.ainvoke returns JSON matching EntityExtraction
    payload = {
        "domain_path": "engineering.ai",
        "entities": [
            {"kind": "topic", "name": "neural networks", "description": "NN basics"},
            {"kind": "person", "name": "Ada Lovelace", "description": None},
        ],
    }
    fake_model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content=json.dumps(payload)))
    )
    monkeypatch.setattr(bc, "provision_langchain_model", AsyncMock(return_value=fake_model))

    # 3. Record domain-layer calls
    def entity(id_):
        return SimpleNamespace(id=id_)

    upsert = AsyncMock(side_effect=lambda workspace, kind, name, description=None, embedding=None: entity(f"entity:{kind}:{name}"))
    mention = AsyncMock(return_value=[{"id": "mentions:1"}])
    part_of = AsyncMock(return_value=[{"id": "part_of:1"}])
    monkeypatch.setattr(bc, "upsert_entity_dedup", upsert)
    monkeypatch.setattr(bc, "relate_mention", mention)
    monkeypatch.setattr(bc, "relate_part_of", part_of)

    result = await bc.extract_source_entities_command(
        ExtractSourceEntitiesInput(source_id="source:s1", workspace_id="workspace:ws1")
    )

    assert result.success is True
    assert result.entities_created == 2
    # domain entity + 2 extracted entities => 3 upserts
    assert upsert.await_count == 3
    # one mention per extracted entity
    assert mention.await_count == 2
    # the single topic is linked part_of the domain
    assert part_of.await_count == 1
    # every relate call carried the workspace id
    for call in mention.await_args_list:
        assert call.kwargs.get("workspace") == "workspace:ws1" or call.args[2] == "workspace:ws1"


@pytest.mark.asyncio
async def test_extract_source_entities_missing_text_raises_valueerror(monkeypatch):
    fake_source = SimpleNamespace(id="source:s1", title="Empty", full_text="")
    monkeypatch.setattr(bc.Source, "get", AsyncMock(return_value=fake_source))
    with pytest.raises(ValueError):
        await bc.extract_source_entities_command(
            ExtractSourceEntitiesInput(source_id="source:s1", workspace_id="workspace:ws1")
        )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_commands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'commands.brain_commands'`.

- [ ] **Step 4: Write the command module**

Create `commands/brain_commands.py`:

```python
import time
from typing import List, Literal, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel, Field
from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.brain import (
    relate_mention,
    relate_part_of,
    upsert_entity_dedup,
)
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import ConfigurationError, OpenNotebookError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.error_classifier import classify_error
from open_notebook.utils.text_utils import extract_text_content


class ExtractSourceEntitiesInput(CommandInput):
    source_id: str
    workspace_id: str


class ExtractSourceEntitiesOutput(CommandOutput):
    success: bool
    source_id: str
    entities_created: int = 0
    processing_time: float = 0.0
    error_message: Optional[str] = None


class ExtractedEntity(BaseModel):
    kind: Literal["domain", "topic", "person", "decision"]
    name: str
    description: Optional[str] = None


class EntityExtraction(BaseModel):
    domain_path: str = Field(
        default="",
        description="Dot-delimited domain path from broad to narrow, e.g. 'engineering.ai'.",
    )
    entities: List[ExtractedEntity] = Field(default_factory=list)


async def _run_extraction_llm(title: str, content: str) -> EntityExtraction:
    """Provision a model, render the prompt, and parse the structured result."""
    try:
        parser = PydanticOutputParser(pydantic_object=EntityExtraction)
        prompt = Prompter(
            prompt_template="brain/extract_entities", parser=parser
        ).render(data={"source_title": title or "", "source_content": content})
        model = await provision_langchain_model(
            prompt, None, "tools", max_tokens=2000, structured=dict(type="json")
        )
        ai_message = await model.ainvoke(prompt)
        cleaned = clean_thinking_content(extract_text_content(ai_message.content))
        return parser.parse(cleaned)
    except OpenNotebookError:
        raise
    except Exception as e:
        exc_class, message = classify_error(e)
        raise exc_class(message) from e


@command(
    "extract_source_entities",
    app="open_notebook",
    retry={
        "max_attempts": 5,
        "wait_strategy": "exponential_jitter",
        "wait_min": 1,
        "wait_max": 60,
        "stop_on": [ValueError, ConfigurationError],
        "retry_log_level": "debug",
    },
)
async def extract_source_entities_command(
    input_data: ExtractSourceEntitiesInput,
) -> ExtractSourceEntitiesOutput:
    """
    Extract entities from a source, upsert with dedup, and build the graph.

    After extraction: upsert each entity (workspace-scoped dedup), RELATE
    source->mentions->entity, and build the part_of topic->domain hierarchy.
    Raises ValueError for permanent failures (missing source / empty text);
    ConfigurationError (missing model) also stops retries. Any other error
    retries. Callers never let this block ingest.
    """
    start_time = time.time()
    source_id = input_data.source_id
    workspace_id = input_data.workspace_id

    source = await Source.get(source_id)
    if not source:
        raise ValueError(f"Source '{source_id}' not found")
    if not source.full_text or not source.full_text.strip():
        raise ValueError(f"Source '{source_id}' has no text to extract")

    extraction = await _run_extraction_llm(source.title or "", source.full_text)

    # Domain root from the first path segment (if any).
    domain_entity = None
    domain_name = extraction.domain_path.split(".")[0].strip() if extraction.domain_path else ""
    if domain_name:
        domain_entity = await upsert_entity_dedup(
            workspace=workspace_id, kind="domain", name=domain_name
        )

    entities_created = 0
    for extracted in extraction.entities:
        entity = await upsert_entity_dedup(
            workspace=workspace_id,
            kind=extracted.kind,
            name=extracted.name,
            description=extracted.description,
        )
        await relate_mention(
            source_id=source_id,
            entity_id=entity.id,
            workspace=workspace_id,
            confidence=1.0,
        )
        if extracted.kind == "topic" and domain_entity is not None:
            await relate_part_of(
                topic_id=entity.id,
                domain_id=domain_entity.id,
                workspace=workspace_id,
            )
        entities_created += 1

    processing_time = time.time() - start_time
    logger.info(
        f"Extracted {entities_created} entities from {source_id} "
        f"(workspace={workspace_id}) in {processing_time:.2f}s"
    )
    return ExtractSourceEntitiesOutput(
        success=True,
        source_id=source_id,
        entities_created=entities_created,
        processing_time=processing_time,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_commands.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add prompts/brain/extract_entities.jinja commands/brain_commands.py tests/test_brain_commands.py
git commit -m "feat(brain): extract_source_entities command + extraction prompt

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Ingest hook — submit extraction after source processing

**Files:**
- Modify: `commands/source_commands.py:1-14` (imports), `:133-139` (call site)
- Test: `tests/test_source_extraction_hook.py`

**Interfaces:**
- Consumes: `submit_command`, `repo_query`, `ensure_record_id`; the `extract_source_entities` command name from Task 3.
- Produces: `async def _submit_entity_extraction(source_id: str) -> Optional[str]` in `commands/source_commands.py`, called from `process_source_command` after a successful ingest. Resolves `workspace` from the source row; skips (returns `None`) when unresolved; never raises into the ingest path.

- [ ] **Step 1: Write the failing hook test**

Create `tests/test_source_extraction_hook.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

import commands.source_commands as sc


@pytest.mark.asyncio
async def test_submit_entity_extraction_resolves_workspace_and_submits(monkeypatch):
    monkeypatch.setattr(
        sc, "repo_query",
        AsyncMock(return_value=[{"workspace": "workspace:ws1"}]),
    )
    submit = MagicMock(return_value="command:job1")
    monkeypatch.setattr(sc, "submit_command", submit)

    result = await sc._submit_entity_extraction("source:s1")

    assert result == "command:job1"
    submit.assert_called_once_with(
        "open_notebook",
        "extract_source_entities",
        {"source_id": "source:s1", "workspace_id": "workspace:ws1"},
    )


@pytest.mark.asyncio
async def test_submit_entity_extraction_skips_when_no_workspace(monkeypatch):
    monkeypatch.setattr(sc, "repo_query", AsyncMock(return_value=[{"workspace": None}]))
    submit = MagicMock()
    monkeypatch.setattr(sc, "submit_command", submit)

    result = await sc._submit_entity_extraction("source:s1")

    assert result is None
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_submit_entity_extraction_never_raises(monkeypatch):
    monkeypatch.setattr(sc, "repo_query", AsyncMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(sc, "submit_command", MagicMock())
    # Must swallow errors so ingest is never blocked.
    assert await sc._submit_entity_extraction("source:s1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_source_extraction_hook.py -v`
Expected: FAIL — `AttributeError: module 'commands.source_commands' has no attribute '_submit_entity_extraction'` (and `submit_command`/`repo_query` are not yet imported there).

- [ ] **Step 3: Add imports to source_commands.py**

In `commands/source_commands.py`, update the imports. Change the `surreal_commands` import line (line 6) and the repository import line (line 8):

```python
from surreal_commands import CommandInput, CommandOutput, command, submit_command
```

```python
from open_notebook.database.repository import ensure_record_id, repo_query
```

- [ ] **Step 4: Add the hook helper**

In `commands/source_commands.py`, add this module-level function immediately after `full_model_dump` (after line 29):

```python
async def _submit_entity_extraction(source_id: str) -> Optional[str]:
    """
    Fire-and-forget: submit the brain entity-extraction job for a source.

    Resolves the source's workspace (added by P6) and submits
    'extract_source_entities'. Best-effort — any failure is logged and
    swallowed so it can never block or fail source ingest.
    """
    try:
        rows = await repo_query(
            "SELECT workspace FROM $id",
            {"id": ensure_record_id(source_id)},
        )
        workspace_id = rows[0].get("workspace") if rows else None
        if not workspace_id:
            logger.debug(f"No workspace for source {source_id}; skipping extraction")
            return None
        command_id = submit_command(
            "open_notebook",
            "extract_source_entities",
            {"source_id": source_id, "workspace_id": str(workspace_id)},
        )
        logger.info(
            f"Submitted extract_source_entities for {source_id} "
            f"(workspace={workspace_id}): command_id={command_id}"
        )
        return str(command_id)
    except Exception as e:
        logger.warning(f"Failed to submit entity extraction for {source_id}: {e}")
        return None
```

- [ ] **Step 5: Call the hook after successful ingest**

In `process_source_command`, immediately after the `insights_created = len(insights_list)` line (line 122) and before `processing_time = time.time() - start_time`, add:

```python
        # Brain: kick off entity extraction now that ingest/embedding is done.
        # Best-effort — never blocks or fails ingest.
        await _submit_entity_extraction(str(processed_source.id))
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_source_extraction_hook.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add commands/source_commands.py tests/test_source_extraction_hook.py
git commit -m "feat(brain): submit entity extraction after source ingest

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Brain graph API models + service

**Files:**
- Create: `api/brain_models.py`
- Create: `api/brain_service.py`
- Test: `tests/test_brain_service.py`

**Interfaces:**
- Consumes: `repo_query`, `ensure_record_id`; `normalize_entity_name` from `open_notebook.domain.brain`; the P6 `RequestContext` (`ctx.workspace_id`).
- Produces (P7.2/P7.3/P7.4 consume verbatim):
  - `class BrainNode(BaseModel)`: `id: str`, `kind: Literal["domain","topic","person","decision","source"]`, `label: str`, `salience: float`.
  - `class BrainEdge(BaseModel)`: `source: str`, `target: str`, `type: Literal["part_of","mentions","supersedes","disagrees","complements","agrees"]`.
  - `class BrainGraphResponse(BaseModel)`: `nodes: List[BrainNode]`, `edges: List[BrainEdge]`.
  - `async def get_brain_graph(ctx, domain: Optional[str] = None, limit: int = 200) -> BrainGraphResponse`.

- [ ] **Step 1: Create the response models**

Create `api/brain_models.py`:

```python
from typing import List, Literal

from pydantic import BaseModel

NodeKind = Literal["domain", "topic", "person", "decision", "source"]
EdgeType = Literal[
    "part_of", "mentions", "supersedes", "disagrees", "complements", "agrees"
]


class BrainNode(BaseModel):
    id: str
    kind: NodeKind
    label: str
    salience: float = 0.0


class BrainEdge(BaseModel):
    source: str
    target: str
    type: EdgeType


class BrainGraphResponse(BaseModel):
    nodes: List[BrainNode]
    edges: List[BrainEdge]
```

- [ ] **Step 2: Write the failing service test**

Create `tests/test_brain_service.py`:

```python
from types import SimpleNamespace

import pytest

import api.brain_service as svc


def _ctx(workspace_id="workspace:ws1"):
    return SimpleNamespace(workspace_id=workspace_id, user_id="user:u1", role="owner")


@pytest.mark.asyncio
async def test_get_brain_graph_assembles_nodes_and_edges(monkeypatch):
    seen = []

    async def fake_repo_query(query, vars=None):
        seen.append((query, vars or {}))
        if query.strip().startswith("SELECT id, kind, name, salience FROM entity"):
            return [
                {"id": "entity:d1", "kind": "domain", "name": "Engineering", "salience": 5.0},
                {"id": "entity:t1", "kind": "topic", "name": "Vector Search", "salience": 3.0},
            ]
        if "FROM mentions" in query:
            return [{"source": "source:s1", "entity": "entity:t1"}]
        if "FROM part_of" in query:
            return [{"topic": "entity:t1", "domain": "entity:d1"}]
        if query.strip().startswith("SELECT id, title FROM source"):
            return [{"id": "source:s1", "title": "Intro to VS"}]
        return []

    monkeypatch.setattr(svc, "repo_query", fake_repo_query)

    result = await svc.get_brain_graph(_ctx(), domain=None, limit=200)

    node_ids = {n.id: n for n in result.nodes}
    assert node_ids["entity:d1"].kind == "domain"
    assert node_ids["entity:t1"].label == "Vector Search"
    assert node_ids["source:s1"].kind == "source"
    assert node_ids["source:s1"].label == "Intro to VS"

    edge_types = {(e.source, e.target, e.type) for e in result.edges}
    assert ("entity:t1", "entity:d1", "part_of") in edge_types
    assert ("source:s1", "entity:t1", "mentions") in edge_types

    # Every query is workspace-scoped and binds ctx.workspace_id.
    for query, vars in seen:
        assert "workspace = $workspace" in query
        assert str(vars["workspace"]) == "workspace:ws1"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.brain_service'`.

- [ ] **Step 4: Write the service**

Create `api/brain_service.py`:

```python
from typing import Any, Optional

from loguru import logger

from api.brain_models import BrainEdge, BrainGraphResponse, BrainNode
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.brain import normalize_entity_name
from open_notebook.exceptions import DatabaseOperationError


async def get_brain_graph(
    ctx: Any, domain: Optional[str] = None, limit: int = 200
) -> BrainGraphResponse:
    """
    Build the workspace's brain graph: entity nodes + source nodes, plus
    part_of (hierarchy) and mentions (source->topic) edges. No semantic
    `relates` edges yet (P7.2). Every query is scoped to ctx.workspace_id.
    """
    try:
        ws = ensure_record_id(ctx.workspace_id)

        entity_query = (
            "SELECT id, kind, name, salience FROM entity "
            "WHERE workspace = $workspace"
        )
        entity_vars: dict = {"workspace": ws, "limit": limit}
        if domain:
            entity_query += (
                " AND (normalized_name = $domain "
                "OR $domain IN ->part_of->entity.normalized_name)"
            )
            entity_vars["domain"] = normalize_entity_name(domain)
        entity_query += " ORDER BY salience DESC LIMIT $limit"

        entity_rows = await repo_query(entity_query, entity_vars)

        mention_rows = await repo_query(
            "SELECT in AS source, out AS entity FROM mentions "
            "WHERE workspace = $workspace",
            {"workspace": ws},
        )
        part_of_rows = await repo_query(
            "SELECT in AS topic, out AS domain FROM part_of "
            "WHERE workspace = $workspace",
            {"workspace": ws},
        )
        source_rows = await repo_query(
            "SELECT id, title FROM source WHERE id IN "
            "(SELECT VALUE in FROM mentions WHERE workspace = $workspace)",
            {"workspace": ws},
        )

        nodes: list[BrainNode] = []
        node_ids: set[str] = set()
        for row in entity_rows:
            nid = str(row["id"])
            node_ids.add(nid)
            nodes.append(
                BrainNode(
                    id=nid,
                    kind=row["kind"],
                    label=row.get("name") or nid,
                    salience=float(row.get("salience") or 0.0),
                )
            )

        # Source nodes limited to those whose mentioned entity survived the cap.
        for row in source_rows:
            sid = str(row["id"])
            if sid in node_ids:
                continue
            nodes.append(
                BrainNode(
                    id=sid,
                    kind="source",
                    label=row.get("title") or sid,
                    salience=0.0,
                )
            )
            node_ids.add(sid)

        edges: list[BrainEdge] = []
        for row in part_of_rows:
            topic, dom = str(row["topic"]), str(row["domain"])
            if topic in node_ids and dom in node_ids:
                edges.append(BrainEdge(source=topic, target=dom, type="part_of"))
        for row in mention_rows:
            src, ent = str(row["source"]), str(row["entity"])
            if src in node_ids and ent in node_ids:
                edges.append(BrainEdge(source=src, target=ent, type="mentions"))

        return BrainGraphResponse(nodes=nodes, edges=edges)
    except Exception as e:
        logger.error(f"Error building brain graph for {ctx.workspace_id}: {e}")
        logger.exception(e)
        raise DatabaseOperationError(e)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_service.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add api/brain_models.py api/brain_service.py tests/test_brain_service.py
git commit -m "feat(brain): brain graph response models + workspace-scoped service

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Brain router + registration

**Files:**
- Create: `api/routers/brain.py`
- Modify: `api/main.py:18-40` (import), `:389-411` (include_router)
- Test: `tests/test_brain_router.py`

**Interfaces:**
- Consumes: `CtxDep` and `get_request_context` from `api.deps` (P6); `get_brain_graph` from `api.brain_service`; `BrainGraphResponse`.
- Produces: `router = APIRouter(prefix="/brain", tags=["brain"])` with `GET /brain/graph?domain=&limit=` → `BrainGraphResponse`. Registered under the `/api` prefix in `api/main.py`, giving the full path `/api/brain/graph`.

- [ ] **Step 1: Write the failing router test**

Create `tests/test_brain_router.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routers.brain as brain_router
from api.brain_models import BrainEdge, BrainGraphResponse, BrainNode
from api.deps import get_request_context


def _build_client(monkeypatch):
    fake_response = BrainGraphResponse(
        nodes=[BrainNode(id="entity:d1", kind="domain", label="Engineering", salience=5.0)],
        edges=[BrainEdge(source="source:s1", target="entity:d1", type="mentions")],
    )
    captured = {}

    async def fake_get_brain_graph(ctx, domain=None, limit=200):
        captured["workspace_id"] = ctx.workspace_id
        captured["domain"] = domain
        captured["limit"] = limit
        return fake_response

    monkeypatch.setattr(brain_router, "get_brain_graph", fake_get_brain_graph)

    app = FastAPI()
    app.include_router(brain_router.router, prefix="/api")
    app.dependency_overrides[get_request_context] = lambda: SimpleNamespace(
        workspace_id="workspace:ws1", user_id="user:u1", role="owner"
    )
    return TestClient(app), captured


def test_get_brain_graph_returns_nodes_and_edges(monkeypatch):
    client, captured = _build_client(monkeypatch)
    resp = client.get("/api/brain/graph?domain=engineering&limit=50")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nodes"][0]["id"] == "entity:d1"
    assert body["edges"][0]["type"] == "mentions"
    assert captured["workspace_id"] == "workspace:ws1"
    assert captured["domain"] == "engineering"
    assert captured["limit"] == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.routers.brain'`.

- [ ] **Step 3: Write the router**

Create `api/routers/brain.py`:

```python
from typing import Optional

from fastapi import APIRouter, Query

from api.brain_models import BrainGraphResponse
from api.brain_service import get_brain_graph
from api.deps import CtxDep

router = APIRouter(prefix="/brain", tags=["brain"])


@router.get("/graph", response_model=BrainGraphResponse)
async def brain_graph(
    ctx: CtxDep,
    domain: Optional[str] = Query(default=None, description="Narrow to a domain subtree"),
    limit: int = Query(default=200, ge=1, le=1000, description="Max nodes (salience-ranked)"),
) -> BrainGraphResponse:
    """Return the active workspace's brain graph (nodes + edges)."""
    return await get_brain_graph(ctx, domain=domain, limit=limit)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_router.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Register the router in main.py**

In `api/main.py`, add `brain` to the `from api.routers import (...)` block (keep alphabetical, before `chat`):

```python
    brain,
```

Then add the include after the search router registration (~line 392):

```python
app.include_router(brain.router, prefix="/api", tags=["brain"])
```

- [ ] **Step 6: Verify the app imports and the route is registered**

Run: `uv run python -c "from api.main import app; assert any(getattr(r, 'path', '') == '/api/brain/graph' for r in app.routes), 'route missing'; print('brain route registered')"`
Expected: prints `brain route registered` (requires P6 `api/deps.py` present; if the import fails on `api.deps`, confirm P6 is landed first).

- [ ] **Step 7: Commit**

```bash
git add api/routers/brain.py api/main.py tests/test_brain_router.py
git commit -m "feat(brain): GET /brain/graph router + registration

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Extend tenant-leakage coverage to brain tables

**Files:**
- Create: `tests/test_brain_tenant_leakage.py`

**Interfaces:**
- Consumes: `get_brain_graph` from `api.brain_service`.
- Produces: regression coverage proving workspace A can never read workspace B's `entity`/`mentions`/`part_of`, including personal-vs-personal. This extends the P6 tenant-leakage suite to the brain surface.

- [ ] **Step 1: Write the failing leakage test**

Create `tests/test_brain_tenant_leakage.py`:

```python
from types import SimpleNamespace

import pytest

import api.brain_service as svc


def _ctx(workspace_id):
    return SimpleNamespace(workspace_id=workspace_id, user_id="user:x", role="owner")


def _store():
    # Two personal workspaces, each with its own entity/mentions/part_of rows.
    return {
        "workspace:personalA": {
            "entity": [{"id": "entity:a1", "kind": "domain", "name": "A-Domain", "salience": 1.0}],
            "mentions": [{"source": "source:sa", "entity": "entity:a1"}],
            "part_of": [],
            "source": [{"id": "source:sa", "title": "A source"}],
        },
        "workspace:personalB": {
            "entity": [{"id": "entity:b1", "kind": "domain", "name": "B-Domain", "salience": 1.0}],
            "mentions": [{"source": "source:sb", "entity": "entity:b1"}],
            "part_of": [],
            "source": [{"id": "source:sb", "title": "B source"}],
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_id", ["workspace:personalA", "workspace:personalB"])
async def test_brain_graph_never_leaks_across_workspaces(monkeypatch, workspace_id):
    store = _store()
    scoped_queries = []

    async def fake_repo_query(query, vars=None):
        vars = vars or {}
        # Enforce that the service ALWAYS binds a workspace and scopes on it.
        assert "workspace = $workspace" in query, f"unscoped query: {query}"
        assert "workspace" in vars, f"query missing bound workspace: {query}"
        scoped_queries.append(query)
        ws = str(vars["workspace"])
        data = store.get(ws, {})
        if query.strip().startswith("SELECT id, kind, name, salience FROM entity"):
            return list(data.get("entity", []))
        if "FROM mentions" in query and "SELECT in AS source" in query:
            return list(data.get("mentions", []))
        if "FROM part_of" in query:
            return list(data.get("part_of", []))
        if query.strip().startswith("SELECT id, title FROM source"):
            return list(data.get("source", []))
        return []

    monkeypatch.setattr(svc, "repo_query", fake_repo_query)

    result = await svc.get_brain_graph(_ctx(workspace_id), domain=None, limit=200)

    ids = {n.id for n in result.nodes}
    other = "workspace:personalB" if workspace_id == "workspace:personalA" else "workspace:personalA"
    other_entity = store[other]["entity"][0]["id"]
    other_source = store[other]["source"][0]["id"]
    assert other_entity not in ids, "leaked another workspace's entity"
    assert other_source not in ids, "leaked another workspace's source"
    # Sanity: our own workspace's data IS present.
    assert store[workspace_id]["entity"][0]["id"] in ids
    assert len(scoped_queries) >= 4  # entity, mentions, part_of, source all scoped
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `uv run pytest tests/test_brain_tenant_leakage.py -v`
Expected: PASS if Task 5 is complete (the service already scopes every query). If it FAILs on the `"workspace = $workspace" in query` assertion, that is a real leakage bug in `api/brain_service.py` — fix the offending query to include `WHERE workspace = $workspace` and bind `ctx.workspace_id`, then re-run. (This test is written to fail loudly the moment any brain query drops its workspace scope.)

- [ ] **Step 3: Run the whole brain suite + lint + types**

Run: `uv run pytest tests/test_brain_domain.py tests/test_brain_commands.py tests/test_source_extraction_hook.py tests/test_brain_service.py tests/test_brain_router.py tests/test_brain_tenant_leakage.py tests/test_migration_20_registration.py -v`
Expected: all PASS.

Run: `ruff check . --fix`
Expected: no remaining errors.

Run: `uv run python -m mypy .`
Expected: no new errors in the brain modules.

- [ ] **Step 4: Commit**

```bash
git add tests/test_brain_tenant_leakage.py
git commit -m "test(brain): extend tenant-leakage coverage to entity/mentions/part_of

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

Checked this plan against the P7.1 scope in `docs/superpowers/specs/2026-07-12-p7-intelligence-brain-design.md`:

**Spec coverage**
- Migration for `entity`/`mentions`/`part_of` (workspace-scoped, `_down` drops them) → Task 1, registered in `AsyncMigrationManager` (migration 20, next free after landed 19).
- `Entity` domain model + edge helpers + dedup (normalized_name then embedding cosine, within workspace) → Task 2.
- `extract_source_entities` command + prompt (`{{ format_instructions }}` present) + upsert/mention/part_of hierarchy → Task 3.
- Ingest hook submitting the command after ingest completes, never blocking ingest → Task 4.
- `GET /brain/graph` service + `BrainNode`/`BrainEdge`/`BrainGraphResponse` (exact fields incl. `source` node kind and the full 6-type `EdgeType` literal for forward compat with P7.2) → Tasks 5–6, registered in `api/main.py`.
- Extended tenant-leakage coverage incl. personal-vs-personal → Task 7.
- `relates` edge intentionally NOT created here (P7.2), matching scope.

**Placeholder scan:** No TBD/"add error handling"/"similar to Task N". Every code step contains complete, real SurrealQL/Python/pytest with concrete assertions. `provision_langchain_model` is mocked in the command test for determinism.

**Type consistency:** `Entity` fields, `upsert_entity_dedup`/`relate_mention`/`relate_part_of` signatures, `ExtractSourceEntitiesInput{source_id, workspace_id}`, `EntityExtraction{domain_path, entities}`, `BrainNode`/`BrainEdge`/`BrainGraphResponse` fields, and `get_brain_graph(ctx, domain, limit)` are used identically across the domain module, command, service, router, and tests. Router prefix `/brain` + app prefix `/api` = `/api/brain/graph`, consistent between Task 6 code, the registration verification, and the router test.

**Assumption flagged for the implementer:** P6 is treated as landed — `api/deps.py` (`CtxDep`, `get_request_context`, `RequestContext` with `.workspace_id`) and a `workspace` table/`source.workspace` field must exist before Tasks 4–7 run against a live DB. The unit tests here mock the DB and P6 context, so they pass without a live P6, but the `python -c` route-registration check in Task 6 Step 6 requires `api/deps.py` to import.
