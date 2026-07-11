"""Governance service — Promotion Bridge (P8.2).

A `proposal` is a drafted claim tied to one or more evidentiary source spans
(`derived_from` edges). Accepting a proposal promotes it into a `belief`: the
belief inherits the proposal's provenance edges, a `promotes_to` edge links
proposal->belief, and every state transition is recorded as an `audit_event`
so lineage can be reconstructed later.

Per open_notebook/AGENTS.md ("routes -> services -> models"), fetch/list of
governance domain objects goes through the ObjectModel classmethods
(`Proposal.get`, `Belief.get`, `Proposal.get_all`) rather than hand-written
`SELECT` statements. `repo_query` is used here ONLY for graph-edge reads
(`derived_from` / `audit_event`) that have no domain-model equivalent, and
`repo_relate` is used to create those edges — the same pattern as
`Source.add_to_notebook`'s `RELATE source->reference->notebook`.
"""

from typing import Any, Optional

from open_notebook.database.repository import repo_query, repo_relate
from open_notebook.domain.governance import (
    WORK_PACKAGE_STATUSES,
    AuditEvent,
    Belief,
    Decision,
    Proposal,
    Rule,
    WorkPackage,
)


async def _audit(
    actor: str, action: str, obj: Optional[str], meta: Optional[dict[str, Any]] = None
) -> AuditEvent:
    event = AuditEvent(actor=actor, action=action, object=obj, meta=meta or {})
    await event.save()
    return event


async def create_proposal(
    actor: str,
    *,
    kind: str,
    title: str,
    body: str,
    claim_type: str,
    confidence: float,
    source_spans: list[dict[str, Any]],
) -> Proposal:
    """Draft a new proposal and link it to its evidentiary source spans."""
    proposal = Proposal(
        author=actor,
        kind=kind,
        title=title,
        body=body,
        claim_type=claim_type,
        confidence=confidence,
        status="pending",
    )
    await proposal.save()
    for span in source_spans:
        await repo_relate(
            proposal.id,
            "derived_from",
            span["source_id"],
            {"locator": span.get("locator")},
        )
    await _audit(actor, "proposal.created", proposal.id, {"kind": kind})
    return proposal


async def list_proposals(*, status: Optional[str] = None) -> list[Proposal]:
    """List proposals, optionally filtered by status.

    `Proposal.get_all()` only supports an ORDER BY clause (no WHERE), so the
    status filter is applied in Python rather than hand-writing a query.
    """
    proposals = await Proposal.get_all()
    if status is not None:
        proposals = [p for p in proposals if p.status == status]
    return proposals


async def get_proposal(proposal_id: str) -> Proposal:
    return await Proposal.get(proposal_id)


async def accept_proposal(actor: str, proposal_id: str) -> dict[str, Any]:
    """Promote a pending proposal into a belief.

    Creates the belief, links proposal->promotes_to->belief, copies every
    proposal->derived_from->source edge onto the belief, marks the proposal
    accepted, and writes an audit event.

    Raises:
        ValueError: if the proposal is not currently `pending`.
    """
    proposal = await Proposal.get(proposal_id)
    if proposal.status != "pending":
        raise ValueError(f"proposal {proposal_id} is {proposal.status}, not pending")

    belief = Belief(
        title=proposal.title,
        body=proposal.body,
        claim_type=proposal.claim_type,
        confidence=proposal.confidence,
        status="current",
    )
    await belief.save()

    await repo_relate(proposal.id, "promotes_to", belief.id, {})

    # Copy each proposal->derived_from->source edge onto the new belief so
    # lineage queries never need to hop through the proposal.
    edges = await repo_query(
        "SELECT out AS source, locator FROM derived_from WHERE in = $id",
        {"id": proposal.id},
    )
    for edge in edges:
        await repo_relate(
            belief.id,
            "derived_from",
            edge["source"],
            {"locator": edge.get("locator")},
        )

    proposal.status = "accepted"
    await proposal.save()
    await _audit(actor, "proposal.accepted", proposal.id, {"belief": belief.id})

    return {"proposal": proposal, "belief": belief}


async def request_changes(actor: str, proposal_id: str, note: str) -> Proposal:
    """Send a pending proposal back for revision.

    Raises:
        ValueError: if the proposal is not currently `pending`.
    """
    proposal = await Proposal.get(proposal_id)
    if proposal.status != "pending":
        raise ValueError(f"proposal {proposal_id} is {proposal.status}, not pending")
    proposal.status = "changes_requested"
    await proposal.save()
    await _audit(actor, "proposal.changes_requested", proposal.id, {"note": note})
    return proposal


async def get_belief_lineage(belief_id: str) -> dict[str, Any]:
    """Sources + provenance trail for a belief.

    `derived_work` and `contradictions` are reserved for later phases of the
    Promotion Bridge (belief-to-belief graph) and always come back empty.
    """
    belief = await Belief.get(belief_id)

    sources = await repo_query(
        "SELECT out.id AS id, out.title AS title, locator FROM derived_from "
        "WHERE in = $id",
        {"id": belief_id},
    )
    provenance = await repo_query(
        "SELECT action, actor, object, meta, created FROM audit_event "
        "WHERE object = $id OR meta.belief = $id ORDER BY created",
        {"id": belief_id},
    )

    return {
        "belief": belief,
        "sources": sources,
        "provenance": provenance,
        "derived_work": [],
        "contradictions": [],
    }


async def create_decision(
    actor: str,
    *,
    title: str,
    rationale: str,
    belief_ids: list[str],
) -> Decision:
    """Record a decision and link it to the accepted beliefs that justify it.

    Decisions are promotion-only: belief_ids must reference existing (already
    accepted) Belief records — this function never creates a belief.
    """
    decision = Decision(title=title, rationale=rationale, status="active")
    await decision.save()
    for belief_id in belief_ids:
        await repo_relate(decision.id, "supports", belief_id, {})
    await _audit(actor, "decision.created", decision.id, {"belief_ids": belief_ids})
    return decision


async def list_decisions(*, status: Optional[str] = None) -> list[Decision]:
    """List decisions, optionally filtered by status (filtered in Python,
    same reasoning as list_proposals: Decision.get_all() has no WHERE)."""
    decisions = await Decision.get_all()
    if status is not None:
        decisions = [d for d in decisions if d.status == status]
    return decisions


async def get_decision(decision_id: str) -> Decision:
    return await Decision.get(decision_id)


async def create_rule(
    actor: str,
    *,
    title: str,
    statement: str,
    belief_ids: list[str],
) -> Rule:
    """Record a rule and link it to the accepted beliefs that justify it."""
    rule = Rule(title=title, statement=statement, status="active")
    await rule.save()
    for belief_id in belief_ids:
        await repo_relate(rule.id, "supports", belief_id, {})
    await _audit(actor, "rule.created", rule.id, {"belief_ids": belief_ids})
    return rule


async def list_rules(*, status: Optional[str] = None) -> list[Rule]:
    rules = await Rule.get_all()
    if status is not None:
        rules = [r for r in rules if r.status == status]
    return rules


async def get_rule(rule_id: str) -> Rule:
    return await Rule.get(rule_id)


async def create_work_package(
    actor: str,
    *,
    title: str,
    assignee_kind: str,
    assignee: Optional[str],
    agent_brief: Optional[dict[str, Any]],
    executes_ids: list[str],
) -> WorkPackage:
    """Turn an accepted decision/belief into a governed unit of work.

    Links work_package->executes->{decision|belief} for every id in
    `executes_ids`. Agent execution itself is out of scope here — this only
    records the brief; nothing in this function runs an agent or submits a
    background command.
    """
    work_package = WorkPackage(
        title=title,
        assignee_kind=assignee_kind,
        assignee=assignee,
        agent_brief=agent_brief,
        status="open",
    )
    await work_package.save()
    for target_id in executes_ids:
        await repo_relate(work_package.id, "executes", target_id, {})
    await _audit(
        actor,
        "work_package.created",
        work_package.id,
        {"assignee_kind": assignee_kind, "executes": executes_ids},
    )
    return work_package


async def list_work_packages(*, status: Optional[str] = None) -> list[WorkPackage]:
    """List work packages, optionally filtered by status.

    `WorkPackage.get_all()` only supports an ORDER BY clause (no WHERE), so
    the status filter is applied in Python — matching `list_proposals`.
    """
    work_packages = await WorkPackage.get_all()
    if status is not None:
        work_packages = [w for w in work_packages if w.status == status]
    return work_packages


async def get_work_package(work_package_id: str) -> WorkPackage:
    return await WorkPackage.get(work_package_id)


async def update_work_package_status(
    actor: str, work_package_id: str, status: str
) -> WorkPackage:
    """Transition a work package's status, auditing the before/after.

    Raises:
        ValueError: if `status` is not one of WORK_PACKAGE_STATUSES.
    """
    if status not in WORK_PACKAGE_STATUSES:
        raise ValueError(f"invalid status {status}")
    work_package = await WorkPackage.get(work_package_id)
    previous_status = work_package.status
    work_package.status = status
    await work_package.save()
    await _audit(
        actor,
        "work_package.status_changed",
        work_package.id,
        {"from": previous_status, "to": status},
    )
    return work_package
