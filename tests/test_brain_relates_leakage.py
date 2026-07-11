"""Tenant-leakage regression for the P7.2 `relates` edge (mirrors
`test_brain_tenant_leakage.py` from P7.1, which covers
entity/mentions/part_of/source; extends it to the semantic
source<->source `relates` edge introduced by P7.2 Tasks 1-2).

`relates` carries its OWN native `workspace` record field -- unlike
`source` (no native workspace of its own; scoped only via the `reference`
edge to its project/notebook, see commit 36a5775) -- so the production
read path filters directly: `WHERE workspace = $workspace`. The read
surface under test is:

  - `get_source_relationships(workspace)` (open_notebook/domain/brain.py,
    Task 2): `SELECT ... FROM relates WHERE workspace = $workspace`.
  - `get_brain_graph(ctx)` (api/brain_service.py, Task 5): calls
    `get_source_relationships(ctx.workspace_id)` and additionally gates
    the resulting edges on node membership (defense in depth on top of
    the SQL filter).
  - `get_brain_status(ctx)` (api/brain_service.py, Task 5): same read
    surface family: its counts must also be bound to ctx.workspace_id.

This suite proves BOTH `relates` layers hold, using one FLAT multi-tenant
store per data type (entity/mentions/reference/relates), not
pre-partitioned per workspace -- the fake `repo_query` interprets the
*actual* SurrealQL text and bound `$workspace` value the same way
SurrealDB would, so a regression that drops `WHERE workspace = $workspace`
(or swaps/hardcodes the bound value) is caught by the fake returning the
wrong rows -- not by the store happening to already be workspace-clean.
Includes a personal-vs-personal case (two personal workspaces, one of
which has classified zero relates edges of its own).
"""
from types import SimpleNamespace

import pytest

import api.brain_service as svc
import open_notebook.domain.brain as brain


def _ctx(workspace_id):
    return SimpleNamespace(workspace_id=workspace_id, user_id="user:x", role="owner")


WS_A = "workspace:relA"
WS_B = "workspace:relB"
WS_P1 = "workspace:relPersonal1"
WS_P2 = "workspace:relPersonal2"

# ---------------------------------------------------------------------------
# Flat, multi-tenant store of `relates` edges keyed by workspace -- NOT
# pre-filtered per test. The fake `repo_query` below decides what's visible
# by reading the real bound `$workspace` var, just like SurrealDB would.
# ---------------------------------------------------------------------------
RELATES = {
    WS_A: [
        {
            "source": "source:a1",
            "target": "source:a2",
            "type": "agrees",
            "confidence": 0.9,
            "rationale": "a-only",
        }
    ],
    WS_B: [
        {
            "source": "source:b1",
            "target": "source:b2",
            "type": "supersedes",
            "confidence": 0.8,
            "rationale": "b-only",
        }
    ],
    WS_P1: [
        {
            "source": "source:p1x",
            "target": "source:p1y",
            "type": "complements",
            "confidence": 0.7,
            "rationale": "p1-only",
        }
    ],
    # Second PERSONAL workspace: owns entity/source/mentions data of its
    # own (below) but has classified ZERO relates edges -- proving an
    # empty result isn't a side effect of a broken/empty store, but of
    # correct scoping.
    WS_P2: [],
}


def _fake_relates_repo_query(scoped_queries=None):
    async def fake_repo_query(query, vars=None):
        vars = vars or {}
        if scoped_queries is not None:
            scoped_queries.append((query, dict(vars)))
        assert "FROM relates" in query, f"query didn't hit relates table: {query}"
        assert "workspace = $workspace" in query, f"unscoped relates query: {query}"
        ws = str(vars["workspace"])
        return [dict(r) for r in RELATES.get(ws, [])]

    return fake_repo_query


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "workspace_id,expected_rationale",
    [(WS_A, "a-only"), (WS_B, "b-only"), (WS_P1, "p1-only")],
)
async def test_get_source_relationships_never_crosses_workspace(
    monkeypatch, workspace_id, expected_rationale
):
    """Each workspace's relates read returns ONLY its own edges out of a
    flat multi-tenant store -- never another workspace's, and never all
    workspaces' edges concatenated."""
    monkeypatch.setattr(brain, "repo_query", _fake_relates_repo_query())

    result = await brain.get_source_relationships(workspace_id)

    assert {e["rationale"] for e in result} == {expected_rationale}

    all_other_rationales = {
        r["rationale"]
        for ws, edges in RELATES.items()
        if ws != workspace_id
        for r in edges
    }
    for edge in result:
        assert edge["rationale"] not in all_other_rationales, (
            f"leaked another workspace's relates edge into {workspace_id}"
        )


@pytest.mark.asyncio
async def test_personal_vs_personal_relates_isolation(monkeypatch):
    """A second PERSONAL workspace must see none of the first personal
    workspace's relates edges -- personal-vs-personal is not exempt from
    the workspace filter."""
    monkeypatch.setattr(brain, "repo_query", _fake_relates_repo_query())

    p1 = await brain.get_source_relationships(WS_P1)
    p2 = await brain.get_source_relationships(WS_P2)

    assert {e["rationale"] for e in p1} == {"p1-only"}
    assert p2 == []  # ws:relPersonal2 sees none of relPersonal1's edges


# ---------------------------------------------------------------------------
# Full-graph integration: exercise get_brain_graph(ctx) end-to-end (real
# get_source_relationships, real node-gating) against a flat multi-tenant
# store covering entity/mentions/reference/relates for FOUR workspaces,
# including the personal-vs-personal pair.
# ---------------------------------------------------------------------------
ENTITIES = [
    {"id": "entity:a", "kind": "topic", "name": "A-Topic", "salience": 1.0, "workspace": WS_A},
    {"id": "entity:b", "kind": "topic", "name": "B-Topic", "salience": 1.0, "workspace": WS_B},
    {"id": "entity:p1", "kind": "topic", "name": "P1-Topic", "salience": 1.0, "workspace": WS_P1},
    {"id": "entity:p2", "kind": "topic", "name": "P2-Topic", "salience": 1.0, "workspace": WS_P2},
]

MENTIONS = [
    {"in": "source:a1", "out": "entity:a", "workspace": WS_A},
    {"in": "source:a2", "out": "entity:a", "workspace": WS_A},
    {"in": "source:b1", "out": "entity:b", "workspace": WS_B},
    {"in": "source:b2", "out": "entity:b", "workspace": WS_B},
    {"in": "source:p1x", "out": "entity:p1", "workspace": WS_P1},
    {"in": "source:p1y", "out": "entity:p1", "workspace": WS_P1},
    {"in": "source:p2x", "out": "entity:p2", "workspace": WS_P2},
]

SOURCES = [
    {"id": "source:a1", "title": "A1"},
    {"id": "source:a2", "title": "A2"},
    {"id": "source:b1", "title": "B1"},
    {"id": "source:b2", "title": "B2"},
    {"id": "source:p1x", "title": "P1X"},
    {"id": "source:p1y", "title": "P1Y"},
    {"id": "source:p2x", "title": "P2X"},
]

REFERENCE = [
    {"in": "source:a1", "out": "project:pa"},
    {"in": "source:a2", "out": "project:pa"},
    {"in": "source:b1", "out": "project:pb"},
    {"in": "source:b2", "out": "project:pb"},
    {"in": "source:p1x", "out": "project:pp1"},
    {"in": "source:p1y", "out": "project:pp1"},
    {"in": "source:p2x", "out": "project:pp2"},
]

PROJECT_WORKSPACE = {
    "project:pa": WS_A,
    "project:pb": WS_B,
    "project:pp1": WS_P1,
    "project:pp2": WS_P2,
}


def _make_full_fake_repo_query(scoped_queries):
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
            return []

        if stripped.startswith("SELECT id, title FROM source"):
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

        if "FROM relates" in stripped:
            assert "workspace = $workspace" in query, f"unscoped relates query: {query}"
            ws = str(vars["workspace"])
            return [dict(r) for r in RELATES.get(ws, [])]

        return []

    return fake_repo_query


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_id", [WS_A, WS_B, WS_P1, WS_P2])
async def test_brain_graph_relates_edges_never_leak_across_workspaces(
    monkeypatch, workspace_id
):
    scoped_queries: list = []
    # `get_brain_graph` issues its entity/mentions/part_of/source queries
    # via api.brain_service's own `repo_query` name, but the `relates`
    # lookup goes through the imported `get_source_relationships`, whose
    # `repo_query` call resolves against open_notebook.domain.brain's
    # module globals (Python looks up globals at call time, not import
    # time) -- so BOTH module attributes must be patched to run the real
    # end-to-end read path (no mocking of get_source_relationships itself).
    fake = _make_full_fake_repo_query(scoped_queries)
    monkeypatch.setattr(svc, "repo_query", fake)
    monkeypatch.setattr(brain, "repo_query", fake)

    result = await svc.get_brain_graph(_ctx(workspace_id), domain=None, limit=200)

    edge_tuples = {(e.source, e.target, e.type) for e in result.edges}

    all_relates_edges = {
        (r["source"], r["target"], r["type"])
        for edges in RELATES.values()
        for r in edges
    }
    own_relates_edges = {
        (r["source"], r["target"], r["type"]) for r in RELATES.get(workspace_id, [])
    }
    other_relates_edges = all_relates_edges - own_relates_edges

    # Own relates edge (if any -- relPersonal2 has none) IS present.
    assert own_relates_edges <= edge_tuples, (
        f"missing own relates edge(s) for {workspace_id}: "
        f"{own_relates_edges - edge_tuples}"
    )

    # No OTHER workspace's relates edge ever appears, for every other
    # workspace (not just one hardcoded "other side") -- including the
    # personal-vs-personal pair.
    leaked = other_relates_edges & edge_tuples
    assert not leaked, f"leaked another workspace's relates edge(s): {leaked}"

    # The relates lookup itself was bound to THIS ctx's workspace, verbatim
    # -- not hardcoded, not swapped, not omitted.
    relates_calls = [v["workspace"] for q, v in scoped_queries if "FROM relates" in q]
    assert relates_calls == [workspace_id], (
        f"relates lookup bound to {relates_calls}, expected only [{workspace_id}]"
    )


@pytest.mark.asyncio
async def test_brain_status_reads_are_workspace_scoped(monkeypatch):
    """`get_brain_status` (Task 5) is part of the same P7.2 brain read
    surface as `get_source_relationships` / `get_brain_graph` -- lock in
    that its coverage counts are bound to ctx.workspace_id, never
    hardcoded or swapped for another tenant's."""
    seen_params: list = []

    async def fake_query(sql, vars=None):
        vars = vars or {}
        seen_params.append(vars)
        assert "workspace = $workspace" in sql, f"unscoped brain-status query: {sql}"
        return [{"c": 1}]

    monkeypatch.setattr(svc, "repo_query", fake_query)

    await svc.get_brain_status(_ctx(WS_A))

    assert seen_params
    assert all(str(p["workspace"]) == WS_A for p in seen_params), (
        f"brain-status query(ies) not bound to {WS_A}: {seen_params}"
    )
