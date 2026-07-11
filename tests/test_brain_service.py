from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.brain_service as svc


def _ctx(workspace_id="workspace:ws1"):
    return SimpleNamespace(workspace_id=workspace_id, user_id="user:u1", role="owner")


@pytest.mark.asyncio
async def test_get_brain_graph_assembles_nodes_and_edges(monkeypatch):
    seen = []

    async def fake_repo_query(query, vars=None):
        seen.append((query, vars or {}))
        stripped = query.strip()
        if stripped.startswith("SELECT id, kind, name, salience FROM entity"):
            return [
                {"id": "entity:d1", "kind": "domain", "name": "Engineering", "salience": 5.0},
                {"id": "entity:t1", "kind": "topic", "name": "Vector Search", "salience": 3.0},
            ]
        if stripped.startswith("SELECT id, title FROM source"):
            return [{"id": "source:s1", "title": "Intro to VS"}]
        if stripped.startswith("SELECT in AS source, out AS entity FROM mentions"):
            return [{"source": "source:s1", "entity": "entity:t1"}]
        if stripped.startswith("SELECT in AS topic, out AS domain FROM part_of"):
            return [{"topic": "entity:t1", "domain": "entity:d1"}]
        return []

    monkeypatch.setattr(svc, "repo_query", fake_repo_query)
    monkeypatch.setattr(svc, "get_source_relationships", AsyncMock(return_value=[]))

    result = await svc.get_brain_graph(_ctx(), domain=None, limit=200)

    node_ids = {n.id: n for n in result.nodes}
    assert node_ids["entity:d1"].kind == "domain"
    assert node_ids["entity:t1"].label == "Vector Search"
    assert node_ids["source:s1"].kind == "source"
    assert node_ids["source:s1"].label == "Intro to VS"

    edge_types = {(e.source, e.target, e.type) for e in result.edges}
    assert ("entity:t1", "entity:d1", "part_of") in edge_types
    assert ("source:s1", "entity:t1", "mentions") in edge_types

    # A source has no `workspace` field of its own -- the source-node query
    # must gate on the canonical, DB-enforced `reference` edge (source ->
    # notebook/project -> workspace), not on the `mentions.workspace` stamp.
    source_query = next(
        q for q, _ in seen if q.strip().startswith("SELECT id, title FROM source")
    )
    assert (
        "SELECT VALUE in FROM reference WHERE out.workspace = $workspace"
        in source_query
    )

    # Every query is workspace-scoped and binds ctx.workspace_id.
    for query, vars in seen:
        assert "workspace = $workspace" in query
        assert str(vars["workspace"]) == "workspace:ws1"


@pytest.mark.asyncio
async def test_get_brain_graph_domain_filter(monkeypatch):
    """Covers the `if domain:` branch: normalized-name match plus the
    ->part_of->entity traversal that pulls in topics under that domain."""
    seen = []

    async def fake_repo_query(query, vars=None):
        seen.append((query, vars or {}))
        stripped = query.strip()
        if stripped.startswith("SELECT id, kind, name, salience FROM entity"):
            assert "normalized_name = $domain" in stripped
            assert "->part_of->entity.normalized_name" in stripped
            assert (vars or {}).get("domain") == "engineering"
            return [
                {"id": "entity:d1", "kind": "domain", "name": "Engineering", "salience": 5.0},
                {"id": "entity:t1", "kind": "topic", "name": "Vector Search", "salience": 3.0},
            ]
        if stripped.startswith("SELECT id, title FROM source"):
            return [{"id": "source:s1", "title": "Intro to VS"}]
        if stripped.startswith("SELECT in AS source, out AS entity FROM mentions"):
            return [{"source": "source:s1", "entity": "entity:t1"}]
        if stripped.startswith("SELECT in AS topic, out AS domain FROM part_of"):
            return [{"topic": "entity:t1", "domain": "entity:d1"}]
        return []

    monkeypatch.setattr(svc, "repo_query", fake_repo_query)
    monkeypatch.setattr(svc, "get_source_relationships", AsyncMock(return_value=[]))

    result = await svc.get_brain_graph(_ctx(), domain="Engineering", limit=200)

    node_ids = {n.id for n in result.nodes}
    assert node_ids == {"entity:d1", "entity:t1", "source:s1"}

    edge_types = {(e.source, e.target, e.type) for e in result.edges}
    assert ("entity:t1", "entity:d1", "part_of") in edge_types

    entity_query = next(
        q
        for q, _ in seen
        if q.strip().startswith("SELECT id, kind, name, salience FROM entity")
    )
    assert "normalized_name = $domain" in entity_query
    assert "->part_of->entity.normalized_name" in entity_query
