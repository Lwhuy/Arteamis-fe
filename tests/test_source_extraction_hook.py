from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

import commands.source_commands as sc


@pytest.mark.asyncio
async def test_submit_entity_extraction_resolves_workspace_and_submits(monkeypatch):
    # Sources have no workspace field -- it's resolved via the `reference`
    # edge to the source's notebook/project (same idiom as
    # api/source_permissions.py's _source_workspaces).
    repo_query = AsyncMock(return_value=["workspace:ws1"])
    monkeypatch.setattr(sc, "repo_query", repo_query)
    submit = MagicMock(return_value="command:job1")
    monkeypatch.setattr(sc, "submit_command", submit)

    result = await sc._submit_entity_extraction("source:s1")

    assert result == "command:job1"
    repo_query.assert_called_once_with(
        "SELECT VALUE out.workspace FROM reference WHERE in = $source",
        {"source": ANY},
    )
    submit.assert_called_once_with(
        "open_notebook",
        "extract_source_entities",
        {"source_id": "source:s1", "workspace_id": "workspace:ws1"},
    )


@pytest.mark.asyncio
async def test_submit_entity_extraction_skips_when_no_workspace(monkeypatch):
    # No `reference` row for this source (e.g. not yet linked to any
    # notebook/project) -- workspace cannot be resolved.
    monkeypatch.setattr(sc, "repo_query", AsyncMock(return_value=[]))
    submit = MagicMock()
    monkeypatch.setattr(sc, "submit_command", submit)

    result = await sc._submit_entity_extraction("source:s1")

    assert result is None
    submit.assert_not_called()


@pytest.mark.asyncio
async def test_submit_entity_extraction_never_raises(monkeypatch):
    monkeypatch.setattr(sc, "repo_query", AsyncMock(side_effect=RuntimeError("db down")))
    monkeypatch.setattr(sc, "submit_command", MagicMock())
    # Must swallow errors so ingest is never blocked.
    assert await sc._submit_entity_extraction("source:s1") is None
