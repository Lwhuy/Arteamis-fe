from unittest.mock import AsyncMock

import pytest

import open_notebook.domain.brain as brain
from open_notebook.domain.brain import Entity, normalize_entity_name


def test_normalize_entity_name_folds_case_and_whitespace():
    assert normalize_entity_name("  Machine   Learning ") == "machine learning"


@pytest.mark.asyncio
async def test_upsert_creates_new_entity_when_no_match(monkeypatch):
    calls = []

    async def fake_repo_query(query, vars=None):
        calls.append((query, vars or {}))
        if "SELECT * FROM entity" in query:
            return []  # no name match, no embedding match
        if query.strip().startswith("CREATE entity"):
            return [{
                "id": "entity:new1",
                "workspace": vars["workspace"],
                "kind": vars["kind"],
                "name": vars["name"],
                "normalized_name": vars["normalized"],
                "salience": 1.0,
            }]
        return []

    monkeypatch.setattr(brain, "repo_query", fake_repo_query)

    result = await brain.upsert_entity_dedup(
        workspace="workspace:ws1", kind="topic", name="Machine Learning"
    )
    assert isinstance(result, Entity)
    assert result.id == "entity:new1"
    assert result.normalized_name == "machine learning"
    # Every SELECT/CREATE is workspace-scoped.
    for query, vars in calls:
        assert "$workspace" in query
        assert str(vars.get("workspace")) == "workspace:ws1"


@pytest.mark.asyncio
async def test_upsert_dedups_by_normalized_name(monkeypatch):
    captured = {}

    async def fake_repo_query(query, vars=None):
        vars = vars or {}
        if "SELECT * FROM entity" in query and "normalized_name" in query:
            return [{"id": "entity:existing", "workspace": vars["workspace"],
                     "kind": "topic", "name": "Engineering",
                     "normalized_name": "engineering", "salience": 3.0}]
        if query.strip().startswith("UPDATE"):
            captured["update_id"] = str(vars["id"])
            return [{"id": "entity:existing", "workspace": "workspace:ws1",
                     "kind": "topic", "name": "Engineering",
                     "normalized_name": "engineering", "salience": 4.0}]
        raise AssertionError(f"CREATE should not run on a name match: {query}")

    monkeypatch.setattr(brain, "repo_query", fake_repo_query)
    result = await brain.upsert_entity_dedup(
        workspace="workspace:ws1", kind="topic", name="  engineering "
    )
    assert result.id == "entity:existing"
    assert result.salience == 4.0
    assert captured["update_id"] == "entity:existing"


@pytest.mark.asyncio
async def test_upsert_dedups_by_embedding_when_name_differs(monkeypatch):
    async def fake_repo_query(query, vars=None):
        vars = vars or {}
        if "SELECT * FROM entity" in query and "normalized_name" in query:
            return []  # no name match
        if "vector::similarity::cosine" in query and query.strip().startswith("SELECT"):
            assert vars["threshold"] == brain.ENTITY_DEDUP_SIMILARITY_THRESHOLD
            return [{"id": "entity:sim", "workspace": vars["workspace"], "kind": "topic",
                     "name": "ML", "normalized_name": "ml", "salience": 1.0,
                     "similarity": 0.97}]
        if query.strip().startswith("UPDATE"):
            return [{"id": "entity:sim", "workspace": "workspace:ws1", "kind": "topic",
                     "name": "ML", "normalized_name": "ml", "salience": 2.0}]
        raise AssertionError(f"CREATE should not run on an embedding match: {query}")

    monkeypatch.setattr(brain, "repo_query", fake_repo_query)
    result = await brain.upsert_entity_dedup(
        workspace="workspace:ws1", kind="topic", name="Machine Learning",
        embedding=[0.1, 0.2, 0.3],
    )
    assert result.id == "entity:sim"


@pytest.mark.asyncio
async def test_relate_mention_and_part_of_pass_workspace(monkeypatch):
    calls = []

    async def fake_repo_relate(source, relationship, target, data=None):
        calls.append((str(source), relationship, str(target), data or {}))
        return [{"id": f"{relationship}:1"}]

    monkeypatch.setattr(brain, "repo_relate", fake_repo_relate)

    await brain.relate_mention("source:s1", "entity:e1", "workspace:ws1", 0.8)
    await brain.relate_part_of("entity:topic", "entity:domain", "workspace:ws1")

    assert calls[0][1] == "mentions"
    assert calls[0][3]["confidence"] == 0.8
    assert str(calls[0][3]["workspace"]) == "workspace:ws1"
    assert calls[1][1] == "part_of"
    assert str(calls[1][3]["workspace"]) == "workspace:ws1"
