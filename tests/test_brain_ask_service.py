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
