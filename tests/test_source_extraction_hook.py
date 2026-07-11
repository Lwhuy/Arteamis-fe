from unittest.mock import AsyncMock, MagicMock

import pytest

import commands.source_commands as sc


@pytest.mark.asyncio
async def test_submit_entity_extraction_resolves_workspace_and_submits(monkeypatch):
    monkeypatch.setattr(
        sc, "repo_query",
        AsyncMock(return_value=[{"workspace": "workspace:ws1"}]),
    )
    submit = MagicMock(return_value="command:job1")
    monkeypatch.setattr(sc, "submit_command", submit)

    result = await sc._submit_entity_extraction("source:s1")

    assert result == "command:job1"
    submit.assert_called_once_with(
        "open_notebook",
        "extract_source_entities",
        {"source_id": "source:s1", "workspace_id": "workspace:ws1"},
    )


@pytest.mark.asyncio
async def test_submit_entity_extraction_skips_when_no_workspace(monkeypatch):
    monkeypatch.setattr(sc, "repo_query", AsyncMock(return_value=[{"workspace": None}]))
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
