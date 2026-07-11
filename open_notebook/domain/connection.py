"""Connection domain model — an OAuth connection to an external source provider.

Tokens are encrypted at rest with OPEN_NOTEBOOK_ENCRYPTION_KEY, mirroring the
Credential model's pattern. `workspace` is nullable now; the P2/P5/P6
multitenancy work sets it later.
"""
from datetime import datetime
from typing import ClassVar, List, Optional

from pydantic import SecretStr

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.base import ObjectModel
from open_notebook.utils.encryption import decrypt_value, encrypt_value


class Connection(ObjectModel):
    table_name: ClassVar[str] = "connection"
    nullable_fields: ClassVar[set[str]] = {
        "access_token",
        "refresh_token",
        "token_expires_at",
        "workspace",
    }

    provider: str
    account_label: str
    access_token: Optional[SecretStr] = None
    refresh_token: Optional[SecretStr] = None
    token_expires_at: Optional[datetime] = None
    scopes: List[str] = []
    status: str = "connected"
    workspace: Optional[str] = None  # record<workspace>, set by later multitenancy work

    def _encrypt_secret(self, value: Optional[SecretStr]) -> Optional[str]:
        if not value:
            return None
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        return encrypt_value(raw)

    def _prepare_save_data(self) -> dict:
        data = {}
        for key, value in self.model_dump().items():
            if key in ("access_token", "refresh_token"):
                data[key] = self._encrypt_secret(getattr(self, key))
            elif value is not None or key in self.__class__.nullable_fields:
                data[key] = value
        return data

    async def save(self) -> None:
        original_access, original_refresh = self.access_token, self.refresh_token
        await super().save()
        # Restore plaintext SecretStr after the DB round-trip (super().save may
        # have written the encrypted string back onto the field).
        object.__setattr__(self, "access_token", original_access)
        object.__setattr__(self, "refresh_token", original_refresh)

    @classmethod
    def _from_db_row(cls, row: dict) -> "Connection":
        for field in ("access_token", "refresh_token"):
            val = row.get(field)
            if val and isinstance(val, str):
                row[field] = SecretStr(decrypt_value(val))
            elif val is None:
                row[field] = None
        return cls(**row)

    @classmethod
    async def get(cls, id: str) -> "Connection":
        instance = await super().get(id)
        for field in ("access_token", "refresh_token"):
            val = getattr(instance, field)
            if val:
                raw = val.get_secret_value() if isinstance(val, SecretStr) else val
                object.__setattr__(instance, field, SecretStr(decrypt_value(raw)))
        return instance

    @classmethod
    async def get_by_provider_and_workspace(
        cls, provider: str, workspace_id: str
    ) -> List["Connection"]:
        """Connections for a provider, scoped to a single workspace. Used
        everywhere connections are listed/resolved for a request so one
        workspace can never see another's OAuth connections."""
        results = await repo_query(
            "SELECT * FROM connection WHERE provider = $provider "
            "AND workspace = $workspace ORDER BY created ASC",
            {"provider": provider, "workspace": ensure_record_id(workspace_id)},
        )
        return [cls._from_db_row(r) for r in results]
