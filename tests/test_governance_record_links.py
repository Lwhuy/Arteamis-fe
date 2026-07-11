from surrealdb import RecordID

from open_notebook.domain.governance import AuditEvent, Proposal


def test_proposal_author_converted_to_record_id():
    p = Proposal(author="user:1", title="x")
    data = p._prepare_save_data()
    assert isinstance(data["author"], RecordID)
    assert not isinstance(data["author"], str)
    assert data["author"] == RecordID.parse("user:1")


def test_audit_event_actor_and_object_converted_to_record_id():
    e = AuditEvent(actor="user:1", action="x", object="proposal:1")
    data = e._prepare_save_data()
    assert isinstance(data["actor"], RecordID)
    assert not isinstance(data["actor"], str)
    assert isinstance(data["object"], RecordID)
    assert not isinstance(data["object"], str)
    assert data["actor"] == RecordID.parse("user:1")
    assert data["object"] == RecordID.parse("proposal:1")


def test_audit_event_object_none_is_left_none():
    e = AuditEvent(actor="user:1", action="x")
    data = e._prepare_save_data()
    assert isinstance(data["actor"], RecordID)
    assert data.get("object") is None
