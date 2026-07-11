from typing import Any, Optional

from loguru import logger

from api.brain_models import BrainEdge, BrainGraphResponse, BrainNode
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.brain import normalize_entity_name
from open_notebook.exceptions import DatabaseOperationError


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
