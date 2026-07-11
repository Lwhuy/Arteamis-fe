from typing import Any, ClassVar, Optional

from pydantic import Field, field_validator

from open_notebook.domain.base import ObjectModel

CLAIM_TYPES = ["fact", "inference", "assumption", "recommendation", "preference"]
PROPOSAL_STATUSES = ["pending", "accepted", "changes_requested", "rejected"]
PROPOSAL_KINDS = ["belief", "decision", "rule", "learning"]


class Proposal(ObjectModel):
    table_name: ClassVar[str] = "proposal"
    author: str
    kind: str = "belief"
    title: str
    body: str = ""
    claim_type: str = "inference"
    confidence: float = 0.5
    status: str = "pending"
    visibility: str = "company"

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in PROPOSAL_STATUSES:
            raise ValueError(f"invalid status {v}")
        return v

    @field_validator("claim_type")
    @classmethod
    def _claim(cls, v: str) -> str:
        if v not in CLAIM_TYPES:
            raise ValueError(f"invalid claim_type {v}")
        return v


class Belief(ObjectModel):
    table_name: ClassVar[str] = "belief"
    title: str
    body: str = ""
    status: str = "current"
    claim_type: str = "inference"
    confidence: float = 0.5


class AuditEvent(ObjectModel):
    table_name: ClassVar[str] = "audit_event"
    actor: str
    action: str
    object: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)
