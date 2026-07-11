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


def test_brain_ask_event_defaults_cited_node_ids_to_empty_list():
    from api.brain_models import BrainAskEvent

    event = BrainAskEvent(type="answer", content="hi")
    dumped = event.model_dump()
    assert dumped["type"] == "answer"
    assert dumped["content"] == "hi"
    assert dumped["cited_node_ids"] == []


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
