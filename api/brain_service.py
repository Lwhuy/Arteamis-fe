from typing import Any, Optional

from loguru import logger
from surreal_commands import submit_command

from api.brain_models import (
    BrainEdge,
    BrainGraphResponse,
    BrainNode,
    BrainStatusResponse,
)
from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.brain import get_source_relationships, normalize_entity_name
from open_notebook.exceptions import DatabaseOperationError


async def get_brain_graph(
    ctx: Any, domain: Optional[str] = None, limit: int = 200
) -> BrainGraphResponse:
    """
    Build the workspace's brain graph: entity nodes + source nodes, plus
    part_of (hierarchy), mentions (source->topic) and relates (source<->source
    semantic) edges. Every query is scoped to ctx.workspace_id.
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

        # P7.2: semantic source<->source relationships (relates has a native
        # `workspace` field -- no reference-edge join needed here, unlike
        # the source-node query above). Gated on node_ids like the edges
        # above so we never emit an edge pointing at a node that didn't make
        # the cut (e.g. a source not yet extracted, so it has no mentions
        # edge and never became a node).
        for rel in await get_source_relationships(ctx.workspace_id):
            src, tgt = rel["source"], rel["target"]
            if src in node_ids and tgt in node_ids:
                edges.append(BrainEdge(source=src, target=tgt, type=rel["type"]))

        return BrainGraphResponse(nodes=nodes, edges=edges)
    except Exception as e:
        logger.error(f"Error building brain graph for {ctx.workspace_id}: {e}")
        logger.exception(e)
        raise DatabaseOperationError(e)


async def get_brain_status(ctx: Any) -> BrainStatusResponse:
    """Extraction coverage for the active workspace: built sources / total.

    A `source` row has no `workspace` field of its own (see get_brain_graph
    above) -- its workspace is derived via the `reference` edge to its
    project/notebook. Counting MUST go through `reference`, never
    `source.workspace` (that field does not exist and the filter would
    silently match nothing / leak across tenants).
    """
    ws = ensure_record_id(ctx.workspace_id)

    total_rows = await repo_query(
        "SELECT count(array::distinct("
        "SELECT VALUE in FROM reference WHERE out.workspace = $workspace"
        ")) AS c FROM {}",
        {"workspace": ws},
    )
    total_sources = total_rows[0]["c"] if total_rows else 0

    built_rows = await repo_query(
        "SELECT count(array::distinct("
        "SELECT VALUE in FROM reference WHERE out.workspace = $workspace "
        "AND array::len(in->mentions) > 0"
        ")) AS c FROM {}",
        {"workspace": ws},
    )
    built_sources = built_rows[0]["c"] if built_rows else 0

    # Work remaining implies a build is in progress / needed.
    running = total_sources > 0 and built_sources < total_sources
    return BrainStatusResponse(
        total_sources=total_sources,
        built_sources=built_sources,
        running=running,
    )


async def trigger_rebuild(ctx: Any, mode: str) -> str:
    """Submit rebuild_brain for the active workspace; returns the command id.

    Authorization (owner/admin) is enforced at the router (next task), not
    here.
    """
    command_id = submit_command(
        "open_notebook",
        "rebuild_brain",
        {"workspace_id": ctx.workspace_id, "mode": mode},
    )
    return str(command_id)
