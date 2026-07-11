"""Unit tests for api/governance_service.py (repo layer mocked).

No live database: the repo layer (`repo_query`/`repo_relate`/`repo_create`/
`repo_update`) is patched with AsyncMock, following the pattern established in
tests/test_p2_workspace_service.py. Domain-model fetch/list (`Proposal.get`,
`Proposal.get_all`, `Belief.get`) goes through `open_notebook.domain.base`'s
repo_query/repo_create/repo_update; graph-edge reads/writes go through
api.governance_service's own repo_query/repo_relate imports.
"""

from unittest.mock import AsyncMock, patch

import pytest
from surrealdb import RecordID

from api.governance_service import (
    accept_proposal,
    create_proposal,
    get_belief_lineage,
    get_proposal,
    list_proposals,
    request_changes,
)
from open_notebook.domain.governance import Belief, Proposal

pytestmark = pytest.mark.asyncio


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_proposal_saves_pending_links_sources_and_audits(
    mock_create, mock_relate
):
    mock_create.side_effect = [
        [{"id": "proposal:1", "status": "pending"}],  # proposal.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]
    proposal = await create_proposal(
        "user:1",
        kind="belief",
        title="SMB focus Q3",
        body="...",
        claim_type="inference",
        confidence=0.6,
        source_spans=[{"source_id": "source:1", "locator": "p.4"}],
    )

    assert proposal.status == "pending"
    assert proposal.id == "proposal:1"
    mock_relate.assert_awaited_once_with(
        "proposal:1", "derived_from", "source:1", {"locator": "p.4"}
    )
    # Second repo_create call is the audit event.
    audit_kwargs_call = mock_create.await_args_list[1]
    audit_data = audit_kwargs_call.args[1]
    assert audit_data["action"] == "proposal.created"
    # object is a record<> link field, so AuditEvent._prepare_save_data()
    # converts it to a RecordID before it reaches repo_create.
    assert audit_data["object"] == RecordID.parse("proposal:1")


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_list_proposals_filters_by_status_in_python(mock_query):
    mock_query.return_value = [
        {"id": "proposal:1", "author": "user:1", "title": "a", "status": "pending"},
        {"id": "proposal:2", "author": "user:1", "title": "b", "status": "accepted"},
    ]
    result = await list_proposals(status="accepted")
    assert len(result) == 1
    assert result[0].id == "proposal:2"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_proposal_returns_proposal(mock_query):
    mock_query.return_value = [
        {"id": "proposal:1", "author": "user:1", "title": "a", "status": "pending"}
    ]
    proposal = await get_proposal("proposal:1")
    assert isinstance(proposal, Proposal)
    assert proposal.title == "a"


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_update", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_accept_proposal_makes_belief_copies_edges_and_audits(
    mock_base_query, mock_create, mock_update, mock_gov_query, mock_relate
):
    mock_base_query.return_value = [
        {
            "id": "proposal:1",
            "author": "user:1",
            "title": "SMB focus Q3",
            "body": "...",
            "claim_type": "inference",
            "confidence": 0.6,
            "status": "pending",
        }
    ]
    mock_create.side_effect = [
        [{"id": "belief:1", "status": "current"}],  # belief.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]
    mock_update.return_value = [{"id": "proposal:1", "status": "accepted"}]
    mock_gov_query.return_value = [{"source": "source:1", "locator": "p.4"}]

    result = await accept_proposal("user:1", "proposal:1")

    assert result["belief"].title == "SMB focus Q3"
    assert result["belief"].id == "belief:1"
    assert result["proposal"].status == "accepted"

    mock_relate.assert_any_await("proposal:1", "promotes_to", "belief:1", {})
    mock_relate.assert_any_await(
        "belief:1", "derived_from", "source:1", {"locator": "p.4"}
    )

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "proposal.accepted"
    assert audit_data["meta"] == {"belief": "belief:1"}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_accept_proposal_raises_when_not_pending(mock_query):
    mock_query.return_value = [
        {"id": "proposal:1", "author": "user:1", "title": "x", "status": "accepted"}
    ]
    with pytest.raises(ValueError):
        await accept_proposal("user:1", "proposal:1")


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_update", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_request_changes_sets_status_and_audits_with_note(
    mock_query, mock_update, mock_create
):
    mock_query.return_value = [
        {"id": "proposal:1", "author": "user:1", "title": "x", "status": "pending"}
    ]
    mock_update.return_value = [{"id": "proposal:1", "status": "changes_requested"}]
    mock_create.return_value = [{"id": "audit_event:1"}]

    proposal = await request_changes("user:1", "proposal:1", "needs a second source")

    assert proposal.status == "changes_requested"
    audit_data = mock_create.await_args.args[1]
    assert audit_data["action"] == "proposal.changes_requested"
    assert audit_data["meta"] == {"note": "needs a second source"}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_request_changes_raises_when_not_pending(mock_query):
    mock_query.return_value = [
        {
            "id": "proposal:1",
            "author": "user:1",
            "title": "x",
            "status": "changes_requested",
        }
    ]
    with pytest.raises(ValueError):
        await request_changes("user:1", "proposal:1", "note")


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_belief_lineage_returns_sources_and_provenance(
    mock_base_query, mock_gov_query
):
    mock_base_query.return_value = [
        {"id": "belief:1", "title": "SMB focus Q3", "status": "current"}
    ]
    mock_gov_query.side_effect = [
        [{"id": "source:1", "title": "Notes.pdf", "locator": "p.4"}],  # sources
        [
            {
                "action": "proposal.accepted",
                "actor": "user:1",
                "object": "proposal:1",
                "meta": {"belief": "belief:1"},
                "created": "2026-07-12T00:00:00Z",
            }
        ],  # provenance
    ]

    lineage = await get_belief_lineage("belief:1")

    assert isinstance(lineage["belief"], Belief)
    assert any(s["id"] == "source:1" for s in lineage["sources"])
    assert any(e["action"] == "proposal.accepted" for e in lineage["provenance"])
    assert lineage["derived_work"] == []
    assert lineage["contradictions"] == []
