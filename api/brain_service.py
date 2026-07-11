from typing import Any, AsyncIterator, Optional

from loguru import logger

from api.brain_models import BrainAskEvent, BrainEdge, BrainGraphResponse, BrainNode
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.brain import get_source_relationships, normalize_entity_name
from open_notebook.domain.notebook import vector_search
from open_notebook.exceptions import DatabaseOperationError
from open_notebook.graphs.ask import graph as ask_graph
from open_notebook.utils.error_classifier import classify_error


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
        # A `source` row has no `workspace` field of its own -- it inherits
        # its workspace from its notebook/project via the `reference` edge
        # (migration 23). That's the canonical, DB-enforced workspace gate;
        # the `mentions` join here only restricts to sources that actually
        # appear in this graph (mentions.workspace is correct for that join,
        # but must not be relied on as the source's own workspace proof).
        source_rows = await repo_query(
            "SELECT id, title FROM source WHERE id IN "
            "(SELECT VALUE in FROM reference WHERE out.workspace = $workspace) "
            "AND id IN (SELECT VALUE in FROM mentions WHERE workspace = $workspace)",
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


async def ask_brain(
    ctx: Any,
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
