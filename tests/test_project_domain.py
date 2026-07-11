from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.notebook import Notebook, Project, ProjectMember


def test_project_keeps_notebook_table_name():
    assert Project.table_name == "notebook"


def test_notebook_is_backcompat_alias_for_project():
    assert Notebook is Project


def test_project_has_governance_fields_with_defaults():
    p = Project(name="Acme", description="", workspace="workspace:a", owner="user:1")
    assert p.workspace == "workspace:a"
    assert p.owner == "user:1"
    assert p.default_source_scope == "personal"
    assert p.promoted_from is None


def test_project_name_must_not_be_empty():
    from open_notebook.exceptions import InvalidInputError

    with pytest.raises(InvalidInputError):
        Project(name="   ", description="")


def test_prepare_save_data_coerces_record_links():
    from surrealdb import RecordID

    p = Project(
        name="Acme",
        description="",
        workspace="workspace:a",
        owner="user:1",
        promoted_from="notebook:old",
    )
    data = p._prepare_save_data()
    assert isinstance(data["workspace"], RecordID)
    assert isinstance(data["owner"], RecordID)
    assert isinstance(data["promoted_from"], RecordID)


def test_project_member_defaults():
    m = ProjectMember(project="notebook:1", user="user:1")
    assert m.table_name == "project_member"
    assert m.role == "member"
    assert m.status == "active"


@pytest.mark.asyncio
@patch("open_notebook.domain.notebook.repo_query", new_callable=AsyncMock)
async def test_project_member_get_for_project(mock_q):
    mock_q.return_value = [
        {"id": "project_member:1", "project": "notebook:1", "user": "user:1", "role": "admin", "status": "active"}
    ]
    rows = await ProjectMember.get_for_project("notebook:1")
    assert len(rows) == 1 and rows[0].role == "admin"
    assert "project_member" in mock_q.await_args_list[0].args[0]
    assert mock_q.await_args_list[0].args[1]["project"] is not None
