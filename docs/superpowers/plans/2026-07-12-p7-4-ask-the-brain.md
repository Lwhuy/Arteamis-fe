# P7.4 — Graph-Aware Ask the Brain — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a graph-aware RAG chat (`POST /brain/ask`) that reuses the existing `ask` pipeline, injects subgraph relationship annotations into the answer context, streams `cited_node_ids`, and drives an `AskTheBrainPanel` that highlights cited nodes on the Intelligence canvas.

**Architecture:** `ask_brain` runs the existing vector retrieval, expands the retrieved sources to their surrounding subgraph via `get_source_relationships(workspace)`, folds the relationship edges into an augmented question string, then drives the already-compiled `ask_graph` (`open_notebook/graphs/ask.py`) — mirroring `stream_ask_response`'s SSE framing but tagging every event with `cited_node_ids`. The frontend `useBrainAsk` hook consumes those ids and calls `useBrainStore.setHighlighted(...)`; `AskTheBrainPanel` reuses the existing search answer components.

**Tech Stack:** Python 3 / FastAPI / LangGraph (`ask_graph`) / SurrealDB; Next.js (App Router) / React / TypeScript / Zustand / TanStack Query / vitest.

## Global Constraints

- **Async-first:** every DB query, graph invocation and AI call is `await`-ed. `ask_brain` is an `async def ... -> AsyncIterator`.
- **Reuse, don't rebuild:** reuse the existing `ask_graph` and `vector_search`; all LLM calls stay inside the graph via `provision_langchain_model()`. No new chat/agent framework.
- **Typed exceptions:** raise from `open_notebook.exceptions`; convert LLM/stream failures with `open_notebook.utils.error_classifier.classify_error` (never bare `HTTPException` for domain errors). Stream errors are emitted as `{"type":"error"}` events, never crash the request.
- **Workspace-scoped:** the route depends on `CtxDep` (`from api.deps import CtxDep`); every graph read goes through `get_source_relationships(ctx.workspace_id)`. Workspace A can never read workspace B's graph.
- **TDD mandatory:** strict RED → GREEN → REFACTOR, one behavior at a time. Mock `provision_langchain_model` (indirectly, via mocking `ask_graph.astream`), `vector_search`, and `get_source_relationships` on the backend; mock the stream client (`brainApi.askBrain`) on the frontend.
- **Backend gates:** `uv run pytest tests/` · `ruff check . --fix` · `uv run python -m mypy .` all green.
- **Frontend gates (inside `frontend/`):** `npm run test` · `npm run lint` · `npm run build` all green. i18n keys added to all 7 locales.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `api/brain_models.py` | Modify | Add `BrainAskEvent` Pydantic model (ask stream event + `cited_node_ids`) alongside the P7.1 brain models. |
| `api/brain_service.py` | Modify (P7.1/7.2 file) | Add `build_subgraph_context()` helper + `async def ask_brain(...)` streaming generator. |
| `api/routers/brain.py` | Modify (P7.1/7.2 file) | Add `POST /brain/ask` SSE route (`CtxDep`, any member). |
| `tests/test_brain_ask_service.py` | Create | Unit tests: subgraph context assembly + `cited_node_ids` population (mock `vector_search`, `get_source_relationships`, `ask_graph`). |
| `tests/test_brain_ask_api.py` | Create | Route tests: SSE framing, model validation, workspace scoping / leakage. |
| `frontend/src/lib/types/brain.ts` | Modify (P7.3 file) | Add `BrainAskStreamEvent` type (`AskStreamEvent` + `cited_node_ids?`). |
| `frontend/src/lib/api/brain.ts` | Modify (P7.3 file) | Add `brainApi.askBrain(params, onEvent)` streaming client. |
| `frontend/src/lib/hooks/use-brain-ask.ts` | Create | `useBrainAsk()` — extends the `useAsk` pattern, exposes `citedNodeIds`, wires `setHighlighted`. |
| `frontend/src/lib/api/brain.test.ts` | Create | Tests for `askBrain` SSE parse + error throw. |
| `frontend/src/lib/hooks/use-brain-ask.test.ts` | Create | Tests: parses events, sets `citedNodeIds`, calls `setHighlighted`, error state. |
| `frontend/src/components/intelligence/AskTheBrainPanel.tsx` | Create | Panel reusing `AnswerBody`/`SourcesPanel`/`StrategyDisclosure`/`AnswerFeedback`, wired to `useBrainAsk`, inline error state. |
| `frontend/src/components/intelligence/AskTheBrainPanel.test.tsx` | Create | Renders streamed answer + error state (mock `useBrainAsk`). |
| `frontend/src/app/(dashboard)/intelligence/page.tsx` | Modify (P7.3 file) | Mount `<AskTheBrainPanel />` in the right-panel slot. |
| `frontend/src/lib/locales/*/` (7 locales) | Modify | Add `intelligence.ask.*` copy keys. |

---

### Task 1: `BrainAskEvent` stream-event model + subgraph context helper

**Files:**
- Modify: `api/brain_models.py`
- Modify: `api/brain_service.py`
- Test: `tests/test_brain_ask_service.py`

**Interfaces:**
- Consumes (P7.1/7.2): `open_notebook.domain.brain.get_source_relationships(workspace)` → `list[dict]`, each `{"source": str, "target": str, "type": str, "rationale": str}` where `type ∈ {supersedes, disagrees, complements, agrees}`.
- Produces:
  - `api.brain_models.BrainAskEvent(type:str, reasoning:Optional[str]=None, searches:Optional[list[dict]]=None, content:Optional[str]=None, final_answer:Optional[str]=None, message:Optional[str]=None, cited_node_ids:list[str]=[])`
  - `api.brain_service.build_subgraph_context(retrieved_ids:list[str], relationships:list[dict]) -> tuple[str, list[str]]` — returns `(annotations_text, cited_node_ids)`.

- [ ] **Step 1: Write the failing test for `build_subgraph_context`**

Create `tests/test_brain_ask_service.py`:

```python
from api.brain_service import build_subgraph_context


def test_build_subgraph_context_annotates_edges_touching_retrieved_sources():
    retrieved = ["source:a", "source:b"]
    relationships = [
        {"source": "source:a", "target": "source:z", "type": "supersedes", "rationale": "newer"},
        {"source": "source:q", "target": "source:r", "type": "agrees", "rationale": "unrelated"},
    ]

    annotations, cited = build_subgraph_context(retrieved, relationships)

    # Only the edge touching a retrieved source is annotated
    assert annotations == "source:a supersedes source:z"
    # cited = retrieved sources first, then newly-connected subgraph nodes, de-duped, order-preserving
    assert cited == ["source:a", "source:b", "source:z"]


def test_build_subgraph_context_empty_when_no_edges_match():
    annotations, cited = build_subgraph_context(["source:a"], [])
    assert annotations == ""
    assert cited == ["source:a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_ask_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_subgraph_context'`.

- [ ] **Step 3: Implement `build_subgraph_context`**

Add to `api/brain_service.py` (module level):

```python
def build_subgraph_context(
    retrieved_ids: list[str], relationships: list[dict]
) -> tuple[str, list[str]]:
    """Expand retrieved sources to their surrounding subgraph.

    Returns a newline-joined set of relationship annotations
    ("A supersedes B") for every relates-edge that touches a retrieved
    source, plus the ordered, de-duplicated list of cited node ids
    (retrieved sources first, then newly-connected nodes).
    """
    retrieved = set(retrieved_ids)
    lines: list[str] = []
    cited: list[str] = list(retrieved_ids)
    for rel in relationships:
        src = rel.get("source")
        tgt = rel.get("target")
        rtype = rel.get("type")
        if src in retrieved or tgt in retrieved:
            lines.append(f"{src} {rtype} {tgt}")
            for node in (src, tgt):
                if node and node not in cited:
                    cited.append(node)
    return "\n".join(lines), cited
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_ask_service.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Add the `BrainAskEvent` model + its test**

Append to `tests/test_brain_ask_service.py`:

```python
def test_brain_ask_event_defaults_cited_node_ids_to_empty_list():
    from api.brain_models import BrainAskEvent

    event = BrainAskEvent(type="answer", content="hi")
    dumped = event.model_dump()
    assert dumped["type"] == "answer"
    assert dumped["content"] == "hi"
    assert dumped["cited_node_ids"] == []
```

Add to `api/brain_models.py` (the file P7.1 created for `BrainNode`/`BrainEdge`/`BrainGraphResponse`; ensure `Optional` from `typing` and `BaseModel`/`Field` from `pydantic` are imported at the top):

```python
class BrainAskEvent(BaseModel):
    """A single SSE event for the graph-aware /brain/ask stream.

    Mirrors the existing ask stream shape (strategy/answer/final_answer/
    complete/error) and adds cited_node_ids for canvas highlighting.
    """

    type: str = Field(..., description="strategy | answer | final_answer | complete | error")
    reasoning: Optional[str] = None
    searches: Optional[list[dict]] = None
    content: Optional[str] = None
    final_answer: Optional[str] = None
    message: Optional[str] = None
    cited_node_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_ask_service.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Lint, typecheck, commit**

```bash
ruff check . --fix && uv run python -m mypy api/brain_service.py api/brain_models.py
git add api/brain_models.py api/brain_service.py tests/test_brain_ask_service.py
git commit -m "feat(brain): BrainAskEvent model + subgraph context helper"
```

---

### Task 2: `ask_brain` streaming service

**Files:**
- Modify: `api/brain_service.py`
- Test: `tests/test_brain_ask_service.py`

**Interfaces:**
- Consumes: `build_subgraph_context` (Task 1); `open_notebook.domain.notebook.vector_search(keyword, results, source, note, minimum_score)`; `get_source_relationships(workspace)` (P7.2); `open_notebook.graphs.ask.graph` (the compiled `ask_graph`); `CtxDep` context object exposing `ctx.workspace_id`.
- Produces: `api.brain_service.ask_brain(ctx, question:str, strategy_model:str, answer_model:str, final_answer_model:str) -> AsyncIterator[BrainAskEvent]`.

- [ ] **Step 1: Write the failing test (cited_node_ids tagged on every event)**

Append to `tests/test_brain_ask_service.py`:

```python
import types
from unittest.mock import AsyncMock, patch

import pytest


class _Strategy:
    reasoning = "plan"
    searches: list = []


async def _fake_astream(*args, **kwargs):
    # Mimic ask_graph.astream stream_mode="updates" chunk shape
    yield {"agent": {"strategy": _Strategy()}}
    yield {"provide_answer": {"answers": ["partial answer"]}}
    yield {"write_final_answer": {"final_answer": "the final answer"}}


@pytest.mark.asyncio
async def test_ask_brain_injects_relationships_and_tags_cited_node_ids():
    ctx = types.SimpleNamespace(workspace_id="workspace:alpha")
    fake_graph = types.SimpleNamespace(astream=_fake_astream)

    with (
        patch("api.brain_service.vector_search", new_callable=AsyncMock) as mock_vs,
        patch("api.brain_service.get_source_relationships", new_callable=AsyncMock) as mock_rel,
        patch("api.brain_service.ask_graph", fake_graph),
    ):
        mock_vs.return_value = [{"id": "source:a"}, {"id": "source:b"}]
        mock_rel.return_value = [
            {"source": "source:a", "target": "source:z", "type": "supersedes", "rationale": "r"}
        ]

        events = [e async for e in _drive(ctx)]

    # Graph is read scoped to the caller's workspace
    mock_rel.assert_awaited_once_with("workspace:alpha")
    types_seen = [e.type for e in events]
    assert types_seen == ["strategy", "answer", "final_answer", "complete"]
    # Every event carries the same cited node ids (retrieved + subgraph)
    for e in events:
        assert e.cited_node_ids == ["source:a", "source:b", "source:z"]
    assert events[-1].final_answer == "the final answer"


async def _drive(ctx):
    from api.brain_service import ask_brain

    async for e in ask_brain(ctx, "q?", "model:s", "model:a", "model:f"):
        yield e
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_ask_service.py::test_ask_brain_injects_relationships_and_tags_cited_node_ids -v`
Expected: FAIL with `ImportError: cannot import name 'ask_brain'`.

- [ ] **Step 3: Implement `ask_brain`**

Add imports at the top of `api/brain_service.py` if not present:

```python
from typing import AsyncIterator

from loguru import logger

from api.brain_models import BrainAskEvent
from open_notebook.domain.brain import get_source_relationships
from open_notebook.domain.notebook import vector_search
from open_notebook.graphs.ask import graph as ask_graph
from open_notebook.utils.error_classifier import classify_error
```

Add the generator:

```python
async def ask_brain(
    ctx,
    question: str,
    strategy_model: str,
    answer_model: str,
    final_answer_model: str,
) -> AsyncIterator[BrainAskEvent]:
    """Graph-aware RAG: reuse the ask pipeline, but expand the retrieved
    sources to their surrounding subgraph and inject relationship
    annotations into the question context. Every emitted event carries
    cited_node_ids so the canvas can highlight cited nodes."""
    try:
        results = await vector_search(question, 10, True, False)
        retrieved_ids = [r["id"] for r in (results or [])]
        relationships = await get_source_relationships(ctx.workspace_id)
        annotations, cited_node_ids = build_subgraph_context(retrieved_ids, relationships)

        augmented_question = question
        if annotations:
            augmented_question = (
                f"{question}\n\nKnown relationships between sources "
                f"(use these to weight and reconcile evidence):\n{annotations}"
            )

        final_answer = None
        async for chunk in ask_graph.astream(
            input=dict(question=augmented_question),  # type: ignore[arg-type]
            config=dict(
                configurable=dict(
                    strategy_model=strategy_model,
                    answer_model=answer_model,
                    final_answer_model=final_answer_model,
                )
            ),
            stream_mode="updates",
        ):
            if "agent" in chunk:
                strategy = chunk["agent"]["strategy"]
                yield BrainAskEvent(
                    type="strategy",
                    reasoning=strategy.reasoning,
                    searches=[
                        {"term": s.term, "instructions": s.instructions}
                        for s in strategy.searches
                    ],
                    cited_node_ids=cited_node_ids,
                )
            elif "provide_answer" in chunk:
                for answer in chunk["provide_answer"]["answers"]:
                    yield BrainAskEvent(
                        type="answer", content=answer, cited_node_ids=cited_node_ids
                    )
            elif "write_final_answer" in chunk:
                final_answer = chunk["write_final_answer"]["final_answer"]
                yield BrainAskEvent(
                    type="final_answer",
                    content=final_answer,
                    cited_node_ids=cited_node_ids,
                )

        yield BrainAskEvent(
            type="complete", final_answer=final_answer, cited_node_ids=cited_node_ids
        )
    except Exception as e:
        _, user_message = classify_error(e)
        logger.error(f"Error in ask_brain streaming: {str(e)}")
        yield BrainAskEvent(type="error", message=user_message, cited_node_ids=[])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_ask_service.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Add the error-path test**

Append to `tests/test_brain_ask_service.py`:

```python
@pytest.mark.asyncio
async def test_ask_brain_emits_error_event_without_raising():
    ctx = types.SimpleNamespace(workspace_id="workspace:alpha")
    with patch("api.brain_service.vector_search", new_callable=AsyncMock) as mock_vs:
        mock_vs.side_effect = RuntimeError("boom")
        events = [e async for e in _drive(ctx)]

    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].message  # a user-facing message, not empty
    assert events[0].cited_node_ids == []
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_ask_service.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Lint, typecheck, commit**

```bash
ruff check . --fix && uv run python -m mypy api/brain_service.py
git add api/brain_service.py tests/test_brain_ask_service.py
git commit -m "feat(brain): ask_brain subgraph-augmented streaming service"
```

---

### Task 3: `POST /brain/ask` SSE route + workspace scoping

**Files:**
- Modify: `api/routers/brain.py`
- Test: `tests/test_brain_ask_api.py`

**Interfaces:**
- Consumes: `ask_brain` (Task 2); `BrainAskEvent` (Task 1); `api.models.AskRequest` (`question`, `strategy_model`, `answer_model`, `final_answer_model`); `CtxDep` + `get_request_context` (P6); `open_notebook.ai.models.Model.get` / `model_manager` (model validation, mirrors existing ask endpoint). The brain `router` is already mounted with prefix `/brain` (P7.1).
- Produces: `POST /brain/ask` → `text/event-stream` of `data: {BrainAskEvent}\n\n` lines; body = `AskRequest`; role = any member.

- [ ] **Step 1: Write the failing route test (happy path SSE framing)**

Create `tests/test_brain_ask_api.py`:

```python
import types
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.deps import get_request_context
    from api.main import app

    app.dependency_overrides[get_request_context] = lambda: types.SimpleNamespace(
        workspace_id="workspace:alpha"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _one_answer_event(*args, **kwargs):
    from api.brain_models import BrainAskEvent

    yield BrainAskEvent(type="answer", content="A", cited_node_ids=["source:a"])
    yield BrainAskEvent(type="complete", final_answer="A", cited_node_ids=["source:a"])


def _body():
    return {
        "question": "q?",
        "strategy_model": "model:s",
        "answer_model": "model:a",
        "final_answer_model": "model:f",
    }


def test_brain_ask_streams_events_with_cited_node_ids(client):
    with (
        patch("api.routers.brain.Model.get", new_callable=AsyncMock, return_value=object()),
        patch(
            "api.routers.brain.model_manager.get_embedding_model",
            new_callable=AsyncMock,
            return_value=object(),
        ),
        patch("api.routers.brain.ask_brain", _one_answer_event),
    ):
        resp = client.post("/api/brain/ask", json=_body())

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert '"type": "answer"' in body
    assert '"cited_node_ids": ["source:a"]' in body
    assert '"type": "complete"' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_brain_ask_api.py -v`
Expected: FAIL — 404 (route not registered) or `AttributeError: ask_brain`.

- [ ] **Step 3: Implement the route**

Add to `api/routers/brain.py` (imports as needed; `router` already exists with prefix `/brain`):

```python
import json

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from api.brain_service import ask_brain
from api.deps import CtxDep
from api.models import AskRequest
from open_notebook.ai.models import Model, model_manager


@router.post("/ask")
async def ask_brain_endpoint(ask_request: AskRequest, ctx: CtxDep):
    """Graph-aware RAG over the active workspace's brain (SSE stream, any member)."""
    strategy_model = await Model.get(ask_request.strategy_model)
    answer_model = await Model.get(ask_request.answer_model)
    final_answer_model = await Model.get(ask_request.final_answer_model)
    if not strategy_model:
        raise HTTPException(status_code=400, detail=f"Strategy model {ask_request.strategy_model} not found")
    if not answer_model:
        raise HTTPException(status_code=400, detail=f"Answer model {ask_request.answer_model} not found")
    if not final_answer_model:
        raise HTTPException(status_code=400, detail=f"Final answer model {ask_request.final_answer_model} not found")
    if not await model_manager.get_embedding_model():
        raise HTTPException(
            status_code=400,
            detail="Ask the Brain requires an embedding model. Please configure one in the Models section.",
        )

    async def event_stream():
        try:
            async for event in ask_brain(
                ctx,
                ask_request.question,
                ask_request.strategy_model,
                ask_request.answer_model,
                ask_request.final_answer_model,
            ):
                yield f"data: {json.dumps(event.model_dump())}\n\n"
        except Exception as e:  # defensive: ask_brain already converts errors to events
            logger.error(f"Error in /brain/ask stream: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'cited_node_ids': []})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_brain_ask_api.py -v`
Expected: PASS.

- [ ] **Step 5: Write the workspace-scoping / leakage test**

Append to `tests/test_brain_ask_api.py`:

```python
def test_brain_ask_reads_graph_scoped_to_caller_workspace(client):
    captured = {}

    async def _spy_ask_brain(ctx, *args, **kwargs):
        from api.brain_models import BrainAskEvent

        captured["workspace_id"] = ctx.workspace_id
        yield BrainAskEvent(type="complete", final_answer="ok", cited_node_ids=[])

    with (
        patch("api.routers.brain.Model.get", new_callable=AsyncMock, return_value=object()),
        patch(
            "api.routers.brain.model_manager.get_embedding_model",
            new_callable=AsyncMock,
            return_value=object(),
        ),
        patch("api.routers.brain.ask_brain", _spy_ask_brain),
    ):
        resp = client.post("/api/brain/ask", json=_body())

    assert resp.status_code == 200
    # The overridden context is workspace:alpha — ask_brain must be scoped to it,
    # never to another workspace. This extends the P6 tenant-leakage guarantee to /brain/ask.
    assert captured["workspace_id"] == "workspace:alpha"


def test_brain_ask_missing_model_returns_400(client):
    with (
        patch("api.routers.brain.Model.get", new_callable=AsyncMock, return_value=None),
        patch(
            "api.routers.brain.model_manager.get_embedding_model",
            new_callable=AsyncMock,
            return_value=object(),
        ),
    ):
        resp = client.post("/api/brain/ask", json=_body())
    assert resp.status_code == 400
```

Also extend the P6 leakage suite: add a case to `tests/test_brain_leakage.py` (from P7.1) asserting `get_source_relationships` is invoked only with the requesting workspace id when `/brain/ask` runs — reuse the `_spy_ask_brain`/context-override pattern above so workspace B's request can never surface workspace A's edges.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_brain_ask_api.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Lint, typecheck, commit**

```bash
ruff check . --fix && uv run python -m mypy api/routers/brain.py
git add api/routers/brain.py tests/test_brain_ask_api.py
git commit -m "feat(brain): POST /brain/ask SSE route with workspace scoping"
```

---

### Task 4: `BrainAskStreamEvent` type + `brainApi.askBrain` stream client

**Files:**
- Modify: `frontend/src/lib/types/brain.ts`
- Modify: `frontend/src/lib/api/brain.ts`
- Test: `frontend/src/lib/api/brain.test.ts`

**Interfaces:**
- Consumes: `AskStreamEvent` and `AskRequest` (`frontend/src/lib/types/search.ts`); the token-from-`auth-storage` pattern from `searchApi.askKnowledgeBase`.
- Produces:
  - `BrainAskStreamEvent = AskStreamEvent & { cited_node_ids?: string[] }`
  - `brainApi.askBrain(params: AskRequest, onEvent: (event: BrainAskStreamEvent) => void): Promise<void>` — POSTs to `/api/brain/ask`, parses SSE `data:` lines, calls `onEvent` per event, throws `Error("Stream failed: <status>")` on non-OK.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/api/brain.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from 'vitest'
import { brainApi } from './brain'
import type { BrainAskStreamEvent } from '@/lib/types/brain'

function sseStream(lines: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const l of lines) controller.enqueue(enc.encode(l))
      controller.close()
    },
  })
}

afterEach(() => vi.restoreAllMocks())

const params = { question: 'q?', strategy_model: 's', answer_model: 'a', final_answer_model: 'f' }

describe('brainApi.askBrain', () => {
  it('parses SSE data lines and invokes onEvent per event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      body: sseStream([
        'data: {"type":"answer","content":"A","cited_node_ids":["source:a"]}\n\n',
        'data: {"type":"complete","final_answer":"A","cited_node_ids":["source:a"]}\n\n',
      ]),
    }))

    const events: BrainAskStreamEvent[] = []
    await brainApi.askBrain(params, (e) => events.push(e))

    expect(events.map((e) => e.type)).toEqual(['answer', 'complete'])
    expect(events[0].cited_node_ids).toEqual(['source:a'])
  })

  it('throws "Stream failed: <status>" on non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 402, body: null }))
    await expect(brainApi.askBrain(params, () => {})).rejects.toThrow('Stream failed: 402')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (in `frontend/`): `npm run test -- src/lib/api/brain.test.ts`
Expected: FAIL — `askBrain` is not a function / `BrainAskStreamEvent` not exported.

- [ ] **Step 3: Add the type**

Add to `frontend/src/lib/types/brain.ts`:

```ts
import type { AskStreamEvent } from '@/lib/types/search'

export type BrainAskStreamEvent = AskStreamEvent & {
  cited_node_ids?: string[]
}
```

- [ ] **Step 4: Implement `askBrain`**

Add to `frontend/src/lib/api/brain.ts` (inside the existing `brainApi` object):

```ts
import type { AskRequest } from '@/lib/types/search'
import type { BrainAskStreamEvent } from '@/lib/types/brain'

// ...inside `export const brainApi = { ... }`:
  askBrain: async (
    params: AskRequest,
    onEvent: (event: BrainAskStreamEvent) => void
  ): Promise<void> => {
    let token: string | null = null
    if (typeof window !== 'undefined') {
      const authStorage = localStorage.getItem('auth-storage')
      if (authStorage) {
        try {
          const { state } = JSON.parse(authStorage)
          if (state?.token) token = state.token
        } catch (error) {
          console.error('Error parsing auth storage:', error)
        }
      }
    }

    const response = await fetch('/api/brain/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: JSON.stringify(params),
    })

    if (!response.ok) {
      throw new Error(`Stream failed: ${response.status}`)
    }
    if (!response.body) {
      throw new Error('No response body received')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const jsonStr = line.slice(6).trim()
        if (!jsonStr) continue
        try {
          onEvent(JSON.parse(jsonStr) as BrainAskStreamEvent)
        } catch (e) {
          if (!(e instanceof SyntaxError)) throw e
          // incomplete/garbled JSON — skip, matching useAsk buffer behaviour
        }
      }
    }
  },
```

- [ ] **Step 5: Run test to verify it passes**

Run (in `frontend/`): `npm run test -- src/lib/api/brain.test.ts`
Expected: PASS (2 passed).

- [ ] **Step 6: Lint, commit**

```bash
cd frontend && npm run lint
git add src/lib/types/brain.ts src/lib/api/brain.ts src/lib/api/brain.test.ts
git commit -m "feat(brain): brainApi.askBrain SSE stream client + event type"
```

---

### Task 5: `useBrainAsk` hook (+ `setHighlighted` wiring)

**Files:**
- Create: `frontend/src/lib/hooks/use-brain-ask.ts`
- Test: `frontend/src/lib/hooks/use-brain-ask.test.ts`

**Interfaces:**
- Consumes: `brainApi.askBrain` (Task 4); `BrainAskStreamEvent` (Task 4); `useBrainStore` (P7.3) exposing `setHighlighted(ids: string[])` via `useBrainStore.getState()`; the `useAsk` state shape (`isStreaming`, `strategy`, `answers`, `finalAnswer`, `error`).
- Produces: `useBrainAsk() => { isStreaming, strategy, answers, finalAnswer, error, citedNodeIds: string[], sendAsk(question, models), reset() }` where `models = { strategy, answer, finalAnswer }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/hooks/use-brain-ask.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useBrainAsk } from './use-brain-ask'
import { brainApi } from '@/lib/api/brain'

const setHighlighted = vi.fn()
vi.mock('@/lib/stores/brain-store', () => ({
  useBrainStore: { getState: () => ({ setHighlighted }) },
}))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))
vi.mock('@/lib/api/brain', () => ({ brainApi: { askBrain: vi.fn() } }))

const models = { strategy: 's', answer: 'a', finalAnswer: 'f' }

beforeEach(() => vi.clearAllMocks())

describe('useBrainAsk', () => {
  it('parses events, exposes citedNodeIds, and calls setHighlighted', async () => {
    vi.mocked(brainApi.askBrain).mockImplementation(async (_params, onEvent) => {
      onEvent({ type: 'answer', content: 'A', cited_node_ids: ['source:a', 'source:z'] })
      onEvent({ type: 'final_answer', content: 'Final', cited_node_ids: ['source:a', 'source:z'] })
      onEvent({ type: 'complete', final_answer: 'Final', cited_node_ids: ['source:a', 'source:z'] })
    })

    const { result } = renderHook(() => useBrainAsk())
    await act(async () => {
      await result.current.sendAsk('q?', models)
    })

    await waitFor(() => expect(result.current.finalAnswer).toBe('Final'))
    expect(result.current.answers).toEqual(['A'])
    expect(result.current.citedNodeIds).toEqual(['source:a', 'source:z'])
    expect(setHighlighted).toHaveBeenCalledWith(['source:a', 'source:z'])
    expect(result.current.isStreaming).toBe(false)
  })

  it('sets error state when the stream client throws', async () => {
    vi.mocked(brainApi.askBrain).mockRejectedValue(new Error('Stream failed: 402'))
    const { result } = renderHook(() => useBrainAsk())
    await act(async () => {
      await result.current.sendAsk('q?', models)
    })
    await waitFor(() => expect(result.current.error).toBe('Stream failed: 402'))
    expect(result.current.isStreaming).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (in `frontend/`): `npm run test -- src/lib/hooks/use-brain-ask.test.ts`
Expected: FAIL — cannot resolve `./use-brain-ask`.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/lib/hooks/use-brain-ask.ts`:

```ts
'use client'

import { useState, useCallback } from 'react'
import { toast } from 'sonner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { brainApi } from '@/lib/api/brain'
import { useBrainStore } from '@/lib/stores/brain-store'
import type { BrainAskStreamEvent } from '@/lib/types/brain'

interface AskModels {
  strategy: string
  answer: string
  finalAnswer: string
}

interface StrategyData {
  reasoning: string
  searches: Array<{ term: string; instructions: string }>
}

interface BrainAskState {
  isStreaming: boolean
  strategy: StrategyData | null
  answers: string[]
  finalAnswer: string | null
  error: string | null
  citedNodeIds: string[]
}

const INITIAL: BrainAskState = {
  isStreaming: false,
  strategy: null,
  answers: [],
  finalAnswer: null,
  error: null,
  citedNodeIds: [],
}

export function useBrainAsk() {
  const { t } = useTranslation()
  const [state, setState] = useState<BrainAskState>(INITIAL)

  const sendAsk = useCallback(
    async (question: string, models: AskModels) => {
      if (!question.trim()) {
        toast.error(t('apiErrors.pleaseEnterQuestion'))
        return
      }
      if (!models.strategy || !models.answer || !models.finalAnswer) {
        toast.error(t('apiErrors.pleaseConfigureModels'))
        return
      }

      setState({ ...INITIAL, isStreaming: true })

      try {
        await brainApi.askBrain(
          {
            question,
            strategy_model: models.strategy,
            answer_model: models.answer,
            final_answer_model: models.finalAnswer,
          },
          (data: BrainAskStreamEvent) => {
            if (data.cited_node_ids && data.cited_node_ids.length > 0) {
              const ids = data.cited_node_ids
              setState((prev) => ({ ...prev, citedNodeIds: ids }))
              useBrainStore.getState().setHighlighted(ids)
            }
            if (data.type === 'strategy') {
              setState((prev) => ({
                ...prev,
                strategy: { reasoning: data.reasoning || '', searches: data.searches || [] },
              }))
            } else if (data.type === 'answer') {
              setState((prev) => ({ ...prev, answers: [...prev.answers, data.content || ''] }))
            } else if (data.type === 'final_answer') {
              setState((prev) => ({ ...prev, finalAnswer: data.content || '', isStreaming: false }))
            } else if (data.type === 'complete') {
              setState((prev) => ({ ...prev, isStreaming: false }))
            } else if (data.type === 'error') {
              throw new Error(data.message || 'Stream error occurred')
            }
          }
        )
        setState((prev) => ({ ...prev, isStreaming: false }))
      } catch (error) {
        const err = error as { message?: string }
        const errorMessage = err.message || 'An unexpected error occurred'
        console.error('Brain ask error:', error)
        setState((prev) => ({ ...prev, isStreaming: false, error: errorMessage }))
        toast.error(t('apiErrors.askFailed'), {
          description: getApiErrorMessage(errorMessage, (key) => t(key)),
        })
      }
    },
    [t]
  )

  const reset = useCallback(() => setState(INITIAL), [])

  return { ...state, sendAsk, reset }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (in `frontend/`): `npm run test -- src/lib/hooks/use-brain-ask.test.ts`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint, commit**

```bash
cd frontend && npm run lint
git add src/lib/hooks/use-brain-ask.ts src/lib/hooks/use-brain-ask.test.ts
git commit -m "feat(brain): useBrainAsk hook with cited-node highlight wiring"
```

---

### Task 6: `AskTheBrainPanel` + mount in Intelligence page

**Files:**
- Create: `frontend/src/components/intelligence/AskTheBrainPanel.tsx`
- Test: `frontend/src/components/intelligence/AskTheBrainPanel.test.tsx`
- Modify: `frontend/src/app/(dashboard)/intelligence/page.tsx`
- Modify: `frontend/src/lib/locales/*/` (7 locales)

**Interfaces:**
- Consumes: `useBrainAsk` (Task 5); `AnswerBody({ isStreaming, finalAnswer })`, `StrategyDisclosure({ strategy, answers })`, `SourcesPanel({ references })`, `AnswerFeedback({ answer, children })` (existing search components); `buildReferenceIndex` (`@/lib/utils/source-references`) for `SourcesPanel` references; the right-panel slot in P7.3's `page.tsx`.
- Produces: `<AskTheBrainPanel />` (default export-free named export) mounted in the Intelligence right panel.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/intelligence/AskTheBrainPanel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AskTheBrainPanel } from './AskTheBrainPanel'

const useBrainAskMock = vi.fn()
vi.mock('@/lib/hooks/use-brain-ask', () => ({ useBrainAsk: () => useBrainAskMock() }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
// Stub the reused search components to keep this a unit test of the panel wiring
vi.mock('@/components/search/AnswerBody', () => ({
  AnswerBody: ({ finalAnswer }: { finalAnswer: string | null }) => <div>answer:{finalAnswer}</div>,
}))
vi.mock('@/components/search/StrategyDisclosure', () => ({ StrategyDisclosure: () => <div /> }))
vi.mock('@/components/search/SourcesPanel', () => ({ SourcesPanel: () => <div /> }))
vi.mock('@/components/search/AnswerFeedback', () => ({
  AnswerFeedback: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

beforeEach(() => vi.clearAllMocks())

const base = {
  isStreaming: false,
  strategy: null,
  answers: [],
  finalAnswer: null,
  error: null,
  citedNodeIds: [],
  sendAsk: vi.fn(),
  reset: vi.fn(),
}

describe('AskTheBrainPanel', () => {
  it('renders the streamed final answer', () => {
    useBrainAskMock.mockReturnValue({ ...base, finalAnswer: 'The answer' })
    render(<AskTheBrainPanel />)
    expect(screen.getByText('answer:The answer')).toBeInTheDocument()
  })

  it('renders an inline error state without crashing', () => {
    useBrainAskMock.mockReturnValue({ ...base, error: 'Stream failed: 402' })
    render(<AskTheBrainPanel />)
    expect(screen.getByRole('alert')).toHaveTextContent('Stream failed: 402')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run (in `frontend/`): `npm run test -- src/components/intelligence/AskTheBrainPanel.test.tsx`
Expected: FAIL — cannot resolve `./AskTheBrainPanel`.

- [ ] **Step 3: Implement the panel**

Create `frontend/src/components/intelligence/AskTheBrainPanel.tsx`:

```tsx
'use client'

import { useState } from 'react'
import { Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { AnswerBody } from '@/components/search/AnswerBody'
import { StrategyDisclosure } from '@/components/search/StrategyDisclosure'
import { SourcesPanel } from '@/components/search/SourcesPanel'
import { AnswerFeedback } from '@/components/search/AnswerFeedback'
import { useBrainAsk } from '@/lib/hooks/use-brain-ask'
import { useTranslation } from '@/lib/hooks/use-translation'
import { buildReferenceIndex } from '@/lib/utils/source-references'
import { useModelDefaults } from '@/lib/hooks/use-model-defaults'

export function AskTheBrainPanel() {
  const { t } = useTranslation()
  const [question, setQuestion] = useState('')
  const { models } = useModelDefaults()
  const { isStreaming, strategy, answers, finalAnswer, error, sendAsk } = useBrainAsk()

  const handleSend = () => {
    sendAsk(question, {
      strategy: models.strategy,
      answer: models.answer,
      finalAnswer: models.finalAnswer,
    })
  }

  const references = finalAnswer ? buildReferenceIndex(finalAnswer).references : []

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <h2 className="text-sm font-semibold">{t('intelligence.ask.title')}</h2>

      <div className="flex-1 overflow-y-auto space-y-3">
        <StrategyDisclosure strategy={strategy} answers={answers} />
        {finalAnswer ? (
          <AnswerFeedback answer={finalAnswer}>
            <AnswerBody isStreaming={isStreaming} finalAnswer={finalAnswer} />
          </AnswerFeedback>
        ) : (
          <AnswerBody isStreaming={isStreaming} finalAnswer={finalAnswer} />
        )}
        {references.length > 0 && <SourcesPanel references={references} />}
        {error && (
          <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive">
            {error}
          </div>
        )}
      </div>

      <div className="flex items-end gap-2">
        <Textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('intelligence.ask.placeholder')}
          rows={2}
          disabled={isStreaming}
        />
        <Button onClick={handleSend} disabled={isStreaming || !question.trim()} size="icon" aria-label={t('intelligence.ask.send')}>
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
```

> Note: `useModelDefaults` is the existing ask-model-config hook the search page uses to resolve `{ strategy, answer, finalAnswer }` (reuse it; if the search page reads defaults differently, match that source). This keeps the model-config guard behaviour identical to the existing Ask experience.

- [ ] **Step 4: Add i18n keys, run test to verify it passes**

Add to each of the 7 locale files under `src/lib/locales/<locale>/` (translate per locale; en-US shown):

```json
"intelligence": {
  "ask": {
    "title": "Ask the Brain",
    "placeholder": "Ask a question about this workspace…",
    "send": "Send"
  }
}
```

Run (in `frontend/`): `npm run test -- src/components/intelligence/AskTheBrainPanel.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Mount in the Intelligence page**

Edit `frontend/src/app/(dashboard)/intelligence/page.tsx`: import and render the panel in the existing right-panel slot (P7.3). Add the import:

```tsx
import { AskTheBrainPanel } from '@/components/intelligence/AskTheBrainPanel'
```

and place `<AskTheBrainPanel />` inside the right-hand panel container (the collapsible right column that P7.3 left as a slot), replacing any placeholder there.

- [ ] **Step 6: Run the full frontend gate**

Run (in `frontend/`): `npm run test && npm run lint && npm run build`
Expected: all PASS (build compiles, no lint/type errors).

- [ ] **Step 7: Commit**

```bash
cd frontend
git add src/components/intelligence/AskTheBrainPanel.tsx \
        src/components/intelligence/AskTheBrainPanel.test.tsx \
        'src/app/(dashboard)/intelligence/page.tsx' \
        src/lib/locales
git commit -m "feat(brain): AskTheBrainPanel wired to useBrainAsk + mounted in Intelligence page"
```

---

## Self-Review

**Spec coverage (P7.4 scope):**
- `POST /brain/ask` graph-aware RAG, SSE, `CtxDep`, any member → **Task 3**.
- Reuse existing ask pipeline (`ask_graph`, `provision_langchain_model` inside the graph) rather than a new engine → **Task 2** (`ask_brain` drives `ask_graph.astream`; no new graph).
- After vector retrieval, expand to surrounding subgraph via `get_source_relationships(ctx.workspace_id)` and inject relationship annotations ("A supersedes B") into the ask context → **Task 1** (`build_subgraph_context`) + **Task 2** (augmented question string; prefers reusing the existing ask prompt over a new `prompts/brain/` template, as instructed).
- Stream events carry `cited_node_ids` → **Task 1** (`BrainAskEvent` field) + **Task 2** (every event tagged).
- Stream-event model extension matching existing shape → **Task 1** (`BrainAskEvent` mirrors the strategy/answer/final_answer/complete/error dict shape + adds `cited_node_ids`).
- `brainApi.askBrain(params, onEvent)` mirroring `searchApi.askKnowledgeBase` → **Task 4**.
- `useBrainAsk()` extending `useAsk`, exposing `{ ...askState, citedNodeIds, sendAsk }`, calling `setHighlighted` on each `cited_node_ids` event → **Task 5**.
- `AskTheBrainPanel` reusing `AnswerBody`/`SourcesPanel`/`StrategyDisclosure`/`AnswerFeedback`, mounted in `page.tsx` right slot, inline error handling ("Stream failed: 402") without crashing → **Task 6** (panel + Task 5 error state + Task 4 error throw).
- Backend tests: subgraph context includes relationship annotations (mock `vector_search` + `get_source_relationships`), `cited_node_ids` populated, workspace scoping / leakage → **Tasks 1–3**.
- Frontend tests: `useBrainAsk` parses stream + calls `setHighlighted`; `AskTheBrainPanel` renders answer + error state; stream client mocked → **Tasks 4–6**.

**Placeholder scan:** No TBD/TODO; every code step is complete Python/TSX with concrete assertions. The only deferred external names (`useModelDefaults`, right-panel slot location, `tests/test_brain_leakage.py`) are P7.1/7.3-provided and flagged with reuse guidance, not invented behaviour.

**Type consistency:** `BrainAskEvent`/`BrainAskStreamEvent` fields (`type`, `reasoning`, `searches`, `content`, `final_answer`, `message`, `cited_node_ids`) are identical across backend model, frontend type, hook, and tests. `ask_brain(ctx, question, strategy_model, answer_model, final_answer_model)` signature is consistent between Task 2, the Task 3 route call, and the leakage spy. `build_subgraph_context(retrieved_ids, relationships) -> (str, list[str])` is used identically in Tasks 1 and 2. `useBrainAsk` return keys match what `AskTheBrainPanel` destructures.

**Out of P7.4 scope (correctly not covered):** schema/migration, `GraphCanvas`, `NodeDetailPanel`, `/brain/graph`, `/brain/status`, `/brain/rebuild`, extraction commands — all delivered by P7.1–P7.3.
