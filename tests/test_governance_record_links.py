from surrealdb import RecordID

from open_notebook.domain.governance import AuditEvent, Decision, Proposal, Rule, WorkPackage


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


def test_decision_and_rule_have_no_direct_record_link_fields():
    """Decision/Rule link to beliefs only via the `supports` edge (created
    through repo_relate, which converts ids to RecordID itself) — neither
    model has a `record<>`-typed field of its own, so unlike Proposal.author
    or AuditEvent.actor/object, no _prepare_save_data() override is needed.
    This pins that invariant: if a future field like `decided_by:
    record<user>` is ever added to Decision, model_dump() and
    _prepare_save_data() diverge and this test starts failing — the trigger
    to add the same ensure_record_id override Proposal/AuditEvent use (this
    exact omission was a Critical bug in P8.2).
    """
    d = Decision(title="x")
    assert d._prepare_save_data() == {
        k: v for k, v in d.model_dump().items() if v is not None
    }
    r = Rule(title="y", statement="z")
    assert r._prepare_save_data() == {
        k: v for k, v in r.model_dump().items() if v is not None
    }


def test_work_package_assignee_is_left_as_plain_string():
    """CRITICAL LESSON (was a Critical bug in P8.2): every record<> link
    field needs `_prepare_save_data` + `ensure_record_id`, or SurrealDB
    stores a bare string that graph traversal can't follow.
    `WorkPackage.assignee` is deliberately a plain string (not
    `record<user>` — a work package can be assigned to an "agent" that has
    no user record at all), so it must NOT be converted to a RecordID. This
    confirms the override was correctly *omitted*, not forgotten.
    """
    wp = WorkPackage(title="x", assignee_kind="human", assignee="user:1")
    data = wp._prepare_save_data()
    assert data["assignee"] == "user:1"
    assert not isinstance(data["assignee"], RecordID)
