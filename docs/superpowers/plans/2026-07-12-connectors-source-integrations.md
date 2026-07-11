# Connectors — Source Integrations (Drive / Slack / Notion) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user connect Google Drive, Slack, and Notion via OAuth, pick items, and import them once as Arteamis sources; render seven more apps as disabled "Coming soon" cards on a new `/connections` page.

**Architecture:** A thin `/api/connectors` router delegates to `connectors_service`, which drives one `BaseConnector` adapter per provider (all provider HTTP via `httpx`). OAuth tokens persist encrypted in a new `connection` table (mirrors the `Credential` encryption pattern). Imports fan out to the existing `create_source(..., async_processing=True)` pipeline. The frontend adds a `/connections` page, TanStack Query hooks, and an item-picker dialog.

**Tech Stack:** Python/FastAPI, SurrealDB (SurrealQL migrations), `httpx` (already a dep), Pydantic v2, Next.js/React, TanStack Query, shadcn/ui, i18next.

## Global Constraints

- **Async-first:** every DB query, graph invocation, and AI/HTTP call is `await`-ed. No sync DB access. (root AGENTS.md)
- **Never commit secrets.** OAuth app creds come only from `.env`. Tokens are encrypted at rest with `OPEN_NOTEBOOK_ENCRYPTION_KEY` via `encrypt_value`/`decrypt_value`. (root AGENTS.md)
- **i18n mandatory:** every UI string goes through `t('section.key')`; add each new key to `en-US` (source of truth) and every other locale under `frontend/src/lib/locales/*/index.ts`. Missing keys fall back to en-US. (frontend/AGENTS.md)
- **All FE requests go through `apiClient`** (`src/lib/api/client.ts`). Never create a second axios instance. (frontend/AGENTS.md)
- **Data fetching = TanStack Query hooks** in `src/lib/hooks/` with a `QUERY_KEYS` object; mutations invalidate caches and toast via sonner. (frontend/AGENTS.md)
- **No new Python dependencies.** Use `httpx` for all provider calls (`authlib`/`google-auth` are present but not required).
- **Tenant model:** single-user now. OAuth `state` carries only a CSRF nonce. `Connection.workspace` is a **nullable** `record<workspace>` field, set later by the P2/P5/P6 multitenancy work — do not populate it now.
- **Providers (verbatim ids):** live = `gdrive`, `slack`, `notion`. Coming soon = `sharepoint`, `box`, `dropbox`, `confluence`, `msteams`, `gmail`, `s3`.
- **Migration number:** the next unused number is **20**. If a P2–P6 migration claiming 20 merges first, bump this migration to the next free number and update the registration in `async_migrate.py` accordingly.

---

## What YOU (the operator) need to configure

Before the Connect buttons work, register one OAuth app per provider and put the creds in `.env`. Redirect URIs use `CONNECTORS_API_URL` (the FastAPI origin, port 5055). After a successful connect the API redirects the browser back to `CONNECTORS_APP_URL` (the Next.js origin, port 3000).

**`.env` (backend) — add these:**
```
# Origins used to build OAuth redirect URIs and the post-callback bounce.
CONNECTORS_API_URL=http://localhost:5055        # FastAPI origin (callback lives here)
CONNECTORS_APP_URL=http://localhost:3000        # Next.js origin (user lands here after connect)

# Google Drive
GDRIVE_CLIENT_ID=...
GDRIVE_CLIENT_SECRET=...

# Slack
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...

# Notion
NOTION_CLIENT_ID=...
NOTION_CLIENT_SECRET=...
```

**Per-provider OAuth app setup:**

| Provider | Where | Redirect URI to register | Scopes to request |
|---|---|---|---|
| **Google Drive** | console.cloud.google.com → new project → enable **Google Drive API** → OAuth consent screen (External) → Credentials → **OAuth client ID (Web application)** | `${CONNECTORS_API_URL}/api/connectors/gdrive/callback` | `https://www.googleapis.com/auth/drive.readonly`, `https://www.googleapis.com/auth/drive.metadata.readonly` |
| **Slack** | api.slack.com/apps → Create New App → **OAuth & Permissions** | `${CONNECTORS_API_URL}/api/connectors/slack/callback` | Bot token scopes: `channels:read`, `channels:history`, `pins:read` (canvases: `files:read`) |
| **Notion** | notion.so/my-integrations → New integration → type **Public** (OAuth) | `${CONNECTORS_API_URL}/api/connectors/notion/callback` | Notion grants page access at consent time; no scope strings needed |

A provider whose two env vars are missing still appears on the page as `available`, but its Connect button is disabled with a hint. So you can ship the UI and wire providers in one at a time.

**Dev note (Google):** Google allows `http://localhost` redirect URIs without HTTPS, so local dev works. Non-localhost deployments must use HTTPS.

---

## File structure

**Backend (create):**
- `open_notebook/domain/connection.py` — `Connection` domain model (encrypted tokens, nullable `workspace`).
- `open_notebook/database/migrations/20.surrealql` + `20_down.surrealql` — `connection` table.
- `open_notebook/domain/connectors/__init__.py` — registry (`CONNECTOR_REGISTRY`, `COMING_SOON`, `get_connector`).
- `open_notebook/domain/connectors/base.py` — `BaseConnector`, `TokenSet`, `ConnectorItem`, `ImportedDoc`.
- `open_notebook/domain/connectors/oauth_state.py` — CSRF `state` store (create/consume, TTL).
- `open_notebook/domain/connectors/gdrive.py` — Google Drive adapter.
- `open_notebook/domain/connectors/notion.py` — Notion adapter.
- `open_notebook/domain/connectors/slack.py` — Slack adapter.
- `api/connectors_service.py` — orchestration (status, authorize, callback, items, import, disconnect).
- `api/routers/connectors.py` — HTTP layer, `prefix="/connectors"`.

**Backend (modify):**
- `open_notebook/database/async_migrate.py` — register migration 20 (up + down).
- `api/models.py` — request/response Pydantic models for connectors.
- `api/main.py` — `include_router(connectors.router, prefix="/api", ...)`.
- `api/auth.py` — let the callback path bypass password auth.

**Frontend (create):**
- `frontend/src/lib/api/connectors.ts` — API module + types.
- `frontend/src/lib/hooks/use-connectors.ts` — hooks + `CONNECTOR_QUERY_KEYS`.
- `frontend/src/app/(dashboard)/connections/page.tsx` — the page.
- `frontend/src/components/connectors/ConnectorCard.tsx` — one connector card.
- `frontend/src/components/connectors/ConnectedSourceCard.tsx` — one connected account card.
- `frontend/src/components/connectors/ImportItemsDialog.tsx` — item picker + import.
- `frontend/src/components/connectors/index.ts` — barrel export.
- `frontend/src/components/connectors/ImportItemsDialog.test.tsx` — component test.

**Frontend (modify):**
- `frontend/src/lib/locales/*/index.ts` — add `navigation.connections` + a `connections.*` block to every locale.
- `frontend/src/components/layout/AppSidebar.tsx` — add the nav item.

---

## Task 1: `Connection` domain model + migration

**Files:**
- Create: `open_notebook/domain/connection.py`
- Create: `open_notebook/database/migrations/20.surrealql`, `open_notebook/database/migrations/20_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (register up ~line 134, down ~line 193)
- Test: `tests/test_connection_model.py`

**Interfaces:**
- Produces:
  - `class Connection(ObjectModel)` with fields `provider: str`, `account_label: str`, `access_token: Optional[SecretStr]`, `refresh_token: Optional[SecretStr]`, `token_expires_at: Optional[datetime]`, `scopes: List[str] = []`, `status: str = "connected"`, `workspace: Optional[str] = None`. `table_name = "connection"`.
  - `async def save(self) -> None` — encrypts both token fields, restores plaintext `SecretStr` after the DB round-trip.
  - `@classmethod async def get(cls, id) -> Connection` — decrypts tokens.
  - `@classmethod async def get_by_provider(cls, provider) -> List[Connection]` — decrypts tokens per row.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connection_model.py
import pytest
from open_notebook.domain.connection import Connection


def test_prepare_save_encrypts_both_tokens(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.domain.connection.encrypt_value", lambda v: f"enc({v})"
    )
    conn = Connection(
        provider="gdrive",
        account_label="a@b.com",
        access_token="ACCESS",
        refresh_token="REFRESH",
        scopes=["drive.readonly"],
    )
    data = conn._prepare_save_data()
    assert data["access_token"] == "enc(ACCESS)"
    assert data["refresh_token"] == "enc(REFRESH)"
    assert data["provider"] == "gdrive"
    assert data["workspace"] is None  # nullable, unset now


def test_from_db_row_decrypts_tokens(monkeypatch):
    monkeypatch.setattr(
        "open_notebook.domain.connection.decrypt_value", lambda v: v.replace("enc(", "").rstrip(")")
    )
    row = {
        "id": "connection:1",
        "provider": "notion",
        "account_label": "My WS",
        "access_token": "enc(TOK)",
        "refresh_token": None,
        "scopes": [],
        "status": "connected",
    }
    conn = Connection._from_db_row(row)
    assert conn.access_token.get_secret_value() == "TOK"
    assert conn.refresh_token is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connection_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'open_notebook.domain.connection'`

- [ ] **Step 3: Write the domain model**

```python
# open_notebook/domain/connection.py
"""Connection domain model — an OAuth connection to an external source provider.

Tokens are encrypted at rest with OPEN_NOTEBOOK_ENCRYPTION_KEY, mirroring the
Credential model's pattern. `workspace` is nullable now; the P2/P5/P6
multitenancy work sets it later.
"""
from datetime import datetime
from typing import ClassVar, List, Optional

from loguru import logger
from pydantic import SecretStr

from open_notebook.database.repository import repo_query
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
    async def get_all_connected(cls) -> List["Connection"]:
        results = await repo_query(
            "SELECT * FROM connection ORDER BY created ASC", {}
        )
        out: List["Connection"] = []
        for row in results:
            try:
                out.append(cls._from_db_row(row))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Skipping undecryptable connection {row.get('id')}: {e}")
        return out

    @classmethod
    async def get_by_provider(cls, provider: str) -> List["Connection"]:
        results = await repo_query(
            "SELECT * FROM connection WHERE provider = $provider ORDER BY created ASC",
            {"provider": provider},
        )
        return [cls._from_db_row(r) for r in results]
```

- [ ] **Step 4: Run the model tests to verify they pass**

Run: `uv run pytest tests/test_connection_model.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Write the migration files**

```sql
-- open_notebook/database/migrations/20.surrealql
-- Migration 20: connection table — encrypted OAuth connections to external source providers.

DEFINE TABLE IF NOT EXISTS connection SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS provider ON TABLE connection TYPE string;
DEFINE FIELD IF NOT EXISTS account_label ON TABLE connection TYPE string;
DEFINE FIELD IF NOT EXISTS access_token ON TABLE connection TYPE option<string>;
DEFINE FIELD IF NOT EXISTS refresh_token ON TABLE connection TYPE option<string>;
DEFINE FIELD IF NOT EXISTS token_expires_at ON TABLE connection TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS scopes ON TABLE connection TYPE array<string> DEFAULT [];
DEFINE FIELD IF NOT EXISTS status ON TABLE connection TYPE string DEFAULT "connected";
DEFINE FIELD IF NOT EXISTS workspace ON TABLE connection TYPE option<record<workspace>>;
DEFINE FIELD IF NOT EXISTS created ON connection DEFAULT time::now() VALUE $before OR time::now();
DEFINE FIELD IF NOT EXISTS updated ON connection DEFAULT time::now() VALUE time::now();
DEFINE INDEX IF NOT EXISTS idx_connection_provider ON TABLE connection FIELDS provider;
```

```sql
-- open_notebook/database/migrations/20_down.surrealql
REMOVE TABLE IF EXISTS connection;
```

- [ ] **Step 6: Register the migration in `async_migrate.py`**

Open `open_notebook/database/async_migrate.py`. After the entry for `19.surrealql` in the up-migrations list (~line 134), add:

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20.surrealql"
            ),
```

After the entry for `19_down.surrealql` in the down-migrations list (~line 193), add:

```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/20_down.surrealql"
            ),
```

(Match the exact call form already used for entries 17–19 in that file.)

- [ ] **Step 7: Write a registration test mirroring `test_migration_19_registration.py`**

```python
# tests/test_migration_20_registration.py
from open_notebook.database.async_migrate import AsyncMigrationRunner


def test_migration_20_is_registered():
    runner = AsyncMigrationRunner()
    up_sql = "\n".join(m.up_sql for m in runner.up_migrations)
    assert "DEFINE TABLE IF NOT EXISTS connection" in up_sql
    # 20 up + 20 down both registered
    assert len(runner.up_migrations) == len(runner.down_migrations)
```

> Before writing, open `tests/test_migration_19_registration.py` and copy its exact construction of the runner and its attribute names (`up_migrations`, `up_sql` may differ — use whatever that test uses). Adjust the assertions to match.

- [ ] **Step 8: Run the registration test**

Run: `uv run pytest tests/test_migration_20_registration.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add open_notebook/domain/connection.py open_notebook/database/migrations/20.surrealql open_notebook/database/migrations/20_down.surrealql open_notebook/database/async_migrate.py tests/test_connection_model.py tests/test_migration_20_registration.py
git commit -m "feat(connectors): add Connection domain model + connection table migration"
```

---

## Task 2: Connector base types, registry, and OAuth state store

**Files:**
- Create: `open_notebook/domain/connectors/__init__.py`, `open_notebook/domain/connectors/base.py`, `open_notebook/domain/connectors/oauth_state.py`
- Test: `tests/test_connector_registry.py`, `tests/test_oauth_state.py`

**Interfaces:**
- Produces:
  - `@dataclass TokenSet(access_token: str, refresh_token: Optional[str], expires_at: Optional[datetime], scopes: list[str], account_label: str)`
  - `@dataclass ConnectorItem(id: str, kind: str, title: str, subtitle: Optional[str] = None, mime: Optional[str] = None, modified_at: Optional[str] = None)`
  - `@dataclass ImportedDoc(title: str, content: Optional[str] = None, file_path: Optional[str] = None)`
  - `class BaseConnector(ABC)` with attrs `provider: str`, `display_name: str`, `description: str`, `scopes: list[str]`, `client_id_env: str`, `client_secret_env: str`; methods `is_configured() -> bool`, `authorize_url(state, redirect_uri) -> str`, `async exchange_code(code, redirect_uri) -> TokenSet`, `async refresh(refresh_token) -> TokenSet`, `async list_items(conn) -> list[ConnectorItem]`, `async fetch_content(conn, item) -> ImportedDoc`.
  - `CONNECTOR_REGISTRY: dict[str, type[BaseConnector]]` (populated in Task 3–5), `get_connector(provider) -> BaseConnector`, `COMING_SOON: list[dict]`.
  - `oauth_state.create_state() -> str`, `oauth_state.consume_state(state) -> bool` (single-use, TTL 600s).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_oauth_state.py
from open_notebook.domain.connectors import oauth_state


def test_state_roundtrip_is_single_use():
    s = oauth_state.create_state()
    assert isinstance(s, str) and len(s) >= 16
    assert oauth_state.consume_state(s) is True
    assert oauth_state.consume_state(s) is False  # already consumed


def test_unknown_state_rejected():
    assert oauth_state.consume_state("never-issued") is False
```

```python
# tests/test_connector_registry.py
import pytest
from open_notebook.domain.connectors import get_connector, COMING_SOON


def test_get_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_connector("does-not-exist")


def test_coming_soon_ids():
    ids = {c["provider"] for c in COMING_SOON}
    assert ids == {"sharepoint", "box", "dropbox", "confluence", "msteams", "gmail", "s3"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_oauth_state.py tests/test_connector_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: open_notebook.domain.connectors`

- [ ] **Step 3: Write `base.py`**

```python
# open_notebook/domain/connectors/base.py
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
```

- [ ] **Step 4: Write `oauth_state.py`**

```python
# open_notebook/domain/connectors/oauth_state.py
"""In-process single-use CSRF state store for the OAuth handshake.

State lives ~10 minutes and is consumed exactly once. In-process is fine for a
single-instance deployment; a future multi-process deploy would swap this for a
shared store (Redis/DB) behind the same two functions.
"""
import secrets
import time
from typing import Dict

_TTL_SECONDS = 600
_states: Dict[str, float] = {}


def _purge(now: float) -> None:
    for key in [k for k, exp in _states.items() if exp < now]:
        _states.pop(key, None)


def create_state() -> str:
    now = time.monotonic()
    _purge(now)
    token = secrets.token_urlsafe(32)
    _states[token] = now + _TTL_SECONDS
    return token


def consume_state(state: str) -> bool:
    now = time.monotonic()
    _purge(now)
    return _states.pop(state, None) is not None
```

- [ ] **Step 5: Write `__init__.py` (registry)**

```python
# open_notebook/domain/connectors/__init__.py
from typing import Dict, List, Type

from open_notebook.domain.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ImportedDoc,
    TokenSet,
)

# Adapters register themselves here as they are added (Tasks 3–5).
CONNECTOR_REGISTRY: Dict[str, Type[BaseConnector]] = {}

COMING_SOON: List[dict] = [
    {"provider": "sharepoint", "display_name": "SharePoint",
     "description": "Microsoft 365 SharePoint and OneDrive for Business"},
    {"provider": "box", "display_name": "Box",
     "description": "Enterprise content management with folder permissions"},
    {"provider": "dropbox", "display_name": "Dropbox",
     "description": "Cloud storage with shared folder access"},
    {"provider": "confluence", "display_name": "Confluence",
     "description": "Wiki pages, blog posts, and attachments"},
    {"provider": "msteams", "display_name": "Microsoft Teams",
     "description": "Meeting transcripts, channels, wiki, and files"},
    {"provider": "gmail", "display_name": "Gmail",
     "description": "Your email — indexed only for you, not your teammates"},
    {"provider": "s3", "display_name": "S3 Bucket",
     "description": "Connect your S3 bucket via cross-account IAM role"},
]


def get_connector(provider: str) -> BaseConnector:
    cls = CONNECTOR_REGISTRY.get(provider)
    if cls is None:
        raise ValueError(f"Unknown or unsupported connector: {provider}")
    return cls()


def _register(cls: Type[BaseConnector]) -> None:
    CONNECTOR_REGISTRY[cls.provider] = cls


__all__ = [
    "BaseConnector", "ConnectorItem", "ImportedDoc", "TokenSet",
    "CONNECTOR_REGISTRY", "COMING_SOON", "get_connector", "_register",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_oauth_state.py tests/test_connector_registry.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Commit**

```bash
git add open_notebook/domain/connectors/ tests/test_oauth_state.py tests/test_connector_registry.py
git commit -m "feat(connectors): add BaseConnector interface, registry, and OAuth state store"
```

---

## Task 3: Google Drive adapter

**Files:**
- Create: `open_notebook/domain/connectors/gdrive.py`
- Modify: `open_notebook/domain/connectors/__init__.py` (import + register at bottom)
- Test: `tests/test_gdrive_connector.py`

**Interfaces:**
- Consumes: `BaseConnector`, `TokenSet`, `ConnectorItem`, `ImportedDoc`, `_register` (Task 2); `Connection` (Task 1).
- Produces: `class GDriveConnector(BaseConnector)` with `provider = "gdrive"`; registered in `CONNECTOR_REGISTRY["gdrive"]`.

- [ ] **Step 1: Write the failing test** (mock all HTTP via `respx`/monkeypatched `httpx.AsyncClient`)

```python
# tests/test_gdrive_connector.py
import pytest
from open_notebook.domain.connectors.gdrive import GDriveConnector


def test_authorize_url_has_offline_and_scopes(monkeypatch):
    monkeypatch.setenv("GDRIVE_CLIENT_ID", "cid")
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", "secret")
    url = GDriveConnector().authorize_url("STATE123", "http://localhost:5055/api/connectors/gdrive/callback")
    assert "accounts.google.com" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=STATE123" in url
    assert "drive.readonly" in url


def test_is_configured_reflects_env(monkeypatch):
    monkeypatch.delenv("GDRIVE_CLIENT_ID", raising=False)
    assert GDriveConnector().is_configured() is False
    monkeypatch.setenv("GDRIVE_CLIENT_ID", "cid")
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", "sec")
    assert GDriveConnector().is_configured() is True


def test_pick_export_mime_for_google_doc():
    c = GDriveConnector()
    assert c._export_mime("application/vnd.google-apps.document") == "text/markdown"
    assert c._export_mime("application/pdf") is None  # binary download, not export
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gdrive_connector.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the adapter**

```python
# open_notebook/domain/connectors/gdrive.py
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode

import httpx

from open_notebook.domain.connection import Connection
from open_notebook.domain.connectors import _register
from open_notebook.domain.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ImportedDoc,
    TokenSet,
)

_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_FILES = "https://www.googleapis.com/drive/v3/files"

# Google-native mime -> export mime. Everything else is downloaded as-is.
_EXPORT = {
    "application/vnd.google-apps.document": "text/markdown",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


class GDriveConnector(BaseConnector):
    provider = "gdrive"
    display_name = "Google Drive"
    description = "Native connector with file-level permissions"
    scopes = [
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
    ]
    client_id_env = "GDRIVE_CLIENT_ID"
    client_secret_env = "GDRIVE_CLIENT_SECRET"

    def _export_mime(self, mime: str) -> Optional[str]:
        return _EXPORT.get(mime)

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._env(self.client_id_env),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, data={
                "code": code,
                "client_id": self._env(self.client_id_env),
                "client_secret": self._env(self.client_secret_env),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            resp.raise_for_status()
            tok = resp.json()
        label = await self._account_email(tok["access_token"])
        return TokenSet(
            access_token=tok["access_token"],
            refresh_token=tok.get("refresh_token"),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600)),
            scopes=self.scopes,
            account_label=label,
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, data={
                "refresh_token": refresh_token,
                "client_id": self._env(self.client_id_env),
                "client_secret": self._env(self.client_secret_env),
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            tok = resp.json()
        return TokenSet(
            access_token=tok["access_token"],
            refresh_token=refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600)),
            scopes=self.scopes,
        )

    async def _account_email(self, access_token: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code == 200:
                return r.json().get("email", "Google Drive")
        return "Google Drive"

    async def list_items(self, conn: Connection) -> List[ConnectorItem]:
        token = conn.access_token.get_secret_value()
        params = {
            "pageSize": 100,
            "fields": "files(id,name,mimeType,modifiedTime)",
            "q": "trashed = false",
            "orderBy": "modifiedTime desc",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(_FILES, params=params,
                                  headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            files = r.json().get("files", [])
        return [
            ConnectorItem(id=f["id"], kind="file", title=f["name"],
                          mime=f.get("mimeType"), modified_at=f.get("modifiedTime"))
            for f in files
        ]

    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc:
        token = conn.access_token.get_secret_value()
        headers = {"Authorization": f"Bearer {token}"}
        export_mime = self._export_mime(item.mime or "")
        async with httpx.AsyncClient(timeout=60) as client:
            if export_mime:
                r = await client.get(f"{_FILES}/{item.id}/export",
                                     params={"mimeType": export_mime}, headers=headers)
                r.raise_for_status()
                return ImportedDoc(title=item.title, content=r.text)
            # Binary/other: download bytes to a temp file for upload ingestion.
            r = await client.get(f"{_FILES}/{item.id}", params={"alt": "media"}, headers=headers)
            r.raise_for_status()
            suffix = os.path.splitext(item.title)[1] or ""
            fd, path = tempfile.mkstemp(suffix=suffix)
            with os.fdopen(fd, "wb") as fh:
                fh.write(r.content)
            return ImportedDoc(title=item.title, file_path=path)


_register(GDriveConnector)
```

- [ ] **Step 4: Register the adapter import**

At the bottom of `open_notebook/domain/connectors/__init__.py`, add (after the `__all__`):

```python
# Import adapters for their registration side effects. Kept at the bottom to
# avoid a circular import (adapters import from this module).
from open_notebook.domain.connectors import gdrive  # noqa: E402,F401
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_gdrive_connector.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add open_notebook/domain/connectors/gdrive.py open_notebook/domain/connectors/__init__.py tests/test_gdrive_connector.py
git commit -m "feat(connectors): add Google Drive adapter"
```

---

## Task 4: Notion adapter

**Files:**
- Create: `open_notebook/domain/connectors/notion.py`
- Modify: `open_notebook/domain/connectors/__init__.py` (add `notion` import)
- Test: `tests/test_notion_connector.py`

**Interfaces:**
- Produces: `class NotionConnector(BaseConnector)` `provider = "notion"`; helper `_blocks_to_markdown(blocks: list[dict]) -> str`. Registered as `CONNECTOR_REGISTRY["notion"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notion_connector.py
from open_notebook.domain.connectors.notion import NotionConnector


def test_authorize_url_shape(monkeypatch):
    monkeypatch.setenv("NOTION_CLIENT_ID", "cid")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "sec")
    url = NotionConnector().authorize_url("ST", "http://localhost:5055/api/connectors/notion/callback")
    assert "api.notion.com/v1/oauth/authorize" in url
    assert "owner=user" in url
    assert "state=ST" in url


def test_blocks_to_markdown_renders_headings_and_paragraphs():
    blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello world"}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "point"}]}},
    ]
    md = NotionConnector()._blocks_to_markdown(blocks)
    assert "# Title" in md
    assert "Hello world" in md
    assert "- point" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_notion_connector.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the adapter**

```python
# open_notebook/domain/connectors/notion.py
import base64
from typing import List
from urllib.parse import urlencode

import httpx

from open_notebook.domain.connection import Connection
from open_notebook.domain.connectors import _register
from open_notebook.domain.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ImportedDoc,
    TokenSet,
)

_AUTH = "https://api.notion.com/v1/oauth/authorize"
_TOKEN = "https://api.notion.com/v1/oauth/token"
_SEARCH = "https://api.notion.com/v1/search"
_BLOCKS = "https://api.notion.com/v1/blocks"
_VERSION = "2022-06-28"


class NotionConnector(BaseConnector):
    provider = "notion"
    display_name = "Notion"
    description = "Pages, databases, and workspace content"
    scopes: List[str] = []  # Notion grants page access interactively, no scope strings
    client_id_env = "NOTION_CLIENT_ID"
    client_secret_env = "NOTION_CLIENT_SECRET"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._env(self.client_id_env),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "owner": "user",
            "state": state,
        }
        return f"{_AUTH}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        basic = base64.b64encode(
            f"{self._env(self.client_id_env)}:{self._env(self.client_secret_env)}".encode()
        ).decode()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }, headers={"Authorization": f"Basic {basic}",
                        "Content-Type": "application/json"})
            resp.raise_for_status()
            tok = resp.json()
        return TokenSet(
            access_token=tok["access_token"],
            refresh_token=None,  # Notion tokens don't expire
            scopes=[],
            account_label=tok.get("workspace_name") or "Notion",
        )

    def _headers(self, conn: Connection) -> dict:
        return {
            "Authorization": f"Bearer {conn.access_token.get_secret_value()}",
            "Notion-Version": _VERSION,
            "Content-Type": "application/json",
        }

    async def list_items(self, conn: Connection) -> List[ConnectorItem]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(_SEARCH, json={
                "filter": {"property": "object", "value": "page"},
                "page_size": 100,
            }, headers=self._headers(conn))
            r.raise_for_status()
            results = r.json().get("results", [])
        items: List[ConnectorItem] = []
        for p in results:
            title = self._page_title(p)
            items.append(ConnectorItem(
                id=p["id"], kind="page", title=title,
                modified_at=p.get("last_edited_time")))
        return items

    def _page_title(self, page: dict) -> str:
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                parts = prop.get("title", [])
                if parts:
                    return "".join(t.get("plain_text", "") for t in parts) or "Untitled"
        return "Untitled"

    def _rich(self, block: dict, key: str) -> str:
        return "".join(t.get("plain_text", "") for t in block.get(key, {}).get("rich_text", []))

    def _blocks_to_markdown(self, blocks: List[dict]) -> str:
        lines: List[str] = []
        for b in blocks:
            t = b.get("type")
            if t == "heading_1":
                lines.append(f"# {self._rich(b, 'heading_1')}")
            elif t == "heading_2":
                lines.append(f"## {self._rich(b, 'heading_2')}")
            elif t == "heading_3":
                lines.append(f"### {self._rich(b, 'heading_3')}")
            elif t == "bulleted_list_item":
                lines.append(f"- {self._rich(b, 'bulleted_list_item')}")
            elif t == "numbered_list_item":
                lines.append(f"1. {self._rich(b, 'numbered_list_item')}")
            elif t == "paragraph":
                lines.append(self._rich(b, "paragraph"))
        return "\n\n".join(line for line in lines if line is not None)

    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{_BLOCKS}/{item.id}/children",
                                 params={"page_size": 100}, headers=self._headers(conn))
            r.raise_for_status()
            blocks = r.json().get("results", [])
        return ImportedDoc(title=item.title, content=self._blocks_to_markdown(blocks))


_register(NotionConnector)
```

- [ ] **Step 4: Register the adapter import**

In `open_notebook/domain/connectors/__init__.py`, next to the `gdrive` import line, add:

```python
from open_notebook.domain.connectors import notion  # noqa: E402,F401
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_notion_connector.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add open_notebook/domain/connectors/notion.py open_notebook/domain/connectors/__init__.py tests/test_notion_connector.py
git commit -m "feat(connectors): add Notion adapter"
```

---

## Task 5: Slack adapter (pinned messages + canvases)

**Files:**
- Create: `open_notebook/domain/connectors/slack.py`
- Modify: `open_notebook/domain/connectors/__init__.py` (add `slack` import)
- Test: `tests/test_slack_connector.py`

**Interfaces:**
- Produces: `class SlackConnector(BaseConnector)` `provider = "slack"`; helper `_render_pins(items: list[dict]) -> str`. Registered as `CONNECTOR_REGISTRY["slack"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_slack_connector.py
from open_notebook.domain.connectors.slack import SlackConnector


def test_authorize_url_uses_v2_and_scopes(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "sec")
    url = SlackConnector().authorize_url("ST", "http://localhost:5055/api/connectors/slack/callback")
    assert "slack.com/oauth/v2/authorize" in url
    assert "pins:read" in url
    assert "state=ST" in url


def test_render_pins_concatenates_message_text():
    pins = [
        {"message": {"text": "first pinned", "user": "U1"}},
        {"message": {"text": "second pinned", "user": "U2"}},
    ]
    out = SlackConnector()._render_pins(pins)
    assert "first pinned" in out and "second pinned" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_slack_connector.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the adapter**

```python
# open_notebook/domain/connectors/slack.py
from typing import List
from urllib.parse import urlencode

import httpx

from open_notebook.domain.connection import Connection
from open_notebook.domain.connectors import _register
from open_notebook.domain.connectors.base import (
    BaseConnector,
    ConnectorItem,
    ImportedDoc,
    TokenSet,
)

_AUTH = "https://slack.com/oauth/v2/authorize"
_TOKEN = "https://slack.com/api/oauth.v2.access"
_API = "https://slack.com/api"
_SCOPES = ["channels:read", "channels:history", "pins:read", "files:read"]


class SlackConnector(BaseConnector):
    provider = "slack"
    display_name = "Slack"
    description = "Pinned messages, canvases, bookmarks, and knowledge artifacts"
    scopes = _SCOPES
    client_id_env = "SLACK_CLIENT_ID"
    client_secret_env = "SLACK_CLIENT_SECRET"

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._env(self.client_id_env),
            "redirect_uri": redirect_uri,
            "scope": ",".join(self.scopes),
            "state": state,
        }
        return f"{_AUTH}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN, data={
                "code": code,
                "client_id": self._env(self.client_id_env),
                "client_secret": self._env(self.client_secret_env),
                "redirect_uri": redirect_uri,
            })
            resp.raise_for_status()
            tok = resp.json()
        if not tok.get("ok"):
            raise ValueError(f"Slack OAuth failed: {tok.get('error')}")
        token = tok.get("access_token") or tok["authed_user"]["access_token"]
        return TokenSet(
            access_token=token,
            refresh_token=None,  # Slack bot tokens do not expire
            scopes=self.scopes,
            account_label=tok.get("team", {}).get("name", "Slack"),
        )

    async def list_items(self, conn: Connection) -> List[ConnectorItem]:
        token = conn.access_token.get_secret_value()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{_API}/conversations.list",
                                 params={"types": "public_channel", "limit": 200},
                                 headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
        if not data.get("ok"):
            raise ValueError(f"Slack conversations.list failed: {data.get('error')}")
        return [
            ConnectorItem(id=ch["id"], kind="channel", title=f"#{ch['name']}")
            for ch in data.get("channels", [])
        ]

    def _render_pins(self, pins: List[dict]) -> str:
        out = []
        for p in pins:
            msg = p.get("message") or {}
            text = msg.get("text")
            if text:
                out.append(text)
        return "\n\n---\n\n".join(out)

    async def fetch_content(self, conn: Connection, item: ConnectorItem) -> ImportedDoc:
        token = conn.access_token.get_secret_value()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{_API}/pins.list",
                                 params={"channel": item.id},
                                 headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()
        if not data.get("ok"):
            raise ValueError(f"Slack pins.list failed: {data.get('error')}")
        content = self._render_pins(data.get("items", []))
        return ImportedDoc(title=f"Slack {item.title} — pinned", content=content or "(no pinned content)")


_register(SlackConnector)
```

- [ ] **Step 4: Register the adapter import**

In `open_notebook/domain/connectors/__init__.py`, next to the other adapter imports, add:

```python
from open_notebook.domain.connectors import slack  # noqa: E402,F401
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_slack_connector.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add open_notebook/domain/connectors/slack.py open_notebook/domain/connectors/__init__.py tests/test_slack_connector.py
git commit -m "feat(connectors): add Slack adapter (pinned messages)"
```

---

## Task 6: `connectors_service` orchestration

**Files:**
- Create: `api/connectors_service.py`
- Test: `tests/test_connectors_service.py`

**Interfaces:**
- Consumes: `get_connector`, `CONNECTOR_REGISTRY`, `COMING_SOON` (Task 2); `Connection` (Task 1); `oauth_state` (Task 2); the source-creation domain path — `Source`/`Asset` (`open_notebook.domain.notebook`), `SourceProcessingInput` (`commands.source_commands`), `CommandService.submit_command_job` (`api.command_service`) — same as `api/routers/sources.py`. **Do NOT use `api.sources_service.SourceService`** (client-side HTTP wrapper).
- Produces:
  - `def list_connectors() -> list[dict]` — merges live (with `status`) + coming-soon; each dict: `provider`, `display_name`, `description`, `status` ∈ `{connected, configured, available, coming_soon}`, `connections: list[dict]`.
  - `def redirect_uri_for(provider: str) -> str` — `{CONNECTORS_API_URL}/api/connectors/{provider}/callback`.
  - `def build_authorize_url(provider: str) -> str` — creates state, returns provider consent URL.
  - `async def handle_callback(provider: str, code: str, state: str) -> Connection` — validates state, exchanges code, persists encrypted `Connection`.
  - `async def list_items(provider: str, connection_id: str) -> list[dict]`.
  - `async def import_items(provider, connection_id, item_ids, notebooks) -> dict` — `{accepted: [...], failed: [{item_id, error}]}`.
  - `async def disconnect(connection_id: str) -> None`.
  - `app_redirect(query: str) -> str` — `{CONNECTORS_APP_URL}/connections?{query}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connectors_service.py
import pytest
from api import connectors_service as svc


def test_list_connectors_marks_coming_soon(monkeypatch):
    monkeypatch.delenv("GDRIVE_CLIENT_ID", raising=False)
    result = {c["provider"]: c for c in svc.list_connectors()}
    assert result["s3"]["status"] == "coming_soon"
    # gdrive present, but not configured (no env) and not connected
    assert result["gdrive"]["status"] == "available"


def test_redirect_uri_uses_api_url(monkeypatch):
    monkeypatch.setenv("CONNECTORS_API_URL", "https://api.example.com")
    assert svc.redirect_uri_for("gdrive") == "https://api.example.com/api/connectors/gdrive/callback"


@pytest.mark.asyncio
async def test_handle_callback_rejects_bad_state(monkeypatch):
    monkeypatch.setattr(svc.oauth_state, "consume_state", lambda s: False)
    with pytest.raises(ValueError):
        await svc.handle_callback("gdrive", code="x", state="bad")
```

> `list_connectors` reads live connection counts. For `test_list_connectors_marks_coming_soon`, monkeypatch the connection lookup to return `[]` so the test needs no DB: `monkeypatch.setattr(svc, "_provider_connections_sync", lambda p: [])` (see the helper in Step 3), or mark the test to require the DB fixture from `tests/conftest.py`. Prefer the monkeypatch — keep this unit test DB-free.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.connectors_service'`

- [ ] **Step 3: Write the service**

```python
# api/connectors_service.py
"""Business logic for external source connectors. The router is a thin shell
over this module. All provider I/O is delegated to BaseConnector adapters."""
import os
from typing import List, Optional

from loguru import logger

from api.command_service import CommandService
from open_notebook.database.repository import ensure_record_id, repo_delete
from open_notebook.domain.connection import Connection
from open_notebook.domain.connectors import (
    COMING_SOON,
    CONNECTOR_REGISTRY,
    get_connector,
    oauth_state,
)
from open_notebook.domain.notebook import Asset, Source

# IMPORTANT: create sources via the DOMAIN layer (Source + CommandService),
# exactly like api/routers/sources.py does — NOT via api.sources_service.SourceService,
# which is a client-side HTTP wrapper (api_client → httpx to the running API) and would
# make the API call itself over HTTP. The domain path is the correct in-process route.


def _api_url() -> str:
    return os.getenv("CONNECTORS_API_URL", "http://localhost:5055").rstrip("/")


def _app_url() -> str:
    return os.getenv("CONNECTORS_APP_URL", "http://localhost:3000").rstrip("/")


def redirect_uri_for(provider: str) -> str:
    return f"{_api_url()}/api/connectors/{provider}/callback"


def app_redirect(query: str) -> str:
    return f"{_app_url()}/connections?{query}"


def _connection_public(conn: Connection) -> dict:
    return {
        "id": conn.id,
        "provider": conn.provider,
        "account_label": conn.account_label,
        "status": conn.status,
        "created": conn.created.isoformat() if conn.created else None,
    }


async def _provider_connections(provider: str) -> List[Connection]:
    return await Connection.get_by_provider(provider)


def list_connectors() -> List[dict]:
    """Live connectors first (with per-provider status), then coming-soon cards.

    Note: connection counts are resolved lazily by the router via
    `list_connectors_with_connections`. This sync function reports config/live
    status without a DB round-trip so it stays unit-testable."""
    out: List[dict] = []
    for provider, cls in CONNECTOR_REGISTRY.items():
        adapter = cls()
        out.append({
            "provider": provider,
            "display_name": adapter.display_name,
            "description": adapter.description,
            "status": "configured" if adapter.is_configured() else "available",
            "connections": [],
        })
    for cs in COMING_SOON:
        out.append({**cs, "status": "coming_soon", "connections": []})
    return out


async def list_connectors_with_connections() -> List[dict]:
    base = list_connectors()
    for entry in base:
        if entry["status"] == "coming_soon":
            continue
        conns = await _provider_connections(entry["provider"])
        entry["connections"] = [_connection_public(c) for c in conns]
        if conns:
            entry["status"] = "connected"
    return base


def build_authorize_url(provider: str) -> str:
    adapter = get_connector(provider)
    if not adapter.is_configured():
        raise ValueError(f"{provider} OAuth app is not configured (missing env vars)")
    state = oauth_state.create_state()
    return adapter.authorize_url(state, redirect_uri_for(provider))


async def handle_callback(provider: str, code: str, state: str) -> Connection:
    if not oauth_state.consume_state(state):
        raise ValueError("Invalid or expired OAuth state")
    adapter = get_connector(provider)
    token = await adapter.exchange_code(code, redirect_uri_for(provider))
    conn = Connection(
        provider=provider,
        account_label=token.account_label or adapter.display_name,
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        token_expires_at=token.expires_at,
        scopes=token.scopes,
        status="connected",
    )
    await conn.save()
    return conn


async def list_items(provider: str, connection_id: str) -> List[dict]:
    adapter = get_connector(provider)
    conn = await Connection.get(connection_id)
    items = await adapter.list_items(conn)
    return [
        {"id": i.id, "kind": i.kind, "title": i.title, "subtitle": i.subtitle,
         "mime": i.mime, "modified_at": i.modified_at}
        for i in items
    ]


async def _ingest_doc(doc, notebooks: Optional[List[str]]) -> str:
    """Create a Source from an ImportedDoc and queue async processing, mirroring
    the async path of api/routers/sources.py. Returns the command id.

    `doc.file_path` (binary download) → upload-style content_state; otherwise
    `doc.content` → text content_state. The background `process_source` command
    reads content_state and runs extraction/embedding; the worker
    (`make worker-start`) must be running or the job queues forever.
    """
    # Ensure the process_source command is registered before submitting.
    import commands.source_commands  # noqa: F401
    from commands.source_commands import SourceProcessingInput

    if doc.file_path:
        asset = Asset(file_path=doc.file_path)
        content_state = {"file_path": doc.file_path, "delete_source": True}
    else:
        asset = None
        content_state = {"content": doc.content or ""}

    source = Source(title=doc.title or "Untitled", topics=[], asset=asset)
    await source.save()
    for notebook_id in notebooks or []:
        await source.add_to_notebook(notebook_id)

    try:
        command_input = SourceProcessingInput(
            source_id=str(source.id),
            content_state=content_state,
            notebook_ids=notebooks,
            transformations=[],
            embed=True,
        )
        command_id = await CommandService.submit_command_job(
            "open_notebook", "process_source", command_input.model_dump()
        )
        source.command = ensure_record_id(command_id)
        await source.save()
        return command_id
    except Exception:
        # Roll back the half-created source so a failed queue submission doesn't
        # leave an orphan record (mirrors the sources router's cleanup).
        try:
            await source.delete()
        except Exception:  # noqa: BLE001
            pass
        raise


async def import_items(
    provider: str, connection_id: str, item_ids: List[str],
    notebooks: Optional[List[str]] = None,
) -> dict:
    adapter = get_connector(provider)
    conn = await Connection.get(connection_id)
    all_items = {i.id: i for i in await adapter.list_items(conn)}
    accepted, failed = [], []
    for item_id in item_ids:
        item = all_items.get(item_id)
        if item is None:
            failed.append({"item_id": item_id, "error": "item not found"})
            continue
        try:
            doc = await adapter.fetch_content(conn, item)
            await _ingest_doc(doc, notebooks)
            accepted.append(item_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"connector import failed for {provider}/{item_id}: {e}")
            failed.append({"item_id": item_id, "error": str(e)})
    return {"accepted": accepted, "failed": failed}


async def disconnect(connection_id: str) -> None:
    await repo_delete(ensure_record_id(connection_id))
```

> **Why the domain layer, not `SourceService`:** `api.sources_service.SourceService` delegates to `api_client` (an `httpx` client pointed at `http://127.0.0.1:5055`) — it is a *client-side* wrapper that calls the API over HTTP. Calling it from inside the API (connectors_service runs in-process) would make the server call itself. No router uses `SourceService`; they all create sources through the `Source` domain model + `CommandService.submit_command_job`, which is what `_ingest_doc` above does. Import paths verified against `api/routers/sources.py` (lines ~448–484): `Asset, Source` from `open_notebook.domain.notebook`; `SourceProcessingInput` from `commands.source_commands`; `CommandService` from `api.command_service`; `ensure_record_id`, `repo_delete` from `open_notebook.database.repository`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_connectors_service.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add api/connectors_service.py tests/test_connectors_service.py
git commit -m "feat(connectors): add connectors_service orchestration layer"
```

---

## Task 7: API models, router, and app wiring

**Files:**
- Modify: `api/models.py` (append request/response models)
- Create: `api/routers/connectors.py`
- Modify: `api/main.py` (register router after the `credentials` include ~line 393)
- Modify: `api/auth.py` (let `/api/connectors/{provider}/callback` bypass password auth)
- Test: `tests/test_connectors_router.py`

**Interfaces:**
- Consumes: everything from `connectors_service` (Task 6).
- Produces: `router = APIRouter(prefix="/connectors", tags=["connectors"])` with:
  - `GET /connectors` → `list[ConnectorResponse]`
  - `GET /connectors/{provider}/authorize` → `AuthorizeResponse{authorize_url}`
  - `GET /connectors/{provider}/callback?code&state` → `RedirectResponse` to the app
  - `GET /connectors/{provider}/items?connection_id` → `list[ConnectorItemResponse]`
  - `POST /connectors/{provider}/import` (`ImportRequest`) → `ImportResponse`
  - `DELETE /connectors/connections/{connection_id}` → `204`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_connectors_router.py
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_list_connectors_endpoint(monkeypatch):
    resp = client.get("/api/connectors")
    assert resp.status_code == 200
    providers = {c["provider"] for c in resp.json()}
    assert {"gdrive", "slack", "notion"}.issubset(providers)
    assert "s3" in providers


def test_callback_redirects_to_app(monkeypatch):
    async def fake_handle(provider, code, state):
        class C: id = "connection:1"
        return C()
    monkeypatch.setattr("api.routers.connectors.svc.handle_callback", fake_handle)
    monkeypatch.setattr("api.routers.connectors.svc.app_redirect",
                        lambda q: f"http://localhost:3000/connections?{q}")
    resp = client.get("/api/connectors/gdrive/callback?code=abc&state=xyz",
                      follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "connected=gdrive" in resp.headers["location"]


def test_callback_error_redirects_with_error(monkeypatch):
    async def boom(provider, code, state):
        raise ValueError("Invalid or expired OAuth state")
    monkeypatch.setattr("api.routers.connectors.svc.handle_callback", boom)
    monkeypatch.setattr("api.routers.connectors.svc.app_redirect",
                        lambda q: f"http://localhost:3000/connections?{q}")
    resp = client.get("/api/connectors/gdrive/callback?code=abc&state=bad",
                      follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "error=" in resp.headers["location"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_connectors_router.py -v`
Expected: FAIL (router not mounted → 404 on `/api/connectors`)

- [ ] **Step 3: Append API models to `api/models.py`**

```python
# --- Connectors ---
class ConnectionPublic(BaseModel):
    id: Optional[str] = None
    provider: str
    account_label: str
    status: str
    created: Optional[str] = None


class ConnectorResponse(BaseModel):
    provider: str
    display_name: str
    description: str
    status: str  # connected | configured | available | coming_soon
    connections: List[ConnectionPublic] = []


class AuthorizeResponse(BaseModel):
    authorize_url: str


class ConnectorItemResponse(BaseModel):
    id: str
    kind: str
    title: str
    subtitle: Optional[str] = None
    mime: Optional[str] = None
    modified_at: Optional[str] = None


class ImportRequest(BaseModel):
    connection_id: str
    item_ids: List[str]
    notebooks: Optional[List[str]] = None


class ImportFailure(BaseModel):
    item_id: str
    error: str


class ImportResponse(BaseModel):
    accepted: List[str]
    failed: List[ImportFailure]
```

> Confirm `BaseModel`, `Optional`, `List` are already imported at the top of `api/models.py` (they are used throughout). If not, add `from typing import List, Optional`.

- [ ] **Step 4: Write the router**

```python
# api/routers/connectors.py
"""Connectors Router — thin HTTP layer over api.connectors_service."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from loguru import logger

from api import connectors_service as svc
from api.models import (
    AuthorizeResponse,
    ConnectorItemResponse,
    ConnectorResponse,
    ImportRequest,
    ImportResponse,
)

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.get("", response_model=list[ConnectorResponse])
async def list_connectors():
    return await svc.list_connectors_with_connections()


@router.get("/{provider}/authorize", response_model=AuthorizeResponse)
async def authorize(provider: str):
    try:
        return AuthorizeResponse(authorize_url=svc.build_authorize_url(provider))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{provider}/callback")
async def callback(provider: str, code: str = Query(...), state: str = Query(...)):
    try:
        await svc.handle_callback(provider, code, state)
        return RedirectResponse(svc.app_redirect(f"connected={provider}"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"OAuth callback failed for {provider}: {e}")
        return RedirectResponse(svc.app_redirect(f"error=oauth_failed&provider={provider}"))


@router.get("/{provider}/items", response_model=list[ConnectorItemResponse])
async def list_items(provider: str, connection_id: str = Query(...)):
    try:
        return await svc.list_items(provider, connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{provider}/import", response_model=ImportResponse)
async def import_items(provider: str, body: ImportRequest):
    try:
        return await svc.import_items(
            provider, body.connection_id, body.item_ids, body.notebooks)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(connection_id: str):
    await svc.disconnect(connection_id)
```

- [ ] **Step 5: Register the router in `api/main.py`**

Add the import next to the other router imports, and after the `credentials` include (~line 393) add:

```python
from api.routers import connectors  # (with the other router imports)
app.include_router(connectors.router, prefix="/api", tags=["connectors"])
```

- [ ] **Step 6: Let the callback bypass password auth**

In `api/auth.py`, inside `PasswordAuthMiddleware.dispatch`, add a prefix/suffix skip **before** the auth-header check (after the OPTIONS skip):

```python
        # OAuth provider callbacks arrive without a Bearer header; CSRF state
        # (validated in the service) is the protection here.
        if request.url.path.startswith("/api/connectors/") and request.url.path.endswith("/callback"):
            return await call_next(request)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_connectors_router.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Full backend check**

Run: `uv run pytest tests/test_connection_model.py tests/test_oauth_state.py tests/test_connector_registry.py tests/test_gdrive_connector.py tests/test_notion_connector.py tests/test_slack_connector.py tests/test_connectors_service.py tests/test_connectors_router.py -v && ruff check api open_notebook --fix`
Expected: all PASS, ruff clean.

- [ ] **Step 9: Commit**

```bash
git add api/models.py api/routers/connectors.py api/main.py api/auth.py tests/test_connectors_router.py
git commit -m "feat(connectors): add connectors router, API models, and app wiring"
```

---

## Task 8: Frontend API module

**Files:**
- Create: `frontend/src/lib/api/connectors.ts`
- Test: covered via the hook test in Task 9 (this module is a thin `apiClient` wrapper).

**Interfaces:**
- Produces `connectorsApi` with: `list()`, `authorize(provider)`, `items(provider, connectionId)`, `import(provider, body)`, `disconnect(connectionId)`, plus the TS types `Connector`, `ConnectionPublic`, `ConnectorItem`, `ImportResult`.

- [ ] **Step 1: Write the module**

```typescript
// frontend/src/lib/api/connectors.ts
import apiClient from './client'

export interface ConnectionPublic {
  id: string
  provider: string
  account_label: string
  status: string
  created?: string | null
}

export type ConnectorStatus = 'connected' | 'configured' | 'available' | 'coming_soon'

export interface Connector {
  provider: string
  display_name: string
  description: string
  status: ConnectorStatus
  connections: ConnectionPublic[]
}

export interface ConnectorItem {
  id: string
  kind: string
  title: string
  subtitle?: string | null
  mime?: string | null
  modified_at?: string | null
}

export interface ImportResult {
  accepted: string[]
  failed: { item_id: string; error: string }[]
}

export interface ImportBody {
  connection_id: string
  item_ids: string[]
  notebooks?: string[]
}

export const connectorsApi = {
  async list(): Promise<Connector[]> {
    const { data } = await apiClient.get('/connectors')
    return data
  },
  async authorize(provider: string): Promise<{ authorize_url: string }> {
    const { data } = await apiClient.get(`/connectors/${provider}/authorize`)
    return data
  },
  async items(provider: string, connectionId: string): Promise<ConnectorItem[]> {
    const { data } = await apiClient.get(`/connectors/${provider}/items`, {
      params: { connection_id: connectionId },
    })
    return data
  },
  async import(provider: string, body: ImportBody): Promise<ImportResult> {
    const { data } = await apiClient.post(`/connectors/${provider}/import`, body)
    return data
  },
  async disconnect(connectionId: string): Promise<void> {
    await apiClient.delete(`/connectors/connections/${connectionId}`)
  },
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors from `connectors.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api/connectors.ts
git commit -m "feat(connectors): add frontend connectors API module"
```

---

## Task 9: Frontend hooks

**Files:**
- Create: `frontend/src/lib/hooks/use-connectors.ts`
- Test: `frontend/src/lib/hooks/use-connectors.test.ts`

**Interfaces:**
- Consumes: `connectorsApi` (Task 8).
- Produces: `CONNECTOR_QUERY_KEYS`, `useConnectors()`, `useConnectionItems(provider, connectionId, enabled)`, `useImportItems()`, `useDisconnect()`, `useStartConnect()` (calls `authorize` then sets `window.location.href`).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/hooks/use-connectors.test.ts
import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useConnectors } from './use-connectors'

vi.mock('@/lib/api/connectors', () => ({
  connectorsApi: {
    list: vi.fn().mockResolvedValue([
      { provider: 'gdrive', display_name: 'Google Drive', description: '', status: 'available', connections: [] },
    ]),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useConnectors', () => {
  it('returns connectors from the api', async () => {
    const { result } = renderHook(() => useConnectors(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.[0].provider).toBe('gdrive')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/hooks/use-connectors.test.ts`
Expected: FAIL (module `./use-connectors` not found).

- [ ] **Step 3: Write the hooks**

```typescript
// frontend/src/lib/hooks/use-connectors.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { connectorsApi, ImportBody } from '@/lib/api/connectors'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'

export const CONNECTOR_QUERY_KEYS = {
  all: ['connectors'] as const,
  items: (provider: string, connectionId: string) =>
    ['connectors', provider, 'items', connectionId] as const,
}

export function useConnectors() {
  return useQuery({
    queryKey: CONNECTOR_QUERY_KEYS.all,
    queryFn: () => connectorsApi.list(),
  })
}

export function useConnectionItems(provider: string, connectionId: string, enabled: boolean) {
  return useQuery({
    queryKey: CONNECTOR_QUERY_KEYS.items(provider, connectionId),
    queryFn: () => connectorsApi.items(provider, connectionId),
    enabled: enabled && !!connectionId,
  })
}

export function useStartConnect() {
  const { t } = useTranslation()
  return useMutation({
    mutationFn: (provider: string) => connectorsApi.authorize(provider),
    onSuccess: (data) => { window.location.href = data.authorize_url },
    onError: (e) => toast.error(t(getApiErrorKey(e))),
  })
}

export function useImportItems(provider: string) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ImportBody) => connectorsApi.import(provider, body),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['sources'] })
      if (res.failed.length === 0) {
        toast.success(t('connections.importStarted').replace('{count}', String(res.accepted.length)))
      } else {
        toast.warning(
          t('connections.importPartial')
            .replace('{ok}', String(res.accepted.length))
            .replace('{fail}', String(res.failed.length)),
        )
      }
    },
    onError: (e) => toast.error(t(getApiErrorKey(e))),
  })
}

export function useDisconnect() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (connectionId: string) => connectorsApi.disconnect(connectionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CONNECTOR_QUERY_KEYS.all })
      toast.success(t('connections.disconnected'))
    },
    onError: (e) => toast.error(t(getApiErrorKey(e))),
  })
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/hooks/use-connectors.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hooks/use-connectors.ts frontend/src/lib/hooks/use-connectors.test.ts
git commit -m "feat(connectors): add frontend connectors hooks"
```

---

## Task 10: i18n keys + nav item

**Files:**
- Modify: every `frontend/src/lib/locales/*/index.ts` (add `navigation.connections` + a `connections` block)
- Modify: `frontend/src/components/layout/AppSidebar.tsx`
- Test: `frontend/src/lib/locales/index.test.ts` already checks locale key parity — rely on it.

**Interfaces:**
- Produces: `navigation.connections` and `connections.{title, subtitle, connected, addMore, comingSoon, connect, connectDisabledHint, disconnect, importStarted, importPartial, disconnected, pickItems, import, selectNotebook, searchItems, noItems}` in each locale.

- [ ] **Step 1: Add keys to `en-US` (source of truth)**

In `frontend/src/lib/locales/en-US/index.ts`, add to the `navigation` object:

```typescript
    connections: "Connections",
```

Add a new top-level block (near the `sources` block):

```typescript
  connections: {
    title: "Connections",
    subtitle: "Connect the tools where your company's knowledge lives.",
    connected: "Connected sources",
    addMore: "Add more",
    comingSoon: "Coming soon",
    connect: "Connect",
    connectDisabledHint: "Ask your admin to configure this connector's OAuth app.",
    disconnect: "Disconnect",
    pickItems: "Select items to import",
    import: "Import",
    selectNotebook: "Add to notebook (optional)",
    searchItems: "Search…",
    noItems: "Nothing available to import.",
    importStarted: "Importing {count} item(s) — processing in the background.",
    importPartial: "{ok} imported, {fail} failed.",
    disconnected: "Disconnected.",
  },
```

- [ ] **Step 2: Mirror the keys into every other locale**

For each of `pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN, ca-ES, de-DE, es-ES, fr-FR, it-IT, pl-PL, tr-TR`: add the same `navigation.connections` key and the same `connections` block. Translate where you can; English fallback text is acceptable for locales you can't translate (missing keys fall back to en-US anyway, but the parity test wants the keys present). Keep the exact key names.

- [ ] **Step 3: Run the locale parity test**

Run: `cd frontend && npx vitest run src/lib/locales/index.test.ts`
Expected: PASS (no missing keys across locales).

- [ ] **Step 4: Add the nav item**

In `frontend/src/components/layout/AppSidebar.tsx`, in the `collect` section's items array (next to the existing `sources` entry ~line 50), add:

```typescript
      { name: t('navigation.connections'), href: '/connections', icon: Plug },
```

Add `Plug` to the `lucide-react` import at the top of the file.

- [ ] **Step 5: Verify build compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/locales frontend/src/components/layout/AppSidebar.tsx
git commit -m "feat(connectors): add Connections nav item and i18n keys"
```

---

## Task 11: `/connections` page + connector cards

**Files:**
- Create: `frontend/src/app/(dashboard)/connections/page.tsx`
- Create: `frontend/src/components/connectors/ConnectorCard.tsx`
- Create: `frontend/src/components/connectors/ConnectedSourceCard.tsx`
- Create: `frontend/src/components/connectors/index.ts`
- Test: `frontend/src/components/connectors/ConnectorCard.test.tsx`

**Interfaces:**
- Consumes: `useConnectors`, `useStartConnect`, `useDisconnect` (Task 9); `Connector` type (Task 8).
- Produces: `<ConnectorCard connector onConnect />`, `<ConnectedSourceCard connection onDisconnect onManage />`, and the page composing "Connected sources" + "Add more" grid.

- [ ] **Step 1: Write the failing component test**

```tsx
// frontend/src/components/connectors/ConnectorCard.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ConnectorCard } from './ConnectorCard'

vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const base = { provider: 'gdrive', display_name: 'Google Drive', description: 'desc', connections: [] }

describe('ConnectorCard', () => {
  it('coming_soon card is disabled and shows the badge', () => {
    render(<ConnectorCard connector={{ ...base, status: 'coming_soon' }} onConnect={vi.fn()} />)
    expect(screen.getByText('connections.comingSoon')).toBeInTheDocument()
  })

  it('configured card fires onConnect when clicked', () => {
    const onConnect = vi.fn()
    render(<ConnectorCard connector={{ ...base, status: 'configured' }} onConnect={onConnect} />)
    fireEvent.click(screen.getByRole('button', { name: /connect/i }))
    expect(onConnect).toHaveBeenCalledWith('gdrive')
  })

  it('available-but-unconfigured card disables connect', () => {
    render(<ConnectorCard connector={{ ...base, status: 'available' }} onConnect={vi.fn()} />)
    expect(screen.getByRole('button', { name: /connect/i })).toBeDisabled()
  })
})
```

> `status: 'available'` means "adapter exists but OAuth env not set" → Connect disabled with hint. `status: 'configured'` means "env set, ready to connect" → Connect enabled. `status: 'connected'` is rendered as a `ConnectedSourceCard`, not here.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/connectors/ConnectorCard.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Write `ConnectorCard.tsx`**

```tsx
// frontend/src/components/connectors/ConnectorCard.tsx
'use client'

import { Connector } from '@/lib/api/connectors'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'

interface Props {
  connector: Connector
  onConnect: (provider: string) => void
}

export function ConnectorCard({ connector, onConnect }: Props) {
  const { t } = useTranslation()
  const comingSoon = connector.status === 'coming_soon'
  const canConnect = connector.status === 'configured'

  return (
    <div className={cn(
      'rounded-lg border p-4 flex flex-col gap-3',
      comingSoon && 'opacity-50',
    )}>
      <div className="flex items-start justify-between">
        <div>
          <div className="font-medium">{connector.display_name}</div>
          <p className="text-sm text-muted-foreground mt-1">{connector.description}</p>
        </div>
        {comingSoon && <Badge variant="secondary">{t('connections.comingSoon')}</Badge>}
      </div>
      {!comingSoon && (
        <div className="mt-auto">
          <Button
            size="sm"
            disabled={!canConnect}
            title={canConnect ? undefined : t('connections.connectDisabledHint')}
            onClick={() => onConnect(connector.provider)}
          >
            {t('connections.connect')}
          </Button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Write `ConnectedSourceCard.tsx`**

```tsx
// frontend/src/components/connectors/ConnectedSourceCard.tsx
'use client'

import { ConnectionPublic } from '@/lib/api/connectors'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

interface Props {
  connection: ConnectionPublic
  onManage: (connection: ConnectionPublic) => void
  onDisconnect: (connectionId: string) => void
}

export function ConnectedSourceCard({ connection, onManage, onDisconnect }: Props) {
  const { t } = useTranslation()
  return (
    <div className="rounded-lg border p-4 flex items-center justify-between">
      <div>
        <div className="font-medium capitalize">{connection.provider}</div>
        <p className="text-sm text-muted-foreground">{connection.account_label}</p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => onManage(connection)}>
          {t('connections.import')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDisconnect(connection.id)}>
          {t('connections.disconnect')}
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Write the barrel and the page**

```typescript
// frontend/src/components/connectors/index.ts
export { ConnectorCard } from './ConnectorCard'
export { ConnectedSourceCard } from './ConnectedSourceCard'
export { ImportItemsDialog } from './ImportItemsDialog'
```

```tsx
// frontend/src/app/(dashboard)/connections/page.tsx
'use client'

import { useState } from 'react'
import { AppShell } from '@/components/layout/AppShell'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ConnectorCard, ConnectedSourceCard, ImportItemsDialog } from '@/components/connectors'
import { useConnectors, useStartConnect, useDisconnect } from '@/lib/hooks/use-connectors'
import { ConnectionPublic } from '@/lib/api/connectors'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function ConnectionsPage() {
  const { t } = useTranslation()
  const { data: connectors, isLoading } = useConnectors()
  const startConnect = useStartConnect()
  const disconnect = useDisconnect()
  const [manage, setManage] = useState<{ provider: string; connection: ConnectionPublic } | null>(null)

  if (isLoading) return <AppShell><LoadingSpinner /></AppShell>

  const connected = (connectors ?? []).flatMap((c) =>
    c.connections.map((conn) => ({ provider: c.provider, conn })))

  return (
    <AppShell>
      <div className="max-w-4xl mx-auto p-6 space-y-8">
        <div>
          <h1 className="text-2xl font-semibold">{t('connections.title')}</h1>
          <p className="text-muted-foreground">{t('connections.subtitle')}</p>
        </div>

        {connected.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm uppercase text-muted-foreground">{t('connections.connected')}</h2>
            {connected.map(({ provider, conn }) => (
              <ConnectedSourceCard
                key={conn.id}
                connection={conn}
                onManage={(c) => setManage({ provider, connection: c })}
                onDisconnect={(id) => disconnect.mutate(id)}
              />
            ))}
          </section>
        )}

        <section className="space-y-3">
          <h2 className="text-sm uppercase text-muted-foreground">{t('connections.addMore')}</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(connectors ?? [])
              .filter((c) => c.status !== 'connected')
              .map((c) => (
                <ConnectorCard key={c.provider} connector={c}
                  onConnect={(p) => startConnect.mutate(p)} />
              ))}
          </div>
        </section>
      </div>

      {manage && (
        <ImportItemsDialog
          open={!!manage}
          provider={manage.provider}
          connectionId={manage.connection.id}
          onOpenChange={(o) => !o && setManage(null)}
        />
      )}
    </AppShell>
  )
}
```

> Confirm `AppShell` and `LoadingSpinner` import paths against an existing dashboard page (e.g. `app/(dashboard)/sources/page.tsx`) and match them exactly.

- [ ] **Step 6: Run the component test**

Run: `cd frontend && npx vitest run src/components/connectors/ConnectorCard.test.tsx`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/\(dashboard\)/connections frontend/src/components/connectors
git commit -m "feat(connectors): add /connections page and connector cards"
```

---

## Task 12: Import-items dialog + OAuth redirect handling

**Files:**
- Create: `frontend/src/components/connectors/ImportItemsDialog.tsx`
- Modify: `frontend/src/app/(dashboard)/connections/page.tsx` (handle `?connected=` / `?error=` query params)
- Test: `frontend/src/components/connectors/ImportItemsDialog.test.tsx`

**Interfaces:**
- Consumes: `useConnectionItems`, `useImportItems` (Task 9).
- Produces: `<ImportItemsDialog open provider connectionId onOpenChange />` — searchable checkbox list, Import button.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/connectors/ImportItemsDialog.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ImportItemsDialog } from './ImportItemsDialog'

const importMutate = vi.fn()
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('@/lib/hooks/use-connectors', () => ({
  useConnectionItems: () => ({
    data: [{ id: 'f1', kind: 'file', title: 'Doc One' }, { id: 'f2', kind: 'file', title: 'Doc Two' }],
    isLoading: false,
  }),
  useImportItems: () => ({ mutate: importMutate, isPending: false }),
}))

describe('ImportItemsDialog', () => {
  it('imports the selected item ids', () => {
    render(<ImportItemsDialog open provider="gdrive" connectionId="connection:1" onOpenChange={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Doc One'))
    fireEvent.click(screen.getByRole('button', { name: /import/i }))
    expect(importMutate).toHaveBeenCalledWith(
      expect.objectContaining({ connection_id: 'connection:1', item_ids: ['f1'] }),
      expect.anything(),
    )
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/connectors/ImportItemsDialog.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Write the dialog**

```tsx
// frontend/src/components/connectors/ImportItemsDialog.tsx
'use client'

import { useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useConnectionItems, useImportItems } from '@/lib/hooks/use-connectors'
import { useTranslation } from '@/lib/hooks/use-translation'

interface Props {
  open: boolean
  provider: string
  connectionId: string
  onOpenChange: (open: boolean) => void
}

export function ImportItemsDialog({ open, provider, connectionId, onOpenChange }: Props) {
  const { t } = useTranslation()
  const { data: items, isLoading } = useConnectionItems(provider, connectionId, open)
  const importItems = useImportItems(provider)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')

  const filtered = useMemo(
    () => (items ?? []).filter((i) => i.title.toLowerCase().includes(query.toLowerCase())),
    [items, query],
  )

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const onImport = () => {
    importItems.mutate(
      { connection_id: connectionId, item_ids: Array.from(selected) },
      { onSuccess: () => { setSelected(new Set()); onOpenChange(false) } },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{t('connections.pickItems')}</DialogTitle></DialogHeader>
        <Input placeholder={t('connections.searchItems')} value={query}
               onChange={(e) => setQuery(e.target.value)} />
        <div className="max-h-80 overflow-y-auto space-y-1 mt-2">
          {isLoading && <LoadingSpinner />}
          {!isLoading && filtered.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('connections.noItems')}</p>
          )}
          {filtered.map((item) => (
            <label key={item.id} className="flex items-center gap-2 py-1 cursor-pointer">
              <Checkbox
                aria-label={item.title}
                checked={selected.has(item.id)}
                onCheckedChange={() => toggle(item.id)}
              />
              <span className="text-sm truncate">{item.title}</span>
            </label>
          ))}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
          <Button disabled={selected.size === 0 || importItems.isPending} onClick={onImport}>
            {t('connections.import')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

> Confirm `Checkbox` and `Dialog*` primitives exist under `@/components/ui/`. If `Checkbox` is absent, use the existing pattern from another multi-select dialog in the repo (e.g. the notebook multi-select in `AddSourceDialog`), keeping the `aria-label={item.title}` so the test's `getByLabelText` resolves.

- [ ] **Step 4: Handle the OAuth redirect query params on the page**

In `frontend/src/app/(dashboard)/connections/page.tsx`, add near the top of the component body:

```tsx
  import { useEffect } from 'react'
  import { useSearchParams, useRouter } from 'next/navigation'
  import { toast } from 'sonner'
  // ...inside the component:
  const params = useSearchParams()
  const router = useRouter()
  useEffect(() => {
    const connected = params.get('connected')
    const error = params.get('error')
    if (connected) {
      toast.success(t('connections.disconnected') /* reuse or add a 'connected' key */)
      router.replace('/connections')
    } else if (error) {
      toast.error(t('connections.connectDisabledHint'))
      router.replace('/connections')
    }
  }, [params, router, t])
```

> Add a dedicated `connections.connectedToast` key to the locales in Task 10's block if you prefer distinct copy over reusing existing keys. Keep the effect idempotent — `router.replace` clears the query so it fires once.

- [ ] **Step 5: Run the dialog test**

Run: `cd frontend && npx vitest run src/components/connectors/ImportItemsDialog.test.tsx`
Expected: PASS.

- [ ] **Step 6: Full frontend check**

Run: `cd frontend && npm run lint && npx vitest run src/components/connectors src/lib/hooks/use-connectors.test.ts && npx tsc --noEmit`
Expected: lint clean, tests pass, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/connectors/ImportItemsDialog.tsx frontend/src/app/\(dashboard\)/connections/page.tsx
git commit -m "feat(connectors): add import-items dialog and OAuth redirect handling"
```

---

## Task 13: End-to-end manual verification

**Files:** none (manual smoke test with one real provider).

- [ ] **Step 1: Configure one provider**

Register a Google Drive OAuth app (see "What YOU need to configure"), put `GDRIVE_CLIENT_ID/SECRET` + `CONNECTORS_API_URL`/`CONNECTORS_APP_URL` in `.env`.

- [ ] **Step 2: Start the stack**

Run: `make database && make api && make worker-start && make frontend`
Expected: all four tiers up (the worker is REQUIRED — imports are async jobs).

- [ ] **Step 3: Walk the flow**

Open `http://localhost:3000/connections`. Confirm: Google Drive shows Connect enabled; SharePoint/Box/etc. show "Coming soon" disabled. Click Connect → Google consent → returns to `/connections` with a success toast and a Connected card. Click Import → pick a Doc → Import → success toast.

- [ ] **Step 4: Confirm the source landed**

Open `/sources`. The imported document appears (status may be processing, then done). If it stays queued, the worker isn't running (Step 2).

- [ ] **Step 5: Commit any fixes discovered**

```bash
git add -A
git commit -m "fix(connectors): address issues found in end-to-end verification"
```

---

## Self-review notes (for the implementer)

- **Source creation path (RESOLVED):** Task 6 creates sources via the domain layer (`Source` + `CommandService.submit_command_job`), NOT `SourceService` (a client-side HTTP wrapper). Verified against `api/routers/sources.py`. The `process_source` background command requires the worker (`make worker-start`); imported temp files (Drive binaries) must be readable by the worker process (same host in dev).
- **`repo_delete` signature:** Task 6's `disconnect` mirrors the delete pattern already in `api/routers/credentials.py`. Match that file's exact `ensure_record_id`/`repo_delete` usage.
- **Checkbox primitive:** Task 12 assumes `@/components/ui/checkbox`. If absent, reuse the repo's existing multi-select pattern (see `AddSourceDialog`), preserving `aria-label`.
- **Migration number:** if a P2–P6 migration lands on 20 before this merges, bump to the next free number in both the filenames and `async_migrate.py`.
