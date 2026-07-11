import pytest

from open_notebook.domain.governance import (
    CLAIM_TYPES,
    PROPOSAL_STATUSES,
    Belief,
    Proposal,
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
