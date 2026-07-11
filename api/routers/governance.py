"""POST/GET /proposals + /beliefs — Promotion Bridge (P8.2) governance router.

Routers stay thin (per api/AGENTS.md); all business logic lives in
api/governance_service.py. Functions are imported directly (not via
`from api import governance_service as gs`) so tests can patch them at
`api.routers.governance.<name>` the same way tests/test_p2_workspaces_router.py
patches api.routers.workspaces.create_workspace.
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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

router = APIRouter()


class SourceSpan(BaseModel):
    source_id: str
    locator: Optional[str] = None


class CreateProposalBody(BaseModel):
    kind: str = "belief"
    title: str
    body: str = ""
    claim_type: str = "inference"
    confidence: float = 0.5
    source_spans: list[SourceSpan] = []


class ChangesBody(BaseModel):
    note: str = ""


class RecordTraceBody(BaseModel):
    summary: str
    sources_used: list[str] = []
    outcome: str = "pending"


class CreateLearningProposalBody(BaseModel):
    title: str
    body: str = ""
    belief_id: str


class CreateDecisionBody(BaseModel):
    title: str
    rationale: str = ""
    belief_ids: list[str] = []


class CreateRuleBody(BaseModel):
    title: str
    statement: str
    belief_ids: list[str] = []


def _actor(request: Request) -> str:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "auth required")
    return uid


@router.post("/proposals", status_code=201)
async def create_proposal_endpoint(body: CreateProposalBody, request: Request) -> dict[str, Any]:
    proposal = await create_proposal(
        _actor(request),
        kind=body.kind,
        title=body.title,
        body=body.body,
        claim_type=body.claim_type,
        confidence=body.confidence,
        source_spans=[s.model_dump() for s in body.source_spans],
    )
    return proposal.model_dump()


@router.get("/proposals")
async def list_proposals_endpoint(status: Optional[str] = None) -> list[dict[str, Any]]:
    proposals = await list_proposals(status=status)
    return [p.model_dump() for p in proposals]


@router.get("/proposals/{proposal_id}")
async def get_proposal_endpoint(proposal_id: str) -> dict[str, Any]:
    proposal = await get_proposal(proposal_id)
    return proposal.model_dump()


@router.post("/proposals/{proposal_id}/accept")
async def accept_proposal_endpoint(proposal_id: str, request: Request) -> dict[str, Any]:
    try:
        result = await accept_proposal(_actor(request), proposal_id)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {
        "proposal": result["proposal"].model_dump(),
        "belief": result["belief"].model_dump(),
    }


@router.post("/proposals/{proposal_id}/request-changes")
async def request_changes_endpoint(
    proposal_id: str, body: ChangesBody, request: Request
) -> dict[str, Any]:
    try:
        proposal = await request_changes(_actor(request), proposal_id, body.note)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return proposal.model_dump()


@router.get("/beliefs")
async def list_beliefs_endpoint() -> list[dict[str, Any]]:
    from open_notebook.database.repository import repo_query

    rows = await repo_query(
        "SELECT * FROM belief WHERE status = 'current' ORDER BY updated DESC", {}
    )
    return rows


@router.get("/beliefs/{belief_id}")
async def belief_lineage_endpoint(belief_id: str) -> dict[str, Any]:
    result = await get_belief_lineage(belief_id)
    return {**result, "belief": result["belief"].model_dump()}


@router.post("/work-packages/{work_package_id}/trace", status_code=201)
async def record_trace_endpoint(
    work_package_id: str, body: RecordTraceBody, request: Request
) -> dict[str, Any]:
    trace = await record_trace(
        _actor(request), work_package_id,
        summary=body.summary, sources_used=body.sources_used, outcome=body.outcome,
    )
    return trace.model_dump()


@router.get("/work-packages/{work_package_id}/traces")
async def list_traces_endpoint(work_package_id: str) -> list[dict[str, Any]]:
    return await list_traces_for_work_package(work_package_id)


@router.get("/traces/{trace_id}")
async def get_trace_endpoint(trace_id: str) -> dict[str, Any]:
    trace = await get_trace(trace_id)
    return trace.model_dump()


@router.post("/traces/{trace_id}/learning", status_code=201)
async def create_learning_proposal_endpoint(
    trace_id: str, body: CreateLearningProposalBody, request: Request
) -> dict[str, Any]:
    proposal = await create_learning_proposal(
        _actor(request), trace_id,
        title=body.title, body=body.body, belief_id=body.belief_id,
    )
    return proposal.model_dump()


@router.post("/decisions", status_code=201)
async def create_decision_endpoint(
    body: CreateDecisionBody, request: Request
) -> dict[str, Any]:
    decision = await create_decision(
        _actor(request),
        title=body.title,
        rationale=body.rationale,
        belief_ids=body.belief_ids,
    )
    return decision.model_dump()


@router.get("/decisions")
async def list_decisions_endpoint(status: Optional[str] = None) -> list[dict[str, Any]]:
    decisions = await list_decisions(status=status)
    return [d.model_dump() for d in decisions]


@router.get("/decisions/{decision_id}")
async def get_decision_endpoint(decision_id: str) -> dict[str, Any]:
    decision = await get_decision(decision_id)
    return decision.model_dump()


@router.post("/rules", status_code=201)
async def create_rule_endpoint(body: CreateRuleBody, request: Request) -> dict[str, Any]:
    rule = await create_rule(
        _actor(request),
        title=body.title,
        statement=body.statement,
        belief_ids=body.belief_ids,
    )
    return rule.model_dump()


@router.get("/rules")
async def list_rules_endpoint(status: Optional[str] = None) -> list[dict[str, Any]]:
    rules = await list_rules(status=status)
    return [r.model_dump() for r in rules]


@router.get("/rules/{rule_id}")
async def get_rule_endpoint(rule_id: str) -> dict[str, Any]:
    rule = await get_rule(rule_id)
    return rule.model_dump()


class AgentBriefBody(BaseModel):
    objective: str
    allowed_context: list[str] = []
    budget: Optional[str] = None
    approval_gate: bool = True


class CreateWorkPackageBody(BaseModel):
    title: str
    assignee_kind: str = "human"
    assignee: Optional[str] = None
    agent_brief: Optional[AgentBriefBody] = None
    executes_ids: list[str] = []


class UpdateWorkPackageStatusBody(BaseModel):
    status: str


@router.post("/work-packages", status_code=201)
async def create_work_package_endpoint(
    body: CreateWorkPackageBody, request: Request
) -> dict[str, Any]:
    work_package = await create_work_package(
        _actor(request),
        title=body.title,
        assignee_kind=body.assignee_kind,
        assignee=body.assignee,
        agent_brief=body.agent_brief.model_dump() if body.agent_brief else None,
        executes_ids=body.executes_ids,
    )
    return work_package.model_dump()


@router.get("/work-packages")
async def list_work_packages_endpoint(
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    work_packages = await list_work_packages(status=status)
    return [w.model_dump() for w in work_packages]


@router.get("/work-packages/{work_package_id}")
async def get_work_package_endpoint(work_package_id: str) -> dict[str, Any]:
    work_package = await get_work_package(work_package_id)
    return work_package.model_dump()


@router.post("/work-packages/{work_package_id}/status")
async def update_work_package_status_endpoint(
    work_package_id: str, body: UpdateWorkPackageStatusBody, request: Request
) -> dict[str, Any]:
    try:
        work_package = await update_work_package_status(
            _actor(request), work_package_id, body.status
        )
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return work_package.model_dump()
