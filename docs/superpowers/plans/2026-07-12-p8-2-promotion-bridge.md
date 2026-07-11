# P8.2 — Promotion Bridge (Propose → Review → Belief) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the defining Arteamis mechanic — from a private source insight, a user **proposes** a belief to the company; in Company scope a reviewer **accepts** it (making it a source-backed Company Belief) or **requests changes**; every transition is audited; the accepted belief exposes a **lineage** (its sources + provenance) in the artifact panel.

**Architecture:** Single-tenant, workspace-ready (Option B). New SurrealDB tables `proposal`, `belief`, `audit_event` + graph edges `derived_from` (proposal/belief → source, carrying a `locator`) and `promotes_to` (proposal → belief), all carrying a nullable `workspace`. A thin router → service → domain-model stack (matching `api/AGENTS.md`). Frontend adds a governance API client + TanStack hooks, a `Propose` action on chat insights, a `ReviewInbox` (Company scope) and `CompanyBrain` sidebar section, and completes the artifact panel's belief `LineagePanel` (the P8.1 stub).

**Tech Stack:** SurrealDB migrations, FastAPI, Python 3.12 (`uv`, pytest, ruff), surreal graph edges, Next.js 16 / React 19 / TanStack Query 5 / Zustand 5 / vitest.

## Global Constraints

- **Depends on P8.0 + P8.1** (control plane shell, scope store, artifact reader, `source.visibility`, `useArtifact`). Treat as landed.
- **Single-tenant / workspace-ready:** every new table carries `workspace: option<record<workspace>>` (nullable; `workspace` table doesn't exist yet — declare the field `FLEXIBLE`/`option<>` so it doesn't break). No role gating in this plan (owner = the single user); the seam (`AuthContext.role`) is where P2 will add it.
- **Promotion is the only private→company bridge.** Nothing becomes a belief except via `proposal → accept`. No endpoint writes a belief directly.
- **Async-first / data discipline:** HTTP via `apiClient`; TanStack hooks in `lib/hooks/`; broad invalidation + toast. Every governance write appends an `audit_event`.
- **i18n test-enforced:** new strings → `t()`, keys in all 14 locales, referenced in source.
- **Migrations hard-coded:** add `21.surrealql` + `21_down.surrealql`, register both in `open_notebook/database/async_migrate.py`.
- **Router registration:** add the router in `api/main.py` (`app.include_router(governance.router, prefix="/api", ...)`) and import it in `api/routers/__init__.py`, matching the existing router registration block.
- Backend: `uv run pytest tests/`, `ruff check . --fix`. Frontend (`frontend/`): `npm run test`, `npm run lint`, `npm run build`.

---

### Task 1: Migration 21 — governance tables + edges

**Files:**
- Create: `open_notebook/database/migrations/21.surrealql`
- Create: `open_notebook/database/migrations/21_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (register both)
- Test: `tests/test_migration_21_governance.py`

**Interfaces:**
- Produces tables `proposal`, `belief`, `audit_event` and edges `derived_from`, `promotes_to`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_21_governance.py
from pathlib import Path

def test_migration_21_defines_governance_tables():
    up = Path("open_notebook/database/migrations/21.surrealql").read_text()
    for t in ["DEFINE TABLE proposal", "DEFINE TABLE belief", "DEFINE TABLE audit_event",
              "DEFINE TABLE derived_from", "DEFINE TABLE promotes_to"]:
        assert t in up, t
    assert "workspace" in up  # workspace-ready
    down = Path("open_notebook/database/migrations/21_down.surrealql").read_text()
    assert "REMOVE TABLE proposal" in down and "REMOVE TABLE belief" in down

def test_migration_21_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "21.surrealql" in src and "21_down.surrealql" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration_21_governance.py -v`
Expected: FAIL.

- [ ] **Step 3: Write the migration + register**

```surql
-- open_notebook/database/migrations/21.surrealql
DEFINE TABLE proposal SCHEMAFULL;
DEFINE FIELD workspace   ON proposal FLEXIBLE TYPE option<record<workspace>>;
DEFINE FIELD author      ON proposal TYPE record<user>;
DEFINE FIELD kind        ON proposal TYPE string DEFAULT 'belief' ASSERT $value IN ['belief','decision','rule','learning'];
DEFINE FIELD title       ON proposal TYPE string;
DEFINE FIELD body        ON proposal TYPE string DEFAULT '';
DEFINE FIELD claim_type  ON proposal TYPE string DEFAULT 'inference' ASSERT $value IN ['fact','inference','assumption','recommendation','preference'];
DEFINE FIELD confidence  ON proposal TYPE float DEFAULT 0.5;
DEFINE FIELD status      ON proposal TYPE string DEFAULT 'pending' ASSERT $value IN ['pending','accepted','changes_requested','rejected'];
DEFINE FIELD visibility  ON proposal TYPE string DEFAULT 'company' ASSERT $value IN ['private','company'];
DEFINE FIELD created     ON proposal TYPE datetime DEFAULT time::now();
DEFINE FIELD updated     ON proposal TYPE datetime DEFAULT time::now();

DEFINE TABLE belief SCHEMAFULL;
DEFINE FIELD workspace  ON belief FLEXIBLE TYPE option<record<workspace>>;
DEFINE FIELD title      ON belief TYPE string;
DEFINE FIELD body       ON belief TYPE string DEFAULT '';
DEFINE FIELD status     ON belief TYPE string DEFAULT 'current' ASSERT $value IN ['current','superseded'];
DEFINE FIELD claim_type ON belief TYPE string DEFAULT 'inference';
DEFINE FIELD confidence ON belief TYPE float DEFAULT 0.5;
DEFINE FIELD created    ON belief TYPE datetime DEFAULT time::now();
DEFINE FIELD updated    ON belief TYPE datetime DEFAULT time::now();

DEFINE TABLE audit_event SCHEMAFULL;
DEFINE FIELD workspace ON audit_event FLEXIBLE TYPE option<record<workspace>>;
DEFINE FIELD actor     ON audit_event TYPE record<user>;
DEFINE FIELD action    ON audit_event TYPE string;
DEFINE FIELD object    ON audit_event FLEXIBLE TYPE option<record>;
DEFINE FIELD meta      ON audit_event FLEXIBLE TYPE option<object>;
DEFINE FIELD created   ON audit_event TYPE datetime DEFAULT time::now();

-- edges
DEFINE TABLE derived_from SCHEMAFULL TYPE RELATION;
DEFINE FIELD locator ON derived_from TYPE option<string>;
DEFINE TABLE promotes_to SCHEMAFULL TYPE RELATION;
```

```surql
-- open_notebook/database/migrations/21_down.surrealql
REMOVE TABLE promotes_to;
REMOVE TABLE derived_from;
REMOVE TABLE audit_event;
REMOVE TABLE belief;
REMOVE TABLE proposal;
```

Register `"21.surrealql"` / `"21_down.surrealql"` in `AsyncMigrationManager.__init__`.

> Verify the `DEFINE TABLE ... TYPE RELATION` idiom against how existing edge tables (`reference`, `artifact`, `refers_to`) are defined in earlier migrations, and copy that exact syntax (SurrealDB version-specific).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migration_21_governance.py -v`
Expected: PASS.

- [ ] **Step 5: Apply + smoke**

Run: `make database && make api`; confirm logs advance to migration 21 without error.

- [ ] **Step 6: Commit**

```bash
git add open_notebook/database/migrations/21.surrealql open_notebook/database/migrations/21_down.surrealql open_notebook/database/async_migrate.py tests/test_migration_21_governance.py
git commit -m "feat(governance): migration 21 - proposal/belief/audit tables + edges"
```

---

### Task 2: Governance domain models

**Files:**
- Create: `open_notebook/domain/governance.py`
- Test: `tests/test_governance_models.py`

**Interfaces:**
- Produces (extend `ObjectModel` from `open_notebook/domain/base.py`):
  - `Proposal`: `author, kind='belief', title, body='', claim_type='inference', confidence=0.5, status='pending', visibility='company'`; `table_name = 'proposal'`.
  - `Belief`: `title, body='', status='current', claim_type='inference', confidence=0.5`; `table_name='belief'`.
  - `AuditEvent`: `actor, action, object=None, meta={}`; `table_name='audit_event'`.
  - Enums as module constants: `PROPOSAL_STATUSES`, `CLAIM_TYPES`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_governance_models.py
import pytest
from open_notebook.domain.governance import Proposal, Belief, CLAIM_TYPES, PROPOSAL_STATUSES

def test_proposal_defaults():
    p = Proposal(author="user:1", title="SMB focus")
    assert p.status == "pending"
    assert p.kind == "belief"
    assert p.visibility == "company"
    assert p.claim_type in CLAIM_TYPES

def test_proposal_rejects_bad_status():
    with pytest.raises(Exception):
        Proposal(author="user:1", title="x", status="banana")

def test_belief_defaults_current():
    b = Belief(title="SMB focus")
    assert b.status == "current"

def test_enum_constants():
    assert "pending" in PROPOSAL_STATUSES and "accepted" in PROPOSAL_STATUSES
    assert "inference" in CLAIM_TYPES and "fact" in CLAIM_TYPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_governance_models.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the models**

```python
# open_notebook/domain/governance.py
from typing import Any, Literal, Optional
from pydantic import Field, field_validator
from open_notebook.domain.base import ObjectModel

CLAIM_TYPES = ["fact", "inference", "assumption", "recommendation", "preference"]
PROPOSAL_STATUSES = ["pending", "accepted", "changes_requested", "rejected"]
PROPOSAL_KINDS = ["belief", "decision", "rule", "learning"]

class Proposal(ObjectModel):
    table_name: str = "proposal"
    author: str
    kind: str = "belief"
    title: str
    body: str = ""
    claim_type: str = "inference"
    confidence: float = 0.5
    status: str = "pending"
    visibility: str = "company"

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in PROPOSAL_STATUSES:
            raise ValueError(f"invalid status {v}")
        return v

    @field_validator("claim_type")
    @classmethod
    def _claim(cls, v: str) -> str:
        if v not in CLAIM_TYPES:
            raise ValueError(f"invalid claim_type {v}")
        return v

class Belief(ObjectModel):
    table_name: str = "belief"
    title: str
    body: str = ""
    status: str = "current"
    claim_type: str = "inference"
    confidence: float = 0.5

class AuditEvent(ObjectModel):
    table_name: str = "audit_event"
    actor: str
    action: str
    object: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)
```

> Match `ObjectModel`'s conventions (how `table_name` is declared, how `.save()`/`get`/`get_all` work) exactly against `open_notebook/domain/base.py` and an existing model like `SourceInsight` in `open_notebook/domain/notebook.py`. If `table_name` is set via a different mechanism (class attr vs field), follow that.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_governance_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add open_notebook/domain/governance.py tests/test_governance_models.py
git commit -m "feat(governance): Proposal/Belief/AuditEvent domain models"
```

---

### Task 3: Governance service — create / list / accept / request-changes / lineage

**Files:**
- Create: `api/governance_service.py`
- Test: `tests/test_governance_service.py` (integration — follows the existing DB-fixture pattern in `tests/`)

**Interfaces:**
- Consumes: `Proposal`, `Belief`, `AuditEvent`; `Source`; the repository/graph helpers used elsewhere (`repo_relate`/`RELATE`), `AuthContext` (for `actor` = user id).
- Produces (async functions):
  - `create_proposal(actor, *, kind, title, body, claim_type, confidence, source_spans: list[{source_id, locator}]) -> Proposal` — saves proposal (`status='pending'`), `RELATE proposal->derived_from->source` per span (with `locator`), writes `audit_event(action='proposal.created')`.
  - `list_proposals(*, status: str | None) -> list[Proposal]`.
  - `get_proposal(id) -> Proposal`.
  - `accept_proposal(actor, id) -> {"proposal": Proposal, "belief": Belief}` — guards `status=='pending'`; creates `Belief` from the proposal, `RELATE proposal->promotes_to->belief`, copies each `derived_from` edge to the belief, sets `proposal.status='accepted'`, writes `audit_event(action='proposal.accepted')`. **Raises `ValueError` if not pending.**
  - `request_changes(actor, id, note) -> Proposal` — guards pending; `status='changes_requested'`; `audit_event(action='proposal.changes_requested', meta={'note': note})`.
  - `get_belief_lineage(id) -> {"belief": Belief, "sources": [...], "provenance": [...], "derived_work": [], "contradictions": []}` — sources from belief's `derived_from` edges; provenance from `audit_event`s referencing the originating proposal/belief.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_governance_service.py
import pytest
from api import governance_service as gs

# Uses the same async DB fixture other integration tests in tests/ use.
pytestmark = pytest.mark.asyncio

async def test_create_then_accept_makes_belief_and_audit(seeded_source, actor_user):
    prop = await gs.create_proposal(
        actor_user, kind="belief", title="SMB focus Q3", body="...",
        claim_type="inference", confidence=0.6,
        source_spans=[{"source_id": seeded_source.id, "locator": "p.4"}],
    )
    assert prop.status == "pending"

    result = await gs.accept_proposal(actor_user, prop.id)
    assert result["belief"].title == "SMB focus Q3"
    reloaded = await gs.get_proposal(prop.id)
    assert reloaded.status == "accepted"

    lineage = await gs.get_belief_lineage(result["belief"].id)
    assert any(s["id"] == seeded_source.id for s in lineage["sources"])
    assert any(e["action"] == "proposal.accepted" for e in lineage["provenance"])

async def test_accept_twice_raises(seeded_source, actor_user):
    prop = await gs.create_proposal(actor_user, kind="belief", title="x", body="",
                                    claim_type="inference", confidence=0.5,
                                    source_spans=[{"source_id": seeded_source.id, "locator": None}])
    await gs.accept_proposal(actor_user, prop.id)
    with pytest.raises(ValueError):
        await gs.accept_proposal(actor_user, prop.id)  # already accepted
```

> If `tests/` has no `seeded_source`/`actor_user` fixtures, add them in `tests/conftest.py` following the existing source-creation test helpers. Match the async fixture style already in the suite.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: FAIL — `api.governance_service` missing.

- [ ] **Step 3: Implement the service**

```python
# api/governance_service.py
from typing import Any, Optional
from open_notebook.domain.governance import Proposal, Belief, AuditEvent
# import the graph RELATE helper + query fn used elsewhere (e.g. repo_query / repo_relate)
from open_notebook.database.repository import repo_query, repo_relate  # adjust to real names

async def _audit(actor: str, action: str, obj: Optional[str], meta: dict | None = None) -> None:
    await AuditEvent(actor=actor, action=action, object=obj, meta=meta or {}).save()

async def create_proposal(actor: str, *, kind: str, title: str, body: str,
                          claim_type: str, confidence: float,
                          source_spans: list[dict[str, Any]]) -> Proposal:
    prop = Proposal(author=actor, kind=kind, title=title, body=body,
                    claim_type=claim_type, confidence=confidence, status="pending")
    await prop.save()
    for span in source_spans:
        await repo_relate(prop.id, "derived_from", span["source_id"], {"locator": span.get("locator")})
    await _audit(actor, "proposal.created", prop.id, {"kind": kind})
    return prop

async def list_proposals(*, status: Optional[str] = None) -> list[Proposal]:
    q = "SELECT * FROM proposal"
    if status:
        q += " WHERE status = $status"
    rows = await repo_query(q, {"status": status} if status else {})
    return [Proposal(**r) for r in rows]

async def get_proposal(pid: str) -> Proposal:
    rows = await repo_query("SELECT * FROM $id", {"id": pid})
    return Proposal(**rows[0])

async def accept_proposal(actor: str, pid: str) -> dict[str, Any]:
    prop = await get_proposal(pid)
    if prop.status != "pending":
        raise ValueError(f"proposal {pid} is {prop.status}, not pending")
    belief = Belief(title=prop.title, body=prop.body, claim_type=prop.claim_type,
                    confidence=prop.confidence, status="current")
    await belief.save()
    await repo_relate(prop.id, "promotes_to", belief.id, {})
    # copy provenance edges proposal->derived_from->source onto belief
    edges = await repo_query(
        "SELECT out AS source, locator FROM derived_from WHERE in = $id", {"id": prop.id})
    for e in edges:
        await repo_relate(belief.id, "derived_from", e["source"], {"locator": e.get("locator")})
    prop.status = "accepted"
    await prop.save()
    await _audit(actor, "proposal.accepted", prop.id, {"belief": belief.id})
    return {"proposal": prop, "belief": belief}

async def request_changes(actor: str, pid: str, note: str) -> Proposal:
    prop = await get_proposal(pid)
    if prop.status != "pending":
        raise ValueError(f"proposal {pid} is {prop.status}, not pending")
    prop.status = "changes_requested"
    await prop.save()
    await _audit(actor, "proposal.changes_requested", prop.id, {"note": note})
    return prop

async def get_belief_lineage(bid: str) -> dict[str, Any]:
    belief_rows = await repo_query("SELECT * FROM $id", {"id": bid})
    sources = await repo_query(
        "SELECT out.id AS id, out.title AS title, locator FROM derived_from WHERE in = $id", {"id": bid})
    provenance = await repo_query(
        "SELECT action, actor, created, meta FROM audit_event "
        "WHERE object = $id OR meta.belief = $id ORDER BY created", {"id": bid})
    return {"belief": Belief(**belief_rows[0]), "sources": sources,
            "provenance": provenance, "derived_work": [], "contradictions": []}
```

> The `repo_query`/`repo_relate` names/signatures are placeholders — replace with the **actual** query + RELATE helpers used in `open_notebook/database/repository.py` and the graph-edge helper used by `Source.add_to_notebook` (which does `RELATE source->reference->notebook`). Copy that exact call style.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_governance_service.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add api/governance_service.py tests/test_governance_service.py tests/conftest.py
git commit -m "feat(governance): promotion service (create/accept/request-changes/lineage)"
```

---

### Task 4: Governance router + registration

**Files:**
- Create: `api/routers/governance.py`
- Modify: `api/routers/__init__.py` (export `governance`)
- Modify: `api/main.py` (register router)
- Test: `tests/test_governance_router.py`

**Interfaces:**
- Produces endpoints (all read `actor` from `AuthContext`/`request.state.user_id`):
  - `POST /api/proposals` · `GET /api/proposals?status=` · `GET /api/proposals/{id}`
  - `POST /api/proposals/{id}/accept` · `POST /api/proposals/{id}/request-changes`
  - `GET /api/beliefs` · `GET /api/beliefs/{id}` (lineage)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_governance_router.py
import pytest
from httpx import AsyncClient
# reuse the wired-app fixture other router tests use (e.g. `async_client`)
pytestmark = pytest.mark.asyncio

async def test_propose_then_review_flow(async_client: AsyncClient, seeded_source, auth_headers):
    r = await async_client.post("/api/proposals", headers=auth_headers, json={
        "kind": "belief", "title": "SMB focus", "body": "...",
        "claim_type": "inference", "confidence": 0.6,
        "source_spans": [{"source_id": seeded_source.id, "locator": "p.4"}],
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    lst = await async_client.get("/api/proposals?status=pending", headers=auth_headers)
    assert any(p["id"] == pid for p in lst.json())

    acc = await async_client.post(f"/api/proposals/{pid}/accept", headers=auth_headers)
    assert acc.status_code == 200
    belief_id = acc.json()["belief"]["id"]

    lineage = await async_client.get(f"/api/beliefs/{belief_id}", headers=auth_headers)
    assert lineage.status_code == 200
    assert len(lineage.json()["sources"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_governance_router.py -v`
Expected: FAIL — endpoints 404.

- [ ] **Step 3: Implement the router + register**

```python
# api/routers/governance.py
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from api import governance_service as gs

router = APIRouter(tags=["governance"])

class SourceSpan(BaseModel):
    source_id: str
    locator: str | None = None

class CreateProposal(BaseModel):
    kind: str = "belief"
    title: str
    body: str = ""
    claim_type: str = "inference"
    confidence: float = 0.5
    source_spans: list[SourceSpan] = []

class ChangesBody(BaseModel):
    note: str = ""

def _actor(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "auth required")
    return uid

@router.post("/proposals", status_code=201)
async def create_proposal(body: CreateProposal, request: Request):
    p = await gs.create_proposal(_actor(request), kind=body.kind, title=body.title,
        body=body.body, claim_type=body.claim_type, confidence=body.confidence,
        source_spans=[s.model_dump() for s in body.source_spans])
    return p.model_dump()

@router.get("/proposals")
async def list_proposals(status: str | None = None):
    return [p.model_dump() for p in await gs.list_proposals(status=status)]

@router.get("/proposals/{pid}")
async def get_proposal(pid: str):
    return (await gs.get_proposal(pid)).model_dump()

@router.post("/proposals/{pid}/accept")
async def accept(pid: str, request: Request):
    try:
        res = await gs.accept_proposal(_actor(request), pid)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"proposal": res["proposal"].model_dump(), "belief": res["belief"].model_dump()}

@router.post("/proposals/{pid}/request-changes")
async def request_changes(pid: str, body: ChangesBody, request: Request):
    try:
        p = await gs.request_changes(_actor(request), pid, body.note)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return p.model_dump()

@router.get("/beliefs")
async def list_beliefs():
    from open_notebook.database.repository import repo_query
    rows = await repo_query("SELECT * FROM belief WHERE status = 'current' ORDER BY updated DESC", {})
    return rows

@router.get("/beliefs/{bid}")
async def belief_lineage(bid: str):
    res = await gs.get_belief_lineage(bid)
    return {**res, "belief": res["belief"].model_dump()}
```

Register in `api/routers/__init__.py` (add `governance` to the imports/exports) and in `api/main.py` add, alongside the other `include_router` calls (~`:389-411`):

```python
from api.routers import governance
app.include_router(governance.router, prefix="/api")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_governance_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/governance.py api/routers/__init__.py api/main.py tests/test_governance_router.py
git commit -m "feat(governance): /api/proposals + /api/beliefs router"
```

---

### Task 5: Frontend governance API client + hooks

**Files:**
- Create: `frontend/src/lib/api/governance.ts`
- Create: `frontend/src/lib/hooks/use-governance.ts`
- Test: `frontend/src/lib/hooks/use-governance.test.tsx`

**Interfaces:**
- Produces:
  - `governanceApi`: `createProposal(payload)`, `listProposals(status?)`, `acceptProposal(id)`, `requestChanges(id, note)`, `listBeliefs()`, `getBelief(id)` — all via `apiClient`.
  - Hooks: `useProposals(status?)`, `useCreateProposal()`, `useAcceptProposal()`, `useRequestChanges()`, `useBeliefs()`, `useBelief(id)`. Mutations invalidate `['proposals']` + `['beliefs']` and toast.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/lib/hooks/use-governance.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/lib/api/governance', () => ({
  governanceApi: { listProposals: vi.fn().mockResolvedValue([{ id: 'proposal:1', title: 'SMB', status: 'pending' }]) },
}));

import { useProposals } from './use-governance';

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
};

describe('useProposals', () => {
  it('fetches pending proposals', async () => {
    const { result } = renderHook(() => useProposals('pending'), { wrapper });
    await waitFor(() => expect(result.current.data?.[0].title).toBe('SMB'));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- use-governance`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement client + hooks**

```ts
// frontend/src/lib/api/governance.ts
import { apiClient } from '@/lib/api/client';

export interface Proposal { id: string; title: string; body: string; status: string; kind: string; claim_type: string; confidence: number; }
export interface Belief { id: string; title: string; body: string; status: string; }
export interface CreateProposalPayload {
  kind?: string; title: string; body?: string; claim_type?: string; confidence?: number;
  source_spans: { source_id: string; locator?: string }[];
}

export const governanceApi = {
  createProposal: (p: CreateProposalPayload) => apiClient.post<Proposal>('/proposals', p).then((r) => r.data),
  listProposals: (status?: string) => apiClient.get<Proposal[]>('/proposals', { params: { status } }).then((r) => r.data),
  acceptProposal: (id: string) => apiClient.post(`/proposals/${id}/accept`).then((r) => r.data),
  requestChanges: (id: string, note: string) => apiClient.post(`/proposals/${id}/request-changes`, { note }).then((r) => r.data),
  listBeliefs: () => apiClient.get<Belief[]>('/beliefs').then((r) => r.data),
  getBelief: (id: string) => apiClient.get(`/beliefs/${id}`).then((r) => r.data),
};
```

```ts
// frontend/src/lib/hooks/use-governance.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { governanceApi, type CreateProposalPayload } from '@/lib/api/governance';
import { useToast } from '@/lib/hooks/use-toast';

const KEYS = { proposals: ['proposals'] as const, beliefs: ['beliefs'] as const };

export const useProposals = (status?: string) =>
  useQuery({ queryKey: [...KEYS.proposals, status ?? 'all'], queryFn: () => governanceApi.listProposals(status) });

export const useBeliefs = () => useQuery({ queryKey: KEYS.beliefs, queryFn: () => governanceApi.listBeliefs() });
export const useBelief = (id?: string) =>
  useQuery({ queryKey: [...KEYS.beliefs, id], queryFn: () => governanceApi.getBelief(id as string), enabled: !!id });

export function useCreateProposal() {
  const qc = useQueryClient(); const { toast } = useToast();
  return useMutation({
    mutationFn: (p: CreateProposalPayload) => governanceApi.createProposal(p),
    onSuccess: () => { qc.invalidateQueries({ queryKey: KEYS.proposals }); toast({ title: 'Proposed to company' }); },
  });
}
export function useAcceptProposal() {
  const qc = useQueryClient(); const { toast } = useToast();
  return useMutation({
    mutationFn: (id: string) => governanceApi.acceptProposal(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: KEYS.proposals }); qc.invalidateQueries({ queryKey: KEYS.beliefs }); toast({ title: 'Accepted into Company Brain' }); },
  });
}
export function useRequestChanges() {
  const qc = useQueryClient(); const { toast } = useToast();
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) => governanceApi.requestChanges(id, note),
    onSuccess: () => { qc.invalidateQueries({ queryKey: KEYS.proposals }); toast({ title: 'Sent back for changes' }); },
  });
}
```

> Confirm `apiClient` import path + response shape (`.data`) against `frontend/src/lib/api/client.ts` and an existing API module (e.g. `lib/api/sources.ts`). Toast text should be routed through `t()` in the components that call these (hooks can stay literal or accept a message).

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- use-governance`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api/governance.ts frontend/src/lib/hooks/use-governance.ts frontend/src/lib/hooks/use-governance.test.tsx
git commit -m "feat(control-plane): governance api client + hooks"
```

---

### Task 6: ReviewInbox + CompanyBrain sidebar sections + Propose action

Wire scope: **Personal** shows Sources + Loop; **Company** shows ReviewInbox (pending proposals) + CompanyBrain (beliefs). Add a `Propose` action that, from a source insight, creates a proposal.

**Files:**
- Create: `frontend/src/components/control-plane/ReviewInbox.tsx`
- Create: `frontend/src/components/control-plane/CompanyBrainSection.tsx`
- Create: `frontend/src/components/control-plane/ProposeButton.tsx`
- Modify: `frontend/src/components/control-plane/ContextSidebar.tsx` (branch sections by `useScopeStore`)
- Test: `frontend/src/components/control-plane/ReviewInbox.test.tsx`

**Interfaces:**
- Consumes: `useProposals('pending')`, `useAcceptProposal`, `useRequestChanges`, `useBeliefs`, `useCreateProposal`, `useScopeStore`, `useArtifact` (belief click → lineage).
- Produces: `<ReviewInbox />`, `<CompanyBrainSection />`, `<ProposeButton source_spans title body />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/ReviewInbox.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const accept = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useProposals: () => ({ data: [{ id: 'proposal:1', title: 'SMB focus', status: 'pending' }], isLoading: false }),
  useAcceptProposal: () => ({ mutate: accept, isPending: false }),
  useRequestChanges: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ReviewInbox } from './ReviewInbox';

describe('ReviewInbox', () => {
  it('lists a pending proposal and accepts it', () => {
    render(<ReviewInbox />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /controlPlane\.review\.accept|accept|duyệt/i }));
    expect(accept).toHaveBeenCalledWith('proposal:1');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- ReviewInbox`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

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
          <div className="text-xs font-bold text-foreground">{p.title}</div>
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

```tsx
// frontend/src/components/control-plane/CompanyBrainSection.tsx
'use client';
import { Sparkles } from 'lucide-react';
import { useBeliefs } from '@/lib/hooks/use-governance';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';

export function CompanyBrainSection() {
  const { t } = useTranslation();
  const { data } = useBeliefs();
  const { openArtifact } = useArtifact();
  const beliefs = (data ?? []) as { id: string; title: string }[];
  if (beliefs.length === 0)
    return <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{t('controlPlane.sidebar.brainEmpty')}</div>;
  return (
    <div className="flex flex-col gap-1.5">
      {beliefs.map((b) => (
        <button key={b.id} type="button" onClick={() => openArtifact('belief', b.id)}
          className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5 text-left hover:border-primary">
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="flex-1 truncate text-xs font-semibold text-foreground">{b.title}</span>
          <span className="text-[10px] text-muted-foreground">{t('controlPlane.brain.view')}</span>
        </button>
      ))}
    </div>
  );
}
```

```tsx
// frontend/src/components/control-plane/ProposeButton.tsx
'use client';
import { ArrowUp } from 'lucide-react';
import { useCreateProposal } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

export function ProposeButton({ title, body, sourceSpans }: {
  title: string; body: string; sourceSpans: { source_id: string; locator?: string }[];
}) {
  const { t } = useTranslation();
  const create = useCreateProposal();
  return (
    <button type="button" disabled={create.isPending}
      onClick={() => create.mutate({ kind: 'belief', title, body, source_spans: sourceSpans })}
      className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground">
      <ArrowUp className="h-3.5 w-3.5" /> {t('controlPlane.proposeToCompany')}
    </button>
  );
}
```

Branch `ContextSidebar.tsx` by scope:

```tsx
const scope = useScopeStore((s) => s.scope);
// ...
{scope === 'personal' ? (
  <>
    <Section title={t('controlPlane.sidebar.sources')}><SourcesSection /></Section>
    <Section title={t('controlPlane.sidebar.loop')}><LoopWidget currentIndex={0} /></Section>
  </>
) : (
  <>
    <Section title={t('controlPlane.sidebar.review')}><ReviewInbox /></Section>
    <Section title={t('controlPlane.sidebar.loop')}><LoopWidget currentIndex={3} /></Section>
    <Section title={t('controlPlane.sidebar.brain')}><CompanyBrainSection /></Section>
  </>
)}
```

Render `<ProposeButton>` inside the chat insight card (`ControlPlaneChat.tsx`) when an insight is shown, passing the cited source id(s) as `sourceSpans`. Add i18n keys `controlPlane.review.accept`, `controlPlane.review.changes`, `controlPlane.brain.view`, `controlPlane.proposeToCompany` to all 14 locales.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- ReviewInbox`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/ReviewInbox.tsx frontend/src/components/control-plane/CompanyBrainSection.tsx frontend/src/components/control-plane/ProposeButton.tsx frontend/src/components/control-plane/ContextSidebar.tsx frontend/src/components/control-plane/ReviewInbox.test.tsx frontend/src/lib/locales
git commit -m "feat(control-plane): review inbox, company brain section, propose action, scope branching"
```

---

### Task 7: Belief `LineagePanel` in the artifact reader

Complete the P8.1 `BeliefArtifactStub`: render the belief lineage (sources · provenance · contradiction placeholder) in the artifact panel.

**Files:**
- Create: `frontend/src/components/control-plane/LineagePanel.tsx`
- Modify: `frontend/src/components/control-plane/ArtifactReader.tsx` (replace `BeliefArtifactStub` with `<LineagePanel id={artifact.id} />`)
- Test: `frontend/src/components/control-plane/LineagePanel.test.tsx`

**Interfaces:**
- Consumes: `useBelief(id)` (Task 5).
- Produces: `<LineagePanel id />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/LineagePanel.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-governance', () => ({
  useBelief: () => ({ data: {
    belief: { id: 'belief:1', title: 'SMB focus' },
    sources: [{ id: 'source:9', title: 'Q3 Research', locator: 'p.4' }],
    provenance: [{ action: 'proposal.accepted', actor: 'user:1' }],
    derived_work: [], contradictions: [],
  }, isLoading: false }),
}));

import { LineagePanel } from './LineagePanel';

describe('LineagePanel', () => {
  it('shows belief title, its source, and provenance', () => {
    render(<LineagePanel id="belief:1" />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/proposal\.accepted|accepted/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- LineagePanel`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/control-plane/LineagePanel.tsx
'use client';
import { FileText } from 'lucide-react';
import { useBelief } from '@/lib/hooks/use-governance';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';

export function LineagePanel({ id }: { id: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useBelief(id) as { data: any; isLoading: boolean };
  const { openArtifact } = useArtifact();
  if (isLoading || !data) return <div className="p-4 text-sm text-muted-foreground">{t('common.loading')}</div>;
  const { belief, sources, provenance } = data;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
      <div className="text-[11px] font-bold uppercase tracking-wide text-primary">{t('controlPlane.lineage.belief')}</div>
      <h2 className="mb-3 font-serif text-lg text-foreground">{belief.title}</h2>

      <div className="mb-4">
        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.lineage.sources')}</div>
        {sources.map((s: any) => (
          <button key={s.id} type="button" onClick={() => openArtifact('source', s.id, s.locator)}
            className="flex w-full items-center gap-2 border-b border-border py-2 text-left text-sm text-foreground hover:text-primary">
            <FileText className="h-4 w-4 text-muted-foreground" /> <span className="flex-1">{s.title}</span>
            {s.locator ? <span className="text-xs text-muted-foreground">{s.locator}</span> : null}
          </button>
        ))}
      </div>

      <div className="mb-4">
        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.lineage.provenance')}</div>
        {provenance.map((p: any, i: number) => (
          <div key={i} className="border-b border-border py-2 text-sm text-foreground">{p.action} · {p.actor}</div>
        ))}
      </div>

      <div className="rounded-lg bg-muted/60 p-3">
        <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.lineage.contradiction')}</div>
        <div className="text-sm text-muted-foreground">{t('controlPlane.lineage.contradictionNone')}</div>
      </div>
    </div>
  );
}
```

In `ArtifactReader.tsx`, replace `<BeliefArtifactStub />` with `<LineagePanel id={artifact.id} />` (and delete the stub). Add i18n keys `controlPlane.lineage.*` to all 14 locales.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- LineagePanel`
Expected: PASS.

- [ ] **Step 5: Full gate + end-to-end smoke**

Run: `npm run test -- locales` (parity + unused-key green), `npm run lint && npm run build`; backend `uv run pytest tests/ && ruff check .`.
Manual (stack up): Personal → add source → ask → citation opens artifact → from an insight click **Propose to company** (toast). Switch scope → **Company** → the proposal shows in **To review** → **Accept** → a belief appears in **Company Brain** → click it → the artifact panel shows its **lineage** (source + `proposal.accepted` provenance) → click the source in lineage → source artifact opens. Full bridge works.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/control-plane/LineagePanel.tsx frontend/src/components/control-plane/ArtifactReader.tsx frontend/src/components/control-plane/LineagePanel.test.tsx frontend/src/lib/locales
git commit -m "feat(control-plane): belief lineage panel in artifact reader"
```

---

## Self-Review

**Spec coverage (§6, §7 bridge; UX4/UX6/UX7):**
- `proposal`/`belief`/`audit_event` + edges `derived_from`/`promotes_to`, workspace-ready nullable → Task 1–2. ✓
- Propose → Review → Accept → Belief (the bridge, step 3–4/6) → Tasks 3,4,6. ✓
- Promotion is the only private→company write; belief only via accept → Task 3 (no direct belief endpoint). ✓
- Audit on every transition → Task 3 `_audit` calls. ✓
- ReviewInbox (Company scope) + scope branching → Task 6. ✓
- Belief lineage in artifact panel (UX6) → Task 7. ✓
- Accept idempotency guard (`ValueError` if not pending → 409) → Tasks 3,4. ✓

**Out of scope (later plans, correctly deferred):** decision/rule (P8.3), handoff/agent brief (P8.4), trace + learning propose-only loop (P8.5), contradiction detection D4 (placeholder only), PII/secret DLP, real multitenancy roles.

**Placeholder scan:** No TBD/TODO. Contradiction block is an explicit "none" placeholder matching the D4-deferral in the spec. Loop widget `currentIndex` is hardcoded (0 personal / 3 company) — it reflects scope, not live per-item loop state, which is a later refinement (noted).

**Type consistency:** `Proposal`/`Belief` fields align across migration (21) ↔ domain (Task 2) ↔ service (Task 3) ↔ router (Task 4) ↔ TS interfaces (Task 5). `openArtifact('belief', id)` (Task 6) ↔ `useArtifact` type `'belief'` (P8.1 Task 3) ↔ `LineagePanel` (Task 7). Status strings `pending/accepted/changes_requested` consistent everywhere. `source_spans: {source_id, locator}` shape consistent client↔server.

**Implementer verification points (flagged inline):** real `repo_query`/`repo_relate`/RELATE helper names in `open_notebook/database/repository.py`; `ObjectModel` `table_name`/save conventions; `tests/` DB fixtures (`seeded_source`, `async_client`, `auth_headers`); `apiClient` response shape; `request.state.user_id` availability on these routes (added by `JWTAuthMiddleware`).
