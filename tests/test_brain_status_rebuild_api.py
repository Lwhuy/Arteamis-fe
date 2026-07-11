from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.brain_service as brain_service
from api.brain_models import BrainStatusResponse
from api.deps import get_auth_context
from api.security import AuthContext


def _ctx(workspace_id="workspace:ws1", role="owner"):
    return SimpleNamespace(workspace_id=workspace_id, user_id="user:1", role=role)


@pytest.mark.asyncio
async def test_get_brain_status_reports_coverage(monkeypatch):
    # First query = total, second = built.
    query = AsyncMock(side_effect=[[{"c": 5}], [{"c": 3}]])
    monkeypatch.setattr(brain_service, "repo_query", query)

    status = await brain_service.get_brain_status(_ctx())

    assert isinstance(status, BrainStatusResponse)
    assert status.total_sources == 5
    assert status.built_sources == 3
    assert status.running is True  # unbuilt sources remain

    # Both queries must be scoped to THIS ctx's workspace, and must gate via
    # the `reference` edge (a `source` row has no `workspace` field of its
    # own -- see get_brain_graph), never `source.workspace`.
    assert len(query.await_args_list) == 2
    for call in query.await_args_list:
        sql, params = call.args
        assert "reference" in sql
        assert "out.workspace = $workspace" in sql
        assert "source.workspace" not in sql
        assert str(params["workspace"]) == "workspace:ws1"


@pytest.mark.asyncio
async def test_get_brain_status_all_built_not_running(monkeypatch):
    monkeypatch.setattr(
        brain_service, "repo_query", AsyncMock(side_effect=[[{"c": 2}], [{"c": 2}]])
    )
    status = await brain_service.get_brain_status(_ctx())
    assert status.running is False


@pytest.mark.asyncio
async def test_get_brain_status_no_sources_not_running(monkeypatch):
    monkeypatch.setattr(
        brain_service, "repo_query", AsyncMock(side_effect=[[{"c": 0}], [{"c": 0}]])
    )
    status = await brain_service.get_brain_status(_ctx())
    assert status.total_sources == 0
    assert status.built_sources == 0
    assert status.running is False


@pytest.mark.asyncio
async def test_get_brain_status_handles_empty_result_rows(monkeypatch):
    # A degenerate/empty result set (e.g. no reference rows at all) must not
    # raise an IndexError -- it should read as zero.
    monkeypatch.setattr(brain_service, "repo_query", AsyncMock(side_effect=[[], []]))
    status = await brain_service.get_brain_status(_ctx())
    assert status.total_sources == 0
    assert status.built_sources == 0
    assert status.running is False


@pytest.mark.asyncio
async def test_trigger_rebuild_submits_command_and_returns_id(monkeypatch):
    submit = MagicMock(return_value="command:xyz")
    monkeypatch.setattr(brain_service, "submit_command", submit)

    command_id = await brain_service.trigger_rebuild(_ctx(), "full")

    assert command_id == "command:xyz"
    submit.assert_called_once_with(
        "open_notebook",
        "rebuild_brain",
        {"workspace_id": "workspace:ws1", "mode": "full"},
    )


@pytest.mark.asyncio
async def test_trigger_rebuild_defaults_to_ctx_workspace_and_given_mode(monkeypatch):
    submit = MagicMock(return_value="command:abc")
    monkeypatch.setattr(brain_service, "submit_command", submit)

    command_id = await brain_service.trigger_rebuild(
        _ctx(workspace_id="workspace:other"), "incremental"
    )

    assert command_id == "command:abc"
    submit.assert_called_once_with(
        "open_notebook",
        "rebuild_brain",
        {"workspace_id": "workspace:other", "mode": "incremental"},
    )


@pytest.mark.asyncio
async def test_get_brain_graph_includes_relates_edges(monkeypatch):
    """P7.2: get_brain_graph now also surfaces `relates` (source<->source
    semantic) edges alongside part_of/mentions, scoped via
    get_source_relationships (relates has a native workspace field)."""

    async def fake_repo_query(query, vars=None):
        stripped = query.strip()
        if stripped.startswith("SELECT id, kind, name, salience FROM entity"):
            return []
        if stripped.startswith("SELECT id, title FROM source"):
            return [
                {"id": "source:s1", "title": "Source One"},
                {"id": "source:s2", "title": "Source Two"},
            ]
        if stripped.startswith("SELECT in AS source, out AS entity FROM mentions"):
            return []
        if stripped.startswith("SELECT in AS topic, out AS domain FROM part_of"):
            return []
        return []

    monkeypatch.setattr(brain_service, "repo_query", fake_repo_query)

    relationships = AsyncMock(
        return_value=[
            {
                "source": "source:s1",
                "target": "source:s2",
                "type": "agrees",
                "confidence": 0.9,
                "rationale": "aligned",
            }
        ]
    )
    monkeypatch.setattr(brain_service, "get_source_relationships", relationships)

    result = await brain_service.get_brain_graph(_ctx(), domain=None, limit=200)

    relationships.assert_awaited_once_with("workspace:ws1")
    edge_tuples = {(e.source, e.target, e.type) for e in result.edges}
    assert ("source:s1", "source:s2", "agrees") in edge_tuples


@pytest.mark.asyncio
async def test_get_brain_graph_drops_relates_edge_for_unlisted_node(monkeypatch):
    """A relates edge pointing at a source that never became a node (e.g. it
    has no mentions edge yet, so it's absent from source_rows) must not leak
    into the response as a dangling edge."""

    async def fake_repo_query(query, vars=None):
        stripped = query.strip()
        if stripped.startswith("SELECT id, title FROM source"):
            return [{"id": "source:s1", "title": "Source One"}]
        return []

    monkeypatch.setattr(brain_service, "repo_query", fake_repo_query)
    monkeypatch.setattr(
        brain_service,
        "get_source_relationships",
        AsyncMock(
            return_value=[
                {
                    "source": "source:s1",
                    "target": "source:unlisted",
                    "type": "agrees",
                    "confidence": 0.9,
                    "rationale": "aligned",
                }
            ]
        ),
    )

    result = await brain_service.get_brain_graph(_ctx(), domain=None, limit=200)

    assert all(e.target != "source:unlisted" for e in result.edges)


def _client(role="owner"):
    """TestClient with get_auth_context + the router's owner_or_admin gate
    overridden, mirroring tests/test_projects_api.py's auth-override pattern
    (the P7.2 brain router uses get_auth_context/require_role, not P6's
    CtxDep/get_request_context)."""
    import api.routers.brain as brain_router
    from api.main import app

    ctx = AuthContext(user_id="user:1", workspace_id="workspace:ws1", role=role)
    app.dependency_overrides[get_auth_context] = lambda: ctx

    def _gate():
        if role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="forbidden")
        return ctx

    app.dependency_overrides[brain_router.owner_or_admin] = _gate
    return TestClient(app), app


def test_brain_status_route(monkeypatch):
    import api.routers.brain as brain_router

    monkeypatch.setattr(
        brain_router,
        "get_brain_status",
        AsyncMock(
            return_value=BrainStatusResponse(
                total_sources=4, built_sources=2, running=True
            )
        ),
    )
    client, app = _client()
    try:
        resp = client.get("/api/brain/status")
        assert resp.status_code == 200
        assert resp.json() == {
            "total_sources": 4,
            "built_sources": 2,
            "running": True,
        }
    finally:
        app.dependency_overrides.clear()


def test_brain_rebuild_route_owner(monkeypatch):
    import api.routers.brain as brain_router

    monkeypatch.setattr(
        brain_router, "trigger_rebuild", AsyncMock(return_value="command:abc")
    )
    client, app = _client(role="owner")
    try:
        resp = client.post("/api/brain/rebuild", json={"mode": "full"})
        assert resp.status_code == 200
        assert resp.json() == {"command_id": "command:abc"}
    finally:
        app.dependency_overrides.clear()


def test_brain_rebuild_route_forbidden_for_member(monkeypatch):
    client, app = _client(role="member")
    try:
        resp = client.post("/api/brain/rebuild", json={"mode": "incremental"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
