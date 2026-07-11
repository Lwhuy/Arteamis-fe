# P7.2 — Brain Relationship Classification & Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the semantic relationship layer (`relates` edges: supersedes / disagrees / complements / agrees) and workspace-level rebuild orchestration on top of P7.1's entity/mentions/part_of graph.

**Architecture:** A new `relates` edge (source→source) is written by an async `classify_relationships` worker command that vector-searches the top-K most similar *other* sources in the workspace and asks an LLM to classify each pair. A `rebuild_brain` command orchestrates extraction+classification across a workspace; `extract_source_entities` (P7.1) is extended to chain into classification on completion. Reads go through `api/brain_service.py` → `api/routers/brain.py`, scoped by the P6 request context.

**Tech Stack:** FastAPI, SurrealDB (SurrealQL migrations), `surreal_commands` worker, `ai_prompter.Prompter` + `PydanticOutputParser`, `provision_langchain_model()`, pytest + `pytest.mark.asyncio` + `monkeypatch`.

## Global Constraints

- **Async-first**: every DB query, edge write, and AI call is `await`-ed. No sync DB access.
- **LLM provisioning**: all LLM calls go through `provision_langchain_model(content, model_id, default_type, **kwargs)`. Missing/unconfigured model → it raises `ConfigurationError` (422). Never instantiate provider clients directly.
- **Typed exceptions**: raise from `open_notebook.exceptions` (`InvalidInputError`→400, `NotFoundError`→404, `ConfigurationError`→422, `DatabaseOperationError`→500). Never raise bare `HTTPException` for domain errors.
- **Migration registration**: a new migration is a file `open_notebook/database/migrations/N.surrealql` (+ `N_down.surrealql`) **and** an edit to `AsyncMigrationManager` (both `up_migrations` and `down_migrations`) — migrations are hard-coded, not auto-discovered.
- **Workspace scoping**: every brain query is scoped by workspace. API handlers read `ctx` via `from api.deps import CtxDep` (`ctx.workspace_id`, `ctx.user_id`, `ctx.role`); domain/command functions take an explicit `workspace` / `workspace_id` argument and filter on it.
- **Commands**: retry blocklist `stop_on: [ValueError, ConfigurationError]`; raise `ValueError` for permanent per-item failures; submit is fire-and-forget via `submit_command()`; commands must be idempotent under retry.
- **TDD mandatory**: strict RED → GREEN → REFACTOR, one behavior at a time.
- **CI gates (run after every task)**: `uv run pytest tests/`, `ruff check . --fix`, `uv run python -m mypy .`.

---

## File Structure

**Created:**
- `open_notebook/database/migrations/21.surrealql` — defines the `relates` edge (source→source) + workspace index.
- `open_notebook/database/migrations/21_down.surrealql` — drops the `relates` edge table.
- `prompts/brain/classify_relationship.jinja` — LLM prompt classifying a pair of sources; contains `{{ format_instructions }}`.
- `tests/test_migration_21_registration.py` — migration file content + registration test.
- `tests/test_brain_relates.py` — `relate_sources` dedup/orientation + `get_source_relationships` unit tests.
- `tests/test_brain_classify_command.py` — mocked-LLM determinism + `rebuild_brain` orchestration + extract→classify chaining.
- `tests/test_brain_status_rebuild_api.py` — `get_brain_status` / `trigger_rebuild` service + `/brain/status` + `/brain/rebuild` routes.
- `tests/test_brain_relates_leakage.py` — extends the P6 tenant-leakage suite to `relates`.

**Modified (created by P7.1 — this plan assumes P7.1 has landed):**
- `open_notebook/database/async_migrate.py` — register migration 21 in both lists.
- `open_notebook/domain/brain.py` — add `relate_sources(...)` and `get_source_relationships(...)`.
- `commands/brain_commands.py` — add `ClassifyRelationshipsInput`, `classify_relationships` command, `RebuildBrainInput`, `rebuild_brain` command; **modify `extract_source_entities`** to chain `classify_relationships`.
- `api/brain_service.py` — add `get_brain_status(...)` and `trigger_rebuild(...)`; **modify `get_brain_graph(...)`** to include `relates` edges.
- `api/routers/brain.py` — add `GET /brain/status` and `POST /brain/rebuild`.
- `api/brain_models.py` — add `BrainStatusResponse`, `BrainRebuildRequest`, `BrainRebuildResponse` (alongside the P7.1 brain models).

---

### Task 1: `relates` migration (21) + registration

**Files:**
- Create: `open_notebook/database/migrations/21.surrealql`
- Create: `open_notebook/database/migrations/21_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py`
- Test: `tests/test_migration_21_registration.py`

**Interfaces:**
- Consumes (P7.1): migration `20.surrealql` (entity/mentions/part_of) is already registered, so `AsyncMigrationManager` currently holds 20 up + 20 down entries.
- Produces: SurrealDB edge table `relates` with fields `type` ∈ {supersedes, disagrees, complements, agrees}, `confidence` (float), `rationale` (string), `workspace` (string), `created` (datetime); index `idx_relates_workspace`. After this task the manager holds 21 up + 21 down entries.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_21_registration.py
from open_notebook.database.async_migrate import AsyncMigration, AsyncMigrationManager


def test_migration_21_is_registered_in_both_lists():
    manager = AsyncMigrationManager()
    assert len(manager.up_migrations) == 21
    assert len(manager.down_migrations) == 21


def test_migration_21_defines_relates_edge():
    up = AsyncMigration.from_file("open_notebook/database/migrations/21.surrealql")
    sql = up.sql
    assert "DEFINE TABLE IF NOT EXISTS relates" in sql
    assert "TYPE RELATION IN source OUT source" in sql
    assert 'ASSERT $value IN ["supersedes", "disagrees", "complements", "agrees"]' in sql
    assert "DEFINE FIELD IF NOT EXISTS confidence ON TABLE relates TYPE float" in sql
    assert "DEFINE FIELD IF NOT EXISTS rationale ON TABLE relates TYPE string" in sql
    assert "DEFINE FIELD IF NOT EXISTS workspace ON TABLE relates TYPE string" in sql
    assert "idx_relates_workspace" in sql
    # The cleaner joins with spaces and drops comment lines: no stray "--" survives.
    assert "--" not in sql

    down = AsyncMigration.from_file("open_notebook/database/migrations/21_down.surrealql")
    assert "REMOVE TABLE IF EXISTS relates" in down.sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration_21_registration.py -v`
Expected: FAIL — `FileNotFoundError` for `21.surrealql` (and/or `assert 21 == 20`).

- [ ] **Step 3: Create the migration files**

```sql
-- open_notebook/database/migrations/21.surrealql
-- Migration 21: Brain semantic relationship layer (P7.2).
-- Adds the `relates` edge (source -> source) carrying the four semantic
-- relationship types classified by the brain worker. Workspace-scoped.

DEFINE TABLE IF NOT EXISTS relates SCHEMAFULL TYPE RELATION IN source OUT source;
DEFINE FIELD IF NOT EXISTS type ON TABLE relates TYPE string ASSERT $value IN ["supersedes", "disagrees", "complements", "agrees"];
DEFINE FIELD IF NOT EXISTS confidence ON TABLE relates TYPE float;
DEFINE FIELD IF NOT EXISTS rationale ON TABLE relates TYPE string;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE relates TYPE string;
DEFINE FIELD IF NOT EXISTS created ON TABLE relates DEFAULT time::now() VALUE $before OR time::now();
DEFINE INDEX IF NOT EXISTS idx_relates_workspace ON TABLE relates FIELDS workspace;
```

```sql
-- open_notebook/database/migrations/21_down.surrealql
-- Rollback migration 21: drop the relates edge.

REMOVE TABLE IF EXISTS relates;
```

- [ ] **Step 4: Register migration 21 in `AsyncMigrationManager`**

In `open_notebook/database/async_migrate.py`, append to `self.up_migrations` (immediately after the `20.surrealql` entry added by P7.1):

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/21.surrealql"
            ),
```

And append to `self.down_migrations` (immediately after the `20_down.surrealql` entry):

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/21_down.surrealql"
            ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_migration_21_registration.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add open_notebook/database/migrations/21.surrealql open_notebook/database/migrations/21_down.surrealql open_notebook/database/async_migrate.py tests/test_migration_21_registration.py
git commit -m "feat(brain): add relates edge migration 21 (P7.2)"
```

---

### Task 2: `relate_sources` + `get_source_relationships` in `open_notebook/domain/brain.py`

**Files:**
- Modify: `open_notebook/domain/brain.py`
- Test: `tests/test_brain_relates.py`

**Interfaces:**
- Consumes (P7.1): `open_notebook/domain/brain.py` module already exists with `class Entity(ObjectModel)` and imports `repo_query`, `repo_relate`, `ensure_record_id`. Consumes `open_notebook.domain.notebook.Source` (`Source.get(id)`, `Source.created: Optional[datetime]`).
- Produces:
  - `async def relate_sources(source_id: str, target_id: str, rel_type: str, confidence: float, rationale: str, workspace: str) -> dict` — creates/updates a `relates` edge, deduping the ordered `(in, out)` pair; orients `'supersedes'` newer→older by `Source.created`. Returns `{"id": str, "updated": bool}`.
  - `async def get_source_relationships(workspace: str) -> list[dict]` — returns `[{"source", "target", "type", "confidence", "rationale"}]` for the workspace.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_relates.py
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import open_notebook.domain.brain as brain


def _source(created):
    return SimpleNamespace(created=created)


@pytest.mark.asyncio
async def test_supersedes_is_oriented_newer_to_older(monkeypatch):
    older = _source(datetime(2020, 1, 1))
    newer = _source(datetime(2024, 1, 1))

    async def fake_get(source_id):
        return {"source:old": older, "source:new": newer}[source_id]

    monkeypatch.setattr(brain, "ensure_record_id", lambda v: f"rid:{v}")
    monkeypatch.setattr(brain.Source, "get", AsyncMock(side_effect=fake_get))
    # dedup lookup returns no existing edge
    monkeypatch.setattr(brain, "repo_query", AsyncMock(return_value=[]))
    relate = AsyncMock(return_value=[{"id": "relates:1"}])
    monkeypatch.setattr(brain, "repo_relate", relate)

    # Called with older first, but newer supersedes older -> edge in=newer out=older
    await brain.relate_sources(
        "source:old", "source:new", "supersedes", 0.9, "b restates a", "ws:1"
    )

    args = relate.await_args.args
    assert args[0] == "rid:source:new"   # in (source): newer
    assert args[1] == "relates"
    assert args[2] == "rid:source:old"   # out (target): older
    assert relate.await_args.args[3]["type"] == "supersedes"
    assert relate.await_args.args[3]["workspace"] == "ws:1"


@pytest.mark.asyncio
async def test_non_supersedes_keeps_argument_order(monkeypatch):
    monkeypatch.setattr(brain, "ensure_record_id", lambda v: f"rid:{v}")
    monkeypatch.setattr(brain, "repo_query", AsyncMock(return_value=[]))
    relate = AsyncMock(return_value=[{"id": "relates:2"}])
    monkeypatch.setattr(brain, "repo_relate", relate)

    await brain.relate_sources("source:a", "source:b", "agrees", 0.7, "aligned", "ws:1")

    args = relate.await_args.args
    assert args[0] == "rid:source:a"
    assert args[2] == "rid:source:b"


@pytest.mark.asyncio
async def test_existing_ordered_pair_is_updated_not_duplicated(monkeypatch):
    monkeypatch.setattr(brain, "ensure_record_id", lambda v: f"rid:{v}")
    query = AsyncMock(return_value=[{"id": "relates:existing"}])
    monkeypatch.setattr(brain, "repo_query", query)
    relate = AsyncMock()
    monkeypatch.setattr(brain, "repo_relate", relate)

    result = await brain.relate_sources(
        "source:a", "source:b", "complements", 0.5, "adds detail", "ws:1"
    )

    relate.assert_not_awaited()          # no new edge created
    assert result == {"id": "relates:existing", "updated": True}
    # second query call is the UPDATE
    update_sql = query.await_args_list[-1].args[0]
    assert "UPDATE" in update_sql


@pytest.mark.asyncio
async def test_get_source_relationships_scopes_by_workspace(monkeypatch):
    rows = [
        {
            "source": "source:a",
            "target": "source:b",
            "type": "agrees",
            "confidence": 0.8,
            "rationale": "aligned",
        }
    ]
    query = AsyncMock(return_value=rows)
    monkeypatch.setattr(brain, "repo_query", query)

    out = await brain.get_source_relationships("ws:1")

    sql, params = query.await_args.args
    assert "FROM relates WHERE workspace = $workspace" in sql
    assert params == {"workspace": "ws:1"}
    assert out == [
        {
            "source": "source:a",
            "target": "source:b",
            "type": "agrees",
            "confidence": 0.8,
            "rationale": "aligned",
        }
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_relates.py -v`
Expected: FAIL — `AttributeError: module 'open_notebook.domain.brain' has no attribute 'relate_sources'`.

- [ ] **Step 3: Implement the functions**

Add to `open_notebook/domain/brain.py`. Ensure these imports exist at the top of the file (add any that P7.1 did not already import):

```python
from datetime import datetime

from open_notebook.database.repository import (
    ensure_record_id,
    repo_query,
    repo_relate,
)
from open_notebook.domain.notebook import Source
```

Then add the functions:

```python
async def relate_sources(
    source_id: str,
    target_id: str,
    rel_type: str,
    confidence: float,
    rationale: str,
    workspace: str,
) -> dict:
    """Create (or update) a `relates` edge between two sources in a workspace.

    - Orients 'supersedes' newer -> older by Source.created: the more recent
      source is always the edge's `in`, the source it supersedes the `out`.
    - Dedupes on the ordered (in, out) pair: an existing edge is updated in
      place instead of creating a duplicate.
    """
    in_rid = ensure_record_id(source_id)
    out_rid = ensure_record_id(target_id)

    if rel_type == "supersedes":
        source_obj = await Source.get(source_id)
        target_obj = await Source.get(target_id)
        source_created = source_obj.created or datetime.min
        target_created = target_obj.created or datetime.min
        # If the passed source is older than the target, swap so the newer
        # source becomes the edge's `in`.
        if source_created < target_created:
            in_rid, out_rid = out_rid, in_rid

    existing = await repo_query(
        "SELECT id FROM relates WHERE in = $in AND out = $out",
        {"in": in_rid, "out": out_rid},
    )
    if existing:
        edge_id = str(existing[0]["id"])
        await repo_query(
            "UPDATE $id SET type = $type, confidence = $confidence, "
            "rationale = $rationale, workspace = $workspace",
            {
                "id": ensure_record_id(edge_id),
                "type": rel_type,
                "confidence": confidence,
                "rationale": rationale,
                "workspace": workspace,
            },
        )
        return {"id": edge_id, "updated": True}

    result = await repo_relate(
        in_rid,
        "relates",
        out_rid,
        {
            "type": rel_type,
            "confidence": confidence,
            "rationale": rationale,
            "workspace": workspace,
        },
    )
    return {"id": str(result[0]["id"]), "updated": False}


async def get_source_relationships(workspace: str) -> list[dict]:
    """Return all `relates` edges for a workspace as plain dicts for the graph API."""
    rows = await repo_query(
        "SELECT in AS source, out AS target, type, confidence, rationale "
        "FROM relates WHERE workspace = $workspace",
        {"workspace": workspace},
    )
    return [
        {
            "source": str(r["source"]),
            "target": str(r["target"]),
            "type": r["type"],
            "confidence": r.get("confidence"),
            "rationale": r.get("rationale"),
        }
        for r in (rows or [])
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_relates.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add open_notebook/domain/brain.py tests/test_brain_relates.py
git commit -m "feat(brain): relate_sources + get_source_relationships (P7.2)"
```

---

### Task 3: `classify_relationship` prompt + `classify_relationships` command

**Files:**
- Create: `prompts/brain/classify_relationship.jinja`
- Modify: `commands/brain_commands.py`
- Test: `tests/test_brain_classify_command.py`

**Interfaces:**
- Consumes: `open_notebook.domain.brain.relate_sources(...)` (Task 2); `open_notebook.domain.notebook.vector_search(keyword, results, source, note, minimum_score)` and `Source.get(id)` (returns object with `.title`, `.full_text`, and a `.workspace` attribute added in P6); `provision_langchain_model`; `Prompter`; `PydanticOutputParser`; `clean_thinking_content`; `extract_text_content`; `CommandInput`/`CommandOutput`/`command`.
- Produces:
  - `class ClassifyRelationshipsInput(CommandInput)` with `source_id: str`, `workspace_id: str`, `top_k: int = 5`.
  - `class RelationshipClassification(BaseModel)` with `type: Literal["supersedes","disagrees","complements","agrees","none"]`, `confidence: float`, `rationale: str`.
  - command `"classify_relationships"` → `classify_relationships_command(input_data)` returning `ClassifyRelationshipsOutput`.

- [ ] **Step 1: Create the prompt template**

```jinja
{# prompts/brain/classify_relationship.jinja #}
# ROLE

You classify the semantic relationship between two research sources in a knowledge graph.

# SOURCE A (the source being classified)

Title: {{ source_a_title }}

{{ source_a_text }}

# SOURCE B (a candidate related source)

Title: {{ source_b_title }}

{{ source_b_text }}

# TASK

Decide how Source A relates to Source B. Choose exactly one `type`:

- `supersedes`: A updates, replaces, or corrects B (A is the newer, authoritative version).
- `disagrees`: A contradicts or argues against a claim in B.
- `complements`: A adds detail to, or extends, B on the same topic without conflict.
- `agrees`: A independently supports or restates the same conclusion as B.
- `none`: there is no meaningful relationship.

Provide a `confidence` between 0.0 and 1.0 and a one-sentence `rationale`.

{{ format_instructions }}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_brain_classify_command.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from surreal_commands import registry

import commands  # noqa: F401  (registers commands)
import commands.brain_commands as brain_commands


def test_classify_relationships_is_registered():
    assert "classify_relationships" in registry.list_commands()["open_notebook"]


@pytest.mark.asyncio
async def test_classify_relationships_creates_edges_and_skips_none(monkeypatch):
    primary = SimpleNamespace(
        title="A", full_text="alpha text", workspace="ws:1"
    )
    cand_a = SimpleNamespace(title="B", full_text="beta text", workspace="ws:1")
    cand_b = SimpleNamespace(title="C", full_text="gamma text", workspace="ws:1")

    async def fake_get(source_id):
        return {
            "source:primary": primary,
            "source:b": cand_a,
            "source:c": cand_b,
        }[source_id]

    monkeypatch.setattr(brain_commands.Source, "get", AsyncMock(side_effect=fake_get))
    # vector_search returns two OTHER sources plus the source itself (must be skipped)
    monkeypatch.setattr(
        brain_commands,
        "vector_search",
        AsyncMock(
            return_value=[
                {"parent_id": "source:primary", "similarity": 1.0},
                {"parent_id": "source:b", "similarity": 0.9},
                {"parent_id": "source:c", "similarity": 0.8},
            ]
        ),
    )
    # Stub the prompt renderer so the test needs no template/format_instructions.
    monkeypatch.setattr(
        brain_commands,
        "Prompter",
        lambda **kw: SimpleNamespace(render=lambda data: "PROMPT"),
    )

    # First pair -> supersedes; second pair -> none (skipped).
    responses = [
        SimpleNamespace(
            content='{"type": "supersedes", "confidence": 0.9, "rationale": "a updates b"}'
        ),
        SimpleNamespace(
            content='{"type": "none", "confidence": 0.1, "rationale": "unrelated"}'
        ),
    ]
    fake_model = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
    monkeypatch.setattr(
        brain_commands, "provision_langchain_model", AsyncMock(return_value=fake_model)
    )

    relate = AsyncMock(return_value={"id": "relates:1", "updated": False})
    monkeypatch.setattr(brain_commands, "relate_sources", relate)

    result = await brain_commands.classify_relationships_command(
        brain_commands.ClassifyRelationshipsInput(
            source_id="source:primary", workspace_id="ws:1", top_k=5
        )
    )

    assert result.success is True
    assert result.edges_created == 1
    relate.assert_awaited_once()
    call = relate.await_args
    assert call.args[0] == "source:primary"
    assert call.args[1] == "source:b"
    assert call.args[2] == "supersedes"
    assert call.args[5] == "ws:1"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_classify_command.py -v`
Expected: FAIL — `AttributeError: module 'commands.brain_commands' has no attribute 'classify_relationships_command'` (and the registration test fails).

- [ ] **Step 4: Implement the command**

Ensure these imports are present at the top of `commands/brain_commands.py` (add any P7.1 did not already add):

```python
import time
from typing import Literal, Optional

from ai_prompter import Prompter
from langchain_core.output_parsers.pydantic import PydanticOutputParser
from loguru import logger
from pydantic import BaseModel
from surreal_commands import CommandInput, CommandOutput, command, submit_command

from open_notebook.ai.provision import provision_langchain_model
from open_notebook.domain.brain import relate_sources
from open_notebook.domain.notebook import Source, vector_search
from open_notebook.exceptions import ConfigurationError
from open_notebook.utils import clean_thinking_content
from open_notebook.utils.text_utils import extract_text_content
```

Then add:

```python
class ClassifyRelationshipsInput(CommandInput):
    """Input for classifying a source against its top-K similar peers."""

    source_id: str
    workspace_id: str
    top_k: int = 5


class ClassifyRelationshipsOutput(CommandOutput):
    """Output from the classify_relationships command."""

    success: bool
    source_id: str
    edges_created: int = 0
    processing_time: float
    error_message: Optional[str] = None


class RelationshipClassification(BaseModel):
    """LLM-parsed classification of one source pair."""

    type: Literal["supersedes", "disagrees", "complements", "agrees", "none"]
    confidence: float
    rationale: str


@command(
    "classify_relationships",
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
async def classify_relationships_command(
    input_data: ClassifyRelationshipsInput,
) -> ClassifyRelationshipsOutput:
    """Classify semantic relationships between a source and its top-K peers.

    Uses vector_search to fetch the top-K most similar OTHER sources in the
    workspace, then asks the LLM to classify each pair. Non-'none' results are
    written as `relates` edges via relate_sources (which dedups + orients).
    Linear in source count (top-K per source), not O(n^2).
    """
    start_time = time.time()
    try:
        source = await Source.get(input_data.source_id)
        if not source or not source.full_text or not source.full_text.strip():
            raise ValueError(
                f"Source '{input_data.source_id}' has no text to classify"
            )

        candidates = await vector_search(
            keyword=source.full_text,
            results=input_data.top_k + 5,  # buffer for self + dupes
            source=True,
            note=False,
        )

        parser = PydanticOutputParser(pydantic_object=RelationshipClassification)
        seen: set[str] = set()
        edges_created = 0

        for cand in candidates or []:
            cand_id = str(cand.get("parent_id") or cand.get("id") or "")
            if (
                not cand_id
                or cand_id == input_data.source_id
                or cand_id in seen
            ):
                continue
            seen.add(cand_id)
            if len(seen) > input_data.top_k:
                break

            other = await Source.get(cand_id)
            if getattr(other, "workspace", None) != input_data.workspace_id:
                continue  # never cross workspace boundaries

            prompt = Prompter(
                prompt_template="brain/classify_relationship", parser=parser
            ).render(
                data={
                    "source_a_title": source.title,
                    "source_a_text": source.full_text,
                    "source_b_title": other.title,
                    "source_b_text": other.full_text,
                }
            )
            model = await provision_langchain_model(
                prompt,
                None,
                "tools",
                max_tokens=1000,
                structured=dict(type="json"),
            )
            ai_message = await model.ainvoke(prompt)
            content = clean_thinking_content(
                extract_text_content(ai_message.content)
            )
            classification = parser.parse(content)

            if classification.type == "none":
                continue

            await relate_sources(
                input_data.source_id,
                cand_id,
                classification.type,
                classification.confidence,
                classification.rationale,
                input_data.workspace_id,
            )
            edges_created += 1

        return ClassifyRelationshipsOutput(
            success=True,
            source_id=input_data.source_id,
            edges_created=edges_created,
            processing_time=time.time() - start_time,
        )

    except (ValueError, ConfigurationError) as e:
        logger.error(
            f"classify_relationships permanent failure for "
            f"{input_data.source_id}: {e}"
        )
        raise  # in stop_on: no retry, job marked failed
    except Exception as e:
        logger.debug(
            f"Transient error classifying relationships for "
            f"{input_data.source_id}: {e}"
        )
        raise
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_classify_command.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add prompts/brain/classify_relationship.jinja commands/brain_commands.py tests/test_brain_classify_command.py
git commit -m "feat(brain): classify_relationships command + prompt (P7.2)"
```

---

### Task 4: `rebuild_brain` command + extract→classify chaining

**Files:**
- Modify: `commands/brain_commands.py`
- Test: `tests/test_brain_classify_command.py` (add tests)

**Interfaces:**
- Consumes: `submit_command`; `repo_query`; the command names `"extract_source_entities"` (P7.1) and `"classify_relationships"` (Task 3).
- Produces:
  - `class RebuildBrainInput(CommandInput)` with `workspace_id: str`, `mode: Literal["incremental","full"] = "incremental"`.
  - command `"rebuild_brain"` → `rebuild_brain_command(input_data)` returning `RebuildBrainOutput`.
  - **Modification to P7.1**: `extract_source_entities` submits `classify_relationships` on completion.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_classify_command.py  (append)
from unittest.mock import MagicMock


def test_rebuild_brain_is_registered():
    from surreal_commands import registry

    assert "rebuild_brain" in registry.list_commands()["open_notebook"]


@pytest.mark.asyncio
async def test_rebuild_brain_full_submits_extract_and_classify_per_source(monkeypatch):
    monkeypatch.setattr(
        brain_commands,
        "repo_query",
        AsyncMock(return_value=[{"id": "source:1"}, {"id": "source:2"}]),
    )
    submit = MagicMock()
    monkeypatch.setattr(brain_commands, "submit_command", submit)

    result = await brain_commands.rebuild_brain_command(
        brain_commands.RebuildBrainInput(workspace_id="ws:1", mode="full")
    )

    assert result.success is True
    assert result.sources_processed == 2
    submitted = [(c.args[1], c.args[2]) for c in submit.call_args_list]
    assert ("extract_source_entities", {"source_id": "source:1", "workspace_id": "ws:1"}) in submitted
    assert ("classify_relationships", {"source_id": "source:1", "workspace_id": "ws:1"}) in submitted
    assert ("extract_source_entities", {"source_id": "source:2", "workspace_id": "ws:1"}) in submitted


@pytest.mark.asyncio
async def test_rebuild_brain_incremental_filters_unbuilt_sources(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(brain_commands, "repo_query", query)
    monkeypatch.setattr(brain_commands, "submit_command", MagicMock())

    await brain_commands.rebuild_brain_command(
        brain_commands.RebuildBrainInput(workspace_id="ws:1", mode="incremental")
    )

    sql = query.await_args.args[0]
    assert "->mentions" in sql  # only sources without extracted entities
    assert "workspace = $workspace" in sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_classify_command.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'rebuild_brain_command'`.

- [ ] **Step 3: Implement `rebuild_brain` and chain the extract command**

Add to `commands/brain_commands.py` (ensure `repo_query` is imported: `from open_notebook.database.repository import repo_query`):

```python
class RebuildBrainInput(CommandInput):
    """Input for the workspace-level rebuild orchestration command."""

    workspace_id: str
    mode: Literal["incremental", "full"] = "incremental"


class RebuildBrainOutput(CommandOutput):
    """Output from the rebuild_brain command."""

    success: bool
    workspace_id: str
    sources_processed: int = 0
    processing_time: float
    error_message: Optional[str] = None


@command("rebuild_brain", app="open_notebook", retry=None)
async def rebuild_brain_command(
    input_data: RebuildBrainInput,
) -> RebuildBrainOutput:
    """Orchestrate brain (re)build across a workspace.

    Incremental (default) processes only sources that have no extracted
    entities yet (no outgoing `mentions` edge); full processes every source.
    For each source, submits extract_source_entities then classify_relationships
    (extract also chains classify on completion; relate_sources dedup makes the
    overlap idempotent). Fire-and-forget; returns after submitting.
    """
    start_time = time.time()
    try:
        if input_data.mode == "incremental":
            rows = await repo_query(
                "SELECT id FROM source "
                "WHERE workspace = $workspace AND array::len(->mentions) == 0",
                {"workspace": input_data.workspace_id},
            )
        else:
            rows = await repo_query(
                "SELECT id FROM source WHERE workspace = $workspace",
                {"workspace": input_data.workspace_id},
            )

        processed = 0
        for row in rows or []:
            source_id = str(row["id"])
            payload = {
                "source_id": source_id,
                "workspace_id": input_data.workspace_id,
            }
            submit_command("open_notebook", "extract_source_entities", payload)
            submit_command("open_notebook", "classify_relationships", payload)
            processed += 1

        return RebuildBrainOutput(
            success=True,
            workspace_id=input_data.workspace_id,
            sources_processed=processed,
            processing_time=time.time() - start_time,
        )
    except Exception as e:
        logger.error(f"rebuild_brain failed for {input_data.workspace_id}: {e}")
        logger.exception(e)
        return RebuildBrainOutput(
            success=False,
            workspace_id=input_data.workspace_id,
            processing_time=time.time() - start_time,
            error_message=str(e),
        )
```

**Modification to P7.1's `extract_source_entities`** — immediately before its successful `return ...Output(...)`, add the classify chaining:

```python
        # P7.2: chain relationship classification once entities are extracted.
        submit_command(
            "open_notebook",
            "classify_relationships",
            {
                "source_id": input_data.source_id,
                "workspace_id": input_data.workspace_id,
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_classify_command.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add commands/brain_commands.py tests/test_brain_classify_command.py
git commit -m "feat(brain): rebuild_brain orchestration + extract->classify chain (P7.2)"
```

---

### Task 5: `get_brain_status` + `trigger_rebuild` + `get_brain_graph` relates; API models

**Files:**
- Modify: `api/brain_service.py`
- Modify: `api/models.py`
- Test: `tests/test_brain_status_rebuild_api.py`

**Interfaces:**
- Consumes (P7.1): `api/brain_service.py` module with `async def get_brain_graph(ctx, domain, limit) -> BrainGraphResponse` and API models `BrainNode`, `BrainEdge` (whose `type` `Literal` already includes `'part_of','mentions','supersedes','disagrees','complements','agrees'`), `BrainGraphResponse`. Consumes `get_source_relationships(workspace)` (Task 2), `submit_command`, `repo_query`, and the P6 request context (`ctx.workspace_id`, `ctx.role`).
- Produces:
  - `api/brain_models.py`: `BrainStatusResponse{total_sources: int, built_sources: int, running: bool}`, `BrainRebuildRequest{mode: Literal["incremental","full"] = "incremental"}`, `BrainRebuildResponse{command_id: str}`.
  - `api/brain_service.py`: `async def get_brain_status(ctx) -> BrainStatusResponse`, `async def trigger_rebuild(ctx, mode: str) -> str`.
  - **Modification to P7.1**: `get_brain_graph` now also appends `relates` edges.

- [ ] **Step 1: Add API models**

In `api/brain_models.py` (the file P7.1 created; ensure `from typing import Literal` and `from pydantic import BaseModel` are imported):

```python
class BrainStatusResponse(BaseModel):
    total_sources: int
    built_sources: int
    running: bool


class BrainRebuildRequest(BaseModel):
    mode: Literal["incremental", "full"] = "incremental"


class BrainRebuildResponse(BaseModel):
    command_id: str
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_brain_status_rebuild_api.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import api.brain_service as brain_service
from api.brain_models import BrainStatusResponse


def _ctx(workspace_id="ws:1", role="owner"):
    return SimpleNamespace(workspace_id=workspace_id, user_id="user:1", role=role)


@pytest.mark.asyncio
async def test_get_brain_status_reports_coverage(monkeypatch):
    # First query = total, second = built.
    query = AsyncMock(side_effect=[[{"c": 5}], [{"c": 3}]])
    monkeypatch.setattr(brain_service, "repo_query", query)

    status = await brain_service.get_brain_status(_ctx())

    assert isinstance(status, BrainStatusResponse)
    assert status.total_sources == 5
    assert status.built_sources == 3
    assert status.running is True  # unbuilt sources remain
    # both queries scoped by workspace
    for call in query.await_args_list:
        assert call.args[1] == {"workspace": "ws:1"}


@pytest.mark.asyncio
async def test_get_brain_status_all_built_not_running(monkeypatch):
    monkeypatch.setattr(
        brain_service, "repo_query", AsyncMock(side_effect=[[{"c": 2}], [{"c": 2}]])
    )
    status = await brain_service.get_brain_status(_ctx())
    assert status.running is False


@pytest.mark.asyncio
async def test_trigger_rebuild_submits_command_and_returns_id(monkeypatch):
    submit = MagicMock(return_value="command:xyz")
    monkeypatch.setattr(brain_service, "submit_command", submit)

    command_id = await brain_service.trigger_rebuild(_ctx(), "full")

    assert command_id == "command:xyz"
    submit.assert_called_once_with(
        "open_notebook", "rebuild_brain", {"workspace_id": "ws:1", "mode": "full"}
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_status_rebuild_api.py -v`
Expected: FAIL — `AttributeError: module 'api.brain_service' has no attribute 'get_brain_status'`.

- [ ] **Step 4: Implement the service functions and update the graph**

Ensure imports in `api/brain_service.py` (add any missing):

```python
from surreal_commands import submit_command

from api.brain_models import BrainStatusResponse
from open_notebook.database.repository import repo_query
from open_notebook.domain.brain import get_source_relationships
```

Add:

```python
async def get_brain_status(ctx) -> BrainStatusResponse:
    """Extraction coverage for the active workspace: built sources / total."""
    total_rows = await repo_query(
        "SELECT count() AS c FROM source WHERE workspace = $workspace GROUP ALL",
        {"workspace": ctx.workspace_id},
    )
    total_sources = total_rows[0]["c"] if total_rows else 0

    built_rows = await repo_query(
        "SELECT count() AS c FROM source "
        "WHERE workspace = $workspace AND array::len(->mentions) > 0 GROUP ALL",
        {"workspace": ctx.workspace_id},
    )
    built_sources = built_rows[0]["c"] if built_rows else 0

    # Work remaining implies a build is in progress / needed.
    running = total_sources > 0 and built_sources < total_sources
    return BrainStatusResponse(
        total_sources=total_sources,
        built_sources=built_sources,
        running=running,
    )


async def trigger_rebuild(ctx, mode: str) -> str:
    """Submit rebuild_brain for the active workspace; returns the command id.

    Authorization (owner/admin) is enforced at the route via require_role.
    """
    command_id = submit_command(
        "open_notebook",
        "rebuild_brain",
        {"workspace_id": ctx.workspace_id, "mode": mode},
    )
    return str(command_id)
```

**Modification to P7.1's `get_brain_graph`** — after it has assembled its `edges` list from `part_of`/`mentions` and before building the `BrainGraphResponse`, append the `relates` edges:

```python
    # P7.2: include semantic relationship edges.
    for rel in await get_source_relationships(ctx.workspace_id):
        edges.append(
            BrainEdge(
                source=rel["source"],
                target=rel["target"],
                type=rel["type"],
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_status_rebuild_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add api/brain_service.py api/brain_models.py tests/test_brain_status_rebuild_api.py
git commit -m "feat(brain): get_brain_status, trigger_rebuild, relates in graph (P7.2)"
```

---

### Task 6: `/brain/status` + `/brain/rebuild` routes

**Files:**
- Modify: `api/routers/brain.py`
- Test: `tests/test_brain_status_rebuild_api.py` (add route tests)

**Interfaces:**
- Consumes (P6): `from api.deps import CtxDep, require_role`; the P6 request-context dependency function (referenced here as `get_request_context`, the callable behind `CtxDep`). Consumes `get_brain_status`, `trigger_rebuild` (Task 5) and models from Task 5.
- Produces: `GET /brain/status` → `BrainStatusResponse` (any member); `POST /brain/rebuild` body `{mode}` → `BrainRebuildResponse{command_id}` (owner/admin via `require_role`). Exposes a module-level dependency `owner_or_admin = require_role("owner", "admin")` so it can be overridden in tests.

- [ ] **Step 1: Write the failing route tests**

```python
# tests/test_brain_status_rebuild_api.py  (append)
from fastapi.testclient import TestClient


def _client(monkeypatch, role="owner"):
    from api.main import app
    from api.deps import get_request_context
    import api.routers.brain as brain_router

    ctx = _ctx(role=role)
    app.dependency_overrides[get_request_context] = lambda: ctx
    # require_role gate: allow when role permits, else 403
    def _gate():
        if role not in ("owner", "admin"):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="forbidden")
        return ctx

    app.dependency_overrides[brain_router.owner_or_admin] = _gate
    return TestClient(app), app


def test_brain_status_route(monkeypatch):
    import api.routers.brain as brain_router

    monkeypatch.setattr(
        brain_router,
        "get_brain_status",
        AsyncMock(
            return_value=BrainStatusResponse(
                total_sources=4, built_sources=2, running=True
            )
        ),
    )
    client, app = _client(monkeypatch)
    try:
        resp = client.get("/api/brain/status")
        assert resp.status_code == 200
        assert resp.json() == {
            "total_sources": 4,
            "built_sources": 2,
            "running": True,
        }
    finally:
        app.dependency_overrides.clear()


def test_brain_rebuild_route_owner(monkeypatch):
    import api.routers.brain as brain_router

    monkeypatch.setattr(
        brain_router, "trigger_rebuild", AsyncMock(return_value="command:abc")
    )
    client, app = _client(monkeypatch, role="owner")
    try:
        resp = client.post("/api/brain/rebuild", json={"mode": "full"})
        assert resp.status_code == 200
        assert resp.json() == {"command_id": "command:abc"}
    finally:
        app.dependency_overrides.clear()


def test_brain_rebuild_route_forbidden_for_member(monkeypatch):
    client, app = _client(monkeypatch, role="member")
    try:
        resp = client.post("/api/brain/rebuild", json={"mode": "incremental"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_status_rebuild_api.py -k route -v`
Expected: FAIL — `AttributeError: module 'api.routers.brain' has no attribute 'owner_or_admin'` / 404 on the routes.

- [ ] **Step 3: Add the routes**

In `api/routers/brain.py` (P7.1 already defines `router` and `GET /brain/graph`), ensure imports:

```python
from fastapi import Depends

from api.brain_service import get_brain_status, trigger_rebuild
from api.deps import CtxDep, require_role
from api.brain_models import (
    BrainRebuildRequest,
    BrainRebuildResponse,
    BrainStatusResponse,
)

# Module-level so tests can override it via app.dependency_overrides.
owner_or_admin = require_role("owner", "admin")
```

Add the endpoints:

```python
@router.get("/brain/status", response_model=BrainStatusResponse)
async def brain_status(ctx: CtxDep) -> BrainStatusResponse:
    """Extraction coverage + build state for the active workspace (any member)."""
    return await get_brain_status(ctx)


@router.post("/brain/rebuild", response_model=BrainRebuildResponse)
async def brain_rebuild(
    body: BrainRebuildRequest,
    ctx: CtxDep,
    _member=Depends(owner_or_admin),
) -> BrainRebuildResponse:
    """Trigger a workspace brain rebuild (owner/admin only)."""
    command_id = await trigger_rebuild(ctx, body.mode)
    return BrainRebuildResponse(command_id=command_id)
```

(The router is already registered in `api/main.py` by P7.1 as
`app.include_router(brain.router, prefix="/api", tags=["brain"])`; no change needed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_status_rebuild_api.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add api/routers/brain.py tests/test_brain_status_rebuild_api.py
git commit -m "feat(brain): /brain/status + /brain/rebuild routes (P7.2)"
```

---

### Task 7: Extend the P6 tenant-leakage suite to `relates`

**Files:**
- Create: `tests/test_brain_relates_leakage.py`
- Test: `tests/test_brain_relates_leakage.py`

**Interfaces:**
- Consumes: `get_source_relationships(workspace)` (Task 2) and `get_brain_status(ctx)` (Task 5).
- Produces: proof that workspace A never reads workspace B's `relates` edges, including a personal-vs-personal case. No production code — tests only.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_relates_leakage.py
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import open_notebook.domain.brain as brain
import api.brain_service as brain_service


# Simulated per-workspace store of relates edges.
_EDGES = {
    "ws:a": [
        {
            "source": "source:a1",
            "target": "source:a2",
            "type": "agrees",
            "confidence": 0.9,
            "rationale": "a-only",
        }
    ],
    "ws:b": [
        {
            "source": "source:b1",
            "target": "source:b2",
            "type": "supersedes",
            "confidence": 0.8,
            "rationale": "b-only",
        }
    ],
    # Two distinct PERSONAL workspaces (personal-vs-personal case).
    "ws:personal-1": [
        {
            "source": "source:p1",
            "target": "source:p2",
            "type": "complements",
            "confidence": 0.7,
            "rationale": "p1-only",
        }
    ],
    "ws:personal-2": [],
}


@pytest.mark.asyncio
async def test_get_source_relationships_never_crosses_workspace(monkeypatch):
    async def fake_query(sql, params):
        assert "workspace = $workspace" in sql  # scoping is enforced in SQL
        return _EDGES.get(params["workspace"], [])

    monkeypatch.setattr(brain, "repo_query", AsyncMock(side_effect=fake_query))

    a = await brain.get_source_relationships("ws:a")
    b = await brain.get_source_relationships("ws:b")

    assert {e["rationale"] for e in a} == {"a-only"}
    assert {e["rationale"] for e in b} == {"b-only"}
    assert all(e["rationale"] != "b-only" for e in a)


@pytest.mark.asyncio
async def test_personal_vs_personal_isolation(monkeypatch):
    async def fake_query(sql, params):
        return _EDGES.get(params["workspace"], [])

    monkeypatch.setattr(brain, "repo_query", AsyncMock(side_effect=fake_query))

    p1 = await brain.get_source_relationships("ws:personal-1")
    p2 = await brain.get_source_relationships("ws:personal-2")

    assert {e["rationale"] for e in p1} == {"p1-only"}
    assert p2 == []  # a second personal brain sees none of the first's edges


@pytest.mark.asyncio
async def test_brain_status_counts_are_workspace_scoped(monkeypatch):
    seen_params = []

    async def fake_query(sql, params):
        seen_params.append(params)
        return [{"c": 1}]

    monkeypatch.setattr(brain_service, "repo_query", AsyncMock(side_effect=fake_query))
    ctx = SimpleNamespace(workspace_id="ws:a", user_id="u", role="owner")

    await brain_service.get_brain_status(ctx)

    assert seen_params and all(p == {"workspace": "ws:a"} for p in seen_params)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_brain_relates_leakage.py -v`
Expected: FAIL initially only if earlier tasks are incomplete; if Tasks 2 & 5 are done these should already PASS. Run to confirm the scoping assertions hold (the SQL-contains-`workspace` assertion is the guard that would fail if a later refactor drops scoping).

- [ ] **Step 3: (No production change needed)**

These tests lock in the workspace-scoping behavior already implemented in Tasks 2 and 5. If any assertion fails, fix the offending query to filter by `workspace = $workspace` — do not weaken the test.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_relates_leakage.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite + lint + typecheck**

Run: `uv run pytest tests/ && ruff check . --fix && uv run python -m mypy .`
Expected: PASS / no errors.

- [ ] **Step 6: Commit**

```bash
git add tests/test_brain_relates_leakage.py
git commit -m "test(brain): extend P6 leakage suite to relates edges (P7.2)"
```

---

## Self-Review

**1. Spec coverage** (against the P7.2 scope in the design spec and task brief):
- `relates` migration (edge source→source; fields type/confidence/rationale/workspace/created; workspace index; `_down`; registered in `AsyncMigrationManager`) → **Task 1**. Migration number is **21** (highest existing is 19; P7.1 adds 20; P7.2 adds 21).
- `relate_sources` (dedup ordered pair; `supersedes` oriented newer→older by `Source.created`) + `get_source_relationships` → **Task 2**.
- `classify_relationships` command (vector_search top-K other sources; per-pair LLM via `provision_langchain_model` + `Prompter("brain/classify_relationship")`; skip `none`; call `relate_sources`) + prompt with `{{ format_instructions }}` → **Task 3**.
- `rebuild_brain` command (incremental = sources without entities; full = all; submits extract then classify per source) + `extract_source_entities`→`classify_relationships` chaining (noted as a P7.1 modification) → **Task 4**.
- `get_brain_status` + `trigger_rebuild` (role gate at route) + `get_brain_graph` updated to include `relates` (noted as a P7.1 modification) + `BrainStatusResponse` → **Task 5**.
- `GET /brain/status` (any member) + `POST /brain/rebuild` (owner/admin via `require_role`) → **Task 6**.
- Tests: relates edge dedup + supersedes orientation (Task 2), mocked-LLM determinism (Task 3), rebuild orchestration (Task 4), status/rebuild service + routes (Tasks 5–6), P6 leakage extended to `relates` incl. personal-vs-personal (Task 7). All present.

**2. Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" — every code and test step contains complete, concrete content. All SurrealQL, Python, and pytest are real with concrete assertions. LLM (`provision_langchain_model`) and `vector_search` are mocked in every command test for determinism.

**3. Type consistency:** Names are used verbatim across tasks: `relate_sources(source_id, target_id, rel_type, confidence, rationale, workspace)`, `get_source_relationships(workspace)`, `ClassifyRelationshipsInput{source_id, workspace_id, top_k=5}`, `RebuildBrainInput{workspace_id, mode}`, commands `classify_relationships` / `rebuild_brain`, `get_brain_status(ctx)`, `trigger_rebuild(ctx, mode)`, `BrainStatusResponse{total_sources, built_sources, running}`, `BrainRebuildRequest{mode}`, `BrainRebuildResponse{command_id}`, and the `relates` edge fields — all consistent. `BrainEdge`/`BrainGraphResponse`/`require_role`/`CtxDep`/`extract_source_entities`/`Entity` are consumed from P7.1/P6 exactly as named in the interface contract.

**Explicitly modified P7.1/P6 files (not redefined):** `async_migrate.py` (register 21), `open_notebook/domain/brain.py` (add two functions), `commands/brain_commands.py` (add two commands + chain in `extract_source_entities`), `api/brain_service.py` (add two functions + extend `get_brain_graph`), `api/routers/brain.py` (add two routes), `api/brain_models.py` (add three models).
