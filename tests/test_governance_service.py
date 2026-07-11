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
    create_decision,
    create_learning_proposal,
    create_proposal,
    create_rule,
    create_work_package,
    get_belief_lineage,
    get_decision,
    get_proposal,
    get_rule,
    get_trace,
    get_work_package,
    list_decisions,
    list_proposals,
    list_rules,
    list_traces_for_work_package,
    list_work_packages,
    record_trace,
    request_changes,
    update_work_package_status,
)
from open_notebook.domain.governance import (
    Belief,
    Decision,
    Proposal,
    Rule,
    Trace,
    WorkPackage,
)

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
        [],  # updates edge (this belief was not itself produced by learning)
    ]

    lineage = await get_belief_lineage("belief:1")

    assert isinstance(lineage["belief"], Belief)
    assert any(s["id"] == "source:1" for s in lineage["sources"])
    assert any(e["action"] == "proposal.accepted" for e in lineage["provenance"])
    assert lineage["derived_work"] == []
    assert lineage["contradictions"] == []
    assert lineage["updated_from"] is None


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_decision_saves_active_links_beliefs_and_audits(
    mock_create, mock_relate
):
    mock_create.side_effect = [
        [{"id": "decision:1", "status": "active"}],  # decision.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    decision = await create_decision(
        "user:1",
        title="Ship SMB pricing",
        rationale="Belief-backed: SMBs convert faster on tiered pricing",
        belief_ids=["belief:1", "belief:2"],
    )

    assert isinstance(decision, Decision)
    assert decision.status == "active"
    assert decision.id == "decision:1"
    mock_relate.assert_any_await("decision:1", "supports", "belief:1", {})
    mock_relate.assert_any_await("decision:1", "supports", "belief:2", {})

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "decision.created"
    assert audit_data["meta"] == {"belief_ids": ["belief:1", "belief:2"]}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_list_decisions_filters_by_status_in_python(mock_query):
    mock_query.return_value = [
        {"id": "decision:1", "title": "a", "status": "active"},
        {"id": "decision:2", "title": "b", "status": "superseded"},
    ]
    result = await list_decisions(status="active")
    assert len(result) == 1
    assert result[0].id == "decision:1"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_decision_returns_decision(mock_query):
    mock_query.return_value = [{"id": "decision:1", "title": "a", "status": "active"}]
    decision = await get_decision("decision:1")
    assert isinstance(decision, Decision)
    assert decision.title == "a"


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_rule_saves_active_links_beliefs_and_audits(
    mock_create, mock_relate
):
    mock_create.side_effect = [
        [{"id": "rule:1", "status": "active"}],  # rule.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    rule = await create_rule(
        "user:1",
        title="Always cite two sources",
        statement="Every Company Belief needs at least two independent sources.",
        belief_ids=["belief:3"],
    )

    assert isinstance(rule, Rule)
    assert rule.status == "active"
    assert rule.id == "rule:1"
    mock_relate.assert_awaited_once_with("rule:1", "supports", "belief:3", {})

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "rule.created"
    assert audit_data["meta"] == {"belief_ids": ["belief:3"]}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_list_rules_filters_by_status_in_python(mock_query):
    mock_query.return_value = [
        {"id": "rule:1", "title": "a", "statement": "s1", "status": "active"},
        {"id": "rule:2", "title": "b", "statement": "s2", "status": "superseded"},
    ]
    result = await list_rules(status="active")
    assert len(result) == 1
    assert result[0].id == "rule:1"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_rule_returns_rule(mock_query):
    mock_query.return_value = [
        {"id": "rule:1", "title": "a", "statement": "s1", "status": "active"}
    ]
    rule = await get_rule("rule:1")
    assert isinstance(rule, Rule)
    assert rule.title == "a"


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_work_package_saves_open_links_targets_and_audits(
    mock_create, mock_relate
):
    mock_create.side_effect = [
        [{"id": "work_package:1", "status": "open"}],  # work_package.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]
    work_package = await create_work_package(
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

    assert work_package.status == "open"
    assert work_package.id == "work_package:1"
    mock_relate.assert_awaited_once_with(
        "work_package:1", "executes", "belief:1", {}
    )
    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "work_package.created"
    assert audit_data["object"] == RecordID.parse("work_package:1")


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_list_work_packages_filters_by_status_in_python(mock_query):
    mock_query.return_value = [
        {"id": "work_package:1", "title": "a", "status": "open"},
        {"id": "work_package:2", "title": "b", "status": "done"},
    ]
    result = await list_work_packages(status="done")
    assert len(result) == 1
    assert result[0].id == "work_package:2"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_work_package_returns_work_package(mock_query):
    mock_query.return_value = [
        {"id": "work_package:1", "title": "a", "status": "open"}
    ]
    work_package = await get_work_package("work_package:1")
    assert isinstance(work_package, WorkPackage)
    assert work_package.title == "a"


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_update", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_update_work_package_status_transitions_and_audits(
    mock_query, mock_update, mock_create
):
    mock_query.return_value = [
        {"id": "work_package:1", "title": "a", "status": "open"}
    ]
    mock_update.return_value = [{"id": "work_package:1", "status": "running"}]
    mock_create.return_value = [{"id": "audit_event:1"}]

    work_package = await update_work_package_status(
        "user:1", "work_package:1", "running"
    )

    assert work_package.status == "running"
    audit_data = mock_create.await_args.args[1]
    assert audit_data["action"] == "work_package.status_changed"
    assert audit_data["meta"] == {"from": "open", "to": "running"}


@pytest.mark.asyncio
async def test_update_work_package_status_rejects_invalid_status():
    with pytest.raises(ValueError):
        await update_work_package_status("user:1", "work_package:1", "paused")


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_record_trace_saves_relates_and_audits(mock_create, mock_relate):
    mock_create.side_effect = [
        [{"id": "trace:1", "work_package": "work_package:1", "summary": "Ran playbook", "outcome": "success"}],  # trace.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    trace = await record_trace(
        "user:1", "work_package:1",
        summary="Ran playbook", sources_used=["source:1"], outcome="success",
    )

    assert trace.id == "trace:1"
    assert trace.outcome == "success"
    mock_relate.assert_awaited_once_with("work_package:1", "traced_by", "trace:1", {})

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "trace.recorded"
    assert audit_data["meta"] == {"work_package": "work_package:1", "outcome": "success"}


@pytest.mark.asyncio
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_trace_returns_trace(mock_query):
    mock_query.return_value = [
        {"id": "trace:1", "work_package": "work_package:1", "summary": "x", "outcome": "pending"}
    ]
    trace = await get_trace("trace:1")
    assert isinstance(trace, Trace)
    assert trace.id == "trace:1"


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
async def test_list_traces_for_work_package_returns_edge_rows(mock_query):
    mock_query.return_value = [
        {"id": "trace:1", "summary": "Ran playbook", "outcome": "success", "created": "2026-07-12T00:00:00Z"}
    ]
    rows = await list_traces_for_work_package("work_package:1")
    assert rows[0]["id"] == "trace:1"
    mock_query.assert_awaited_once()


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
async def test_create_learning_proposal_links_trace_and_belief(mock_create, mock_relate):
    mock_create.side_effect = [
        [{"id": "proposal:9", "kind": "learning", "status": "pending", "title": "Outcome: SMB outreach worked"}],  # proposal.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]

    proposal = await create_learning_proposal(
        "user:1", "trace:1",
        title="Outcome: SMB outreach worked",
        body="Response rate was 3x higher for SMBs",
        belief_id="belief:1",
    )

    assert proposal.kind == "learning"
    assert proposal.status == "pending"
    mock_relate.assert_awaited_once_with(
        "proposal:9", "learned_from", "trace:1", {"belief": "belief:1"}
    )
    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "learning.proposed"
    assert audit_data["meta"] == {"trace": "trace:1", "belief": "belief:1"}


@pytest.mark.asyncio
@patch("api.governance_service.repo_relate", new_callable=AsyncMock)
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_update", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_create", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_accept_learning_proposal_updates_belief_and_supersedes_original(
    mock_base_query, mock_create, mock_update, mock_gov_query, mock_relate
):
    # open_notebook.domain.base.repo_query backs Proposal.get / Trace.get / Belief.get,
    # called in that order by _accept_learning_proposal.
    mock_base_query.side_effect = [
        [{"id": "proposal:9", "author": "user:1", "kind": "learning", "title": "Outcome",
          "body": "SMB response rate was 3x higher", "status": "pending"}],  # Proposal.get
        [{"id": "trace:1", "work_package": "work_package:1", "summary": "Ran playbook", "outcome": "success"}],  # Trace.get
        [{"id": "belief:1", "title": "SMB focus Q3", "body": "...", "claim_type": "inference",
          "confidence": 0.6, "status": "current"}],  # Belief.get (original)
    ]
    # api.governance_service.repo_query backs the learned_from edge lookup, then the
    # original belief's derived_from sources being copied forward.
    mock_gov_query.side_effect = [
        [{"trace": "trace:1", "belief": "belief:1"}],
        [{"source": "source:1", "locator": "p.4"}],
    ]
    mock_create.side_effect = [
        [{"id": "belief:2", "status": "current"}],  # updated_belief.save()
        [{"id": "audit_event:1"}],  # AuditEvent().save()
    ]
    mock_update.side_effect = [
        [{"id": "belief:1", "status": "superseded"}],  # original.save()
        [{"id": "proposal:9", "status": "accepted"}],  # proposal.save()
    ]

    result = await accept_proposal("user:1", "proposal:9")

    assert result["belief"].id == "belief:2"
    assert result["belief"].confidence == pytest.approx(0.75)  # 0.6 + 0.15 for a 'success' outcome
    assert result["proposal"].status == "accepted"

    mock_relate.assert_any_await("belief:2", "updates", "belief:1", {"trace": "trace:1"})
    mock_relate.assert_any_await("belief:2", "derived_from", "source:1", {"locator": "p.4"})

    supersede_call = mock_update.await_args_list[0]
    assert supersede_call.args[0] == "belief"
    assert supersede_call.args[1] == "belief:1"
    assert supersede_call.args[2]["status"] == "superseded"

    audit_data = mock_create.await_args_list[1].args[1]
    assert audit_data["action"] == "proposal.accepted"
    assert audit_data["meta"] == {
        "kind": "learning", "belief": "belief:2", "superseded": "belief:1", "trace": "trace:1",
    }


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_accept_learning_proposal_without_belief_link_raises(mock_base_query, mock_gov_query):
    mock_base_query.return_value = [
        {"id": "proposal:9", "author": "user:1", "kind": "learning", "title": "Outcome", "status": "pending"}
    ]
    mock_gov_query.return_value = []  # no learned_from edge found

    with pytest.raises(ValueError):
        await accept_proposal("user:1", "proposal:9")


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_belief_lineage_includes_updated_from_when_present(mock_base_query, mock_gov_query):
    mock_base_query.return_value = [{"id": "belief:2", "title": "SMB focus Q3", "status": "current"}]
    mock_gov_query.side_effect = [
        [],  # sources
        [],  # provenance
        [{"belief": "belief:1", "trace": "trace:1"}],  # updates edge (this belief updates belief:1)
    ]
    lineage = await get_belief_lineage("belief:2")
    assert lineage["updated_from"] == {"belief": "belief:1", "trace": "trace:1"}


@pytest.mark.asyncio
@patch("api.governance_service.repo_query", new_callable=AsyncMock)
@patch("open_notebook.domain.base.repo_query", new_callable=AsyncMock)
async def test_get_belief_lineage_updated_from_none_when_absent(mock_base_query, mock_gov_query):
    mock_base_query.return_value = [{"id": "belief:1", "title": "SMB focus Q3", "status": "current"}]
    mock_gov_query.side_effect = [[], [], []]
    lineage = await get_belief_lineage("belief:1")
    assert lineage["updated_from"] is None
