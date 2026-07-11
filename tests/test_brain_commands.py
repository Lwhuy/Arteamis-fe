import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import commands.brain_commands as bc
from commands.brain_commands import ExtractSourceEntitiesInput


@pytest.mark.asyncio
async def test_extract_source_entities_upserts_relates_and_builds_hierarchy(monkeypatch):
    # 1. Fake source
    fake_source = SimpleNamespace(
        id="source:s1", title="Deep Learning Primer",
        full_text="A primer on neural networks by Ada Lovelace.",
    )
    monkeypatch.setattr(bc.Source, "get", AsyncMock(return_value=fake_source))

    # 2. Deterministic LLM: model.ainvoke returns JSON matching EntityExtraction
    payload = {
        "domain_path": "engineering.ai",
        "entities": [
            {"kind": "topic", "name": "neural networks", "description": "NN basics"},
            {"kind": "person", "name": "Ada Lovelace", "description": None},
        ],
    }
    fake_model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content=json.dumps(payload)))
    )
    monkeypatch.setattr(bc, "provision_langchain_model", AsyncMock(return_value=fake_model))

    # 3. Record domain-layer calls
    def entity(id_):
        return SimpleNamespace(id=id_)

    upsert = AsyncMock(side_effect=lambda workspace, kind, name, description=None, embedding=None: entity(f"entity:{kind}:{name}"))
    mention = AsyncMock(return_value=[{"id": "mentions:1"}])
    part_of = AsyncMock(return_value=[{"id": "part_of:1"}])
    monkeypatch.setattr(bc, "upsert_entity_dedup", upsert)
    monkeypatch.setattr(bc, "relate_mention", mention)
    monkeypatch.setattr(bc, "relate_part_of", part_of)

    result = await bc.extract_source_entities_command(
        ExtractSourceEntitiesInput(source_id="source:s1", workspace_id="workspace:ws1")
    )

    assert result.success is True
    assert result.entities_created == 2
    # domain entity + 2 extracted entities => 3 upserts
    assert upsert.await_count == 3
    # one mention per extracted entity
    assert mention.await_count == 2
    # the single topic is linked part_of the domain
    assert part_of.await_count == 1
    # every relate call carried the workspace id
    for call in mention.await_args_list:
        assert call.kwargs.get("workspace") == "workspace:ws1" or call.args[2] == "workspace:ws1"


@pytest.mark.asyncio
async def test_extract_source_entities_missing_text_raises_valueerror(monkeypatch):
    fake_source = SimpleNamespace(id="source:s1", title="Empty", full_text="")
    monkeypatch.setattr(bc.Source, "get", AsyncMock(return_value=fake_source))
    with pytest.raises(ValueError):
        await bc.extract_source_entities_command(
            ExtractSourceEntitiesInput(source_id="source:s1", workspace_id="workspace:ws1")
        )
