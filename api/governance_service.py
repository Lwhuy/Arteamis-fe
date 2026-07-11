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

from open_notebook.database.repository import ensure_record_id, repo_query, repo_relate
from open_notebook.domain.governance import (
    WORK_PACKAGE_STATUSES,
    AuditEvent,
    Belief,
    Decision,
    Proposal,
    Rule,
    Trace,
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
    """Promote or apply a pending proposal.

    `kind='belief'` proposals promote into a new belief (unchanged P8.2
    behavior). `kind='learning'` proposals apply a traced outcome onto the
    belief they reference, superseding it (P8.5).

    Raises:
        ValueError: if the proposal is not currently `pending`, or (for a
            learning proposal) if it has no linked belief to update.
    """
    proposal = await Proposal.get(proposal_id)
    if proposal.status != "pending":
        raise ValueError(f"proposal {proposal_id} is {proposal.status}, not pending")

    if proposal.kind == "learning":
        return await _accept_learning_proposal(actor, proposal)
    return await _accept_belief_proposal(actor, proposal)


async def _accept_belief_proposal(actor: str, proposal: Proposal) -> dict[str, Any]:
    """Promote a pending belief/decision/rule proposal into a belief.

    Creates the belief, links proposal->promotes_to->belief, copies every
    proposal->derived_from->source edge onto the belief, marks the proposal
    accepted, and writes an audit event.
    """
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
    # `in` is an edge endpoint (record-typed) — a plain string never matches
    # it on a real DB, so the bound id must be coerced to a RecordID.
    edges = await repo_query(
        "SELECT out AS source, locator FROM derived_from WHERE in = $id",
        {"id": ensure_record_id(proposal.id)},
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


async def _accept_learning_proposal(actor: str, proposal: Proposal) -> dict[str, Any]:
    """Apply a traced outcome onto the belief it references.

    Propose-only, per PRD 1.6A/4.5B: this is only ever reached through the
    same pending -> accept_proposal path every other proposal goes through
    (never a direct write). The new belief supersedes the original: same
    title, body rewritten to the learning proposal's content, confidence
    nudged by the trace outcome, and evidentiary sources copied forward so
    lineage never breaks.
    """
    # `in` is an edge endpoint (record-typed) — a plain string never matches
    # it on a real DB, so the bound id must be coerced to a RecordID.
    edges = await repo_query(
        "SELECT out AS trace, belief FROM learned_from WHERE in = $id",
        {"id": ensure_record_id(proposal.id)},
    )
    if not edges or not edges[0].get("belief"):
        raise ValueError(f"learning proposal {proposal.id} has no linked belief to update")

    trace_id = edges[0]["trace"]
    original_belief_id = edges[0]["belief"]

    trace = await Trace.get(trace_id)
    original = await Belief.get(original_belief_id)

    confidence = original.confidence
    if trace.outcome == "success":
        confidence = min(1.0, confidence + 0.15)
    elif trace.outcome == "fail":
        confidence = max(0.0, confidence - 0.15)

    updated_belief = Belief(
        title=original.title,
        body=proposal.body,
        claim_type=original.claim_type,
        confidence=confidence,
        status="current",
    )
    await updated_belief.save()
    # `updates.trace` is a strict `option<record<trace>>` field (migration 25).
    # repo_relate only ensure_record_id's source/target, NOT values inside
    # `data` — so the record id must be coerced here or SurrealDB rejects the
    # RELATE against the schema on a real database (masked by mocked tests).
    await repo_relate(
        updated_belief.id, "updates", original.id, {"trace": ensure_record_id(trace.id)}
    )

    # `in` is an edge endpoint (record-typed) — same coercion as above.
    source_edges = await repo_query(
        "SELECT out AS source, locator FROM derived_from WHERE in = $id",
        {"id": ensure_record_id(original.id)},
    )
    for edge in source_edges:
        await repo_relate(
            updated_belief.id, "derived_from", edge["source"], {"locator": edge.get("locator")}
        )

    original.status = "superseded"
    await original.save()

    proposal.status = "accepted"
    await proposal.save()
    await _audit(
        actor, "proposal.accepted", proposal.id,
        {"kind": "learning", "belief": updated_belief.id, "superseded": original.id, "trace": trace.id},
    )

    return {"proposal": proposal, "belief": updated_belief}


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
    `updated_from` is populated when this belief itself was produced by
    accepting a learning proposal (P8.5) -- it points at the trace and the
    prior belief this one superseded.
    """
    belief = await Belief.get(belief_id)

    # `in` is an edge endpoint (record-typed) — a plain string never matches
    # it on a real DB, so the bound id must be coerced to a RecordID.
    sources = await repo_query(
        "SELECT out.id AS id, out.title AS title, locator FROM derived_from "
        "WHERE in = $id",
        {"id": ensure_record_id(belief_id)},
    )
    # `object` is `option<record>` (migration 22) and AuditEvent._prepare_save_data
    # coerces it to a RecordID at write time, so the read side needs the same
    # coercion. `meta` is a FLEXIBLE `option<object>` (migration 22) whose
    # nested values are never coerced (see `_audit`, which stores plain
    # Python strings inside `meta`), so `meta.belief` must stay a plain
    # string — the same $id can't serve both comparisons.
    provenance = await repo_query(
        "SELECT action, actor, object, meta, created FROM audit_event "
        "WHERE object = $id OR meta.belief = $belief_id ORDER BY created",
        {"id": ensure_record_id(belief_id), "belief_id": belief_id},
    )
    # `in` is an edge endpoint (record-typed) — same coercion as above.
    updated_from_rows = await repo_query(
        "SELECT out AS belief, trace FROM updates WHERE in = $id",
        {"id": ensure_record_id(belief_id)},
    )
    updated_from = (
        {"belief": updated_from_rows[0]["belief"], "trace": updated_from_rows[0]["trace"]}
        if updated_from_rows
        else None
    )

    return {
        "belief": belief,
        "sources": sources,
        "provenance": provenance,
        "derived_work": [],
        "contradictions": [],
        "updated_from": updated_from,
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


async def record_trace(
    actor: str,
    work_package_id: str,
    *,
    summary: str,
    sources_used: Optional[list[str]] = None,
    outcome: str = "pending",
) -> Trace:
    """Record what actually happened when a work package was executed."""
    trace = Trace(
        work_package=work_package_id,
        summary=summary,
        sources_used=sources_used or [],
        outcome=outcome,
    )
    await trace.save()
    await repo_relate(work_package_id, "traced_by", trace.id, {})
    await _audit(
        actor, "trace.recorded", trace.id,
        {"work_package": work_package_id, "outcome": outcome},
    )
    return trace


async def get_trace(trace_id: str) -> Trace:
    return await Trace.get(trace_id)


async def list_traces_for_work_package(work_package_id: str) -> list[dict[str, Any]]:
    """Traces recorded for a work package, most recent first."""
    # `in` is an edge endpoint (record-typed) — a plain string never matches
    # it on a real DB, so the bound id must be coerced to a RecordID.
    return await repo_query(
        "SELECT out.id AS id, out.summary AS summary, out.outcome AS outcome, "
        "out.created AS created FROM traced_by WHERE in = $id ORDER BY out.created DESC",
        {"id": ensure_record_id(work_package_id)},
    )


async def _resolve_belief_id_from_trace(trace: Trace) -> str:
    """Resolve the belief a trace's real-world outcome should update.

    A trace always points at a work package (`trace.work_package`); that work
    package's `executes` edge points at whatever it was created to carry out
    (`create_work_package`) — a belief or a decision. If it points directly
    at a belief, that is the target. If it points at a decision, follow that
    decision's `supports` edge one hop further to the belief it was
    justified by (a work package created from a belief links directly; one
    created from a decision is one hop away).

    Raises:
        ValueError: if no belief can be resolved via either path.
    """
    executes_rows = await repo_query(
        "SELECT out FROM executes WHERE in = $wp",
        {"wp": ensure_record_id(trace.work_package)},
    )
    if not executes_rows:
        raise ValueError(
            f"cannot resolve belief for trace {trace.id}: work package "
            f"{trace.work_package} has no executes edge"
        )
    target_id = str(executes_rows[0]["out"])
    if target_id.startswith("belief:"):
        return target_id
    if target_id.startswith("decision:"):
        supports_rows = await repo_query(
            "SELECT out FROM supports WHERE in = $decision",
            {"decision": ensure_record_id(target_id)},
        )
        if not supports_rows:
            raise ValueError(
                f"cannot resolve belief for trace {trace.id}: decision "
                f"{target_id} has no supports edge to a belief"
            )
        return str(supports_rows[0]["out"])
    raise ValueError(
        f"cannot resolve belief for trace {trace.id}: executes target "
        f"{target_id} is neither a belief nor a decision"
    )


async def create_learning_proposal(
    actor: str,
    trace_id: str,
    *,
    title: str,
    body: str,
    belief_id: Optional[str] = None,
) -> Proposal:
    """Draft a propose-only learning update from a trace's real-world outcome.

    Learning NEVER writes to a belief directly (PRD §1.6A/§4.5B) — it always
    goes through the same pending -> accept/request-changes review as any
    other proposal. `belief_id` is the belief this outcome should update; it
    is carried on the `learned_from` edge so `accept_proposal` can find it
    without re-deriving it through the work_package -> decision/rule chain.

    `belief_id` is optional: when the caller doesn't supply one (the normal
    case — the frontend no longer resolves it client-side), it is derived
    server-side from the trace via `_resolve_belief_id_from_trace`.

    Raises:
        ValueError: if `belief_id` is omitted and no belief can be resolved
            from the trace.
    """
    resolved_belief_id = belief_id
    if not resolved_belief_id:
        trace = await Trace.get(trace_id)
        resolved_belief_id = await _resolve_belief_id_from_trace(trace)

    proposal = Proposal(author=actor, kind="learning", title=title, body=body, status="pending")
    await proposal.save()
    # `learned_from.belief` is a strict `option<record<belief>>` field
    # (migration 25). repo_relate only ensure_record_id's source/target, NOT
    # values inside `data` — so the record id must be coerced here or
    # SurrealDB rejects the RELATE against the schema on a real database
    # (masked by mocked tests).
    await repo_relate(
        proposal.id, "learned_from", trace_id, {"belief": ensure_record_id(resolved_belief_id)}
    )
    await _audit(
        actor, "learning.proposed", proposal.id,
        {"trace": trace_id, "belief": resolved_belief_id},
    )
    return proposal
