import pytest

from open_notebook.domain.governance import (
    ASSIGNEE_KINDS,
    CLAIM_TYPES,
    DECISION_RULE_STATUSES,
    PROPOSAL_STATUSES,
    TRACE_OUTCOMES,
    WORK_PACKAGE_STATUSES,
    Belief,
    Decision,
    Proposal,
    Rule,
    Trace,
    WorkPackage,
)


def test_proposal_defaults():
    p = Proposal(author="user:1", title="SMB focus")
    assert p.status == "pending"
    assert p.kind == "belief"
    assert p.visibility == "company"
    assert p.claim_type in CLAIM_TYPES


def test_proposal_rejects_bad_status():
    with pytest.raises(Exception):
        Proposal(author="user:1", title="x", status="banana")


def test_belief_defaults_current():
    b = Belief(title="SMB focus")
    assert b.status == "current"


def test_enum_constants():
    assert "pending" in PROPOSAL_STATUSES and "accepted" in PROPOSAL_STATUSES
    assert "inference" in CLAIM_TYPES and "fact" in CLAIM_TYPES


def test_decision_defaults():
    d = Decision(title="Ship SMB pricing")
    assert d.status == "active"
    assert d.rationale == ""


def test_decision_rejects_bad_status():
    with pytest.raises(Exception):
        Decision(title="x", status="banana")


def test_rule_defaults():
    r = Rule(title="Always cite two sources", statement="Every Company Belief needs >=2 sources.")
    assert r.status == "active"


def test_decision_rule_status_constant():
    assert "active" in DECISION_RULE_STATUSES and "superseded" in DECISION_RULE_STATUSES


def test_work_package_defaults():
    wp = WorkPackage(title="Draft SMB outreach plan")
    assert wp.assignee_kind == "human"
    assert wp.status == "open"
    assert wp.agent_brief is None


def test_work_package_rejects_bad_assignee_kind():
    with pytest.raises(Exception):
        WorkPackage(title="x", assignee_kind="robot")


def test_work_package_rejects_bad_status():
    with pytest.raises(Exception):
        WorkPackage(title="x", status="paused")


def test_work_package_accepts_agent_brief_dict():
    wp = WorkPackage(
        title="Summarize Q3 churn",
        assignee_kind="agent",
        assignee="research-agent",
        agent_brief={
            "objective": "Summarize churn drivers",
            "allowed_context": ["belief:1", "source:9"],
            "budget": "30 min",
            "approval_gate": True,
        },
    )
    assert wp.agent_brief["objective"] == "Summarize churn drivers"


def test_work_package_status_and_assignee_kind_constants():
    assert WORK_PACKAGE_STATUSES == ["open", "running", "done"]
    assert ASSIGNEE_KINDS == ["human", "agent"]


def test_trace_defaults():
    tr = Trace(work_package="work_package:1", summary="Ran the SMB outreach playbook")
    assert tr.outcome == "pending"
    assert tr.sources_used == []


def test_trace_rejects_bad_outcome():
    with pytest.raises(Exception):
        Trace(work_package="work_package:1", summary="x", outcome="banana")


def test_trace_outcomes_constant():
    assert set(TRACE_OUTCOMES) == {"pending", "success", "fail", "mixed"}
