from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from open_notebook.domain.connection import Connection


@dataclass
class TokenSet:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)
    account_label: str = ""


@dataclass
class ConnectorItem:
    id: str
    kind: str  # "file" | "page" | "channel"
    title: str
    subtitle: Optional[str] = None
    mime: Optional[str] = None
    modified_at: Optional[str] = None


@dataclass
class ImportedDoc:
    title: str
    content: Optional[str] = None   # -> source_type="text"
    file_path: Optional[str] = None  # -> source_type="upload"


class BaseConnector(ABC):
    provider: str = ""
    display_name: str = ""
    description: str = ""
    scopes: List[str] = []
    client_id_env: str = ""
    client_secret_env: str = ""

    def _env(self, name: str) -> Optional[str]:
        import os
        val = os.getenv(name)
        return val.strip() if val else None

    def is_configured(self) -> bool:
        return bool(self._env(self.client_id_env) and self._env(self.client_secret_env))

    @abstractmethod
    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet: ...

    async def refresh(self, refresh_token: str) -> TokenSet:
        raise NotImplementedError(f"{self.provider} does not support token refresh")

    @abstractmethod
    async def list_items(self, conn: Connection) -> List[ConnectorItem]: ...

    @abstractmethod
    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc: ...
