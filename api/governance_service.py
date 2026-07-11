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
from open_notebook.domain.governance import AuditEvent, Belief, Proposal


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
