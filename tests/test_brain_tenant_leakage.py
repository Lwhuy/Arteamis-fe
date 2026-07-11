"""Tenant-leakage regression for the P7.1 brain graph (mirrors the P6/P5
tenant-leakage suites -- `test_p5_search_leakage.py`, `test_p5_chat_context_leak.py`
-- extended to `entity`/`mentions`/`part_of`/`source`).

`get_brain_graph` (api/brain_service.py) scopes:
  - entity, mentions, part_of via their native `workspace` field.
  - source via the `reference` edge to its project/notebook (a `source` row
    has NO `workspace` field of its own -- see commit 36a5775). The
    production query ANDs two subqueries: sources reachable from a project
    in `$workspace` via `reference`, AND sources that appear in `$workspace`
    scoped `mentions`.

This test builds one flat multi-tenant store (not pre-partitioned per
workspace) and has the fake `repo_query` interpret the *actual* SurrealQL
text + bound vars the same way SurrealDB would, so a regression that drops
a WHERE clause or weakens the source AND-gate is caught by the fake
executing the wrong filter -- not by the store happening to already be
workspace-clean.

Includes a deliberately inconsistent "source:leak" row whose `mentions` edge
is stamped workspace A but whose `reference` edge points to a project in
workspace B, proving the service requires BOTH conditions (fail-closed) and
neither workspace can pull it in in isolation.
"""
from types import SimpleNamespace

import pytest

import api.brain_service as svc


def _ctx(workspace_id):
    return SimpleNamespace(workspace_id=workspace_id, user_id="user:x", role="owner")


WS_A = "workspace:personalA"
WS_B = "workspace:personalB"

ENTITIES = [
    {"id": "entity:a1", "kind": "domain", "name": "A-Domain", "salience": 5.0, "workspace": WS_A},
    {"id": "entity:a2", "kind": "topic", "name": "A-Topic", "salience": 3.0, "workspace": WS_A},
    {"id": "entity:b1", "kind": "domain", "name": "B-Domain", "salience": 5.0, "workspace": WS_B},
    {"id": "entity:b2", "kind": "topic", "name": "B-Topic", "salience": 3.0, "workspace": WS_B},
]

MENTIONS = [
    {"in": "source:sa", "out": "entity:a2", "workspace": WS_A},
    {"in": "source:sb", "out": "entity:b2", "workspace": WS_B},
    # Poisoned row: claims source:leak is mentioned in workspace A, but its
    # `reference` edge (below) says the source's project is in workspace B.
    {"in": "source:leak", "out": "entity:a2", "workspace": WS_A},
]

PART_OF = [
    {"in": "entity:a2", "out": "entity:a1", "workspace": WS_A},
    {"in": "entity:b2", "out": "entity:b1", "workspace": WS_B},
]

SOURCES = [
    {"id": "source:sa", "title": "A source"},
    {"id": "source:sb", "title": "B source"},
    {"id": "source:leak", "title": "Cross-tenant leak candidate"},
]

REFERENCE = [
    {"in": "source:sa", "out": "project:pa"},
    {"in": "source:sb", "out": "project:pb"},
    {"in": "source:leak", "out": "project:pb"},  # true owner: workspace B
]

PROJECT_WORKSPACE = {
    "project:pa": WS_A,
    "project:pb": WS_B,
}


def _make_fake_repo_query(scoped_queries):
    async def fake_repo_query(query, vars=None):
        vars = vars or {}
        stripped = query.strip()
        scoped_queries.append((query, dict(vars)))

        if stripped.startswith("SELECT id, kind, name, salience FROM entity"):
            assert "workspace = $workspace" in query, f"unscoped entity query: {query}"
            ws = str(vars["workspace"])
            return [
                {k: v for k, v in e.items() if k != "workspace"}
                for e in ENTITIES
                if e["workspace"] == ws
            ]

        if stripped.startswith("SELECT in AS source, out AS entity FROM mentions"):
            assert "workspace = $workspace" in query, f"unscoped mentions query: {query}"
            ws = str(vars["workspace"])
            return [
                {"source": m["in"], "entity": m["out"]}
                for m in MENTIONS
                if m["workspace"] == ws
            ]

        if stripped.startswith("SELECT in AS topic, out AS domain FROM part_of"):
            assert "workspace = $workspace" in query, f"unscoped part_of query: {query}"
            ws = str(vars["workspace"])
            return [
                {"topic": p["in"], "domain": p["out"]}
                for p in PART_OF
                if p["workspace"] == ws
            ]

        if stripped.startswith("SELECT id, title FROM source"):
            # Must gate via the `reference` edge (source has no workspace
            # field of its own), not via mentions.workspace alone.
            assert (
                "SELECT VALUE in FROM reference WHERE out.workspace = $workspace"
                in query
            ), f"source query not gated via reference edge: {query}"
            assert "workspace = $workspace" in query, f"unscoped source query: {query}"
            ws = str(vars["workspace"])
            referenced = {
                r["in"] for r in REFERENCE if PROJECT_WORKSPACE.get(r["out"]) == ws
            }
            mentioned = {m["in"] for m in MENTIONS if m["workspace"] == ws}
            allowed_ids = referenced & mentioned
            return [s for s in SOURCES if s["id"] in allowed_ids]

        return []

    return fake_repo_query


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_id", [WS_A, WS_B])
async def test_brain_graph_never_leaks_across_workspaces(monkeypatch, workspace_id):
    scoped_queries: list = []
    monkeypatch.setattr(svc, "repo_query", _make_fake_repo_query(scoped_queries))

    relationship_calls: list = []

    async def fake_get_source_relationships(workspace):
        relationship_calls.append(workspace)
        return []

    monkeypatch.setattr(
        svc, "get_source_relationships", fake_get_source_relationships
    )

    result = await svc.get_brain_graph(_ctx(workspace_id), domain=None, limit=200)

    # relates lookup (P7.2) must also be bound to THIS ctx's workspace only.
    assert relationship_calls == [workspace_id]

    node_ids = {n.id for n in result.nodes}
    edge_tuples = {(e.source, e.target, e.type) for e in result.edges}

    own_prefix = "a" if workspace_id == WS_A else "b"
    other_prefix = "b" if workspace_id == WS_A else "a"

    # Own data IS present: both entities, the own part_of edge, own source,
    # and the own mentions edge.
    assert f"entity:{own_prefix}1" in node_ids
    assert f"entity:{own_prefix}2" in node_ids
    assert f"source:s{own_prefix}" in node_ids
    assert (
        f"entity:{own_prefix}2",
        f"entity:{own_prefix}1",
        "part_of",
    ) in edge_tuples
    assert (
        f"source:s{own_prefix}",
        f"entity:{own_prefix}2",
        "mentions",
    ) in edge_tuples

    # Other workspace's entities/source/edges must NEVER appear.
    assert f"entity:{other_prefix}1" not in node_ids, "leaked another workspace's domain entity"
    assert f"entity:{other_prefix}2" not in node_ids, "leaked another workspace's topic entity"
    assert f"source:s{other_prefix}" not in node_ids, "leaked another workspace's source"
    assert (
        f"entity:{other_prefix}2",
        f"entity:{other_prefix}1",
        "part_of",
    ) not in edge_tuples, "leaked another workspace's part_of edge"
    assert (
        f"source:s{other_prefix}",
        f"entity:{other_prefix}2",
        "mentions",
    ) not in edge_tuples, "leaked another workspace's mentions edge"

    # The inconsistent cross-tenant row must never surface for EITHER
    # workspace: workspace A's mentions claim it, workspace B's reference
    # edge claims it -- neither is sufficient alone (fail-closed AND gate).
    assert "source:leak" not in node_ids, (
        "cross-tenant source leaked via a partial (mentions-only or "
        "reference-only) match"
    )

    # Every brain query must be workspace-scoped and bound to THIS ctx's
    # workspace -- never any other.
    assert len(scoped_queries) >= 4  # entity, mentions, part_of, source
    for query, vars in scoped_queries:
        assert "workspace" in vars, f"query missing bound workspace: {query}"
        assert str(vars["workspace"]) == workspace_id, (
            f"query bound to wrong workspace ({vars['workspace']} != "
            f"{workspace_id}): {query}"
        )
