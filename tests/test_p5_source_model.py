"""Source owner/scope/promoted_from fields + get_project_ids (P5, v2 3-scope)."""
from unittest.mock import AsyncMock, patch

import pytest
from surrealdb import RecordID

from open_notebook.domain.notebook import Source


def test_scope_defaults_to_project():
    s = Source(title="t")
    assert s.scope == "project"
    assert s.owner is None
    assert s.promoted_from is None


def test_scope_accepts_personal_and_company():
    assert Source(title="t", scope="personal").scope == "personal"
    assert Source(title="t", scope="company").scope == "company"


def test_owner_string_coerced_to_record_id():
    s = Source(title="t", owner="user:abc")
    assert isinstance(s.owner, RecordID)
    assert str(s.owner) == "user:abc"


def test_owner_none_passthrough():
    s = Source(title="t", owner=None)
    assert s.owner is None


def test_promoted_from_string_coerced_to_record_id():
    s = Source(title="t", promoted_from="source:old")
    assert isinstance(s.promoted_from, RecordID)
    assert str(s.promoted_from) == "source:old"


def test_prepare_save_data_coerces_owner_promoted_from_and_keeps_scope():
    s = Source(title="t", owner="user:abc", scope="company", promoted_from="source:old")
    data = s._prepare_save_data()
    assert isinstance(data["owner"], RecordID)
    assert isinstance(data["promoted_from"], RecordID)
    assert data["scope"] == "company"


@pytest.mark.asyncio
async def test_get_project_ids_queries_reference_edge():
    s = Source(title="t", id="source:1")
    with patch(
        "open_notebook.domain.notebook.repo_query",
        new=AsyncMock(return_value=[RecordID.parse("notebook:p1"), RecordID.parse("notebook:p2")]),
    ) as mock_q:
        ids = await s.get_project_ids()
    assert ids == ["notebook:p1", "notebook:p2"]
    query = mock_q.call_args.args[0]
    assert "reference" in query and "in = $id" in query
