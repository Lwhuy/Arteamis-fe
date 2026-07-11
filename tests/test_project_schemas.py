import pytest
from pydantic import ValidationError

from api.models import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    RecentlyViewedResponse,
)


def test_project_create_defaults():
    c = ProjectCreate(name="Acme")
    assert c.description == ""
    assert c.default_source_scope is None  # server defaults to "personal"


def test_project_create_rejects_bad_scope():
    with pytest.raises(ValidationError):
        ProjectCreate(name="Acme", default_source_scope="public")


def test_project_response_carries_governance():
    r = ProjectResponse(
        id="notebook:1", name="Acme", description="", archived=False,
        created="t", updated="t", source_count=0, note_count=0,
        workspace="workspace:a", owner="user:1", default_source_scope="personal",
        promoted_from=None,
    )
    assert r.workspace == "workspace:a" and r.default_source_scope == "personal"


def test_recently_viewed_accepts_project_type():
    RecentlyViewedResponse(type="project", id="notebook:1", title="Acme", last_viewed_at="t")


def test_project_update_all_optional():
    u = ProjectUpdate()
    assert u.name is None and u.archived is None and u.default_source_scope is None
