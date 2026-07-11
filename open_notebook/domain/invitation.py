from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, Optional

from pydantic import field_validator

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel


class Invitation(ObjectModel):
    """A pending/accepted/revoked/expired invitation to a workspace or a project.

    Invitations only ever target a `kind="company"` workspace (enforced in
    `api/invitation_service.create_invitation`, not here — a personal workspace
    always has exactly one member, its owner, and can never be invited into).

    `role` overloads two meanings, decided by whether `project` is set:
    - workspace invite (`project is None`): `role` is the WORKSPACE role (admin|member).
    - project invite (`project` set):        `role` is the PROJECT role (admin|member).
    `owner` is never an invitable role (transfer-ownership is out of scope).
    """

    table_name: ClassVar[str] = "invitation"
    # Persist an explicit null project for workspace invites via _prepare_save_data.
    nullable_fields: ClassVar[set[str]] = {"project"}

    workspace: str  # "workspace:<id>"
    email: str
    role: str  # admin|member
    project: Optional[str] = None  # "notebook:<id>" (project) or None
    token_hash: str
    status: str = "pending"
    invited_by: str  # "user:<id>"
    expires_at: datetime

    @field_validator("expires_at", mode="before")
    @classmethod
    def _parse_expires_at(cls, value):
        # Mirror ObjectModel.parse_datetime for created/updated: SurrealDB / API
        # can hand back an ISO string; normalize to a datetime.
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    def _prepare_save_data(self) -> Dict[str, Any]:
        data = super()._prepare_save_data()
        if data.get("workspace") is not None:
            data["workspace"] = ensure_record_id(data["workspace"])
        if data.get("project") is not None:
            data["project"] = ensure_record_id(data["project"])
        if data.get("invited_by") is not None:
            data["invited_by"] = ensure_record_id(data["invited_by"])
        return data

    def is_expired(self) -> bool:
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp < datetime.now(timezone.utc)

    @classmethod
    async def get_by_token_hash(cls, token_hash: str) -> Optional["Invitation"]:
        result = await repo_query(
            "SELECT * FROM invitation WHERE token_hash = $h LIMIT 1",
            {"h": token_hash},
        )
        if not result:
            return None
        return cls(**result[0])
