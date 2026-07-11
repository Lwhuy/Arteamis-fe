"""Unit tests for Workspace / Membership domain models (DB-free)."""

from surrealdb import RecordID

from open_notebook.domain.base import ObjectModel
from open_notebook.domain.workspace import Membership, Workspace


def test_workspace_fields_and_table_name():
    w = Workspace(name="Acme Inc", slug="acme-inc", kind="company", owner="user:abc")
    assert w.table_name == "workspace"
    assert w.name == "Acme Inc"
    assert w.slug == "acme-inc"
    assert w.kind == "company"
    assert w.owner == "user:abc"


def test_personal_workspace_kind():
    w = Workspace(name="Personal", slug="personal-abc", kind="personal", owner="user:abc")
    assert w.kind == "personal"


def test_membership_defaults_active():
    m = Membership(user="user:abc", workspace="workspace:xyz", role="owner")
    assert m.table_name == "membership"
    assert m.status == "active"
    assert m.role == "owner"


def test_workspace_prepare_save_converts_owner_to_record_id():
    data = Workspace(
        name="Acme", slug="acme", kind="company", owner="user:abc"
    )._prepare_save_data()
    assert isinstance(data["owner"], RecordID)
    assert str(data["owner"]) == "user:abc"


def test_membership_prepare_save_converts_links_to_record_id():
    data = Membership(
        user="user:abc", workspace="workspace:xyz", role="member"
    )._prepare_save_data()
    assert isinstance(data["user"], RecordID)
    assert isinstance(data["workspace"], RecordID)
    assert str(data["user"]) == "user:abc"
    assert str(data["workspace"]) == "workspace:xyz"


def test_polymorphic_resolution_registers_subclasses():
    # ObjectModel.get() resolves by table_name prefix; importing workspace.py must
    # register both subclasses so get("workspace:...") / get("membership:...") work.
    assert ObjectModel._get_class_by_table_name("workspace") is Workspace
    assert ObjectModel._get_class_by_table_name("membership") is Membership
