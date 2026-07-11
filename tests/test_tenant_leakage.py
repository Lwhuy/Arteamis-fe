# tests/test_tenant_leakage.py
"""Tenant-leakage suite — the SurrealDB analogue of arteamis-system's
test_projects_rls.py + test_X3_suite1_tenant_leakage.py. Proves workspace A can
never read or mutate workspace B's rows, even by guessing record ids — for two
COMPANY workspaces AND for two PERSONAL workspaces belonging to different
users, using the exact same ScopedRepository code path in both cases.

Requires a live SurrealDB (the API's configured DB). Skipped unless
RUN_TENANT_LEAKAGE_DB=1 so `uv run pytest tests/` is green in CI without a DB.
Seeds two company workspaces A/B + a user/membership in each, then drives
/api/projects with each workspace's access token.
"""
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.security import create_access_token
from open_notebook.database.repository import (
    ensure_record_id,
    repo_create,
    repo_delete,
    repo_query,
)

_requires_db = pytest.mark.skipif(
    os.getenv("RUN_TENANT_LEAKAGE_DB") != "1",
    reason="RUN_TENANT_LEAKAGE_DB not set (needs a live SurrealDB)",
)

pytestmark = [pytest.mark.asyncio, _requires_db]


def _headers(user_id: str, workspace_id: str, role: str = "owner") -> dict:
    tok = create_access_token(user_id=user_id, workspace_id=workspace_id, role=role)
    return {"Authorization": f"Bearer {tok}"}


_RECORD_LINK_FIELDS = ("owner", "workspace", "user", "project")


async def _create(table: str, data: dict) -> dict:
    """repo_create's runtime return shape is inconsistent across SurrealDB
    client versions (a bare dict vs. a one-element list) — normalize here so
    fixture seeding doesn't depend on which shape this environment returns.
    Also coerce record-link fields (owner/workspace/user/project) to a real
    RecordID — the schema enforces record<table> types and repo_create does
    not do this coercion itself (unlike ObjectModel._prepare_save_data)."""
    data = {
        k: (ensure_record_id(v) if k in _RECORD_LINK_FIELDS and v is not None else v)
        for k, v in data.items()
    }
    result = await repo_create(table, data)
    return result[0] if isinstance(result, list) else result


@pytest_asyncio.fixture
async def seeded():
    """Create two COMPANY workspaces, a user + membership in each, and one
    project in A."""
    tag = uuid.uuid4().hex[:8]
    ua = await _create("user", {"email": f"a-{tag}@t.io", "display_name": "A"})
    ub = await _create("user", {"email": f"b-{tag}@t.io", "display_name": "B"})
    wa = await _create("workspace", {"name": f"A-{tag}", "slug": f"a-{tag}", "kind": "company", "owner": ua["id"]})
    wb = await _create("workspace", {"name": f"B-{tag}", "slug": f"b-{tag}", "kind": "company", "owner": ub["id"]})
    await _create("membership", {"user": ua["id"], "workspace": wa["id"], "role": "owner", "status": "active"})
    await _create("membership", {"user": ub["id"], "workspace": wb["id"], "role": "owner", "status": "active"})
    proj_a = await _create(
        "notebook",
        {"name": f"A-proj-{tag}", "description": "secret", "workspace": wa["id"],
         "owner": ua["id"], "default_source_scope": "project", "archived": False},
    )
    data = {
        "user_a": str(ua["id"]), "user_b": str(ub["id"]),
        "workspace_a": str(wa["id"]), "workspace_b": str(wb["id"]),
        "project_a": str(proj_a["id"]),
    }
    yield data
    # teardown — best effort
    for rid in (proj_a["id"], wa["id"], wb["id"], ua["id"], ub["id"]):
        try:
            await repo_delete(rid)
        except Exception:
            pass
    await repo_query("DELETE membership WHERE workspace = $w1 OR workspace = $w2",
                     {"w1": wa["id"], "w2": wb["id"]})


@pytest_asyncio.fixture
async def seeded_personal():
    """Create two PERSONAL workspaces belonging to two different users, each
    with exactly one member (its owner) and one project. Proves the SAME
    ScopedRepository/require_workspace path isolates solo tenants from each
    other with no personal/company special-casing."""
    tag = uuid.uuid4().hex[:8]
    ux = await _create("user", {"email": f"x-{tag}@t.io", "display_name": "X"})
    uy = await _create("user", {"email": f"y-{tag}@t.io", "display_name": "Y"})
    wx = await _create("workspace", {"name": "Personal", "slug": f"x-{tag}", "kind": "personal", "owner": ux["id"]})
    wy = await _create("workspace", {"name": "Personal", "slug": f"y-{tag}", "kind": "personal", "owner": uy["id"]})
    await _create("membership", {"user": ux["id"], "workspace": wx["id"], "role": "owner", "status": "active"})
    await _create("membership", {"user": uy["id"], "workspace": wy["id"], "role": "owner", "status": "active"})
    proj_x = await _create(
        "notebook",
        {"name": f"X-solo-project-{tag}", "description": "private notes", "workspace": wx["id"],
         "owner": ux["id"], "default_source_scope": "personal", "archived": False},
    )
    data = {
        "user_x": str(ux["id"]), "user_y": str(uy["id"]),
        "workspace_x": str(wx["id"]), "workspace_y": str(wy["id"]),
        "project_x": str(proj_x["id"]),
    }
    yield data
    for rid in (proj_x["id"], wx["id"], wy["id"], ux["id"], uy["id"]):
        try:
            await repo_delete(rid)
        except Exception:
            pass
    await repo_query("DELETE membership WHERE workspace = $w1 OR workspace = $w2",
                     {"w1": wx["id"], "w2": wy["id"]})


@pytest_asyncio.fixture
async def client():
    from api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_workspace_b_cannot_list_workspace_a_projects(client, seeded):
    r = await client.get("/api/projects", headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()]
    assert seeded["project_a"] not in ids  # A's project absent from B's list


async def test_workspace_a_can_list_own_projects(client, seeded):
    r = await client.get("/api/projects", headers=_headers(seeded["user_a"], seeded["workspace_a"]))
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert seeded["project_a"] in ids


async def test_workspace_b_cannot_get_workspace_a_project_by_guessed_id(client, seeded):
    r = await client.get(f"/api/projects/{seeded['project_a']}",
                         headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 404, r.text  # not 200, not 403 — no existence oracle


async def test_workspace_b_cannot_update_workspace_a_project(client, seeded):
    r = await client.put(f"/api/projects/{seeded['project_a']}",
                         json={"name": "hijacked"},
                         headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 404
    # A re-reads → unchanged (WITH CHECK analogue)
    ra = await client.get(f"/api/projects/{seeded['project_a']}",
                          headers=_headers(seeded["user_a"], seeded["workspace_a"]))
    assert ra.status_code == 200
    assert ra.json()["name"] != "hijacked"


async def test_workspace_b_cannot_delete_workspace_a_project(client, seeded):
    r = await client.delete(f"/api/projects/{seeded['project_a']}",
                            headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code == 404
    ra = await client.get(f"/api/projects/{seeded['project_a']}",
                          headers=_headers(seeded["user_a"], seeded["workspace_a"]))
    assert ra.status_code == 200  # A still sees it


async def test_create_stamps_callers_workspace_not_client_value(client, seeded):
    # B forges workspace=A in the body; server must stamp B.
    r = await client.post("/api/projects",
                          json={"name": "forge", "workspace": seeded["workspace_a"]},
                          headers=_headers(seeded["user_b"], seeded["workspace_b"]))
    assert r.status_code in (200, 201), r.text
    created_id = r.json()["id"]
    from open_notebook.database.repository import ensure_record_id
    rows = await repo_query("SELECT workspace FROM $rid", {"rid": ensure_record_id(created_id)})
    assert str(rows[0]["workspace"]) == seeded["workspace_b"]  # stamped B, not A
    await repo_delete(created_id)


async def test_identity_only_token_is_401_before_reaching_require_workspace(client, seeded):
    """An identity token (no workspace_id/role claims) never reaches
    require_workspace's dedicated 403 at all — P2's get_auth_context (reused
    unchanged by P6) already 401s it first ("A workspace-scoped access token
    is required"), since decode_access_token requires workspace_id/role to be
    present. require_workspace's own 403 ("No active workspace") is exercised
    directly in tests/test_deps_context.py against a synthetic AuthContext
    (workspace_id=None) — the shape no real HTTP request can produce today,
    since get_auth_context's own gate runs first in every dependency chain."""
    from api.security import create_identity_token
    tok = create_identity_token(seeded["user_b"])  # identity token: no workspace_id
    r = await client.get("/api/projects", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401
    assert "workspace-scoped access token" in r.json()["detail"]


async def test_member_cannot_create_project(client, seeded):
    # A plain member is refused project creation by require_role("owner","admin").
    r = await client.post("/api/projects", json={"name": "nope"},
                          headers=_headers(seeded["user_a"], seeded["workspace_a"], role="member"))
    assert r.status_code == 403
    assert "Requires role" in r.json()["detail"]


async def test_personal_workspace_x_not_visible_to_personal_workspace_y(client, seeded_personal):
    """The uniformity guarantee: user Y (a different user, with their own
    separate personal workspace) cannot list or fetch user X's personal
    project — same 200/404 assertions as the company A/B cases, no special
    personal-workspace code path involved."""
    r_list = await client.get(
        "/api/projects", headers=_headers(seeded_personal["user_y"], seeded_personal["workspace_y"])
    )
    assert r_list.status_code == 200, r_list.text
    assert seeded_personal["project_x"] not in [p["id"] for p in r_list.json()]

    r_get = await client.get(
        f"/api/projects/{seeded_personal['project_x']}",
        headers=_headers(seeded_personal["user_y"], seeded_personal["workspace_y"]),
    )
    assert r_get.status_code == 404, r_get.text  # not 200, not 403 — no existence oracle

    # X still sees their own project in their own personal workspace.
    r_own = await client.get(
        f"/api/projects/{seeded_personal['project_x']}",
        headers=_headers(seeded_personal["user_x"], seeded_personal["workspace_x"]),
    )
    assert r_own.status_code == 200
