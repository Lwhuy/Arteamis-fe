# P8.5 — Trace + Learning (close the loop) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 8-step Arteamis governed-promotion loop. A `work_package` (P8.4) that was executed produces a **trace** (what happened, sources touched, outcome) which can spawn a **learning proposal** — a `proposal(kind='learning')` that goes through the exact same propose-only review as any other proposal (never an automatic write) and, once accepted, **updates** the original belief (superseding it, carrying forward its provenance, and recording the `updates` edge back to the belief it revises).

**Architecture:** Extends the existing single-tenant, workspace-ready governance stack (`open_notebook/domain/governance.py` → `api/governance_service.py` → `api/routers/governance.py`) with a new `trace` table and three graph edges (`traced_by`, `learned_from`, `updates`). Reuses the `proposal`/`belief`/`audit_event` machinery from P8.2 wholesale — a learning update is not a new write path, it is a new `kind` of proposal flowing through the same `accept_proposal`/`request_changes` state machine, which is what makes it propose-only by construction. Frontend adds a `TraceSection` (record outcome → propose learning), a small "Learning" badge on `ReviewInbox` entries, and an "Updated from real outcome" callout in `LineagePanel` so the belief's lineage visibly shows it was revised by a traced result.

**Tech Stack:** SurrealDB migrations, FastAPI, Python 3.12 (`uv`, pytest, ruff), surreal graph edges, Next.js 16 / React 19 / TanStack Query 5 / Zustand 5 / vitest.

## Global Constraints

- **Depends on P8.0–P8.4** (control plane shell, scope store, artifact reader, Promotion Bridge `proposal`/`belief`/`audit_event`, P8.3 `decision`/`rule` (migration 23, landed), P8.4 `work_package` (migration 24, landed)). Treat all as landed; this plan does not re-derive their schemas beyond the `work_package` record id it links to.
- **Migrations are hard-coded, not auto-discovered** (per `open_notebook/AGENTS.md`): next free migration number is **25**. Existing sequence: 20=workspace, 21=visibility, 22=governance (`proposal`/`belief`/`audit_event`), 23=decision/rule, 24=work_package. This plan adds `25.surrealql` + `25_down.surrealql` and registers both in `AsyncMigrationManager.__init__` (`open_notebook/database/async_migrate.py`), immediately after the existing `24.surrealql`/`24_down.surrealql` entries.
- **`table_name` is a `ClassVar[str]` on `ObjectModel` subclasses** (see `open_notebook/domain/base.py:34`), not a plain field — every new domain model follows this exact declaration.
- **CRITICAL LESSON (was a P8.2 Critical bug): every `record<>` link field needs `_prepare_save_data()` + `ensure_record_id()`.** `ObjectModel._prepare_save_data()` only strips `None` fields — it does **not** convert record-link strings (e.g. `"work_package:1"`) into `RecordID` before they reach `repo_create`/`repo_update`. Any field typed `record<...>` in the migration (here: `Trace.work_package`, `Trace.command`) **must** be converted via `open_notebook.database.repository.ensure_record_id` inside an overridden `_prepare_save_data()`, exactly like `Proposal.author` and `AuditEvent.actor`/`object` already do in `open_notebook/domain/governance.py`. `Trace.work_package` is a first-class task (Task 2) with a dedicated test asserting the `RecordID` conversion — do not skip it.
- **DB-free mocked tests.** Backend service/router tests never hit a live SurrealDB — they patch `open_notebook.domain.base.repo_create`/`repo_query`/`repo_update` (used by `ObjectModel.save()`/`get()`/`get_all()`) and `api.governance_service.repo_query`/`repo_relate` (used for raw graph-edge reads/writes) with `unittest.mock.AsyncMock`, exactly as `tests/test_governance_service.py` and `tests/test_governance_router.py` already do. Router tests use `fastapi.testclient.TestClient` + `@patch("api.routers.governance.<fn>")`, not a live app/DB fixture.
- **i18n is test-enforced across all 14 locales**: `bn-IN, ca-ES, de-DE, en-US, es-ES, fr-FR, it-IT, ja-JP, pl-PL, pt-BR, ru-RU, tr-TR, zh-CN, zh-TW` (`frontend/src/lib/locales/<code>/index.ts`). Every new UI string goes through `t('section.key')`; `frontend/src/lib/locales/index.test.ts` fails the build if any locale is missing a key en-US has (or has one en-US lacks), and separately fails if any en-US leaf key is unreferenced in source. New keys must be added to **all 14** files and referenced in a `.tsx`/`.ts` source file.
- **`apiClient` + TanStack Query only.** All HTTP goes through `frontend/src/lib/api/client.ts`'s default-exported `apiClient`; no second axios instance. Query/mutation hooks live in `frontend/src/lib/hooks/`, mutations invalidate the relevant query keys and toast via `useToast`.
- **Single-tenant / workspace-ready.** `trace` carries `workspace: option<record<workspace>>` (nullable, unused by the domain model layer for now — matches how `Proposal`/`Belief`/`AuditEvent` already omit `workspace` from their Pydantic fields even though the DB column exists). No role gating in this plan.
- **Propose-only writes — learning NEVER auto-writes to a belief.** Per PRD §1.6A/§4.5B, the only way a belief changes because of a traced outcome is: `record_trace` → `create_learning_proposal` (creates a `pending` `proposal(kind='learning')`, does **not** touch any belief) → a reviewer calls the existing `accept_proposal` endpoint → **only then** is a new (superseding) belief written. There is no code path that lets a trace or a work package write to `belief` directly.
- **Audit every transition.** `record_trace` → `trace.recorded`; `create_learning_proposal` → `learning.proposed`; accepting a learning proposal → `proposal.accepted` (with `meta.kind='learning'`), same `_audit()` helper already in `api/governance_service.py`.
- Backend: `uv run pytest tests/`, `ruff check . --fix`. Frontend (run inside `frontend/`): `npm run test`, `npm run lint`, `npm run build`.

---

### Task 1: Migration 25 — `trace` table + `traced_by`/`learned_from`/`updates` edges

**Files:**
- Create: `open_notebook/database/migrations/25.surrealql`
- Create: `open_notebook/database/migrations/25_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (register both, right after the `24.surrealql`/`24_down.surrealql` entries)
- Test: `tests/test_migration_25_trace.py`

**Interfaces:**
- Produces table `trace` and edges `traced_by` (work_package→trace), `learned_from` (proposal→trace, carries the target `belief`), `updates` (belief→belief, carries the justifying `trace`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_25_trace.py
from pathlib import Path


def test_migration_25_defines_trace_tables():
    up = Path("open_notebook/database/migrations/25.surrealql").read_text()
    for t in [
        "DEFINE TABLE trace",
        "DEFINE TABLE traced_by",
        "DEFINE TABLE learned_from",
        "DEFINE TABLE updates",
    ]:
        assert t in up, t
    assert "work_package" in up
    assert "workspace" in up  # workspace-ready
    down = Path("open_notebook/database/migrations/25_down.surrealql").read_text()
    assert "REMOVE TABLE trace" in down


def test_migration_25_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "25.surrealql" in src and "25_down.surrealql" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration_25_trace.py -v`
Expected: FAIL — files don't exist yet.

- [ ] **Step 3: Write the migration**

```surql
-- open_notebook/database/migrations/25.surrealql
-- Migration 25: trace + learning tables (Trace + Learning loop closure, P8.5).
-- A work_package (P8.4, migration 24) produces a trace of what actually
-- happened; a trace can spawn a learning proposal (kind='learning' on the
-- existing `proposal` table from migration 22 -- PROPOSAL_KINDS already
-- includes 'learning') that, once accepted, updates the belief it traces
-- back to. Mirrors migration 22/23's workspace-ready idiom: nullable
-- option<record<workspace>>, FLEXIBLE. `learned_from` carries the target
-- belief id and `updates` carries the trace id that justified the update --
-- same idiom as `derived_from`'s `locator` field in migration 22.

DEFINE TABLE trace SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS workspace     ON TABLE trace FLEXIBLE TYPE option<record<workspace>>;
DEFINE FIELD IF NOT EXISTS work_package  ON TABLE trace TYPE record<work_package>;
DEFINE FIELD IF NOT EXISTS summary       ON TABLE trace TYPE string;
DEFINE FIELD IF NOT EXISTS sources_used  ON TABLE trace FLEXIBLE TYPE option<array>;
DEFINE FIELD IF NOT EXISTS command       ON TABLE trace FLEXIBLE TYPE option<record>;
DEFINE FIELD IF NOT EXISTS outcome       ON TABLE trace TYPE string DEFAULT 'pending' ASSERT $value IN ['pending','success','fail','mixed'];
DEFINE FIELD IF NOT EXISTS created       ON trace DEFAULT time::now() VALUE $before OR time::now();

-- edges
DEFINE TABLE traced_by SCHEMAFULL TYPE RELATION;

DEFINE TABLE learned_from SCHEMAFULL TYPE RELATION;
DEFINE FIELD IF NOT EXISTS belief ON TABLE learned_from TYPE option<record<belief>>;

DEFINE TABLE updates SCHEMAFULL TYPE RELATION;
DEFINE FIELD IF NOT EXISTS trace ON TABLE updates TYPE option<record<trace>>;
```

```surql
-- open_notebook/database/migrations/25_down.surrealql
-- Migration 25 rollback: drop edges before the tables they reference, then
-- the trace table itself.
REMOVE TABLE updates;
REMOVE TABLE learned_from;
REMOVE TABLE traced_by;
REMOVE TABLE trace;
```

- [ ] **Step 4: Register in `AsyncMigrationManager`**

Open `open_notebook/database/async_migrate.py`. Find the existing entries for `24.surrealql` in `self.up_migrations` and `24_down.surrealql` in `self.down_migrations` (added by P8.4) and add a new entry directly after each, following the exact multi-line `AsyncMigration.from_file(...)` style already used for every other migration:

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/25.surrealql"
            ),
```

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/25_down.surrealql"
            ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_migration_25_trace.py -v`
Expected: PASS.

- [ ] **Step 6: Apply + smoke**

Run: `make database && make api`; confirm the startup logs advance to migration 25 without error.

- [ ] **Step 7: Commit**

```bash
git add open_notebook/database/migrations/25.surrealql open_notebook/database/migrations/25_down.surrealql open_notebook/database/async_migrate.py tests/test_migration_25_trace.py
git commit -m "feat(governance): migration 25 - trace table + traced_by/learned_from/updates edges"
```

---

### Task 2: `Trace` domain model — with the record-link save-data conversion

**Files:**
- Modify: `open_notebook/domain/governance.py` (append `TRACE_OUTCOMES` + `Trace`)
- Modify: `tests/test_governance_models.py` (defaults/validation)
- Modify: `tests/test_governance_record_links.py` (the CRITICAL record-link conversion test)

**Interfaces:**
- Produces `Trace(ObjectModel)`: `table_name: ClassVar[str] = "trace"`; fields `work_package: str`, `summary: str`, `sources_used: list[str] = []`, `command: Optional[str] = None`, `outcome: str = "pending"` (validated against `TRACE_OUTCOMES`); overrides `_prepare_save_data()` to convert `work_package` and (when present) `command` via `ensure_record_id`.
- Produces module constant `TRACE_OUTCOMES = ["pending", "success", "fail", "mixed"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_governance_models.py`:

```python
from open_notebook.domain.governance import TRACE_OUTCOMES, Trace


def test_trace_defaults():
    tr = Trace(work_package="work_package:1", summary="Ran the SMB outreach playbook")
    assert tr.outcome == "pending"
    assert tr.sources_used == []


def test_trace_rejects_bad_outcome():
    with pytest.raises(Exception):
        Trace(work_package="work_package:1", summary="x", outcome="banana")


def test_trace_outcomes_constant():
    assert set(TRACE_OUTCOMES) == {"pending", "success", "fail", "mixed"}
```

(Adjust the existing `from open_notebook.domain.governance import (...)` import at the top of the file to include `TRACE_OUTCOMES, Trace` instead of a second import line — keep one import block.)

Append to `tests/test_governance_record_links.py`:

```python
from open_notebook.domain.governance import Trace


def test_trace_work_package_converted_to_record_id():
    tr = Trace(work_package="work_package:1", summary="x")
    data = tr._prepare_save_data()
    assert isinstance(data["work_package"], RecordID)
    assert not isinstance(data["work_package"], str)
    assert data["work_package"] == RecordID.parse("work_package:1")


def test_trace_command_converted_to_record_id_when_present():
    tr = Trace(work_package="work_package:1", summary="x", command="command:9")
    data = tr._prepare_save_data()
    assert isinstance(data["command"], RecordID)
    assert data["command"] == RecordID.parse("command:9")


def test_trace_command_none_is_left_none():
    tr = Trace(work_package="work_package:1", summary="x")
    data = tr._prepare_save_data()
    assert data.get("command") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_governance_models.py tests/test_governance_record_links.py -v`
Expected: FAIL — `Trace`/`TRACE_OUTCOMES` don't exist yet.

- [ ] **Step 3: Implement `Trace`**

Append to `open_notebook/domain/governance.py` (after the existing `AuditEvent` class):

```python
TRACE_OUTCOMES = ["pending", "success", "fail", "mixed"]


class Trace(ObjectModel):
    table_name: ClassVar[str] = "trace"
    work_package: str
    summary: str
    sources_used: list[str] = Field(default_factory=list)
    command: Optional[str] = None
    outcome: str = "pending"

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, v: str) -> str:
        if v not in TRACE_OUTCOMES:
            raise ValueError(f"invalid outcome {v}")
        return v

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("work_package") is not None:
            data["work_package"] = ensure_record_id(data["work_package"])
        if data.get("command") is not None:
            data["command"] = ensure_record_id(data["command"])
        return data
```

No new imports are needed — `Field`, `field_validator`, `ClassVar`, `Any`, `Dict`, `Optional`, `ensure_record_id`, and `ObjectModel` are already imported at the top of `open_notebook/domain/governance.py` for `Proposal`/`Belief`/`AuditEvent`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_governance_models.py tests/test_governance_record_links.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add open_notebook/domain/governance.py tests/test_governance_models.py tests/test_governance_record_links.py
git commit -m "feat(governance): Trace domain model with record-link save-data conversion"
```

---

### Task 3: Service — `record_trace` / `get_trace` / `list_traces_for_work_package`

**Files:**
- Modify: `api/governance_service.py`
- Modify: `tests/test_governance_service.py`

**Interfaces:**
- Consumes: `Trace` (Task 2); existing `repo_query`/`repo_relate` imports and `_audit()` helper already in `api/governance_service.py`.
- Produces (async functions):
  - `record_trace(actor: str, work_package_id: str, *, summary: str, sources_used: list[str] | None = None, outcome: str = "pending") -> Trace` — saves the trace, `RELATE work_package->traced_by->trace`, `audit_event(action='trace.recorded', object=trace.id, meta={'work_package': work_package_id, 'outcome': outcome})`.
  - `get_trace(trace_id: str) -> Trace`.
  - `list_traces_for_work_package(work_package_id: str) -> list[dict]` — reads the `traced_by` edge (no domain-model equivalent for a graph traversal, so `repo_query` as `derived_from`/lineage reads already do).

- [ ] **Step 1: Write the failing tests**

Add imports at the top of `tests/test_governance_service.py` (extend the existing `from api.governance_service import (...)` and `from open_notebook.domain.governance import (...)` blocks):

```python
from api.governance_service import (
    accept_proposal,
    create_proposal,
    get_belief_lineage,
    get_proposal,
    get_trace,
    list_proposals,
    list_traces_for_work_package,
    record_trace,
    request_changes,
)
from open_notebook.domain.governance import Belief, Proposal, Trace
```

Append test cases:

```python
@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_record_trace_saves_relates_and_audits(mock_create, mock_relate):
    mock_create.side_effect = [
        [{"id": "trace:1", "work_package": "work_package:1", "summary": "Ran playbook", "outcome": "success"}],  # trace.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    trace = await record_trace(
        "user:1", "work_package:1",
        summary="Ran playbook", sources_used=["source:1"], outcome="success",
    )

    assert trace.id == "trace:1"
    assert trace.outcome == "success"
    mock_relate.assert_awaited_once_with("work_package:1", "traced_by", "trace:1", {})

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "trace.recorded"
    assert audit_data["meta"] == {"work_package": "work_package:1", "outcome": "success"}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_trace_returns_trace(mock_query):
    mock_query.return_value = [
        {"id": "trace:1", "work_package": "work_package:1", "summary": "x", "outcome": "pending"}
    ]
    trace = await get_trace("trace:1")
    assert isinstance(trace, Trace)
    assert trace.id == "trace:1"


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
async def test_list_traces_for_work_package_returns_edge_rows(mock_query):
    mock_query.return_value = [
        {"id": "trace:1", "summary": "Ran playbook", "outcome": "success", "created": "2026-07-12T00:00:00Z"}
    ]
    rows = await list_traces_for_work_package("work_package:1")
    assert rows[0]["id"] == "trace:1"
    mock_query.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: FAIL — `record_trace`/`get_trace`/`list_traces_for_work_package` don't exist yet.

- [ ] **Step 3: Implement**

Add to `api/governance_service.py`. First extend the existing import line at the top from:

```python
from open_notebook.domain.governance import AuditEvent, Belief, Proposal
```

to:

```python
from open_notebook.domain.governance import AuditEvent, Belief, Proposal, Trace
```

Then append (after `get_belief_lineage`, which stays unchanged in this task — it's extended in Task 4):

```python
async def record_trace(
    actor: str,
    work_package_id: str,
    *,
    summary: str,
    sources_used: Optional[list[str]] = None,
    outcome: str = "pending",
) -> Trace:
    """Record what actually happened when a work package was executed."""
    trace = Trace(
        work_package=work_package_id,
        summary=summary,
        sources_used=sources_used or [],
        outcome=outcome,
    )
    await trace.save()
    await repo_relate(work_package_id, "traced_by", trace.id, {})
    await _audit(
        actor, "trace.recorded", trace.id,
        {"work_package": work_package_id, "outcome": outcome},
    )
    return trace


async def get_trace(trace_id: str) -> Trace:
    return await Trace.get(trace_id)


async def list_traces_for_work_package(work_package_id: str) -> list[dict[str, Any]]:
    """Traces recorded for a work package, most recent first."""
    return await repo_query(
        "SELECT out.id AS id, out.summary AS summary, out.outcome AS outcome, "
        "out.created AS created FROM traced_by WHERE in = $id ORDER BY out.created DESC",
        {"id": work_package_id},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add api/governance_service.py tests/test_governance_service.py
git commit -m "feat(governance): record_trace/get_trace/list_traces_for_work_package"
```

---

### Task 4: Service — `create_learning_proposal` + accept a learning proposal (closes the loop)

This is the task that actually closes the loop: a learning proposal is created **propose-only** (no belief write), and only `accept_proposal` — the exact same endpoint every other proposal goes through — is allowed to turn it into an updated belief.

**Files:**
- Modify: `api/governance_service.py`
- Modify: `tests/test_governance_service.py`

**Interfaces:**
- Consumes: `Trace`, `Belief`, `Proposal` (existing + Task 2/3).
- Produces:
  - `create_learning_proposal(actor: str, trace_id: str, *, title: str, body: str, belief_id: str) -> Proposal` — creates `Proposal(kind='learning', status='pending')`, `RELATE proposal->learned_from->trace` carrying `{"belief": belief_id}`, `audit_event(action='learning.proposed')`. Never touches `belief`.
  - `accept_proposal` (existing function) — refactored so `kind='belief'` behavior is unchanged (moved into `_accept_belief_proposal`) and `kind='learning'` proposals are routed to a new `_accept_learning_proposal`, which: looks up the `learned_from` edge to find `(trace_id, belief_id)`; loads the original `Belief` and its `Trace`; creates a **new** `Belief` (title unchanged, `body=proposal.body`, `confidence` nudged by the trace outcome: `+0.15` capped at `1.0` on `success`, `-0.15` floored at `0.0` on `fail`, unchanged on `pending`/`mixed`); `RELATE new_belief->updates->original_belief` carrying `{"trace": trace_id}`; copies the original belief's `derived_from` source edges onto the new belief; sets the original belief's `status='superseded'`; marks the proposal `accepted`; audits `proposal.accepted` with `meta={'kind': 'learning', 'belief': new_belief.id, 'superseded': original_belief.id, 'trace': trace_id}`. Raises `ValueError` if the `learned_from` edge has no linked belief.
  - `get_belief_lineage` (existing function) — extended to also return `updated_from: {"belief": str, "trace": str} | None`, populated from `SELECT out AS belief, trace FROM updates WHERE in = $id` (i.e. "this belief updates that one, via this trace").

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_governance_service.py`:

```python
@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_learning_proposal_links_trace_and_belief(mock_create, mock_relate):
    mock_create.side_effect = [
        [{"id": "proposal:9", "kind": "learning", "status": "pending", "title": "Outcome: SMB outreach worked"}],  # proposal.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    from api.governance_service import create_learning_proposal

    proposal = await create_learning_proposal(
        "user:1", "trace:1",
        title="Outcome: SMB outreach worked",
        body="Response rate was 3x higher for SMBs",
        belief_id="belief:1",
    )

    assert proposal.kind == "learning"
    assert proposal.status == "pending"
    mock_relate.assert_awaited_once_with(
        "proposal:9", "learned_from", "trace:1", {"belief": "belief:1"}
    )
    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "learning.proposed"
    assert audit_data["meta"] == {"trace": "trace:1", "belief": "belief:1"}


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_update", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_accept_learning_proposal_updates_belief_and_supersedes_original(
    mock_base_query, mock_create, mock_update, mock_gov_query, mock_relate
):
    # open_notebook.domain.base.repo_query backs Proposal.get / Trace.get / Belief.get,
    # called in that order by _accept_learning_proposal.
    mock_base_query.side_effect = [
        [{"id": "proposal:9", "author": "user:1", "kind": "learning", "title": "Outcome",
          "body": "SMB response rate was 3x higher", "status": "pending"}],  # Proposal.get
        [{"id": "trace:1", "work_package": "work_package:1", "summary": "Ran playbook", "outcome": "success"}],  # Trace.get
        [{"id": "belief:1", "title": "SMB focus Q3", "body": "...", "claim_type": "inference",
          "confidence": 0.6, "status": "current"}],  # Belief.get (original)
    ]
    # api.governance_service.repo_query backs the learned_from edge lookup, then the
    # original belief's derived_from sources being copied forward.
    mock_gov_query.side_effect = [
        [{"trace": "trace:1", "belief": "belief:1"}],
        [{"source": "source:1", "locator": "p.4"}],
    ]
    mock_create.side_effect = [
        [{"id": "belief:2", "status": "current"}],  # updated_belief.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]
    mock_update.side_effect = [
        [{"id": "belief:1", "status": "superseded"}],  # original.save()
        [{"id": "proposal:9", "status": "accepted"}],  # proposal.save()
    ]

    result = await accept_proposal("user:1", "proposal:9")

    assert result["belief"].id == "belief:2"
    assert result["belief"].confidence == pytest.approx(0.75)  # 0.6 + 0.15 for a 'success' outcome
    assert result["proposal"].status == "accepted"

    mock_relate.assert_any_await("belief:2", "updates", "belief:1", {"trace": "trace:1"})
    mock_relate.assert_any_await("belief:2", "derived_from", "source:1", {"locator": "p.4"})

    supersede_call = mock_update.await_args_list[0]
    assert supersede_call.args[0] == "belief"
    assert supersede_call.args[1] == "belief:1"
    assert supersede_call.args[2]["status"] == "superseded"

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "proposal.accepted"
    assert audit_data["meta"] == {
        "kind": "learning", "belief": "belief:2", "superseded": "belief:1", "trace": "trace:1",
    }


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_accept_learning_proposal_without_belief_link_raises(mock_base_query, mock_gov_query):
    mock_base_query.return_value = [
        {"id": "proposal:9", "author": "user:1", "kind": "learning", "title": "Outcome", "status": "pending"}
    ]
    mock_gov_query.return_value = []  # no learned_from edge found

    with pytest.raises(ValueError):
        await accept_proposal("user:1", "proposal:9")


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_belief_lineage_includes_updated_from_when_present(mock_base_query, mock_gov_query):
    mock_base_query.return_value = [{"id": "belief:2", "title": "SMB focus Q3", "status": "current"}]
    mock_gov_query.side_effect = [
        [],  # sources
        [],  # provenance
        [{"belief": "belief:1", "trace": "trace:1"}],  # updates edge (this belief updates belief:1)
    ]
    lineage = await get_belief_lineage("belief:2")
    assert lineage["updated_from"] == {"belief": "belief:1", "trace": "trace:1"}


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_belief_lineage_updated_from_none_when_absent(mock_base_query, mock_gov_query):
    mock_base_query.return_value = [{"id": "belief:1", "title": "SMB focus Q3", "status": "current"}]
    mock_gov_query.side_effect = [[], [], []]
    lineage = await get_belief_lineage("belief:1")
    assert lineage["updated_from"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: FAIL — `create_learning_proposal` missing; `accept_proposal` doesn't branch on `kind`; `get_belief_lineage` has no `updated_from` key.

- [ ] **Step 3: Implement**

Add `create_learning_proposal` to `api/governance_service.py` (after `list_traces_for_work_package` from Task 3):

```python
async def create_learning_proposal(
    actor: str,
    trace_id: str,
    *,
    title: str,
    body: str,
    belief_id: str,
) -> Proposal:
    """Draft a propose-only learning update from a trace's real-world outcome.

    Learning NEVER writes to a belief directly (PRD §1.6A/§4.5B) — it always
    goes through the same pending -> accept/request-changes review as any
    other proposal. `belief_id` is the belief this outcome should update; it
    is carried on the `learned_from` edge so `accept_proposal` can find it
    without re-deriving it through the work_package -> decision/rule chain.
    """
    proposal = Proposal(author=actor, kind="learning", title=title, body=body, status="pending")
    await proposal.save()
    await repo_relate(proposal.id, "learned_from", trace_id, {"belief": belief_id})
    await _audit(actor, "learning.proposed", proposal.id, {"trace": trace_id, "belief": belief_id})
    return proposal
```

Replace the existing `accept_proposal` function with a thin dispatcher plus the two branch implementations. The `kind='belief'` branch is the exact existing body, renamed:

```python
async def accept_proposal(actor: str, proposal_id: str) -> dict[str, Any]:
    """Promote or apply a pending proposal.

    `kind='belief'` proposals promote into a new belief (unchanged P8.2
    behavior). `kind='learning'` proposals apply a traced outcome onto the
    belief they reference, superseding it (P8.5).

    Raises:
        ValueError: if the proposal is not currently `pending`, or (for a
            learning proposal) if it has no linked belief to update.
    """
    proposal = await Proposal.get(proposal_id)
    if proposal.status != "pending":
        raise ValueError(f"proposal {proposal_id} is {proposal.status}, not pending")

    if proposal.kind == "learning":
        return await _accept_learning_proposal(actor, proposal)
    return await _accept_belief_proposal(actor, proposal)


async def _accept_belief_proposal(actor: str, proposal: Proposal) -> dict[str, Any]:
    """Promote a pending belief/decision/rule proposal into a belief.

    Creates the belief, links proposal->promotes_to->belief, copies every
    proposal->derived_from->source edge onto the belief, marks the proposal
    accepted, and writes an audit event.
    """
    belief = Belief(
        title=proposal.title,
        body=proposal.body,
        claim_type=proposal.claim_type,
        confidence=proposal.confidence,
        status="current",
    )
    await belief.save()

    await repo_relate(proposal.id, "promotes_to", belief.id, {})

    edges = await repo_query(
        "SELECT out AS source, locator FROM derived_from WHERE in = $id",
        {"id": proposal.id},
    )
    for edge in edges:
        await repo_relate(belief.id, "derived_from", edge["source"], {"locator": edge.get("locator")})

    proposal.status = "accepted"
    await proposal.save()
    await _audit(actor, "proposal.accepted", proposal.id, {"belief": belief.id})

    return {"proposal": proposal, "belief": belief}


async def _accept_learning_proposal(actor: str, proposal: Proposal) -> dict[str, Any]:
    """Apply a traced outcome onto the belief it references.

    The new belief supersedes the original: same title, body rewritten to
    the learning proposal's content, confidence nudged by the trace outcome,
    and evidentiary sources copied forward so lineage never breaks.
    """
    edges = await repo_query(
        "SELECT out AS trace, belief FROM learned_from WHERE in = $id",
        {"id": proposal.id},
    )
    if not edges or not edges[0].get("belief"):
        raise ValueError(f"learning proposal {proposal.id} has no linked belief to update")

    trace_id = edges[0]["trace"]
    original_belief_id = edges[0]["belief"]

    trace = await Trace.get(trace_id)
    original = await Belief.get(original_belief_id)

    confidence = original.confidence
    if trace.outcome == "success":
        confidence = min(1.0, confidence + 0.15)
    elif trace.outcome == "fail":
        confidence = max(0.0, confidence - 0.15)

    updated_belief = Belief(
        title=original.title,
        body=proposal.body,
        claim_type=original.claim_type,
        confidence=confidence,
        status="current",
    )
    await updated_belief.save()
    await repo_relate(updated_belief.id, "updates", original.id, {"trace": trace.id})

    source_edges = await repo_query(
        "SELECT out AS source, locator FROM derived_from WHERE in = $id",
        {"id": original.id},
    )
    for edge in source_edges:
        await repo_relate(
            updated_belief.id, "derived_from", edge["source"], {"locator": edge.get("locator")}
        )

    original.status = "superseded"
    await original.save()

    proposal.status = "accepted"
    await proposal.save()
    await _audit(
        actor, "proposal.accepted", proposal.id,
        {"kind": "learning", "belief": updated_belief.id, "superseded": original.id, "trace": trace.id},
    )

    return {"proposal": proposal, "belief": updated_belief}
```

Extend `get_belief_lineage`'s return to include `updated_from`:

```python
async def get_belief_lineage(belief_id: str) -> dict[str, Any]:
    """Sources + provenance trail for a belief.

    `derived_work` and `contradictions` are reserved for later phases of the
    Promotion Bridge (belief-to-belief graph) and always come back empty.
    `updated_from` is populated when this belief itself was produced by
    accepting a learning proposal (P8.5) -- it points at the trace and the
    prior belief this one superseded.
    """
    belief = await Belief.get(belief_id)

    sources = await repo_query(
        "SELECT out.id AS id, out.title AS title, locator FROM derived_from "
        "WHERE in = $id",
        {"id": belief_id},
    )
    provenance = await repo_query(
        "SELECT action, actor, object, meta, created FROM audit_event "
        "WHERE object = $id OR meta.belief = $id ORDER BY created",
        {"id": belief_id},
    )
    updated_from_rows = await repo_query(
        "SELECT out AS belief, trace FROM updates WHERE in = $id",
        {"id": belief_id},
    )
    updated_from = (
        {"belief": updated_from_rows[0]["belief"], "trace": updated_from_rows[0]["trace"]}
        if updated_from_rows
        else None
    )

    return {
        "belief": belief,
        "sources": sources,
        "provenance": provenance,
        "derived_work": [],
        "contradictions": [],
        "updated_from": updated_from,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: PASS (all tests, old and new — including the pre-existing `test_accept_proposal_makes_belief_copies_edges_and_audits`/`test_accept_proposal_raises_when_not_pending`, unaffected by the `kind` dispatch since they use the default `kind='belief'`).

- [ ] **Step 5: Commit**

```bash
git add api/governance_service.py tests/test_governance_service.py
git commit -m "feat(governance): learning proposals close the loop - accept updates + supersedes the belief"
```

---

### Task 5: Router — trace + learning endpoints

**Files:**
- Modify: `api/routers/governance.py`
- Modify: `tests/test_governance_router.py`

**Interfaces:**
- Produces endpoints (all read `actor` via the existing `_actor(request)` helper):
  - `POST /api/work-packages/{work_package_id}/trace` → `record_trace`, 201.
  - `GET /api/work-packages/{work_package_id}/traces` → `list_traces_for_work_package`.
  - `GET /api/traces/{trace_id}` → `get_trace`.
  - `POST /api/traces/{trace_id}/learning` → `create_learning_proposal`, 201.
  - Learning proposals are **accepted/reviewed through the existing** `POST /api/proposals/{id}/accept` and `POST /api/proposals/{id}/request-changes` endpoints — no new review endpoint needed.

- [ ] **Step 1: Write the failing tests**

Extend the domain import at the top of `tests/test_governance_router.py`:

```python
from open_notebook.domain.governance import Belief, Proposal, Trace
```

Add a `_trace` fixture helper next to the existing `_proposal`/`_belief` helpers:

```python
def _trace(**overrides) -> Trace:
    data = dict(
        id="trace:1",
        work_package="work_package:1",
        summary="Ran the SMB outreach playbook",
        sources_used=[],
        outcome="success",
    )
    data.update(overrides)
    return Trace(**data)
```

Append test cases:

```python
@patch("api.routers.governance.record_trace", new_callable=AsyncMock)
def test_record_trace_returns_201(mock_record, client):
    mock_record.return_value = _trace()

    resp = client.post(
        "/api/work-packages/work_package:1/trace",
        json={"summary": "Ran the SMB outreach playbook", "sources_used": ["source:1"], "outcome": "success"},
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "trace:1"
    mock_record.assert_awaited_once_with(
        "user:1", "work_package:1",
        summary="Ran the SMB outreach playbook", sources_used=["source:1"], outcome="success",
    )


@patch("api.routers.governance.list_traces_for_work_package", new_callable=AsyncMock)
def test_list_traces_endpoint_returns_mocked_list(mock_list, client):
    mock_list.return_value = [{"id": "trace:1", "summary": "Ran playbook", "outcome": "success"}]

    resp = client.get("/api/work-packages/work_package:1/traces", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "trace:1"
    mock_list.assert_awaited_once_with("work_package:1")


@patch("api.routers.governance.get_trace", new_callable=AsyncMock)
def test_get_trace_endpoint_returns_trace(mock_get, client):
    mock_get.return_value = _trace()

    resp = client.get("/api/traces/trace:1", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["id"] == "trace:1"


@patch("api.routers.governance.create_learning_proposal", new_callable=AsyncMock)
def test_create_learning_proposal_endpoint_returns_201(mock_create, client):
    mock_create.return_value = _proposal(id="proposal:9", kind="learning", title="Outcome: SMB outreach worked")

    resp = client.post(
        "/api/traces/trace:1/learning",
        json={"title": "Outcome: SMB outreach worked", "body": "3x response rate", "belief_id": "belief:1"},
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "learning"
    mock_create.assert_awaited_once_with(
        "user:1", "trace:1",
        title="Outcome: SMB outreach worked", body="3x response rate", belief_id="belief:1",
    )


def test_record_trace_requires_auth(client):
    resp = client.post(
        "/api/work-packages/work_package:1/trace",
        json={"summary": "x"},
    )
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_governance_router.py -v`
Expected: FAIL — new endpoints 404.

- [ ] **Step 3: Implement**

In `api/routers/governance.py`, extend the import block:

```python
from api.governance_service import (
    accept_proposal,
    create_learning_proposal,
    create_proposal,
    get_belief_lineage,
    get_proposal,
    get_trace,
    list_proposals,
    list_traces_for_work_package,
    record_trace,
    request_changes,
)
```

Add two request bodies next to the existing `SourceSpan`/`CreateProposalBody`/`ChangesBody`:

```python
class RecordTraceBody(BaseModel):
    summary: str
    sources_used: list[str] = []
    outcome: str = "pending"


class CreateLearningProposalBody(BaseModel):
    title: str
    body: str = ""
    belief_id: str
```

Append the endpoints (after the existing `belief_lineage_endpoint`):

```python
@router.post("/work-packages/{work_package_id}/trace", status_code=201)
async def record_trace_endpoint(
    work_package_id: str, body: RecordTraceBody, request: Request
) -> dict[str, Any]:
    trace = await record_trace(
        _actor(request), work_package_id,
        summary=body.summary, sources_used=body.sources_used, outcome=body.outcome,
    )
    return trace.model_dump()


@router.get("/work-packages/{work_package_id}/traces")
async def list_traces_endpoint(work_package_id: str) -> list[dict[str, Any]]:
    return await list_traces_for_work_package(work_package_id)


@router.get("/traces/{trace_id}")
async def get_trace_endpoint(trace_id: str) -> dict[str, Any]:
    trace = await get_trace(trace_id)
    return trace.model_dump()


@router.post("/traces/{trace_id}/learning", status_code=201)
async def create_learning_proposal_endpoint(
    trace_id: str, body: CreateLearningProposalBody, request: Request
) -> dict[str, Any]:
    proposal = await create_learning_proposal(
        _actor(request), trace_id,
        title=body.title, body=body.body, belief_id=body.belief_id,
    )
    return proposal.model_dump()
```

No changes to `api/main.py`/`api/routers/__init__.py` — `governance.router` is already mounted at `/api` (see `api/main.py:407`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_governance_router.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 5: Full backend gate**

Run: `uv run pytest tests/ && ruff check .`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add api/routers/governance.py tests/test_governance_router.py
git commit -m "feat(governance): trace + learning-proposal endpoints"
```

---

### Task 6: Frontend API client + hooks

**Files:**
- Modify: `frontend/src/lib/api/governance.ts`
- Modify: `frontend/src/lib/hooks/use-governance.ts`
- Modify: `frontend/src/lib/hooks/use-governance.test.tsx`

**Interfaces:**
- Produces on `governanceApi`: `recordTrace(workPackageId, payload)`, `listTraces(workPackageId)`, `getTrace(id)`, `createLearningProposal(traceId, payload)`.
- Produces hooks: `useTracesForWorkPackage(workPackageId?)`, `useTrace(id?)`, `useRecordTrace()`, `useCreateLearningProposal()`. Mutations invalidate `['traces', workPackageId]` (record) / `['proposals']` (learning proposal, since it shows up in `ReviewInbox`) and toast.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/lib/hooks/use-governance.test.tsx`:

```tsx
vi.mock('@/lib/api/governance', () => ({
  governanceApi: {
    listProposals: vi.fn().mockResolvedValue([{ id: 'proposal:1', title: 'SMB', status: 'pending' }]),
    listTraces: vi.fn().mockResolvedValue([{ id: 'trace:1', summary: 'Ran playbook', outcome: 'success' }]),
  },
}))

import { useTracesForWorkPackage } from './use-governance'

describe('useTracesForWorkPackage', () => {
  it('fetches traces for a work package', async () => {
    const { result } = renderHook(() => useTracesForWorkPackage('work_package:1'), { wrapper })
    await waitFor(() => expect(result.current.data?.[0].summary).toBe('Ran playbook'))
  })
})
```

Note: this file already has a single `vi.mock('@/lib/api/governance', ...)` call — merge the new `listTraces` mock into that **same** mock object rather than adding a second `vi.mock` call for the same module (vitest only honors the first `vi.mock` factory per module per file).

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- use-governance` (inside `frontend/`)
Expected: FAIL — `useTracesForWorkPackage` doesn't exist yet.

- [ ] **Step 3: Implement**

Append to `frontend/src/lib/api/governance.ts`:

```ts
export interface Trace {
  id: string
  work_package: string
  summary: string
  sources_used: string[]
  outcome: string
  created?: string
}

export interface RecordTracePayload {
  summary: string
  sources_used?: string[]
  outcome?: string
}

export interface CreateLearningProposalPayload {
  title: string
  body?: string
  belief_id: string
}
```

Add to the `governanceApi` object:

```ts
  recordTrace: (workPackageId: string, payload: RecordTracePayload) =>
    apiClient.post<Trace>(`/work-packages/${workPackageId}/trace`, payload).then((r) => r.data),

  listTraces: (workPackageId: string) =>
    apiClient.get<Trace[]>(`/work-packages/${workPackageId}/traces`).then((r) => r.data),

  getTrace: (id: string) => apiClient.get<Trace>(`/traces/${id}`).then((r) => r.data),

  createLearningProposal: (traceId: string, payload: CreateLearningProposalPayload) =>
    apiClient.post<Proposal>(`/traces/${traceId}/learning`, payload).then((r) => r.data),
```

Append to `frontend/src/lib/hooks/use-governance.ts` (extend the existing import from `@/lib/api/governance` to also bring in `type RecordTracePayload, type CreateLearningProposalPayload`):

```ts
export const useTracesForWorkPackage = (workPackageId?: string) =>
  useQuery({
    queryKey: ['traces', workPackageId],
    queryFn: () => governanceApi.listTraces(workPackageId as string),
    enabled: !!workPackageId,
  })

export const useTrace = (id?: string) =>
  useQuery({
    queryKey: ['traces', 'detail', id],
    queryFn: () => governanceApi.getTrace(id as string),
    enabled: !!id,
  })

export function useRecordTrace() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ workPackageId, payload }: { workPackageId: string; payload: RecordTracePayload }) =>
      governanceApi.recordTrace(workPackageId, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['traces', variables.workPackageId] })
      toast({ title: t('governance.toastTraceRecorded') })
    },
  })
}

export function useCreateLearningProposal() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ traceId, payload }: { traceId: string; payload: CreateLearningProposalPayload }) =>
      governanceApi.createLearningProposal(traceId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.proposals })
      toast({ title: t('governance.toastLearningProposed') })
    },
  })
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- use-governance`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api/governance.ts frontend/src/lib/hooks/use-governance.ts frontend/src/lib/hooks/use-governance.test.tsx
git commit -m "feat(control-plane): trace + learning-proposal api client and hooks"
```

---

### Task 7: `TraceSection`, `ReviewInbox` learning badge, `LineagePanel` "updated from real outcome" — plus i18n

**Files:**
- Create: `frontend/src/components/control-plane/TraceSection.tsx`
- Create: `frontend/src/components/control-plane/TraceSection.test.tsx`
- Modify: `frontend/src/components/control-plane/ReviewInbox.tsx`
- Modify: `frontend/src/components/control-plane/ReviewInbox.test.tsx`
- Modify: `frontend/src/components/control-plane/LineagePanel.tsx`
- Modify: `frontend/src/components/control-plane/LineagePanel.test.tsx`
- Modify: all 14 `frontend/src/lib/locales/<code>/index.ts`

**Interfaces:**
- Consumes: `useTracesForWorkPackage`, `useRecordTrace`, `useCreateLearningProposal` (Task 6); `useProposals` (existing, unchanged — `p.kind` is already on the `Proposal` type); `useBelief` (existing, extended payload shape from Task 4).
- Produces: `<TraceSection workPackageId belief​Id />` — this is the UI action described as "Ghi nhận kết quả & học lại" ("record outcome & learn") in the spec: record what happened to a work package, then optionally turn that outcome into a learning proposal that flows into `ReviewInbox`.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/control-plane/TraceSection.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const recordTraceMutate = vi.fn((_vars, opts) => {
  opts?.onSuccess?.({ id: 'trace:1', work_package: 'work_package:1', summary: 'Ran playbook', outcome: 'success', sources_used: [] });
});
const createLearningMutate = vi.fn();

vi.mock('@/lib/hooks/use-governance', () => ({
  useTracesForWorkPackage: () => ({
    data: [{ id: 'trace:0', summary: 'Earlier run', outcome: 'mixed' }],
    isLoading: false,
  }),
  useRecordTrace: () => ({ mutate: recordTraceMutate, isPending: false }),
  useCreateLearningProposal: () => ({ mutate: createLearningMutate, isPending: false }),
}));

import { TraceSection } from './TraceSection';

describe('TraceSection', () => {
  it('lists prior traces, records a new outcome, then proposes a learning update', () => {
    render(<TraceSection workPackageId="work_package:1" beliefId="belief:1" />);

    expect(screen.getByText('Earlier run')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('What happened when this ran?'), {
      target: { value: 'SMB outreach playbook ran; response rate tripled.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Record outcome & learn' }));

    expect(recordTraceMutate).toHaveBeenCalledWith(
      {
        workPackageId: 'work_package:1',
        payload: { summary: 'SMB outreach playbook ran; response rate tripled.', outcome: 'success', sources_used: [] },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );

    fireEvent.change(screen.getByPlaceholderText('What should the company learn from this?'), {
      target: { value: 'SMBs respond 3x better to this outreach angle.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Propose learning' }));

    expect(createLearningMutate).toHaveBeenCalledWith(
      {
        traceId: 'trace:1',
        payload: {
          title: 'Learning from outcome',
          body: 'SMBs respond 3x better to this outreach angle.',
          belief_id: 'belief:1',
        },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
});
```

```tsx
// frontend/src/components/control-plane/ReviewInbox.test.tsx (append this test to the existing describe block's file)
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const accept = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useProposals: () => ({
    data: [
      { id: 'proposal:1', title: 'SMB focus', status: 'pending', kind: 'belief' },
      { id: 'proposal:2', title: 'Outcome: SMB outreach worked', status: 'pending', kind: 'learning' },
    ],
    isLoading: false,
  }),
  useAcceptProposal: () => ({ mutate: accept, isPending: false }),
  useRequestChanges: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ReviewInbox } from './ReviewInbox';

describe('ReviewInbox', () => {
  it('lists a pending proposal and accepts it', () => {
    render(<ReviewInbox />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Accept' })[0]);
    expect(accept).toHaveBeenCalledWith('proposal:1');
  });

  it('badges a learning-kind proposal so reviewers see it closes the loop', () => {
    render(<ReviewInbox />);
    expect(screen.getByText('Outcome: SMB outreach worked')).toBeInTheDocument();
    expect(screen.getByText('Learning')).toBeInTheDocument();
  });
});
```

(This replaces the existing single-test `ReviewInbox.test.tsx` — the mock's `useProposals` data now needs a second, `kind: 'learning'` entry, and the accept-button assertion should target the first "Accept" button since there are now two proposals rendered.)

```tsx
// frontend/src/components/control-plane/LineagePanel.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-governance', () => ({
  useBelief: () => ({ data: {
    belief: { id: 'belief:2', title: 'SMB focus Q3' },
    sources: [{ id: 'source:9', title: 'Q3 Research', locator: 'p.4' }],
    provenance: [{ action: 'proposal.accepted', actor: 'user:1' }],
    derived_work: [], contradictions: [],
    updated_from: { belief: 'belief:1', trace: 'trace:1' },
  }, isLoading: false }),
}));

import { LineagePanel } from './LineagePanel';

describe('LineagePanel', () => {
  it('shows belief title, its source, and provenance', () => {
    render(<LineagePanel id="belief:2" />);
    expect(screen.getByText('SMB focus Q3')).toBeInTheDocument();
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/proposal\.accepted|accepted/i)).toBeInTheDocument();
  });

  it('shows the belief was updated from a real outcome when updated_from is present', () => {
    render(<LineagePanel id="belief:2" />);
    expect(screen.getByText('Updated from real outcome')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- TraceSection ReviewInbox LineagePanel`
Expected: FAIL — `TraceSection` module missing; `ReviewInbox`/`LineagePanel` don't render the new elements yet.

- [ ] **Step 3: Implement `TraceSection`**

```tsx
// frontend/src/components/control-plane/TraceSection.tsx
'use client';
import { useState } from 'react';
import { useTracesForWorkPackage, useRecordTrace, useCreateLearningProposal } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

const OUTCOMES = ['pending', 'success', 'fail', 'mixed'] as const;
type Outcome = (typeof OUTCOMES)[number];

export function TraceSection({ workPackageId, beliefId }: { workPackageId: string; beliefId: string }) {
  const { t } = useTranslation();
  const { data: traces, isLoading } = useTracesForWorkPackage(workPackageId);
  const recordTrace = useRecordTrace();
  const createLearning = useCreateLearningProposal();

  const [summary, setSummary] = useState('');
  const [outcome, setOutcome] = useState<Outcome>('success');
  const [learningNote, setLearningNote] = useState('');
  const [newTraceId, setNewTraceId] = useState<string | null>(null);

  const handleRecordOutcome = () => {
    recordTrace.mutate(
      { workPackageId, payload: { summary, outcome, sources_used: [] } },
      { onSuccess: (trace) => { setNewTraceId(trace.id); setSummary(''); } },
    );
  };

  const handleProposeLearning = () => {
    if (!newTraceId) return;
    createLearning.mutate(
      {
        traceId: newTraceId,
        payload: { title: t('controlPlane.trace.learningTitle'), body: learningNote, belief_id: beliefId },
      },
      { onSuccess: () => { setNewTraceId(null); setLearningNote(''); } },
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
        {t('controlPlane.trace.title')}
      </div>

      {isLoading ? (
        <div className="text-xs text-muted-foreground">{t('common.loading')}</div>
      ) : (traces ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          {t('controlPlane.trace.empty')}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {(traces ?? []).map((tr) => (
            <div key={tr.id} className="rounded-xl border border-border bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-foreground">{tr.summary}</span>
                <span className="text-[10px] uppercase text-muted-foreground">
                  {t(`controlPlane.trace.outcomes.${tr.outcome}`)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-xl border border-border bg-card p-3">
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder={t('controlPlane.trace.summaryPlaceholder')}
          className="w-full rounded-md border border-border bg-background p-2 text-xs"
        />
        <select
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as Outcome)}
          className="mt-2 rounded-md border border-border bg-background p-1.5 text-xs"
        >
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>{t(`controlPlane.trace.outcomes.${o}`)}</option>
          ))}
        </select>
        <button
          type="button"
          disabled={!summary || recordTrace.isPending}
          onClick={handleRecordOutcome}
          className="mt-2 flex items-center rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-50"
        >
          {t('controlPlane.trace.recordOutcome')}
        </button>

        {newTraceId ? (
          <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
            <textarea
              value={learningNote}
              onChange={(e) => setLearningNote(e.target.value)}
              placeholder={t('controlPlane.trace.learningPlaceholder')}
              className="w-full rounded-md border border-border bg-background p-2 text-xs"
            />
            <button
              type="button"
              disabled={!learningNote || createLearning.isPending}
              onClick={handleProposeLearning}
              className="self-start rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground disabled:opacity-50"
            >
              {t('controlPlane.trace.submitLearning')}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add the learning badge to `ReviewInbox`**

```tsx
// frontend/src/components/control-plane/ReviewInbox.tsx
'use client';
import { useProposals, useAcceptProposal, useRequestChanges } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

export function ReviewInbox() {
  const { t } = useTranslation();
  const { data, isLoading } = useProposals('pending');
  const accept = useAcceptProposal();
  const changes = useRequestChanges();
  const items = data ?? [];
  if (isLoading) return <div className="text-xs text-muted-foreground">{t('common.loading')}</div>;
  if (items.length === 0)
    return <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{t('controlPlane.sidebar.reviewEmpty')}</div>;
  return (
    <div className="flex flex-col gap-2">
      {items.map((p) => (
        <div key={p.id} className="rounded-xl border border-border bg-card p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-bold text-foreground">{p.title}</span>
            {p.kind === 'learning' ? (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-primary">
                {t('controlPlane.review.learningBadge')}
              </span>
            ) : null}
          </div>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => accept.mutate(p.id)} disabled={accept.isPending}
              className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground">
              {t('controlPlane.review.accept')}
            </button>
            <button type="button" onClick={() => changes.mutate({ id: p.id, note: '' })}
              className="rounded-md px-2.5 py-1 text-xs font-semibold text-muted-foreground hover:text-foreground">
              {t('controlPlane.review.changes')}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Add the "updated from real outcome" section to `LineagePanel`**

In `frontend/src/components/control-plane/LineagePanel.tsx`, extend the `BeliefLineage` interface:

```tsx
interface BeliefLineage {
  belief: { id: string; title: string };
  sources: LineageSource[];
  provenance: LineageProvenanceRow[];
  derived_work: unknown[];
  contradictions: unknown[];
  updated_from: { belief: string; trace: string } | null;
}
```

Destructure the new field and render a callout right after the title, before the sources section:

```tsx
  const { belief, sources, provenance, updated_from } = data;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
      <div className="text-[11px] font-bold uppercase tracking-wide text-primary">{t('controlPlane.lineage.belief')}</div>
      <h2 className="mb-3 font-serif text-lg text-foreground">{belief.title}</h2>

      {updated_from ? (
        <div className="mb-4 rounded-lg bg-primary/10 p-3">
          <div className="text-[11px] font-bold uppercase tracking-wide text-primary">{t('controlPlane.lineage.updatedFromOutcome')}</div>
          <div className="text-sm text-foreground">{t('controlPlane.lineage.updatedFromOutcomeDetail')}</div>
        </div>
      ) : null}

      <div className="mb-4">
```

(the rest of the component — sources/provenance/contradiction blocks — is unchanged).

- [ ] **Step 6: Add i18n keys to all 14 locales**

Every locale file (`frontend/src/lib/locales/<code>/index.ts`) currently has byte-identical text for the `controlPlane.lineage`, `controlPlane.review`, and top-level `governance` blocks (confirmed: `proposeToCompany`/`review`/`governance.toast*` are still literally the same English strings in every locale — translating that backlog is out of scope for this plan, same as it was for P8.2/P8.3). Because the anchor text is therefore identical across all 14 files, apply the same three insertions to every file with one script instead of 14 sets of manual edits:

```bash
cd /Users/nathan/Documents/morcalab/arteamis-workspace/Arteamis-fe-p8/frontend/src/lib/locales
python3 - <<'PYEOF'
import pathlib

LOCALE_CODES = [
    "bn-IN", "ca-ES", "de-DE", "en-US", "es-ES", "fr-FR", "it-IT",
    "ja-JP", "pl-PL", "pt-BR", "ru-RU", "tr-TR", "zh-CN", "zh-TW",
]

LINEAGE_OLD = '''      contradictionNone: "No contradictions detected",
    },
    proposeToCompany: "Propose to Company",'''

LINEAGE_NEW = '''      contradictionNone: "No contradictions detected",
      updatedFromOutcome: "Updated from real outcome",
      updatedFromOutcomeDetail: "This belief was revised after a real-world result was traced and reviewed.",
    },
    proposeToCompany: "Propose to Company",
    trace: {
      title: "Trace & Learning",
      empty: "No outcomes recorded yet.",
      summaryPlaceholder: "What happened when this ran?",
      learningPlaceholder: "What should the company learn from this?",
      recordOutcome: "Record outcome & learn",
      submitLearning: "Propose learning",
      learningTitle: "Learning from outcome",
      outcomes: {
        pending: "Pending",
        success: "Success",
        fail: "Failed",
        mixed: "Mixed",
      },
    },'''

REVIEW_OLD = '''    review: {
      accept: "Accept",
      changes: "Request changes",
    },'''

REVIEW_NEW = '''    review: {
      accept: "Accept",
      changes: "Request changes",
      learningBadge: "Learning",
    },'''

GOVERNANCE_OLD = '''  governance: {
    toastProposed: "Proposed to company",
    toastAccepted: "Accepted into Company Brain",
    toastChangesRequested: "Sent back for changes",
  },'''

GOVERNANCE_NEW = '''  governance: {
    toastProposed: "Proposed to company",
    toastAccepted: "Accepted into Company Brain",
    toastChangesRequested: "Sent back for changes",
    toastTraceRecorded: "Outcome recorded",
    toastLearningProposed: "Learning proposed to company",
  },'''

for code in LOCALE_CODES:
    path = pathlib.Path(code) / "index.ts"
    text = path.read_text()
    for old, new, name in [
        (LINEAGE_OLD, LINEAGE_NEW, "lineage/trace"),
        (REVIEW_OLD, REVIEW_NEW, "review"),
        (GOVERNANCE_OLD, GOVERNANCE_NEW, "governance"),
    ]:
        if old not in text:
            raise SystemExit(f"{code}: anchor for {name} block not found -- edit manually")
        text = text.replace(old, new, 1)
    path.write_text(text)
    print(f"{code}: updated")
PYEOF
```

Run it once. It will raise (not silently skip) if any locale's anchor text has drifted, which forces a manual look rather than a partial/broken locale file. Translating the newly-inserted English strings into each locale's language is a legitimate follow-up (tracked the same way the pre-existing English `proposeToCompany`/`governance.toast*` strings already are) — it does not block this plan, since the locale test only enforces **key** parity, not translation completeness.

- [ ] **Step 7: Run tests to verify they pass**

Run (inside `frontend/`):
```bash
npm run test -- TraceSection ReviewInbox LineagePanel
npm run test -- locales
```
Expected: PASS — component tests green, locale parity + unused-key detection green.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/control-plane/TraceSection.tsx frontend/src/components/control-plane/TraceSection.test.tsx frontend/src/components/control-plane/ReviewInbox.tsx frontend/src/components/control-plane/ReviewInbox.test.tsx frontend/src/components/control-plane/LineagePanel.tsx frontend/src/components/control-plane/LineagePanel.test.tsx frontend/src/lib/locales
git commit -m "feat(control-plane): TraceSection, learning badge in review inbox, updated-from-outcome lineage callout"
```

---

### Task 8: Wire `TraceSection` into the work-package view + full-stack verification (loop closes)

**Files:**
- Modify: the P8.4 work-package detail/card component that renders a single `work_package` (verify the exact path — search `grep -rl "work_package" frontend/src/components` from the repo root; P8.4 is expected to have landed a component such as `frontend/src/components/control-plane/WorkPackageCard.tsx` or a `WorkPackagePanel` under the same directory, following the existing `*Section.tsx`/`*Card.tsx` naming already used by `SourcesSection.tsx`, `CompanyBrainSection.tsx`). If the P8.4 component's prop for the work package's id or its source belief differs from `workPackageId`/`beliefId`, adjust the two props passed to `<TraceSection />` to match, not the other way around — `TraceSection`'s own prop names (Task 7) are the ones this plan controls.

**Interfaces:**
- Consumes: `<TraceSection workPackageId={workPackage.id} beliefId={workPackage.beliefId} />` (Task 7). The `beliefId` is whatever belief the work package's decision/rule traces back to — P8.4's work-package model is expected to expose this (directly or by one hop through its `decision`/`rule`); if it's one hop away, resolve it in the parent component before passing it down rather than teaching `TraceSection` about `decision`/`rule` shapes it doesn't need to know.

- [ ] **Step 1: Locate the integration point**

Run: `grep -rl "work_package" frontend/src/components` (from repo root) to find the P8.4 work-package view. Read it to find where the work package's own id and its source belief id are available as props or query data.

- [ ] **Step 2: Render `TraceSection`**

Add `import { TraceSection } from './TraceSection';` (adjust the relative path to match where the work-package view lives) and render it inside that view, after whatever status/handoff summary P8.4 already shows:

```tsx
<TraceSection workPackageId={workPackage.id} beliefId={workPackage.beliefId} />
```

- [ ] **Step 3: Full backend gate**

Run: `uv run pytest tests/ && ruff check .`
Expected: all green.

- [ ] **Step 4: Full frontend gate**

Run (inside `frontend/`): `npm run test && npm run lint && npm run build`
Expected: all green (locale parity + unused-key tests included in `npm run test`).

- [ ] **Step 5: Manual end-to-end smoke — confirm the loop visibly closes**

With the stack up (`make start-all`): open a `work_package` that traces back to an accepted belief in **Company Brain**. In its **Trace & Learning** section, fill in a summary ("SMB outreach playbook ran; response rate tripled"), pick outcome **Success**, click **Record outcome & learn** — the trace appears in the list. Fill in the learning note ("SMBs respond 3x better to this outreach angle") and click **Propose learning** — a toast confirms it, and switching to **Company** scope shows it in **To review** tagged **Learning**. Click **Accept** — the belief in **Company Brain** is unchanged in count (superseded belief drops off the `status='current'` list, the new one takes its place) but its confidence has moved and its body reflects the outcome. Open it in the artifact panel: **LineagePanel** shows **Updated from real outcome**, and its sources are still the original belief's sources (lineage never broke). This is `work_package → trace → learning proposal → review → accept → updated belief`, i.e. the full 8-step loop (`capture → draft → propose → review → decision → rule → handoff → trace`, per `frontend/src/components/control-plane/loop-steps.ts`) closing back into Company Brain.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(control-plane): wire TraceSection into the work-package view - loop closes end to end"
```

---

## Self-Review

**Spec coverage:**
- Migration 25 (`trace` + `traced_by`/`learned_from`/`updates`, matching migration 22's idioms, workspace-ready nullable field) → Task 1. ✓
- `Trace` domain model with `_prepare_save_data`/`ensure_record_id` for `work_package` (and `command`) as a first-class task with a dedicated `RecordID` test → Task 2. ✓ (This is explicitly the same class of bug that was Critical in P8.2 — called out in Global Constraints and given its own test file additions, not folded silently into a bigger task.)
- `record_trace(actor, work_package_id, *, summary, sources_used, outcome)` (save + `traced_by` relate + audit) → Task 3. ✓
- `create_learning_proposal(actor, trace_id, *, title, body)` → creates `Proposal(kind='learning', status='pending')` + `learned_from` edge, reusing the existing `proposal` table (`PROPOSAL_KINDS` already includes `'learning'` from P8.2) → Task 4. ✓
- `accept_proposal` extended so accepting a `kind='learning'` proposal creates/links a belief update via the `updates` edge to the original belief → Task 4 (`_accept_learning_proposal`). ✓
- Propose-only: no code path writes a belief from a trace directly — `create_learning_proposal` never touches `belief`; only `accept_proposal` (kind-dispatched) does → Task 4, called out explicitly in Global Constraints. ✓
- Router: `POST /api/work-packages/{id}/trace`, `POST /api/traces/{id}/learning`, plus the existing accept endpoint handling learning acceptance unchanged → Task 5. ✓
- DB-free mocked tests throughout (backend) → Tasks 1–5, all patch `repo_create`/`repo_query`/`repo_update`/`repo_relate`, no live DB. ✓
- Frontend hooks `useRecordTrace`, `useCreateLearningProposal` (+ `useTracesForWorkPackage`, `useTrace`) → Task 6. ✓
- Trace card/section under the work package + outcome review action ("Ghi nhận kết quả & học lại" / "Record outcome & learn") → Task 7 (`TraceSection`) + Task 8 (wiring). ✓
- Learning proposal appears in `ReviewInbox` (propose-only) → Task 7 (badge; no new review path needed since `ReviewInbox` already lists all pending proposals regardless of `kind`). ✓
- Accepting it updates the belief, shown in CompanyBrain/LineagePanel as "updated from real outcome" → Task 4 (`updated_from` in `get_belief_lineage`) + Task 7 (`LineagePanel` callout). CompanyBrainSection needs no change: it already lists `status='current'` beliefs, and the superseded original naturally drops off that list while the new one appears — no separate CompanyBrain task needed. ✓
- i18n across all 14 locales, referenced in source → Task 7 Step 6 (scripted, all 14 files, each new key referenced by `t()` in `TraceSection`/`ReviewInbox`/`LineagePanel`). ✓
- Audit every transition → `trace.recorded` (Task 3), `learning.proposed` (Task 4), `proposal.accepted` with `meta.kind='learning'` (Task 4). ✓
- Loop visibly closes → Task 8 Step 5 manual smoke walks the full `work_package → trace → learning proposal → review → accept → updated belief` path end to end. ✓

**Out of scope (correctly deferred):** translating the newly-inserted (and the pre-existing P8.2/P8.3) English locale strings into each of the 13 non-English locales — only key parity is test-enforced, translation completeness is a tracked backlog item, same precedent as `proposeToCompany`/`governance.toast*` today. Contradiction detection (D4), PII/secret DLP, real multitenancy roles, and any UI for browsing superseded belief history beyond the single `updated_from` hop are all out of scope, matching P8.2's own deferral list.

**Placeholder scan:** no TBD/TODO; every step has complete, runnable code. The one explicit verification point (Task 8 Step 1) is a "locate and verify" instruction for an integration surface owned by P8.4 that this plan cannot read directly — same pattern P8.2's plan used for `repo_query`/`repo_relate` names it couldn't fully pin down in advance, not a disguised placeholder (Task 8's own deliverable code — the `<TraceSection ... />` render call — is fully specified).

**Type consistency:** `Trace` fields (`work_package`, `summary`, `sources_used`, `command`, `outcome`) match across migration (25) ↔ domain (Task 2) ↔ service (Task 3/4) ↔ router (Task 5) ↔ TS `Trace` interface (Task 6). `TRACE_OUTCOMES`/outcome literal `'pending'|'success'|'fail'|'mixed'` consistent everywhere it appears (migration ASSERT, Pydantic validator, TS `OUTCOMES` array, i18n `controlPlane.trace.outcomes.*` keys). `create_learning_proposal(actor, trace_id, *, title, body, belief_id)` signature matches identically in the service, the router's `CreateLearningProposalBody`, and the TS `CreateLearningProposalPayload`/`useCreateLearningProposal` hook. `get_belief_lineage`'s new `updated_from: {belief, trace} | None` key matches the TS `BeliefLineage.updated_from` type used by `LineagePanel`. `accept_proposal`'s return shape (`{"proposal": ..., "belief": ...}`) is unchanged for both branches, so `ReviewInbox`/`useAcceptProposal` need no changes to handle learning acceptances.

**Implementer verification points (flagged inline):** exact P8.4 work-package view file/props (Task 8 Step 1 — the only genuinely unknown surface, since P8.4 wasn't landed in the codebase snapshot this plan was written against); confirm the i18n patch script's anchor text still matches verbatim at execution time (Task 7 Step 6 — it fails loudly rather than silently if not).
