"""Tests for the classify_relationships command (P7.2 task 3).

CRITICAL: `vector_search` is NOT workspace-scoped by itself (it can return
candidates from any tenant). A `source` row has no `workspace` field of its
own (see commit 36a5775 / api/source_permissions.py) -- its workspace is
derived via the `reference` edge: `SELECT VALUE in FROM reference WHERE
out.workspace = $workspace` gives all source ids belonging to a workspace.
The command MUST use that query to filter vector_search candidates down to
the caller's own workspace before classifying or relating them -- `relates`
edges must never cross workspaces.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from surreal_commands import registry

import commands  # noqa: F401  (registers commands)
import commands.brain_commands as brain_commands
from open_notebook.database.repository import ensure_record_id


def _prompter_stub(**kw):
    return SimpleNamespace(render=lambda data: "PROMPT")


def test_classify_relationships_is_registered():
    assert "classify_relationships" in registry.list_commands()["open_notebook"]


@pytest.mark.asyncio
async def test_classify_relationships_creates_edges_and_skips_none(monkeypatch):
    primary = SimpleNamespace(title="A", full_text="alpha text")
    cand_b = SimpleNamespace(title="B", full_text="beta text")
    cand_c = SimpleNamespace(title="C", full_text="gamma text")

    async def fake_get(source_id):
        return {
            "source:primary": primary,
            "source:b": cand_b,
            "source:c": cand_c,
        }[source_id]

    monkeypatch.setattr(brain_commands.Source, "get", AsyncMock(side_effect=fake_get))
    # vector_search returns two OTHER sources plus the source itself (must be
    # skipped as a candidate for itself).
    monkeypatch.setattr(
        brain_commands,
        "vector_search",
        AsyncMock(
            return_value=[
                {"parent_id": "source:primary", "similarity": 1.0},
                {"parent_id": "source:b", "similarity": 0.9},
                {"parent_id": "source:c", "similarity": 0.8},
            ]
        ),
    )
    # Reference-edge scoping query: both candidates belong to the caller's
    # workspace (ws:1).
    repo_query = AsyncMock(return_value=["source:b", "source:c"])
    monkeypatch.setattr(brain_commands, "repo_query", repo_query)
    monkeypatch.setattr(brain_commands, "Prompter", _prompter_stub)

    # First pair -> supersedes; second pair -> none (skipped).
    responses = [
        SimpleNamespace(
            content='{"type": "supersedes", "confidence": 0.9, "rationale": "a updates b"}'
        ),
        SimpleNamespace(
            content='{"type": "none", "confidence": 0.1, "rationale": "unrelated"}'
        ),
    ]
    fake_model = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
    monkeypatch.setattr(
        brain_commands, "provision_langchain_model", AsyncMock(return_value=fake_model)
    )

    relate = AsyncMock(return_value={"id": "relates:1", "updated": False})
    monkeypatch.setattr(brain_commands, "relate_sources", relate)

    result = await brain_commands.classify_relationships_command(
        brain_commands.ClassifyRelationshipsInput(
            source_id="source:primary", workspace_id="ws:1", top_k=5
        )
    )

    assert result.success is True
    assert result.edges_created == 1
    relate.assert_awaited_once()
    call = relate.await_args
    assert call.args[0] == "source:primary"
    assert call.args[1] == "source:b"
    assert call.args[2] == "supersedes"
    assert call.args[5] == "ws:1"

    # The workspace-scoping query itself was bound to the caller's workspace.
    repo_query.assert_awaited_once()
    query_sql, query_vars = repo_query.await_args.args
    assert (
        "SELECT VALUE in FROM reference WHERE out.workspace = $workspace"
        in query_sql
    )
    assert query_vars["workspace"] == ensure_record_id("ws:1")


@pytest.mark.asyncio
async def test_classify_relationships_excludes_cross_workspace_candidates(monkeypatch):
    """A vector_search hit that does NOT belong to the caller's workspace must
    never be classified or related, even if it's the top-ranked candidate."""
    primary = SimpleNamespace(title="A", full_text="alpha text")
    same_ws = SimpleNamespace(title="B", full_text="beta text")

    async def fake_get(source_id):
        return {"source:primary": primary, "source:same": same_ws}[source_id]

    monkeypatch.setattr(brain_commands.Source, "get", AsyncMock(side_effect=fake_get))
    monkeypatch.setattr(
        brain_commands,
        "vector_search",
        AsyncMock(
            return_value=[
                {"parent_id": "source:other-ws", "similarity": 0.95},
                {"parent_id": "source:same", "similarity": 0.9},
            ]
        ),
    )
    # Only source:same resolves to the caller's workspace.
    monkeypatch.setattr(
        brain_commands, "repo_query", AsyncMock(return_value=["source:same"])
    )
    monkeypatch.setattr(brain_commands, "Prompter", _prompter_stub)

    fake_model = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SimpleNamespace(
                content='{"type": "agrees", "confidence": 0.8, "rationale": "aligned"}'
            )
        )
    )
    monkeypatch.setattr(
        brain_commands, "provision_langchain_model", AsyncMock(return_value=fake_model)
    )

    relate = AsyncMock(return_value={"id": "relates:1", "updated": False})
    monkeypatch.setattr(brain_commands, "relate_sources", relate)

    result = await brain_commands.classify_relationships_command(
        brain_commands.ClassifyRelationshipsInput(
            source_id="source:primary", workspace_id="ws:1", top_k=5
        )
    )

    assert result.success is True
    assert result.edges_created == 1
    relate.assert_awaited_once()
    # Only the same-workspace candidate was ever related.
    assert relate.await_args.args[1] == "source:same"
    # Source.get was never called for the cross-workspace candidate id
    # (it was filtered out before any per-candidate work happened).
    called_ids = {c.args[0] for c in brain_commands.Source.get.await_args_list}
    assert "source:other-ws" not in called_ids


@pytest.mark.asyncio
async def test_classify_relationships_logs_and_skips_candidate_failure(monkeypatch):
    """A failure classifying one candidate (e.g. transient LLM error) must be
    logged and skipped -- it must not crash the command or block
    classification of the remaining top-K peers."""
    primary = SimpleNamespace(title="A", full_text="alpha text")
    cand_b = SimpleNamespace(title="B", full_text="beta text")
    cand_c = SimpleNamespace(title="C", full_text="gamma text")

    async def fake_get(source_id):
        return {
            "source:primary": primary,
            "source:b": cand_b,
            "source:c": cand_c,
        }[source_id]

    monkeypatch.setattr(brain_commands.Source, "get", AsyncMock(side_effect=fake_get))
    monkeypatch.setattr(
        brain_commands,
        "vector_search",
        AsyncMock(
            return_value=[
                {"parent_id": "source:b", "similarity": 0.9},
                {"parent_id": "source:c", "similarity": 0.8},
            ]
        ),
    )
    monkeypatch.setattr(
        brain_commands, "repo_query", AsyncMock(return_value=["source:b", "source:c"])
    )
    monkeypatch.setattr(brain_commands, "Prompter", _prompter_stub)

    fake_model = SimpleNamespace(
        ainvoke=AsyncMock(
            side_effect=[
                RuntimeError("provider timeout"),
                SimpleNamespace(
                    content='{"type": "complements", "confidence": 0.6, "rationale": "extends"}'
                ),
            ]
        )
    )
    monkeypatch.setattr(
        brain_commands, "provision_langchain_model", AsyncMock(return_value=fake_model)
    )

    relate = AsyncMock(return_value={"id": "relates:1", "updated": False})
    monkeypatch.setattr(brain_commands, "relate_sources", relate)

    logged = []
    monkeypatch.setattr(brain_commands.logger, "error", lambda msg: logged.append(msg))

    result = await brain_commands.classify_relationships_command(
        brain_commands.ClassifyRelationshipsInput(
            source_id="source:primary", workspace_id="ws:1", top_k=5
        )
    )

    assert result.success is True
    assert result.edges_created == 1
    relate.assert_awaited_once()
    assert relate.await_args.args[1] == "source:c"
    assert any("source:b" in msg for msg in logged)


@pytest.mark.asyncio
async def test_classify_relationships_missing_text_raises_valueerror(monkeypatch):
    fake_source = SimpleNamespace(id="source:s1", title="Empty", full_text="")
    monkeypatch.setattr(brain_commands.Source, "get", AsyncMock(return_value=fake_source))

    with pytest.raises(ValueError):
        await brain_commands.classify_relationships_command(
            brain_commands.ClassifyRelationshipsInput(
                source_id="source:s1", workspace_id="ws:1", top_k=5
            )
        )


# --- rebuild_brain (P7.2 task 4) -------------------------------------------
#
# Sources have no `workspace` field of their own (see commit 36a5775 /
# api/source_permissions.py): workspace membership is derived via the
# `reference` edge, exactly like `_workspace_source_ids` above
# (`SELECT VALUE in FROM reference WHERE out.workspace = $workspace`).
# rebuild_brain MUST use that same reference-edge scoping -- never
# `source.workspace` -- to enumerate a workspace's sources.


def test_rebuild_brain_is_registered():
    assert "rebuild_brain" in registry.list_commands()["open_notebook"]


@pytest.mark.asyncio
async def test_rebuild_brain_full_submits_extract_and_classify_per_source(monkeypatch):
    monkeypatch.setattr(
        brain_commands,
        "repo_query",
        AsyncMock(return_value=["source:1", "source:2"]),
    )
    submit = MagicMock()
    monkeypatch.setattr(brain_commands, "submit_command", submit)

    result = await brain_commands.rebuild_brain_command(
        brain_commands.RebuildBrainInput(workspace_id="ws:1", mode="full")
    )

    assert result.success is True
    assert result.sources_processed == 2
    submitted = [(c.args[1], c.args[2]) for c in submit.call_args_list]
    assert (
        "extract_source_entities",
        {"source_id": "source:1", "workspace_id": "ws:1"},
    ) in submitted
    assert (
        "classify_relationships",
        {"source_id": "source:1", "workspace_id": "ws:1"},
    ) in submitted
    assert (
        "extract_source_entities",
        {"source_id": "source:2", "workspace_id": "ws:1"},
    ) in submitted


@pytest.mark.asyncio
async def test_rebuild_brain_full_uses_reference_edge_not_source_workspace(
    monkeypatch,
):
    query = AsyncMock(return_value=["source:1"])
    monkeypatch.setattr(brain_commands, "repo_query", query)
    monkeypatch.setattr(brain_commands, "submit_command", MagicMock())

    await brain_commands.rebuild_brain_command(
        brain_commands.RebuildBrainInput(workspace_id="ws:1", mode="full")
    )

    sql, params = query.await_args.args
    assert "SELECT VALUE in FROM reference" in sql
    assert "out.workspace = $workspace" in sql
    assert "source.workspace" not in sql
    assert params["workspace"] == ensure_record_id("ws:1")


@pytest.mark.asyncio
async def test_rebuild_brain_incremental_filters_unbuilt_sources(monkeypatch):
    query = AsyncMock(return_value=[])
    monkeypatch.setattr(brain_commands, "repo_query", query)
    monkeypatch.setattr(brain_commands, "submit_command", MagicMock())

    result = await brain_commands.rebuild_brain_command(
        brain_commands.RebuildBrainInput(workspace_id="ws:1", mode="incremental")
    )

    assert result.success is True
    assert result.sources_processed == 0
    sql = query.await_args.args[0]
    assert "->mentions" in sql  # only sources without extracted entities
    assert "workspace = $workspace" in sql


@pytest.mark.asyncio
async def test_rebuild_brain_deduplicates_source_ids(monkeypatch):
    """A source referenced by more than one notebook/project must only be
    processed once."""
    monkeypatch.setattr(
        brain_commands,
        "repo_query",
        AsyncMock(return_value=["source:1", "source:1", "source:2"]),
    )
    submit = MagicMock()
    monkeypatch.setattr(brain_commands, "submit_command", submit)

    result = await brain_commands.rebuild_brain_command(
        brain_commands.RebuildBrainInput(workspace_id="ws:1", mode="full")
    )

    assert result.sources_processed == 2
    assert submit.call_count == 4  # extract + classify for each of 2 sources


@pytest.mark.asyncio
async def test_rebuild_brain_reports_failure_on_query_error(monkeypatch):
    monkeypatch.setattr(
        brain_commands,
        "repo_query",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    monkeypatch.setattr(brain_commands, "submit_command", MagicMock())

    result = await brain_commands.rebuild_brain_command(
        brain_commands.RebuildBrainInput(workspace_id="ws:1", mode="full")
    )

    assert result.success is False
    assert result.error_message is not None
