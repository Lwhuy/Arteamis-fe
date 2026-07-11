"""API tests for /api/proposals + /api/beliefs (service layer mocked, no live DB)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.security import create_identity_token
from open_notebook.domain.governance import (
    Belief,
    Decision,
    Proposal,
    Rule,
    Trace,
    WorkPackage,
)


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


def _decision(**overrides) -> Decision:
    data = dict(
        id="decision:1",
        title="Ship SMB pricing",
        rationale="Belief-backed",
        status="active",
    )
    data.update(overrides)
    return Decision(**data)


def _rule(**overrides) -> Rule:
    data = dict(
        id="rule:1",
        title="Always cite two sources",
        statement="Every Company Belief needs at least two independent sources.",
        status="active",
    )
    data.update(overrides)
    return Rule(**data)


@patch("api.routers.governance.create_decision", new_callable=AsyncMock)
def test_create_decision_returns_201(mock_create, client):
    mock_create.return_value = _decision()

    resp = client.post(
        "/api/decisions",
        json={
            "title": "Ship SMB pricing",
            "rationale": "Belief-backed",
            "belief_ids": ["belief:1", "belief:2"],
        },
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "decision:1"
    mock_create.assert_awaited_once_with(
        "user:1",
        title="Ship SMB pricing",
        rationale="Belief-backed",
        belief_ids=["belief:1", "belief:2"],
    )


def test_create_decision_requires_auth(client):
    resp = client.post(
        "/api/decisions", json={"title": "x", "belief_ids": []}
    )
    assert resp.status_code == 401


@patch("api.routers.governance.list_decisions", new_callable=AsyncMock)
def test_list_decisions_returns_mocked_list(mock_list, client):
    mock_list.return_value = [_decision(), _decision(id="decision:2")]

    resp = client.get("/api/decisions?status=active", headers=_auth())

    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert ids == ["decision:1", "decision:2"]
    mock_list.assert_awaited_once_with(status="active")


@patch("api.routers.governance.get_decision", new_callable=AsyncMock)
def test_get_decision_returns_200(mock_get, client):
    mock_get.return_value = _decision()

    resp = client.get("/api/decisions/decision:1", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["title"] == "Ship SMB pricing"


@patch("api.routers.governance.create_rule", new_callable=AsyncMock)
def test_create_rule_returns_201(mock_create, client):
    mock_create.return_value = _rule()

    resp = client.post(
        "/api/rules",
        json={
            "title": "Always cite two sources",
            "statement": "Every Company Belief needs at least two independent sources.",
            "belief_ids": ["belief:3"],
        },
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "rule:1"
    mock_create.assert_awaited_once_with(
        "user:1",
        title="Always cite two sources",
        statement="Every Company Belief needs at least two independent sources.",
        belief_ids=["belief:3"],
    )


def test_create_rule_requires_auth(client):
    resp = client.post(
        "/api/rules", json={"title": "x", "statement": "y", "belief_ids": []}
    )
    assert resp.status_code == 401


@patch("api.routers.governance.list_rules", new_callable=AsyncMock)
def test_list_rules_returns_mocked_list(mock_list, client):
    mock_list.return_value = [_rule()]

    resp = client.get("/api/rules?status=active", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "rule:1"
    mock_list.assert_awaited_once_with(status="active")


@patch("api.routers.governance.get_rule", new_callable=AsyncMock)
def test_get_rule_returns_200(mock_get, client):
    mock_get.return_value = _rule()

    resp = client.get("/api/rules/rule:1", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["title"] == "Always cite two sources"


def _work_package(**overrides) -> WorkPackage:
    data = dict(
        id="work_package:1",
        title="Draft SMB outreach plan",
        assignee_kind="agent",
        assignee="research-agent",
        status="open",
        agent_brief={
            "objective": "Draft outreach plan",
            "allowed_context": ["belief:1"],
            "budget": "1 hr",
            "approval_gate": True,
        },
    )
    data.update(overrides)
    return WorkPackage(**data)


@patch("api.routers.governance.create_work_package", new_callable=AsyncMock)
def test_create_work_package_returns_201(mock_create, client):
    mock_create.return_value = _work_package()

    resp = client.post(
        "/api/work-packages",
        json={
            "title": "Draft SMB outreach plan",
            "assignee_kind": "agent",
            "assignee": "research-agent",
            "agent_brief": {
                "objective": "Draft outreach plan",
                "allowed_context": ["belief:1"],
                "budget": "1 hr",
                "approval_gate": True,
            },
            "executes_ids": ["belief:1"],
        },
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "work_package:1"
    mock_create.assert_awaited_once_with(
        "user:1",
        title="Draft SMB outreach plan",
        assignee_kind="agent",
        assignee="research-agent",
        agent_brief={
            "objective": "Draft outreach plan",
            "allowed_context": ["belief:1"],
            "budget": "1 hr",
            "approval_gate": True,
        },
        executes_ids=["belief:1"],
    )


@patch("api.routers.governance.list_work_packages", new_callable=AsyncMock)
def test_list_work_packages_returns_mocked_list(mock_list, client):
    mock_list.return_value = [
        _work_package(),
        _work_package(id="work_package:2", status="done"),
    ]

    resp = client.get("/api/work-packages?status=open", headers=_auth())

    assert resp.status_code == 200
    ids = [w["id"] for w in resp.json()]
    assert ids == ["work_package:1", "work_package:2"]
    mock_list.assert_awaited_once_with(status="open")


@patch("api.routers.governance.get_work_package", new_callable=AsyncMock)
def test_get_work_package_returns_200(mock_get, client):
    mock_get.return_value = _work_package()

    resp = client.get("/api/work-packages/work_package:1", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["id"] == "work_package:1"


@patch("api.routers.governance.update_work_package_status", new_callable=AsyncMock)
def test_update_work_package_status_returns_200(mock_update, client):
    mock_update.return_value = _work_package(status="running")

    resp = client.post(
        "/api/work-packages/work_package:1/status",
        json={"status": "running"},
        headers=_auth(),
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    mock_update.assert_awaited_once_with("user:1", "work_package:1", "running")


@patch("api.routers.governance.update_work_package_status", new_callable=AsyncMock)
def test_update_work_package_status_invalid_returns_409(mock_update, client):
    mock_update.side_effect = ValueError("invalid status paused")

    resp = client.post(
        "/api/work-packages/work_package:1/status",
        json={"status": "paused"},
        headers=_auth(),
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "invalid status paused"


def test_create_work_package_requires_auth(client):
    resp = client.post(
        "/api/work-packages",
        json={"title": "x", "executes_ids": []},
    )
    assert resp.status_code == 401


def _trace(**overrides) -> Trace:
    data = dict(
        id="trace:1",
        work_package="work_package:1",
        summary="Ran the SMB outreach playbook",
        sources_used=[],
        outcome="success",
    )
    data.update(overrides)
    return Trace(**data)


@patch("api.routers.governance.record_trace", new_callable=AsyncMock)
def test_record_trace_returns_201(mock_record, client):
    mock_record.return_value = _trace()

    resp = client.post(
        "/api/work-packages/work_package:1/trace",
        json={"summary": "Ran the SMB outreach playbook", "sources_used": ["source:1"], "outcome": "success"},
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "trace:1"
    mock_record.assert_awaited_once_with(
        "user:1", "work_package:1",
        summary="Ran the SMB outreach playbook", sources_used=["source:1"], outcome="success",
    )


@patch("api.routers.governance.list_traces_for_work_package", new_callable=AsyncMock)
def test_list_traces_endpoint_returns_mocked_list(mock_list, client):
    mock_list.return_value = [{"id": "trace:1", "summary": "Ran playbook", "outcome": "success"}]

    resp = client.get("/api/work-packages/work_package:1/traces", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "trace:1"
    mock_list.assert_awaited_once_with("work_package:1")


@patch("api.routers.governance.get_trace", new_callable=AsyncMock)
def test_get_trace_endpoint_returns_trace(mock_get, client):
    mock_get.return_value = _trace()

    resp = client.get("/api/traces/trace:1", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["id"] == "trace:1"


@patch("api.routers.governance.create_learning_proposal", new_callable=AsyncMock)
def test_create_learning_proposal_endpoint_returns_201(mock_create, client):
    mock_create.return_value = _proposal(id="proposal:9", kind="learning", title="Outcome: SMB outreach worked")

    resp = client.post(
        "/api/traces/trace:1/learning",
        json={"title": "Outcome: SMB outreach worked", "body": "3x response rate", "belief_id": "belief:1"},
        headers=_auth(),
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "learning"
    mock_create.assert_awaited_once_with(
        "user:1", "trace:1",
        title="Outcome: SMB outreach worked", body="3x response rate", belief_id="belief:1",
    )


def test_record_trace_requires_auth(client):
    resp = client.post(
        "/api/work-packages/work_package:1/trace",
        json={"summary": "x"},
    )
    assert resp.status_code == 401
