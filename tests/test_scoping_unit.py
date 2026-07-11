# tests/test_scoping_unit.py
"""Unit tests for ScopedRepository guard logic (no live DB — repo_* patched)."""
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.database.scoping import (
    GLOBAL_TABLES,
    INHERITED_WORKSPACE_TABLES,
    NATIVE_WORKSPACE_TABLES,
    WORKSPACE_SCOPED_TABLES,
    ScopedRepository,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError


def _repo() -> ScopedRepository:
    return ScopedRepository(workspace_id="workspace:A", user_id="user:1", role="owner")


def test_policy_sets_are_disjoint_and_cover_expected_tables():
    assert GLOBAL_TABLES.isdisjoint(WORKSPACE_SCOPED_TABLES)
    assert {"user", "auth_identity", "workspace", "membership"} <= GLOBAL_TABLES
    assert {
        "notebook", "source", "note", "chat_session",
        "source_insight", "source_embedding", "project_member", "invitation",
    } <= WORKSPACE_SCOPED_TABLES


def test_native_and_inherited_tables_partition_workspace_scoped_tables():
    """The generic get/list/create/update/delete methods only work correctly on
    tables with a NATIVE `workspace` column. Tables that inherit workspace via
    a parent (source/note via the reference/artifact edge to notebook;
    source_insight/source_embedding via their source) must be a disjoint set
    so `_assert_scoped` can reject them from the generic path fail-closed."""
    assert NATIVE_WORKSPACE_TABLES.isdisjoint(INHERITED_WORKSPACE_TABLES)
    assert NATIVE_WORKSPACE_TABLES | INHERITED_WORKSPACE_TABLES == WORKSPACE_SCOPED_TABLES
    # `episode` (P6 rollout, migration 24) also carries a native `workspace`
    # column -- optional/NULL on pre-migration rows, which fails closed (not
    # open) under the generic methods' `WHERE workspace = $workspace_id`.
    assert NATIVE_WORKSPACE_TABLES == {"notebook", "project_member", "invitation", "episode"}
    assert INHERITED_WORKSPACE_TABLES == {
        "source", "note", "chat_session", "source_insight", "source_embedding",
    }


@pytest.mark.asyncio
async def test_list_rejects_global_table():
    with pytest.raises(InvalidInputError, match="GLOBAL table"):
        await _repo().list("user")


@pytest.mark.asyncio
async def test_list_rejects_unknown_table_fails_closed():
    with pytest.raises(InvalidInputError, match="Unknown table"):
        await _repo().list("widget")


@pytest.mark.asyncio
async def test_create_rejects_global_table():
    with pytest.raises(InvalidInputError, match="GLOBAL table"):
        await _repo().create("membership", {"role": "owner"})


# ---- FIX #1: generic methods must reject INHERITED tables fail-closed ------
# `source`, `note`, `chat_session`, `source_insight`, `source_embedding` have NO
# native `workspace` column (verified: migrations 1-23 never add one). The
# generic get/list/create/update/delete methods build `WHERE workspace = ...`
# against the table directly, which silently misbehaves (always-empty or
# erroring) for these. They must be rejected with a clear, actionable error
# pointing at `.raw()` + a parent-join filter, not merely fail silently.

@pytest.mark.asyncio
async def test_list_rejects_inherited_table_with_clear_message():
    with pytest.raises(InvalidInputError, match="workspace-inherited"):
        await _repo().list("source")


@pytest.mark.asyncio
async def test_get_rejects_inherited_table_with_clear_message():
    with pytest.raises(InvalidInputError, match="workspace-inherited"):
        await _repo().get("source:abc")


@pytest.mark.asyncio
async def test_create_rejects_inherited_table_with_clear_message():
    with pytest.raises(InvalidInputError, match="workspace-inherited"):
        await _repo().create("source", {"title": "x"})


@pytest.mark.asyncio
async def test_update_rejects_inherited_table_with_clear_message():
    with pytest.raises(InvalidInputError, match="workspace-inherited"):
        await _repo().update("source:abc", {"title": "y"})


@pytest.mark.asyncio
async def test_delete_rejects_inherited_table_with_clear_message():
    with pytest.raises(InvalidInputError, match="workspace-inherited"):
        await _repo().delete("source:abc")


@pytest.mark.asyncio
async def test_inherited_table_rejection_mentions_raw_escape_hatch():
    with pytest.raises(InvalidInputError, match=r"\.raw\(\)"):
        await _repo().list("note")


@pytest.mark.asyncio
async def test_raw_still_available_for_inherited_table():
    """`.raw()` remains the sanctioned escape hatch for inherited tables — it
    must NOT be blocked by the same guard as the generic methods."""
    with patch(
        "open_notebook.database.scoping.repo_query",
        new=AsyncMock(return_value=[{"id": "source:x"}]),
    ):
        rows = await _repo().raw("SELECT * FROM source WHERE workspace = $workspace_id")
    assert rows == [{"id": "source:x"}]


@pytest.mark.asyncio
async def test_native_tables_still_work_via_generic_methods():
    """Sanity check: the fix must not regress the NATIVE tables."""
    for table in ("notebook", "project_member", "invitation", "episode"):
        with patch(
            "open_notebook.database.scoping.repo_query", new=AsyncMock(return_value=[])
        ):
            await _repo().list(table)  # must not raise


@pytest.mark.asyncio
async def test_list_ands_workspace_filter_onto_caller_predicate():
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(return_value=[])) as q:
        await _repo().list("notebook", where="archived = false", order_by="updated desc")
    query, params = q.call_args[0]
    assert "workspace = $workspace_id" in query
    assert "(archived = false)" in query
    assert " AND " in query  # caller predicate AND-ed, never replaces the scope
    assert "ORDER BY updated desc" in query
    assert str(params["workspace_id"]) == "workspace:A"


@pytest.mark.asyncio
async def test_get_filters_by_workspace_and_404s_on_empty():
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(return_value=[])) as q:
        with pytest.raises(NotFoundError):
            await _repo().get("notebook:guessed")
    query, params = q.call_args[0]
    assert "workspace = $workspace_id" in query
    assert str(params["rid"]) == "notebook:guessed"


@pytest.mark.asyncio
async def test_create_stamps_workspace_and_overwrites_client_value():
    async def _fake_create(table, data):
        return {"id": f"{table}:new", **data}
    with patch("open_notebook.database.scoping.repo_create", new=AsyncMock(side_effect=_fake_create)) as c:
        await _repo().create("notebook", {"name": "x", "workspace": "workspace:EVIL"})
    _table, data = c.call_args[0]
    assert str(data["workspace"]) == "workspace:A"  # server-set, client value discarded


@pytest.mark.asyncio
async def test_update_strips_workspace_and_ownership_checks_first():
    calls = {"n": 0}
    async def _fake_query(q, params=None):
        calls["n"] += 1
        return [{"id": "notebook:1", "workspace": "workspace:A"}]  # get() ownership check passes
    with patch("open_notebook.database.scoping.repo_query", new=AsyncMock(side_effect=_fake_query)), \
         patch("open_notebook.database.scoping.repo_update", new=AsyncMock(return_value=[{"id": "notebook:1"}])) as u:
        await _repo().update("notebook:1", {"name": "y", "workspace": "workspace:EVIL"})
    _table, _id, data = u.call_args[0]
    assert "workspace" not in data  # workspace immutable post-create
    assert calls["n"] == 1  # get() ran before update


def test_scoped_repository_has_no_kind_parameter():
    """Structural guard for Option A's uniformity: the isolation layer must never
    branch on workspace.kind. If a future change adds a `kind` param or the
    literal strings "personal"/"company" to this module, that's a regression —
    fail loudly here rather than discovering it via a leaked personal workspace."""
    sig = inspect.signature(ScopedRepository.__init__)
    assert "kind" not in sig.parameters

    src = Path(inspect.getfile(ScopedRepository)).read_text(encoding="utf-8")
    # Comments are allowed to explain the invariant (this test's own docstring
    # references the words); the PRODUCTION module must not contain the
    # branching literals as quoted strings.
    assert '"personal"' not in src
    assert '"company"' not in src
    assert "'personal'" not in src
    assert "'company'" not in src
