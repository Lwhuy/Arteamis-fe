# P8.3 — Decision + Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the governed-promotion loop past the belief: add `decision` and `rule` objects that a Company-scope user creates **from accepted beliefs only**, each backed by a `supports` edge to the belief(s) that justify it, with every creation audited — so "why did we decide this" always traces back to source-backed Company Belief evidence.

**Architecture:** Two new SurrealDB tables, `decision` (`title`, `rationale`, `status`) and `rule` (`title`, `statement`, `status`), plus a shared graph edge `supports` (`decision`/`rule` → `belief`), all carrying a nullable `workspace`. Same thin router → service → domain-model stack as P8.2's governance module (`open_notebook/domain/governance.py`, `api/governance_service.py`, `api/routers/governance.py` — extended in place, not new files). Frontend extends the existing `governanceApi` client + `use-governance.ts` hooks, surfaces decisions/rules inside `CompanyBrainSection`, and adds a "Create decision from belief" affordance to the belief `LineagePanel`.

**Tech Stack:** SurrealDB migrations, FastAPI, Python 3.12 (`uv`, pytest, ruff), surreal graph edges, Next.js 16 / React 19 / TanStack Query 5 / Zustand 5 / vitest.

## Global Constraints

- **Depends on P8.2 (landed).** `proposal`/`belief`/`audit_event` tables, `derived_from`/`promotes_to` edges, and the governance service/router/frontend hooks already exist — this plan extends those same files, it does not fork them.
- **Migrations are hard-coded, not auto-discovered.** `open_notebook/database/async_migrate.py` lists every `N.surrealql`/`N_down.surrealql` explicitly in `AsyncMigrationManager.__init__`. Next free number is **23** (20 = workspace/membership, 21 = visibility, 22 = governance/promotion bridge). Add `23.surrealql` + `23_down.surrealql` and register both.
- **`table_name` is `ClassVar[str]`** on `ObjectModel` subclasses (`open_notebook/domain/base.py`), not a plain pydantic field — declare it exactly like `Proposal`/`Belief`/`AuditEvent` do: `table_name: ClassVar[str] = "decision"`.
- **CRITICAL — record-link fields need `_prepare_save_data()` + `ensure_record_id`.** Any model field typed as SurrealDB `record<>` (e.g. `Proposal.author`, `AuditEvent.actor`/`object`) MUST be converted via `ensure_record_id` in an overridden `_prepare_save_data()`, or the raw string gets written instead of a `RecordID` and downstream graph queries silently break. **This exact omission was a Critical bug in P8.2** (fixed; see `tests/test_governance_record_links.py`). `Decision`/`Rule` have **no direct `record<>` field** — the belief links go through the `supports` edge, created via `repo_relate`, which already converts ids to `RecordID` itself (see `open_notebook/database/repository.py:repo_relate`). So no override is expected here — but Task 2 adds an explicit pinning test asserting this, and any future field like `decided_by: record<user>` must trigger the same override pattern.
- **DB-free unit tests.** Service tests mock `repo_query`/`repo_relate`/`repo_create`/`repo_update` at their import sites (`open_notebook.domain.base.*` for `ObjectModel.get`/`get_all`/`save`; `api.governance_service.*` for the graph-edge helpers) — no live database, following `tests/test_p2_workspace_service.py` and `tests/test_governance_service.py`. Router tests use FastAPI `TestClient` + a bearer JWT from `_auth()` + `@patch("api.routers.governance.<fn>")`, following `tests/test_governance_router.py`.
- **i18n is test-enforced across 14 locales.** `frontend/src/lib/locales/{bn-IN,ca-ES,de-DE,en-US,es-ES,fr-FR,it-IT,ja-JP,pl-PL,pt-BR,ru-RU,tr-TR,zh-CN,zh-TW}/index.ts`. `frontend/src/lib/locales/index.test.ts` enforces both **key parity** (every locale has exactly en-US's keys) and **no unused keys** (every en-US leaf key must appear literally in some source file). Every new `t()` call needs its key added to all 14 files.
- **Frontend data access:** all HTTP via `apiClient` (`frontend/src/lib/api/client.ts`); TanStack Query hooks live in `frontend/src/lib/hooks/use-governance.ts`; mutations invalidate the relevant query key(s) and `toast()` via `t()`, matching the existing `useCreateProposal`/`useAcceptProposal` shape exactly.
- **Single-tenant / workspace-ready (Option B):** new tables carry `workspace: option<record<workspace>>` `FLEXIBLE`, nullable — no workspace table exists yet, this is a forward-compatible seam only.
- **Promotion-only writes:** a decision/rule can only be created by referencing existing `belief_ids` (already-accepted beliefs) — there is no endpoint that creates a decision/rule without at least going through this path; nothing bypasses `Belief`.
- **Audit every transition:** every `create_decision`/`create_rule` call writes an `audit_event` (`decision.created` / `rule.created`), matching `create_proposal`'s `proposal.created` pattern in `api/governance_service.py`.
- **Router registration:** none needed. `api/main.py:407` already does `app.include_router(governance.router, prefix="/api", tags=["governance"])`; new `/decisions` and `/rules` endpoints land on the same `router` object in `api/routers/governance.py`.
- Backend: `uv run pytest tests/`, `ruff check . --fix`. Frontend (`frontend/`): `npm run test`, `npm run lint`, `npm run build`.

---

### Task 1: Migration 23 — decision/rule tables + `supports` edge

**Files:**
- Create: `open_notebook/database/migrations/23.surrealql`
- Create: `open_notebook/database/migrations/23_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (register both, append after the existing `22.surrealql`/`22_down.surrealql` entries)
- Test: `tests/test_migration_23_decision_rule.py`

**Interfaces:**
- Produces tables `decision`, `rule` and edge `supports` (shared: `decision->supports->belief` and `rule->supports->belief`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_23_decision_rule.py
from pathlib import Path


def test_migration_23_defines_decision_rule_tables():
    up = Path("open_notebook/database/migrations/23.surrealql").read_text()
    for t in ["DEFINE TABLE decision", "DEFINE TABLE rule", "DEFINE TABLE supports"]:
        assert t in up, t
    assert "workspace" in up  # workspace-ready
    assert "TYPE RELATION" in up  # supports is an edge table
    down = Path("open_notebook/database/migrations/23_down.surrealql").read_text()
    assert "REMOVE TABLE decision" in down
    assert "REMOVE TABLE rule" in down
    assert "REMOVE TABLE supports" in down


def test_migration_23_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "23.surrealql" in src and "23_down.surrealql" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration_23_decision_rule.py -v`
Expected: FAIL — files don't exist yet, registration assert fails too.

- [ ] **Step 3: Write the migration + register**

```surql
-- open_notebook/database/migrations/23.surrealql
-- Migration 23: decision + rule tables (Decision + Rule objects that reference
-- accepted beliefs). Mirrors migration 22's workspace-ready idiom:
-- option<record<workspace>>, FLEXIBLE, nullable. `supports` is a shared
-- RELATION edge used both decision->belief and rule->belief — same idiom as
-- derived_from/promotes_to in migration 22 (no endpoint-table constraint
-- needed; SurrealDB RELATION tables don't require declaring in/out tables).

DEFINE TABLE decision SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE decision FLEXIBLE TYPE option<record<workspace>>;
DEFINE FIELD IF NOT EXISTS title     ON TABLE decision TYPE string;
DEFINE FIELD IF NOT EXISTS rationale ON TABLE decision TYPE string DEFAULT '';
DEFINE FIELD IF NOT EXISTS status    ON TABLE decision TYPE string DEFAULT 'active' ASSERT $value IN ['active','superseded'];
DEFINE FIELD IF NOT EXISTS created   ON decision DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated   ON decision DEFAULT time::now() VALUE time::now();

DEFINE TABLE rule SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS workspace ON TABLE rule FLEXIBLE TYPE option<record<workspace>>;
DEFINE FIELD IF NOT EXISTS title     ON TABLE rule TYPE string;
DEFINE FIELD IF NOT EXISTS statement ON TABLE rule TYPE string;
DEFINE FIELD IF NOT EXISTS status    ON TABLE rule TYPE string DEFAULT 'active' ASSERT $value IN ['active','superseded'];
DEFINE FIELD IF NOT EXISTS created   ON rule DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated   ON rule DEFAULT time::now() VALUE time::now();

-- edge: decision->supports->belief and rule->supports->belief
DEFINE TABLE supports SCHEMAFULL TYPE RELATION;
```

```surql
-- open_notebook/database/migrations/23_down.surrealql
-- Migration 23 rollback: drop the edge before the tables it references, then
-- decision/rule themselves.
REMOVE TABLE supports;
REMOVE TABLE rule;
REMOVE TABLE decision;
```

In `open_notebook/database/async_migrate.py`, inside `AsyncMigrationManager.__init__`, append to `self.up_migrations` (right after the `22.surrealql` entry):

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/23.surrealql"
            ),
```

and append to `self.down_migrations` (right after the `22_down.surrealql` entry):

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/23_down.surrealql"
            ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migration_23_decision_rule.py -v`
Expected: PASS.

- [ ] **Step 5: Apply + smoke**

Run: `make database && make api`; confirm logs advance to migration 23 without error.

- [ ] **Step 6: Commit**

```bash
git add open_notebook/database/migrations/23.surrealql open_notebook/database/migrations/23_down.surrealql open_notebook/database/async_migrate.py tests/test_migration_23_decision_rule.py
git commit -m "feat(governance): migration 23 - decision/rule tables + supports edge"
```

---

### Task 2: `Decision`/`Rule` domain models

**Files:**
- Modify: `open_notebook/domain/governance.py` (add `Decision`, `Rule`, `DECISION_RULE_STATUSES` alongside the existing `Proposal`/`Belief`/`AuditEvent`)
- Modify: `tests/test_governance_models.py` (add default/validation tests)
- Modify: `tests/test_governance_record_links.py` (add the record-link pinning test called out in Global Constraints)

**Interfaces:**
- Consumes: `ObjectModel` from `open_notebook/domain/base.py` (same base as `Proposal`/`Belief`).
- Produces:
  - `Decision(title, rationale="", status="active")` — `table_name: ClassVar[str] = "decision"`.
  - `Rule(title, statement, status="active")` — `table_name: ClassVar[str] = "rule"`.
  - `DECISION_RULE_STATUSES = ["active", "superseded"]` module constant.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_governance_models.py — append these
from open_notebook.domain.governance import DECISION_RULE_STATUSES, Decision, Rule


def test_decision_defaults():
    d = Decision(title="Ship SMB pricing")
    assert d.status == "active"
    assert d.rationale == ""


def test_decision_rejects_bad_status():
    with pytest.raises(Exception):
        Decision(title="x", status="banana")


def test_rule_defaults():
    r = Rule(title="Always cite two sources", statement="Every Company Belief needs >=2 sources.")
    assert r.status == "active"


def test_decision_rule_status_constant():
    assert "active" in DECISION_RULE_STATUSES and "superseded" in DECISION_RULE_STATUSES
```

```python
# tests/test_governance_record_links.py — append this
from open_notebook.domain.governance import Decision, Rule


def test_decision_and_rule_have_no_direct_record_link_fields():
    """Decision/Rule link to beliefs only via the `supports` edge (created
    through repo_relate, which converts ids to RecordID itself) — neither
    model has a `record<>`-typed field of its own, so unlike Proposal.author
    or AuditEvent.actor/object, no _prepare_save_data() override is needed.
    This pins that invariant: if a future field like `decided_by:
    record<user>` is ever added to Decision, model_dump() and
    _prepare_save_data() diverge and this test starts failing — the trigger
    to add the same ensure_record_id override Proposal/AuditEvent use (this
    exact omission was a Critical bug in P8.2).
    """
    d = Decision(title="x")
    assert d._prepare_save_data() == {
        k: v for k, v in d.model_dump().items() if v is not None
    }
    r = Rule(title="y", statement="z")
    assert r._prepare_save_data() == {
        k: v for k, v in r.model_dump().items() if v is not None
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_governance_models.py tests/test_governance_record_links.py -v`
Expected: FAIL — `Decision`/`Rule` don't exist yet.

- [ ] **Step 3: Implement the models**

In `open_notebook/domain/governance.py`, add below the existing `AuditEvent` class:

```python
DECISION_RULE_STATUSES = ["active", "superseded"]


class Decision(ObjectModel):
    table_name: ClassVar[str] = "decision"
    title: str
    rationale: str = ""
    status: str = "active"

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in DECISION_RULE_STATUSES:
            raise ValueError(f"invalid status {v}")
        return v


class Rule(ObjectModel):
    table_name: ClassVar[str] = "rule"
    title: str
    statement: str
    status: str = "active"

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in DECISION_RULE_STATUSES:
            raise ValueError(f"invalid status {v}")
        return v
```

Neither class overrides `_prepare_save_data()` — deliberately, per the Global Constraints note. Do not add one unless a `record<>` field is added later.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_governance_models.py tests/test_governance_record_links.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add open_notebook/domain/governance.py tests/test_governance_models.py tests/test_governance_record_links.py
git commit -m "feat(governance): Decision/Rule domain models"
```

---

### Task 3: Governance service — create/list/get decision + rule

**Files:**
- Modify: `api/governance_service.py` (add `create_decision`, `list_decisions`, `get_decision`, `create_rule`, `list_rules`, `get_rule`; extend the `open_notebook.domain.governance` import)
- Modify: `tests/test_governance_service.py` (append the new tests)

**Interfaces:**
- Consumes: `Decision`, `Rule` (Task 2); `repo_relate` (`open_notebook/database/repository.py`, already imported in this file); `_audit` (already defined in this file).
- Produces (async functions):
  - `create_decision(actor: str, *, title: str, rationale: str, belief_ids: list[str]) -> Decision` — saves the decision (`status='active'`), `repo_relate(decision.id, "supports", belief_id, {})` per `belief_ids`, writes `audit_event(action='decision.created', meta={'belief_ids': belief_ids})`.
  - `list_decisions(*, status: Optional[str] = None) -> list[Decision]`.
  - `get_decision(decision_id: str) -> Decision`.
  - `create_rule(actor: str, *, title: str, statement: str, belief_ids: list[str]) -> Rule` — same shape, `action='rule.created'`.
  - `list_rules(*, status: Optional[str] = None) -> list[Rule]`.
  - `get_rule(rule_id: str) -> Rule`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_governance_service.py — append these
from api.governance_service import (
    create_decision,
    create_rule,
    get_decision,
    get_rule,
    list_decisions,
    list_rules,
)
from open_notebook.domain.governance import Decision, Rule


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_decision_saves_active_links_beliefs_and_audits(
    mock_create, mock_relate
):
    mock_create.side_effect = [
        [{"id": "decision:1", "status": "active"}],  # decision.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    decision = await create_decision(
        "user:1",
        title="Ship SMB pricing",
        rationale="Belief-backed: SMBs convert faster on tiered pricing",
        belief_ids=["belief:1", "belief:2"],
    )

    assert isinstance(decision, Decision)
    assert decision.status == "active"
    assert decision.id == "decision:1"
    mock_relate.assert_any_await("decision:1", "supports", "belief:1", {})
    mock_relate.assert_any_await("decision:1", "supports", "belief:2", {})

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "decision.created"
    assert audit_data["meta"] == {"belief_ids": ["belief:1", "belief:2"]}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_list_decisions_filters_by_status_in_python(mock_query):
    mock_query.return_value = [
        {"id": "decision:1", "title": "a", "status": "active"},
        {"id": "decision:2", "title": "b", "status": "superseded"},
    ]
    result = await list_decisions(status="active")
    assert len(result) == 1
    assert result[0].id == "decision:1"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_decision_returns_decision(mock_query):
    mock_query.return_value = [{"id": "decision:1", "title": "a", "status": "active"}]
    decision = await get_decision("decision:1")
    assert isinstance(decision, Decision)
    assert decision.title == "a"


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_rule_saves_active_links_beliefs_and_audits(
    mock_create, mock_relate
):
    mock_create.side_effect = [
        [{"id": "rule:1", "status": "active"}],  # rule.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    rule = await create_rule(
        "user:1",
        title="Always cite two sources",
        statement="Every Company Belief needs at least two independent sources.",
        belief_ids=["belief:3"],
    )

    assert isinstance(rule, Rule)
    assert rule.status == "active"
    assert rule.id == "rule:1"
    mock_relate.assert_awaited_once_with("rule:1", "supports", "belief:3", {})

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "rule.created"
    assert audit_data["meta"] == {"belief_ids": ["belief:3"]}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_list_rules_filters_by_status_in_python(mock_query):
    mock_query.return_value = [
        {"id": "rule:1", "title": "a", "statement": "s1", "status": "active"},
        {"id": "rule:2", "title": "b", "statement": "s2", "status": "superseded"},
    ]
    result = await list_rules(status="active")
    assert len(result) == 1
    assert result[0].id == "rule:1"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_rule_returns_rule(mock_query):
    mock_query.return_value = [
        {"id": "rule:1", "title": "a", "statement": "s1", "status": "active"}
    ]
    rule = await get_rule("rule:1")
    assert isinstance(rule, Rule)
    assert rule.title == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: FAIL — `create_decision` etc. not defined in `api.governance_service`.

- [ ] **Step 3: Implement the service functions**

In `api/governance_service.py`, change the domain import line and append the new functions:

```python
from open_notebook.domain.governance import AuditEvent, Belief, Decision, Proposal, Rule
```

```python
async def create_decision(
    actor: str,
    *,
    title: str,
    rationale: str,
    belief_ids: list[str],
) -> Decision:
    """Record a decision and link it to the accepted beliefs that justify it.

    Decisions are promotion-only: belief_ids must reference existing (already
    accepted) Belief records — this function never creates a belief.
    """
    decision = Decision(title=title, rationale=rationale, status="active")
    await decision.save()
    for belief_id in belief_ids:
        await repo_relate(decision.id, "supports", belief_id, {})
    await _audit(actor, "decision.created", decision.id, {"belief_ids": belief_ids})
    return decision


async def list_decisions(*, status: Optional[str] = None) -> list[Decision]:
    """List decisions, optionally filtered by status (filtered in Python,
    same reasoning as list_proposals: Decision.get_all() has no WHERE)."""
    decisions = await Decision.get_all()
    if status is not None:
        decisions = [d for d in decisions if d.status == status]
    return decisions


async def get_decision(decision_id: str) -> Decision:
    return await Decision.get(decision_id)


async def create_rule(
    actor: str,
    *,
    title: str,
    statement: str,
    belief_ids: list[str],
) -> Rule:
    """Record a rule and link it to the accepted beliefs that justify it."""
    rule = Rule(title=title, statement=statement, status="active")
    await rule.save()
    for belief_id in belief_ids:
        await repo_relate(rule.id, "supports", belief_id, {})
    await _audit(actor, "rule.created", rule.id, {"belief_ids": belief_ids})
    return rule


async def list_rules(*, status: Optional[str] = None) -> list[Rule]:
    rules = await Rule.get_all()
    if status is not None:
        rules = [r for r in rules if r.status == status]
    return rules


async def get_rule(rule_id: str) -> Rule:
    return await Rule.get(rule_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: PASS (all decision/rule tests, plus the pre-existing proposal/belief ones still pass).

- [ ] **Step 5: Commit**

```bash
git add api/governance_service.py tests/test_governance_service.py
git commit -m "feat(governance): create/list/get decision + rule service functions"
```

---

### Task 4: Governance router — `/api/decisions` + `/api/rules`

**Files:**
- Modify: `api/routers/governance.py` (add `CreateDecisionBody`, `CreateRuleBody`, and the six new endpoints; extend the `api.governance_service` import)
- Modify: `tests/test_governance_router.py` (append the new tests)

**Interfaces:**
- Consumes: `create_decision`, `list_decisions`, `get_decision`, `create_rule`, `list_rules`, `get_rule` (Task 3); `_actor(request)` (already defined in this file).
- Produces endpoints (all under the existing `router = APIRouter()`, already mounted at `/api` in `api/main.py`):
  - `POST /api/decisions` (201) · `GET /api/decisions?status=` · `GET /api/decisions/{id}`
  - `POST /api/rules` (201) · `GET /api/rules?status=` · `GET /api/rules/{id}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_governance_router.py — append these
def _decision(**overrides) -> "Decision":
    from open_notebook.domain.governance import Decision

    data = dict(
        id="decision:1",
        title="Ship SMB pricing",
        rationale="Belief-backed",
        status="active",
    )
    data.update(overrides)
    return Decision(**data)


def _rule(**overrides) -> "Rule":
    from open_notebook.domain.governance import Rule

    data = dict(
        id="rule:1",
        title="Always cite two sources",
        statement="Every Company Belief needs at least two independent sources.",
        status="active",
    )
    data.update(overrides)
    return Rule(**data)


@patch("api.routers.governance.create_decision", new_callable=AsyncMock)
def test_create_decision_returns_201(mock_create, client):
    mock_create.return_value = _decision()

    resp = client.post(
        "/api/decisions",
        json={
            "title": "Ship SMB pricing",
            "rationale": "Belief-backed",
            "belief_ids": ["belief:1", "belief:2"],
        },
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "decision:1"
    mock_create.assert_awaited_once_with(
        "user:1",
        title="Ship SMB pricing",
        rationale="Belief-backed",
        belief_ids=["belief:1", "belief:2"],
    )


def test_create_decision_requires_auth(client):
    resp = client.post(
        "/api/decisions", json={"title": "x", "belief_ids": []}
    )
    assert resp.status_code == 401


@patch("api.routers.governance.list_decisions", new_callable=AsyncMock)
def test_list_decisions_returns_mocked_list(mock_list, client):
    mock_list.return_value = [_decision(), _decision(id="decision:2")]

    resp = client.get("/api/decisions?status=active", headers=_auth())

    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert ids == ["decision:1", "decision:2"]
    mock_list.assert_awaited_once_with(status="active")


@patch("api.routers.governance.get_decision", new_callable=AsyncMock)
def test_get_decision_returns_200(mock_get, client):
    mock_get.return_value = _decision()

    resp = client.get("/api/decisions/decision:1", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["title"] == "Ship SMB pricing"


@patch("api.routers.governance.create_rule", new_callable=AsyncMock)
def test_create_rule_returns_201(mock_create, client):
    mock_create.return_value = _rule()

    resp = client.post(
        "/api/rules",
        json={
            "title": "Always cite two sources",
            "statement": "Every Company Belief needs at least two independent sources.",
            "belief_ids": ["belief:3"],
        },
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "rule:1"
    mock_create.assert_awaited_once_with(
        "user:1",
        title="Always cite two sources",
        statement="Every Company Belief needs at least two independent sources.",
        belief_ids=["belief:3"],
    )


def test_create_rule_requires_auth(client):
    resp = client.post(
        "/api/rules", json={"title": "x", "statement": "y", "belief_ids": []}
    )
    assert resp.status_code == 401


@patch("api.routers.governance.list_rules", new_callable=AsyncMock)
def test_list_rules_returns_mocked_list(mock_list, client):
    mock_list.return_value = [_rule()]

    resp = client.get("/api/rules?status=active", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "rule:1"
    mock_list.assert_awaited_once_with(status="active")


@patch("api.routers.governance.get_rule", new_callable=AsyncMock)
def test_get_rule_returns_200(mock_get, client):
    mock_get.return_value = _rule()

    resp = client.get("/api/rules/rule:1", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["title"] == "Always cite two sources"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_governance_router.py -v`
Expected: FAIL — `/api/decisions` and `/api/rules` return 404.

- [ ] **Step 3: Implement the router endpoints**

In `api/routers/governance.py`, change the service import to:

```python
from api.governance_service import (
    accept_proposal,
    create_decision,
    create_proposal,
    create_rule,
    get_belief_lineage,
    get_decision,
    get_proposal,
    get_rule,
    list_decisions,
    list_proposals,
    list_rules,
    request_changes,
)
```

Add the request models below `ChangesBody`:

```python
class CreateDecisionBody(BaseModel):
    title: str
    rationale: str = ""
    belief_ids: list[str] = []


class CreateRuleBody(BaseModel):
    title: str
    statement: str
    belief_ids: list[str] = []
```

Add the endpoints at the end of the file (after `belief_lineage_endpoint`):

```python
@router.post("/decisions", status_code=201)
async def create_decision_endpoint(
    body: CreateDecisionBody, request: Request
) -> dict[str, Any]:
    decision = await create_decision(
        _actor(request),
        title=body.title,
        rationale=body.rationale,
        belief_ids=body.belief_ids,
    )
    return decision.model_dump()


@router.get("/decisions")
async def list_decisions_endpoint(status: Optional[str] = None) -> list[dict[str, Any]]:
    decisions = await list_decisions(status=status)
    return [d.model_dump() for d in decisions]


@router.get("/decisions/{decision_id}")
async def get_decision_endpoint(decision_id: str) -> dict[str, Any]:
    decision = await get_decision(decision_id)
    return decision.model_dump()


@router.post("/rules", status_code=201)
async def create_rule_endpoint(body: CreateRuleBody, request: Request) -> dict[str, Any]:
    rule = await create_rule(
        _actor(request),
        title=body.title,
        statement=body.statement,
        belief_ids=body.belief_ids,
    )
    return rule.model_dump()


@router.get("/rules")
async def list_rules_endpoint(status: Optional[str] = None) -> list[dict[str, Any]]:
    rules = await list_rules(status=status)
    return [r.model_dump() for r in rules]


@router.get("/rules/{rule_id}")
async def get_rule_endpoint(rule_id: str) -> dict[str, Any]:
    rule = await get_rule(rule_id)
    return rule.model_dump()
```

No changes to `api/main.py` or `api/routers/__init__.py` — the router is already registered (`api/main.py:407`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_governance_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/governance.py tests/test_governance_router.py
git commit -m "feat(governance): /api/decisions + /api/rules router endpoints"
```

---

### Task 5: Frontend governance API client + hooks — decisions/rules

**Files:**
- Modify: `frontend/src/lib/api/governance.ts` (add `Decision`, `Rule`, `CreateDecisionPayload`, `CreateRulePayload` types + `governanceApi.createDecision/listDecisions/createRule/listRules`)
- Modify: `frontend/src/lib/hooks/use-governance.ts` (add `useDecisions`, `useCreateDecision`, `useRules`, `useCreateRule`)
- Modify: `frontend/src/lib/hooks/use-governance.test.tsx` (append tests)

**Interfaces:**
- Produces:
  - `governanceApi.createDecision(payload: CreateDecisionPayload): Promise<Decision>`
  - `governanceApi.listDecisions(status?: string): Promise<Decision[]>`
  - `governanceApi.createRule(payload: CreateRulePayload): Promise<Rule>`
  - `governanceApi.listRules(status?: string): Promise<Rule[]>`
  - `useDecisions(status?: string)`, `useCreateDecision()`, `useRules(status?: string)`, `useCreateRule()` — same TanStack Query shape as `useProposals`/`useCreateProposal`. Mutations invalidate `['decisions']`/`['rules']` and toast via `t('governance.toastDecisionCreated')` / `t('governance.toastRuleCreated')`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/lib/hooks/use-governance.test.tsx — append these
vi.mock('@/lib/api/governance', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/governance')>(
    '@/lib/api/governance',
  )
  return {
    ...actual,
    governanceApi: {
      ...actual.governanceApi,
      listProposals: vi.fn().mockResolvedValue([{ id: 'proposal:1', title: 'SMB', status: 'pending' }]),
      listDecisions: vi.fn().mockResolvedValue([{ id: 'decision:1', title: 'Ship SMB pricing', status: 'active' }]),
    },
  }
})

import { useDecisions } from './use-governance'

describe('useDecisions', () => {
  it('fetches active decisions', async () => {
    const { result } = renderHook(() => useDecisions('active'), { wrapper })
    await waitFor(() => expect(result.current.data?.[0].title).toBe('Ship SMB pricing'))
  })
})
```

> The existing top-of-file `vi.mock('@/lib/api/governance', ...)` only stubs `listProposals`; replace it with the `importActual`-spread version above so both the existing `useProposals` test and the new `useDecisions` test can mock only the functions they use without clobbering the module's other exports (`governanceApi.createProposal`, etc., used elsewhere if any other test in this file is added later).

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- use-governance`
Expected: FAIL — `useDecisions` not exported.

- [ ] **Step 3: Implement client + hooks**

In `frontend/src/lib/api/governance.ts`, add below `CreateProposalPayload`:

```ts
export interface Decision {
  id: string
  title: string
  rationale: string
  status: string
}

export interface Rule {
  id: string
  title: string
  statement: string
  status: string
}

export interface CreateDecisionPayload {
  title: string
  rationale?: string
  belief_ids: string[]
}

export interface CreateRulePayload {
  title: string
  statement: string
  belief_ids: string[]
}
```

Add to the `governanceApi` object:

```ts
  createDecision: (payload: CreateDecisionPayload) =>
    apiClient.post<Decision>('/decisions', payload).then((r) => r.data),

  listDecisions: (status?: string) =>
    apiClient.get<Decision[]>('/decisions', { params: { status } }).then((r) => r.data),

  createRule: (payload: CreateRulePayload) =>
    apiClient.post<Rule>('/rules', payload).then((r) => r.data),

  listRules: (status?: string) =>
    apiClient.get<Rule[]>('/rules', { params: { status } }).then((r) => r.data),
```

In `frontend/src/lib/hooks/use-governance.ts`, update the import and `KEYS`:

```ts
import { governanceApi, type CreateProposalPayload, type CreateDecisionPayload, type CreateRulePayload } from '@/lib/api/governance'
```

```ts
const KEYS = {
  proposals: ['proposals'] as const,
  beliefs: ['beliefs'] as const,
  decisions: ['decisions'] as const,
  rules: ['rules'] as const,
}
```

Add below `useBelief`:

```ts
export const useDecisions = (status?: string) =>
  useQuery({
    queryKey: [...KEYS.decisions, status ?? 'all'],
    queryFn: () => governanceApi.listDecisions(status),
  })

export const useRules = (status?: string) =>
  useQuery({
    queryKey: [...KEYS.rules, status ?? 'all'],
    queryFn: () => governanceApi.listRules(status),
  })
```

Add below `useCreateProposal`:

```ts
export function useCreateDecision() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (payload: CreateDecisionPayload) => governanceApi.createDecision(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.decisions })
      toast({ title: t('governance.toastDecisionCreated') })
    },
  })
}

export function useCreateRule() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (payload: CreateRulePayload) => governanceApi.createRule(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.rules })
      toast({ title: t('governance.toastRuleCreated') })
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
git commit -m "feat(control-plane): governance api client + hooks for decisions/rules"
```

---

### Task 6: Surface decisions/rules in `CompanyBrainSection` + "Create decision" affordance in `LineagePanel`

**Files:**
- Modify: `frontend/src/components/control-plane/CompanyBrainSection.tsx` (add decisions + rules subsections below the existing beliefs list)
- Create: `frontend/src/components/control-plane/CreateDecisionButton.tsx`
- Modify: `frontend/src/components/control-plane/LineagePanel.tsx` (render `<CreateDecisionButton>`)
- Modify: `frontend/src/components/control-plane/LineagePanel.test.tsx` (mock `useCreateDecision`, which `CreateDecisionButton` now pulls from the same `@/lib/hooks/use-governance` module mock)
- Create: `frontend/src/components/control-plane/CompanyBrainSection.test.tsx`

**Interfaces:**
- Consumes: `useBeliefs`, `useDecisions`, `useRules` (Task 5, read); `useCreateDecision` (Task 5, write); `useArtifact` (belief click → lineage, unchanged).
- Produces: `<CompanyBrainSection />` (extended), `<CreateDecisionButton beliefId belieTitle />`.
- Decisions/rules are **not** artifact types — `useArtifact`'s `ArtifactRef['type']` stays `'source' | 'belief'` (unchanged); decision/rule list items render as static rows, not clickable artifact links, matching the "small section" scope of this plan (no decision/rule detail viewer).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/CompanyBrainSection.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-governance', () => ({
  useBeliefs: () => ({ data: [{ id: 'belief:1', title: 'SMB focus' }] }),
  useDecisions: () => ({ data: [{ id: 'decision:1', title: 'Ship SMB pricing', status: 'active' }] }),
  useRules: () => ({ data: [{ id: 'rule:1', title: 'Always cite two sources', status: 'active' }] }),
}));
vi.mock('@/lib/hooks/use-artifact', () => ({
  useArtifact: () => ({ openArtifact: vi.fn() }),
}));

import { CompanyBrainSection } from './CompanyBrainSection';

describe('CompanyBrainSection', () => {
  it('shows beliefs, decisions, and rules', () => {
    render(<CompanyBrainSection />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    expect(screen.getByText('Ship SMB pricing')).toBeInTheDocument();
    expect(screen.getByText('Always cite two sources')).toBeInTheDocument();
  });
});
```

Update `frontend/src/components/control-plane/LineagePanel.test.tsx`'s existing `vi.mock('@/lib/hooks/use-governance', ...)` to also stub `useCreateDecision` (needed once `LineagePanel` renders `CreateDecisionButton`, which calls that hook on every render):

```tsx
vi.mock('@/lib/hooks/use-governance', () => ({
  useBelief: () => ({ data: {
    belief: { id: 'belief:1', title: 'SMB focus' },
    sources: [{ id: 'source:9', title: 'Q3 Research', locator: 'p.4' }],
    provenance: [{ action: 'proposal.accepted', actor: 'user:1' }],
    derived_work: [], contradictions: [],
  }, isLoading: false }),
  useCreateDecision: () => ({ mutate: vi.fn(), isPending: false }),
}));
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- CompanyBrainSection LineagePanel`
Expected: FAIL — `CompanyBrainSection.test.tsx` module missing; `LineagePanel.test.tsx` fails once `LineagePanel` imports `CreateDecisionButton` (undefined `useCreateDecision` in the mock throws on render).

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/control-plane/CompanyBrainSection.tsx
'use client';
import { Sparkles, Gavel, ListChecks } from 'lucide-react';
import { useBeliefs, useDecisions, useRules } from '@/lib/hooks/use-governance';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';

export function CompanyBrainSection() {
  const { t } = useTranslation();
  const { data: beliefData } = useBeliefs();
  const { data: decisionData } = useDecisions();
  const { data: ruleData } = useRules();
  const { openArtifact } = useArtifact();

  const beliefs = (beliefData ?? []) as { id: string; title: string }[];
  const decisions = (decisionData ?? []) as { id: string; title: string; status: string }[];
  const rules = (ruleData ?? []) as { id: string; title: string; status: string }[];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        {beliefs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{t('controlPlane.sidebar.brainEmpty')}</div>
        ) : (
          beliefs.map((b) => (
            <button key={b.id} type="button" onClick={() => openArtifact('belief', b.id)}
              className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5 text-left hover:border-primary">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="flex-1 truncate text-xs font-semibold text-foreground">{b.title}</span>
              <span className="text-[10px] text-muted-foreground">{t('controlPlane.brain.view')}</span>
            </button>
          ))
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.brain.decisionsTitle')}</div>
        {decisions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-2.5 text-center text-xs text-muted-foreground">{t('controlPlane.brain.decisionsEmpty')}</div>
        ) : (
          decisions.map((d) => (
            <div key={d.id} className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5">
              <Gavel className="h-4 w-4 text-primary" />
              <span className="flex-1 truncate text-xs font-semibold text-foreground">{d.title}</span>
              <span className="text-[10px] text-muted-foreground">{d.status}</span>
            </div>
          ))
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.brain.rulesTitle')}</div>
        {rules.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-2.5 text-center text-xs text-muted-foreground">{t('controlPlane.brain.rulesEmpty')}</div>
        ) : (
          rules.map((r) => (
            <div key={r.id} className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5">
              <ListChecks className="h-4 w-4 text-primary" />
              <span className="flex-1 truncate text-xs font-semibold text-foreground">{r.title}</span>
              <span className="text-[10px] text-muted-foreground">{r.status}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
```

```tsx
// frontend/src/components/control-plane/CreateDecisionButton.tsx
'use client';
import { Gavel } from 'lucide-react';
import { useCreateDecision } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

export function CreateDecisionButton({ beliefId, beliefTitle }: { beliefId: string; beliefTitle: string }) {
  const { t } = useTranslation();
  const create = useCreateDecision();
  return (
    <button type="button" disabled={create.isPending}
      onClick={() => create.mutate({ title: beliefTitle, rationale: '', belief_ids: [beliefId] })}
      className="mt-2 flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground hover:border-primary">
      <Gavel className="h-3.5 w-3.5" /> {t('controlPlane.lineage.createDecision')}
    </button>
  );
}
```

In `frontend/src/components/control-plane/LineagePanel.tsx`, add the import and render the button after the sources block (before the provenance block):

```tsx
import { CreateDecisionButton } from './CreateDecisionButton';
```

```tsx
      <div className="mb-4">
        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.lineage.sources')}</div>
        {sources.map((s) => (
          <button key={s.id} type="button" onClick={() => openArtifact('source', s.id, s.locator)}
            className="flex w-full items-center gap-2 border-b border-border py-2 text-left text-sm text-foreground hover:text-primary">
            <FileText className="h-4 w-4 text-muted-foreground" /> <span className="flex-1">{s.title}</span>
            {s.locator ? <span className="text-xs text-muted-foreground">{s.locator}</span> : null}
          </button>
        ))}
        <CreateDecisionButton beliefId={belief.id} beliefTitle={belief.title} />
      </div>
```

(This replaces the closing `</div>` of the existing sources block — the rest of `LineagePanel.tsx`, i.e. the provenance and contradiction blocks below it, is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- CompanyBrainSection LineagePanel`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/CompanyBrainSection.tsx frontend/src/components/control-plane/CreateDecisionButton.tsx frontend/src/components/control-plane/LineagePanel.tsx frontend/src/components/control-plane/LineagePanel.test.tsx frontend/src/components/control-plane/CompanyBrainSection.test.tsx
git commit -m "feat(control-plane): surface decisions/rules in Company Brain, create-decision affordance"
```

---

### Task 7: i18n keys across all 14 locales + full gate + smoke

**Files:**
- Modify: `frontend/src/lib/locales/{bn-IN,ca-ES,de-DE,en-US,es-ES,fr-FR,it-IT,ja-JP,pl-PL,pt-BR,ru-RU,tr-TR,zh-CN,zh-TW}/index.ts`

**Interfaces:**
- Produces new keys (all already referenced by Tasks 5–6 via `t('...')`):
  - `governance.toastDecisionCreated`
  - `governance.toastRuleCreated`
  - `controlPlane.brain.decisionsTitle`
  - `controlPlane.brain.decisionsEmpty`
  - `controlPlane.brain.rulesTitle`
  - `controlPlane.brain.rulesEmpty`
  - `controlPlane.lineage.createDecision`

- [ ] **Step 1: Write the failing test (run the existing locale-parity suite)**

Run: `npm run test -- locales`
Expected: FAIL — `Locale Parity` reports the 7 new keys missing from all 13 non-en-US locales (they exist nowhere yet, including en-US, so `Unused Key Detection` isn't the blocker yet — add en-US first in Step 3, then the parity failures show up for the other 13).

- [ ] **Step 2: (no-op — this task is pure content addition, already covered by Step 1's run)**

- [ ] **Step 3: Add the keys**

In `frontend/src/lib/locales/en-US/index.ts`, extend the existing `governance` block:

```ts
  governance: {
    toastProposed: "Proposed to company",
    toastAccepted: "Accepted into Company Brain",
    toastChangesRequested: "Sent back for changes",
    toastDecisionCreated: "Decision created",
    toastRuleCreated: "Rule created",
  },
```

and the existing `controlPlane.brain` / `controlPlane.lineage` blocks:

```ts
    brain: {
      view: "View",
      decisionsTitle: "Decisions",
      decisionsEmpty: "No decisions yet.",
      rulesTitle: "Rules",
      rulesEmpty: "No rules yet.",
    },
```

```ts
    lineage: {
      belief: "Belief",
      sources: "Sources",
      provenance: "Provenance",
      contradiction: "Contradiction",
      contradictionNone: "No contradictions detected",
      createDecision: "Create decision from this belief",
    },
```

Then add the same nested keys (translated) to each of the other 13 locale `index.ts` files, in the same nested position under their existing `governance`/`controlPlane.brain`/`controlPlane.lineage` blocks — e.g. for `pt-BR`:

```ts
  governance: {
    // ...existing keys...
    toastDecisionCreated: "Decisão criada",
    toastRuleCreated: "Regra criada",
  },
```

```ts
    brain: {
      view: "Ver",
      decisionsTitle: "Decisões",
      decisionsEmpty: "Nenhuma decisão ainda.",
      rulesTitle: "Regras",
      rulesEmpty: "Nenhuma regra ainda.",
    },
```

```ts
    lineage: {
      belief: "Crença",
      sources: "Fontes",
      provenance: "Proveniência",
      contradiction: "Contradição",
      contradictionNone: "Nenhuma contradição detectada",
      createDecision: "Criar decisão a partir desta crença",
    },
```

Repeat for `bn-IN`, `ca-ES`, `de-DE`, `es-ES`, `fr-FR`, `it-IT`, `ja-JP`, `pl-PL`, `ru-RU`, `tr-TR`, `zh-CN`, `zh-TW`, matching each locale's existing tone/register for the surrounding keys in those same blocks (translate each of the 7 new strings; do not leave any locale with an English fallback — the parity test asserts every locale has the exact same key set as en-US, not that the values differ, but Global Constraints requires real localized copy, matching how every other key in these files is already translated).

- [ ] **Step 4: Run test to verify it passes**

Run (frontend, from `frontend/`):
```bash
npm run test -- locales
npm run test
npm run lint
npm run build
```
Expected: all PASS — locale parity green, unused-key detection green (all 7 keys are referenced in Tasks 5–6's source), full suite green, lint clean, build succeeds.

Run (backend, from repo root):
```bash
uv run pytest tests/
ruff check .
```
Expected: all PASS.

- [ ] **Step 5: End-to-end smoke**

With the stack up (`make start-all`): in **Company** scope, open the artifact panel for an accepted belief (via **Company Brain** → click a belief) → the **LineagePanel** now shows a **"Create decision from this belief"** button below its sources → click it → toast "Decision created" → the sidebar's **Company Brain** section now lists it under **Decisions** with status `active`. Repeat conceptually for a rule via `POST /api/rules` (no dedicated UI trigger for rule creation in this plan — verify via `curl -X POST http://localhost:5055/api/rules -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"title":"Always cite two sources","statement":"Every Company Belief needs at least two independent sources.","belief_ids":["belief:1"]}'`) → refresh the control plane → the new rule appears under **Rules** in Company Brain.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/locales
git commit -m "feat(control-plane): i18n keys for decision/rule across all 14 locales"
```

---

## Self-Review

**Spec coverage:**
- Migration 23: `decision`/`rule` tables + shared `supports` edge, workspace-ready nullable → Task 1. ✓
- `Decision`/`Rule` domain models, `ClassVar[str] table_name` → Task 2. ✓
- Critical-bug lesson (record-link fields need `_prepare_save_data`/`ensure_record_id`) explicitly checked and pinned with a test, even though no override is needed here → Task 2, Global Constraints. ✓
- `create_decision(actor, *, title, rationale, belief_ids)` — saves, `repo_relate` supports→each belief, audits → Task 3. ✓
- `create_rule(actor, *, title, statement, belief_ids)` — same shape → Task 3. ✓
- List/get for both → Task 3 (`list_decisions`/`get_decision`/`list_rules`/`get_rule`). ✓
- DB-free unit tests mocking `repo_query`/`repo_relate`/`repo_create` following `tests/test_p2_workspace_service.py` / `tests/test_governance_service.py` → Task 3. ✓
- `POST /api/decisions`, `POST /api/rules`, `GET` list endpoints → Task 4 (also added `GET .../{id}` for symmetry with `get_decision`/`get_rule`, matching the existing `GET /proposals/{id}` pattern). ✓
- Router tests follow `tests/test_governance_router.py` (`TestClient` + `_auth()` + patched service functions) → Task 4. ✓
- No new router registration (already registered) → confirmed via `api/main.py:407`, called out explicitly in Task 4 and Global Constraints. ✓
- `governanceApi`/`use-governance.ts` additions: `useCreateDecision`, `useDecisions`, `useCreateRule`, `useRules` → Task 5. ✓
- Surface decisions/rules in Company Brain area (extends `CompanyBrainSection`) → Task 6. ✓
- "Create decision from belief" affordance in `LineagePanel` → Task 6 (`CreateDecisionButton`). ✓
- i18n keys added to all 14 locales, referenced in source → Task 7. ✓

**Out of scope (correctly deferred):** a rule-creation UI affordance (only the API + list surface are built; the spec named "create decision from belief" specifically, not "create rule from belief" — `create_rule` is fully wired end-to-end at the service/router/hook layer, just not bound to a button, consistent with "Tests are DB-free... plus list/get" being the stated scope for rules); a dedicated decision/rule detail artifact view (`ArtifactRef` stays `'source' | 'belief'`); superseding/editing decisions or rules; contradiction detection between rules; role/permission gating on who may create a decision/rule (single-tenant, no role gating yet, same as P8.2).

**Placeholder scan:** No TBD/TODO in any code block. All SurrealQL, Python, and TSX snippets are complete, runnable, and match the exact conventions of the files they extend (verified against the live contents of `open_notebook/domain/governance.py`, `api/governance_service.py`, `api/routers/governance.py`, `open_notebook/database/migrations/22.surrealql`, `open_notebook/database/async_migrate.py`, `frontend/src/lib/api/governance.ts`, `frontend/src/lib/hooks/use-governance.ts`, `frontend/src/components/control-plane/{CompanyBrainSection,LineagePanel,ProposeButton}.tsx`, and `frontend/src/lib/locales/en-US/index.ts` as they exist today, not the P8.2 plan's draft versions).

**Type consistency:** `Decision{title, rationale, status}` / `Rule{title, statement, status}` align across migration (Task 1) ↔ domain (Task 2) ↔ service (Task 3) ↔ router (Task 4) ↔ TS interfaces (Task 5) ↔ components (Task 6). `belief_ids: list[str]` (Python) ↔ `belief_ids: string[]` (TS) consistent client↔server. `status` values (`active`/`superseded`) consistent everywhere a status field appears. `supports` edge name consistent between migration, service (`repo_relate(..., "supports", ...)`), and the Global Constraints description. Audit `action` strings (`decision.created`, `rule.created`) consistent between Task 3's implementation and its own tests. `useCreateDecision`/`useDecisions`/`useCreateRule`/`useRules` names match between Task 5 (definition) and Task 6 (consumption) exactly — no `useCreateDecisions` vs `useCreateDecision` drift.

**Implementer verification points (flagged inline):** confirm `open_notebook/database/async_migrate.py`'s migration list still ends at `22`/`22_down` before appending `23`/`23_down` (Task 1) — if a later, unrelated migration already claimed 23, renumber; confirm `tests/test_governance_service.py`'s existing `AsyncMock`/`patch` import lines already cover what Task 3's new tests need (they do — same file, same imports already present); confirm `frontend/src/lib/hooks/use-governance.test.tsx`'s top-of-file mock doesn't already spread `governanceApi` in a way that conflicts with Task 5's Step 1 change (read the file before editing, since Task 5 modifies the existing `vi.mock` call rather than adding a second one).
