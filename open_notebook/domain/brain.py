import re
from datetime import datetime
from typing import ClassVar, List, Literal, Optional

from loguru import logger
from pydantic import field_validator

from open_notebook.database.repository import (
    ensure_record_id,
    repo_query,
    repo_relate,
)
from open_notebook.domain.base import ObjectModel
from open_notebook.domain.notebook import Source
from open_notebook.exceptions import DatabaseOperationError

ENTITY_DEDUP_SIMILARITY_THRESHOLD = 0.92


def normalize_entity_name(name: str) -> str:
    """Case- and whitespace-fold an entity name for dedup matching."""
    return re.sub(r"\s+", " ", name).strip().lower()


class Entity(ObjectModel):
    table_name: ClassVar[str] = "entity"
    nullable_fields: ClassVar[set[str]] = {"embedding", "description"}
    workspace: str
    kind: Literal["domain", "topic", "person", "decision"]
    name: str
    normalized_name: str
    embedding: Optional[List[float]] = None
    description: Optional[str] = None
    salience: float = 0.0

    @field_validator("workspace", mode="before")
    @classmethod
    def _stringify_workspace(cls, value):
        # Loads already arrive as strings (repo_query -> parse_record_ids), but a
        # RecordID may be passed in directly; normalize to a plain string so
        # equality checks against ctx.workspace_id compare like-for-like.
        return str(value) if value is not None else None


async def upsert_entity_dedup(
    workspace: str,
    kind: str,
    name: str,
    description: Optional[str] = None,
    embedding: Optional[List[float]] = None,
) -> Entity:
    """
    Upsert an entity, deduplicating within the same workspace.

    Match order: (1) exact normalized_name within workspace+kind, then
    (2) embedding cosine similarity >= ENTITY_DEDUP_SIMILARITY_THRESHOLD.
    A match bumps salience and fills description if newly provided; otherwise
    a new entity is created. Prevents "engineering" becoming N duplicate nodes.
    """
    try:
        normalized = normalize_entity_name(name)
        ws = ensure_record_id(workspace)

        # 1. exact normalized_name match
        rows = await repo_query(
            "SELECT * FROM entity WHERE workspace = $workspace AND kind = $kind "
            "AND normalized_name = $normalized LIMIT 1",
            {"workspace": ws, "kind": kind, "normalized": normalized},
        )
        match = rows[0] if rows else None

        # 2. embedding similarity fallback
        if match is None and embedding is not None:
            sim = await repo_query(
                "SELECT *, vector::similarity::cosine(embedding, $embedding) AS similarity "
                "FROM entity WHERE workspace = $workspace AND kind = $kind "
                "AND embedding != NONE AND array::len(embedding) = array::len($embedding) "
                "AND vector::similarity::cosine(embedding, $embedding) >= $threshold "
                "ORDER BY similarity DESC LIMIT 1",
                {
                    "workspace": ws,
                    "kind": kind,
                    "embedding": embedding,
                    "threshold": ENTITY_DEDUP_SIMILARITY_THRESHOLD,
                },
            )
            match = sim[0] if sim else None

        if match is not None:
            updated = await repo_query(
                "UPDATE $id SET salience = salience + 1, "
                "description = ($description OR description), updated = time::now() "
                "RETURN AFTER",
                {"id": ensure_record_id(match["id"]), "description": description},
            )
            return Entity(**updated[0])

        # 3. create new
        created = await repo_query(
            "CREATE entity CONTENT { workspace: $workspace, kind: $kind, name: $name, "
            "normalized_name: $normalized, description: $description, embedding: $embedding, "
            "salience: 1, created: time::now(), updated: time::now() }",
            {
                "workspace": ws,
                "kind": kind,
                "name": name,
                "normalized": normalized,
                "description": description,
                "embedding": embedding,
            },
        )
        return Entity(**created[0])
    except Exception as e:
        logger.error(f"Error upserting entity '{name}' in {workspace}: {e}")
        logger.exception(e)
        raise DatabaseOperationError(e)


async def relate_mention(
    source_id: str, entity_id: str, workspace: str, confidence: float
) -> list:
    """RELATE source->mentions->entity with confidence, workspace-scoped."""
    return await repo_relate(
        source_id,
        "mentions",
        entity_id,
        {"workspace": ensure_record_id(workspace), "confidence": confidence},
    )


async def relate_part_of(topic_id: str, domain_id: str, workspace: str) -> list:
    """RELATE topic-entity->part_of->domain-entity, workspace-scoped."""
    return await repo_relate(
        topic_id,
        "part_of",
        domain_id,
        {"workspace": ensure_record_id(workspace)},
    )


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
