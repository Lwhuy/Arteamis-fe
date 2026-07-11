from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import open_notebook.domain.brain as brain


def _source(created):
    return SimpleNamespace(created=created)


@pytest.mark.asyncio
async def test_supersedes_is_oriented_newer_to_older(monkeypatch):
    older = _source(datetime(2020, 1, 1))
    newer = _source(datetime(2024, 1, 1))

    async def fake_get(source_id):
        return {"source:old": older, "source:new": newer}[source_id]

    monkeypatch.setattr(brain, "ensure_record_id", lambda v: f"rid:{v}")
    monkeypatch.setattr(brain.Source, "get", AsyncMock(side_effect=fake_get))
    # dedup lookup returns no existing edge
    monkeypatch.setattr(brain, "repo_query", AsyncMock(return_value=[]))
    relate = AsyncMock(return_value=[{"id": "relates:1"}])
    monkeypatch.setattr(brain, "repo_relate", relate)

    # Called with older first, but newer supersedes older -> edge in=newer out=older
    await brain.relate_sources(
        "source:old", "source:new", "supersedes", 0.9, "b restates a", "ws:1"
    )

    args = relate.await_args.args
    assert args[0] == "rid:source:new"   # in (source): newer
    assert args[1] == "relates"
    assert args[2] == "rid:source:old"   # out (target): older
    assert relate.await_args.args[3]["type"] == "supersedes"
    assert relate.await_args.args[3]["workspace"] == "ws:1"


@pytest.mark.asyncio
async def test_non_supersedes_keeps_argument_order(monkeypatch):
    monkeypatch.setattr(brain, "ensure_record_id", lambda v: f"rid:{v}")
    monkeypatch.setattr(brain, "repo_query", AsyncMock(return_value=[]))
    relate = AsyncMock(return_value=[{"id": "relates:2"}])
    monkeypatch.setattr(brain, "repo_relate", relate)

    await brain.relate_sources("source:a", "source:b", "agrees", 0.7, "aligned", "ws:1")

    args = relate.await_args.args
    assert args[0] == "rid:source:a"
    assert args[2] == "rid:source:b"


@pytest.mark.asyncio
async def test_existing_ordered_pair_is_updated_not_duplicated(monkeypatch):
    monkeypatch.setattr(brain, "ensure_record_id", lambda v: f"rid:{v}")
    query = AsyncMock(return_value=[{"id": "relates:existing"}])
    monkeypatch.setattr(brain, "repo_query", query)
    relate = AsyncMock()
    monkeypatch.setattr(brain, "repo_relate", relate)

    result = await brain.relate_sources(
        "source:a", "source:b", "complements", 0.5, "adds detail", "ws:1"
    )

    relate.assert_not_awaited()          # no new edge created
    assert result == {"id": "relates:existing", "updated": True}
    # second query call is the UPDATE
    update_sql = query.await_args_list[-1].args[0]
    assert "UPDATE" in update_sql


@pytest.mark.asyncio
async def test_get_source_relationships_scopes_by_workspace(monkeypatch):
    rows = [
        {
            "source": "source:a",
            "target": "source:b",
            "type": "agrees",
            "confidence": 0.8,
            "rationale": "aligned",
        }
    ]
    query = AsyncMock(return_value=rows)
    monkeypatch.setattr(brain, "repo_query", query)

    out = await brain.get_source_relationships("ws:1")

    sql, params = query.await_args.args
    assert "FROM relates WHERE workspace = $workspace" in sql
    assert params == {"workspace": "ws:1"}
    assert out == [
        {
            "source": "source:a",
            "target": "source:b",
            "type": "agrees",
            "confidence": 0.8,
            "rationale": "aligned",
        }
    ]
