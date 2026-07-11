from typing import Any, ClassVar, Dict, Optional

from pydantic import Field, field_validator

from open_notebook.database.repository import ensure_record_id
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

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("author") is not None:
            data["author"] = ensure_record_id(data["author"])
        return data


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

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("actor") is not None:
            data["actor"] = ensure_record_id(data["actor"])
        if data.get("object") is not None:
            data["object"] = ensure_record_id(data["object"])
        return data


DECISION_RULE_STATUSES = ["active", "superseded"]


class Decision(ObjectModel):
    table_name: ClassVar[str] = "decision"
    title: str
    rationale: str = ""
    status: str = "active"

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in DECISION_RULE_STATUSES:
            raise ValueError(f"invalid status {v}")
        return v


class Rule(ObjectModel):
    table_name: ClassVar[str] = "rule"
    title: str
    statement: str
    status: str = "active"

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in DECISION_RULE_STATUSES:
            raise ValueError(f"invalid status {v}")
        return v
