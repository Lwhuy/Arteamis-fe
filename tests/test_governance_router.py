"""API tests for /api/proposals + /api/beliefs (service layer mocked, no live DB)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token
from open_notebook.domain.governance import Belief, Proposal


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    # Function-scoped and auto-reverted so this test's JWT_SECRET never leaks
    # into other test modules (see tests/test_p2_workspaces_router.py for the
    # same pattern).
    monkeypatch.setenv("JWT_SECRET", "test-secret-p2-router")
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _auth(user_id: str = "user:1") -> dict:
    return {"Authorization": f"Bearer {create_identity_token(user_id)}"}


def _proposal(**overrides) -> Proposal:
    data = dict(
        id="proposal:1",
        author="user:1",
        kind="belief",
        title="SMB focus",
        body="...",
        claim_type="inference",
        confidence=0.6,
        status="pending",
    )
    data.update(overrides)
    return Proposal(**data)


def _belief(**overrides) -> Belief:
    data = dict(
        id="belief:1",
        title="SMB focus",
        body="...",
        status="current",
        claim_type="inference",
        confidence=0.6,
    )
    data.update(overrides)
    return Belief(**data)


@patch("api.routers.governance.create_proposal", new_callable=AsyncMock)
def test_create_proposal_returns_201(mock_create, client):
    mock_create.return_value = _proposal()

    resp = client.post(
        "/api/proposals",
        json={
            "kind": "belief",
            "title": "SMB focus",
            "body": "...",
            "claim_type": "inference",
            "confidence": 0.6,
            "source_spans": [{"source_id": "source:1", "locator": "p.4"}],
        },
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "proposal:1"
    mock_create.assert_awaited_once_with(
        "user:1",
        kind="belief",
        title="SMB focus",
        body="...",
        claim_type="inference",
        confidence=0.6,
        source_spans=[{"source_id": "source:1", "locator": "p.4"}],
    )


@patch("api.routers.governance.list_proposals", new_callable=AsyncMock)
def test_list_proposals_returns_mocked_list(mock_list, client):
    mock_list.return_value = [_proposal(), _proposal(id="proposal:2", status="pending")]

    resp = client.get("/api/proposals?status=pending", headers=_auth())

    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()]
    assert ids == ["proposal:1", "proposal:2"]
    mock_list.assert_awaited_once_with(status="pending")


@patch("api.routers.governance.accept_proposal", new_callable=AsyncMock)
def test_accept_proposal_returns_200_with_belief(mock_accept, client):
    mock_accept.return_value = {"proposal": _proposal(status="accepted"), "belief": _belief()}

    resp = client.post("/api/proposals/proposal:1/accept", headers=_auth())

    assert resp.status_code == 200
    body = resp.json()
    assert body["belief"]["id"] == "belief:1"
    assert body["proposal"]["status"] == "accepted"
    mock_accept.assert_awaited_once_with("user:1", "proposal:1")


@patch("api.routers.governance.accept_proposal", new_callable=AsyncMock)
def test_accept_proposal_not_pending_returns_409(mock_accept, client):
    mock_accept.side_effect = ValueError("proposal proposal:1 is accepted, not pending")

    resp = client.post("/api/proposals/proposal:1/accept", headers=_auth())

    assert resp.status_code == 409
    assert resp.json()["detail"] == "proposal proposal:1 is accepted, not pending"


def test_create_proposal_requires_auth(client):
    resp = client.post(
        "/api/proposals",
        json={"title": "SMB focus", "source_spans": []},
    )
    assert resp.status_code == 401


@patch("api.routers.governance.get_belief_lineage", new_callable=AsyncMock)
def test_belief_lineage_returns_200_with_lineage_shape(mock_lineage, client):
    mock_lineage.return_value = {
        "belief": _belief(),
        "sources": [{"id": "source:1", "title": "Doc", "locator": "p.4"}],
        "provenance": [],
        "derived_work": [],
        "contradictions": [],
    }

    resp = client.get("/api/beliefs/belief:1", headers=_auth())

    assert resp.status_code == 200
    body = resp.json()
    assert body["belief"]["id"] == "belief:1"
    assert len(body["sources"]) == 1
    assert body["derived_work"] == []
    assert body["contradictions"] == []
    mock_lineage.assert_awaited_once_with("belief:1")
