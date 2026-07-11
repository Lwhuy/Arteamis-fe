import pytest
from pydantic import ValidationError

from api.models import SourceCreate, SourceListResponse, SourceResponse, SourceUpdate


def test_source_create_scope_optional_and_unset_by_default():
    assert SourceCreate(type="text", content="x").scope is None


def test_source_create_accepts_all_three_scopes():
    for scope in ("personal", "project", "company"):
        assert SourceCreate(type="text", content="x", scope=scope).scope == scope


def test_source_create_rejects_bad_scope():
    with pytest.raises(ValidationError):
        SourceCreate(type="text", content="x", scope="secret")


def test_source_update_scope_optional():
    assert SourceUpdate().scope is None
    assert SourceUpdate(scope="company").scope == "company"


def test_responses_carry_scope_and_owner():
    r = SourceResponse(
        id="source:1", title="t", topics=[], asset=None, full_text=None,
        embedded=False, embedded_chunks=0, created="c", updated="u",
        scope="personal", owner="user:u1",
    )
    assert r.scope == "personal" and r.owner == "user:u1"
    lr = SourceListResponse(
        id="source:1", title="t", topics=[], asset=None, embedded=False,
        embedded_chunks=0, insights_count=0, created="c", updated="u",
    )
    assert lr.scope == "project" and lr.owner is None
