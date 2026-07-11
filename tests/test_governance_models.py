import pytest

from open_notebook.domain.governance import (
    CLAIM_TYPES,
    DECISION_RULE_STATUSES,
    PROPOSAL_STATUSES,
    Belief,
    Decision,
    Proposal,
    Rule,
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
