# P4 — Invitation Flow (Workspace + Project) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a workspace owner/admin invite a person by email to a `kind="company"` workspace
or a specific project within it; accepting the invite links/creates the `user`, activates a
`membership` (and a `project_member` for project invites), with email delivery that falls back
to a copyable shareable link when no email provider is configured. Inviting into a
`kind="personal"` workspace is always rejected with `403` — personal workspaces are solo tenants
and never have members beyond their owner.

**Architecture:** A new `invitation` SurrealDB table (migration 22) + an `Invitation` domain
model (linked to `workspace`, never `company`), an `api/invitation_service.py` holding token
generation/hashing, the workspace-kind guard, and the create/accept/revoke state machine, an
`api/email_service.py` provider abstraction (console/resend/smtp) with a shareable-link
fallback, and an `api/routers/invitations.py` router mounted at `/api`. The frontend adds an
invite dialog + members panel and a public `/invite/[token]` accept page, wired through
TanStack Query hooks on the single `apiClient`.

**Tech Stack:** FastAPI, SurrealDB (custom async repository), Pydantic, `hashlib`/`secrets`
(stdlib token+hash), `httpx` (resend), `smtplib` (smtp), Next.js 16 App Router, TanStack Query,
Zustand, axios, sonner, i18next.

**Spec:** docs/superpowers/specs/2026-07-11-p4-invitation-design.md
**Depends on:** P1 (users/auth: `user`, `api/security.py` `AuthContext`, `create_identity_token`,
JWTAuthMiddleware in `api/auth.py`), P2 (`workspace`/`membership`, `api/deps.py` with
`get_identity`/`get_auth_context`/`require_role`, `open_notebook/domain/workspace.py`
`Workspace`/`Membership` domain models, `POST /auth/switch-workspace/{id}`, frontend
`useSwitchWorkspace()` hook), P3 (`project`=repurposed `notebook` carrying a `workspace` link,
`project_member`, `Project`/`ProjectMember` domain, `useProjects` hook). · **Branch:**
feat/auth-multitenancy

## Global Constraints
- Async-first: every SurrealDB call is awaited (no sync DB access).
- All frontend HTTP goes through the single axios `apiClient` (frontend/src/lib/api/client.ts)
  — never a 2nd instance.
- i18n MANDATORY: every UI string via t('section.key'); add the key to ALL 14 locales in the
  `resources` map under frontend/src/lib/locales/. The parity test
  `frontend/src/lib/locales/index.test.ts` iterates EVERY locale in `resources` and fails the
  build if any of the 14 locale files drift, so add the new keys to every locale the folder
  contains. The 7 enforced locales (en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN) get real
  translations; the other 7 (it-IT, fr-FR, ca-ES, es-ES, de-DE, pl-PL, tr-TR) get English
  fallback values.
- New SurrealDB schema = new migration pair `22.surrealql` + `22_down.surrealql`, registered by
  hand in `open_notebook/database/async_migrate.py` (migrations are NOT auto-discovered).
  Canonical numbering: P1=19, P2=20, P3=21, P4=22.
- Physical SurrealDB table for a project stays `notebook` (P3 repurpose-in-place). There is NO
  physical `project` table; `invitation.project` is `option<record<notebook>>`.
- Record links are stored as plain strings in domain models (e.g. `"user:abc"`,
  `"workspace:xyz"`), matching P2's `Workspace`/`Membership` models.
- **Invitations only ever target a `kind="company"` workspace.** `create_invitation` loads the
  workspace and 403s before any other check if `workspace.kind != "company"`. This is a
  permanent data-model rule (a personal workspace always has exactly one member, its owner), not
  a feature cut.
- Backend errors: raise typed exceptions from `open_notebook.exceptions` where a mapping exists
  (`NotFoundError`→404, `InvalidInputError`→400). Codes with no typed mapping (403/409/410) are
  raised as `HTTPException(status_code=...)` — the spec sanctions this explicitly for these
  statuses.
- Backend tests: `uv run pytest tests/`. Frontend (inside `frontend/`): `npm run lint`, `npm run
  test`, `npm run build`.

---

### Consumed interfaces from P1/P2/P3 (do NOT redefine — import them)

These are produced by earlier phases; this plan imports them exactly as written:

- `api/security.py` (P1): `@dataclass AuthContext` with fields `user_id: str`, `workspace_id:
  str | None`, `role: str | None`; `create_identity_token(user_id: str) -> str`.
- `api/deps.py` (P2):
  - `async def get_identity() -> str` — returns the caller's `user_id` from an identity **or**
    workspace-scoped access token (decodes the `Authorization: Bearer` header itself; usable
    before any company workspace is active).
  - `async def get_auth_context() -> AuthContext` — requires a workspace-scoped access token.
  - `def require_role(*roles: str)` — returns an async dependency that yields the `AuthContext`
    and raises `HTTPException(403)` when `ctx.role` is not in `roles`.
- `open_notebook/domain/workspace.py` (P2): `class Workspace(ObjectModel)` (`table_name=
  "workspace"`, fields `name`, `slug`, `kind` ("personal"|"company"), `owner`), `class
  Membership(ObjectModel)` (`table_name="membership"`, fields `user`, `workspace`, `role`,
  `status="active"`).
- `open_notebook/domain/user.py` (P1): `class User(ObjectModel)` (`table_name="user"`, field
  `email: str`, lower-cased) with `@classmethod async def get_by_email(cls, email) ->
  Optional[User]`.
- `open_notebook/domain/notebook.py` (P3): `class Project(ObjectModel)` (`table_name="notebook"`,
  fields incl. `workspace`, `owner`, `name`), `class ProjectMember(ObjectModel)`
  (`table_name="project_member"`, fields `project`, `user`, `role`, `status="active"`).
- `api/auth.py` (P1): `JWTAuthMiddleware` (replaces `PasswordAuthMiddleware`), constructed in
  `api/main.py` with an `excluded_paths` list; skips auth entirely when `JWT_SECRET` is unset
  (dev/test).
- Frontend: `frontend/src/lib/stores/auth-store.ts` exposes `token`, `user`, `isAuthenticated`,
  `activeWorkspaceId`, `role`, `memberships`, `applyToken(res)` (P2). `useSwitchWorkspace()`
  (`frontend/src/lib/hooks/use-workspaces.ts`, P2) is the mutation this plan's accept page calls
  to enter a workspace after accepting (it internally calls `applyToken`). `useToast`
  (`frontend/src/lib/hooks/use-toast.ts`), `useTranslation`
  (`frontend/src/lib/hooks/use-translation.ts`), `getApiErrorKey`
  (`frontend/src/lib/utils/error-handler.ts`).

If P1/P2/P3 have not landed yet, this plan cannot be executed — its tasks import the above
symbols directly.

---

### Task 1: Migration 22 — `invitation` table + registration

**Files:**
- Create: `open_notebook/database/migrations/22.surrealql`
- Create: `open_notebook/database/migrations/22_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (append `22` to `up_migrations` and
  `22_down` to `down_migrations`, after the P3-added `21` entries)
- Test: `tests/test_p4_migration_22.py`

**Interfaces:**
- Consumes: `AsyncMigrationManager` (`open_notebook/database/async_migrate.py`);
  `AsyncMigration.from_file` (strips `--` comment lines, joins the rest with spaces, so every
  statement must be `;`-terminated and no code may follow an inline `--`).
- Produces: physical table `invitation` with fields `workspace, email, role, project,
  token_hash, status, invited_by, expires_at, created, updated` and indexes
  `idx_invitation_token_hash` (UNIQUE), `idx_invitation_workspace_status`,
  `idx_invitation_workspace_email`.

- [ ] **Step 1: Write the failing test** — `tests/test_p4_migration_22.py`:
```python
"""P4 migration 22 must exist and be registered in the hard-coded manager lists."""

from pathlib import Path

MIGRATIONS = Path("open_notebook/database/migrations")


def test_migration_22_files_exist_with_schema():
    up = (MIGRATIONS / "22.surrealql").read_text()
    down = (MIGRATIONS / "22_down.surrealql").read_text()

    assert "DEFINE TABLE IF NOT EXISTS invitation" in up
    assert "record<workspace>" in up  # invitation links a workspace, not a company
    assert "token_hash" in up
    assert "idx_invitation_token_hash" in up and "UNIQUE" in up
    assert "idx_invitation_workspace_status" in up
    assert "idx_invitation_workspace_email" in up
    assert "option<record<notebook>>" in up  # project link points at the physical notebook table
    assert "REMOVE TABLE IF EXISTS invitation" in down


def test_migration_22_registered_in_manager():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "22.surrealql" in src
    assert "22_down.surrealql" in src
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p4_migration_22.py -q` — Expected: FAIL (files missing → `FileNotFoundError`, and `"22.surrealql"` not in `async_migrate.py`).

- [ ] **Step 3: Write minimal implementation** —

`open_notebook/database/migrations/22.surrealql`:
```surql
-- Migration 22: Invitations (workspace + project scoped)
DEFINE TABLE IF NOT EXISTS invitation SCHEMALESS;

DEFINE FIELD IF NOT EXISTS workspace  ON TABLE invitation TYPE record<workspace>;
DEFINE FIELD IF NOT EXISTS email      ON TABLE invitation TYPE string ASSERT string::is::email($value);
DEFINE FIELD IF NOT EXISTS role       ON TABLE invitation TYPE string ASSERT $value IN ["owner", "admin", "member"];
DEFINE FIELD IF NOT EXISTS project    ON TABLE invitation TYPE option<record<notebook>>;
DEFINE FIELD IF NOT EXISTS token_hash ON TABLE invitation TYPE string;
DEFINE FIELD IF NOT EXISTS status     ON TABLE invitation TYPE string ASSERT $value IN ["pending", "accepted", "revoked", "expired"] DEFAULT "pending";
DEFINE FIELD IF NOT EXISTS invited_by ON TABLE invitation TYPE record<user>;
DEFINE FIELD IF NOT EXISTS expires_at ON TABLE invitation TYPE datetime;
DEFINE FIELD IF NOT EXISTS created    ON TABLE invitation TYPE option<datetime>;
DEFINE FIELD IF NOT EXISTS updated    ON TABLE invitation TYPE option<datetime>;

DEFINE INDEX IF NOT EXISTS idx_invitation_token_hash ON TABLE invitation FIELDS token_hash UNIQUE;
DEFINE INDEX IF NOT EXISTS idx_invitation_workspace_status ON TABLE invitation FIELDS workspace, status;
DEFINE INDEX IF NOT EXISTS idx_invitation_workspace_email ON TABLE invitation FIELDS workspace, email;
```

> NOTE: keep each `DEFINE ...` on a single physical line ending in `;`. `AsyncMigration.from_file` joins all non-comment lines with spaces; a statement split across two `--`-free lines still works, but never place code after an inline `--`.

`open_notebook/database/migrations/22_down.surrealql`:
```surql
REMOVE TABLE IF EXISTS invitation;
```

In `open_notebook/database/async_migrate.py`, append the P4 entry to each list. After the P3
line `AsyncMigration.from_file("open_notebook/database/migrations/21.surrealql"),` in
`up_migrations`, add:
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/22.surrealql"
            ),
```
After the P3 line `AsyncMigration.from_file("open_notebook/database/migrations/21_down.surrealql"),` in `down_migrations`, add:
```python
            AsyncMigration.from_file(
                "open_notebook/database/migrations/22_down.surrealql"
            ),
```
(The `up_migrations`/`down_migrations` lists must stay index-aligned and contiguous: `...19, 20, 21, 22`.)

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p4_migration_22.py -q` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add open_notebook/database/migrations/22.surrealql open_notebook/database/migrations/22_down.surrealql open_notebook/database/async_migrate.py tests/test_p4_migration_22.py && git commit -m "P4: add invitation table migration 22"`

---

### Task 2: `Invitation` domain model

**Files:**
- Create: `open_notebook/domain/invitation.py`
- Modify: `open_notebook/domain/__init__.py` (import `Invitation` so `ObjectModel.get()`
  polymorphic resolution finds it at startup)
- Test: `tests/test_p4_invitation_domain.py`

**Interfaces:**
- Consumes: `ObjectModel` (`open_notebook/domain/base.py`) — inherited `save()`/`get()`/
  `delete()`, `_prepare_save_data()` honoring `nullable_fields`; `repo_query`,
  `ensure_record_id` (`open_notebook/database/repository.py`).
- Produces: `class Invitation(ObjectModel)` with `table_name="invitation"`, fields `workspace,
  email, role, project(Optional), token_hash, status="pending", invited_by, expires_at`;
  methods `is_expired() -> bool` and `@classmethod async def get_by_token_hash(cls, token_hash:
  str) -> Optional["Invitation"]`.

- [ ] **Step 1: Write the failing test** — `tests/test_p4_invitation_domain.py`:
```python
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from open_notebook.domain.invitation import Invitation


def _make(**over):
    base = dict(
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        token_hash="deadbeef",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    base.update(over)
    return Invitation(**base)


def test_defaults_and_nullable_project():
    inv = _make()
    assert inv.status == "pending"
    assert inv.project is None
    # A workspace invite must persist project=None (nullable_fields lets it through).
    assert "project" in inv._prepare_save_data()
    assert inv._prepare_save_data()["project"] is None


def test_is_expired_true_and_false():
    assert _make(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)).is_expired() is True
    assert _make(expires_at=datetime.now(timezone.utc) + timedelta(days=1)).is_expired() is False
    # Naive datetimes coming back from SurrealDB are treated as UTC.
    naive_past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    assert _make(expires_at=naive_past).is_expired() is True


@pytest.mark.asyncio
async def test_get_by_token_hash_returns_none_when_absent():
    with patch(
        "open_notebook.domain.invitation.repo_query", new_callable=AsyncMock
    ) as q:
        q.return_value = []
        assert await Invitation.get_by_token_hash("nope") is None
        q.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_token_hash_hydrates_row():
    row = dict(
        id="invitation:1",
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        project=None,
        token_hash="abc",
        status="pending",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    with patch(
        "open_notebook.domain.invitation.repo_query", new_callable=AsyncMock
    ) as q:
        q.return_value = [row]
        inv = await Invitation.get_by_token_hash("abc")
        assert inv is not None and inv.id == "invitation:1" and inv.status == "pending"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p4_invitation_domain.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'open_notebook.domain.invitation'`.

- [ ] **Step 3: Write minimal implementation** — `open_notebook/domain/invitation.py`:
```python
from datetime import datetime, timezone
from typing import ClassVar, Optional

from pydantic import field_validator

from open_notebook.database.repository import repo_query
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
```

In `open_notebook/domain/__init__.py`, register the model so polymorphic `get()` can resolve `invitation:` ids at startup:
```python
"""
Domain models for Open Notebook.

This module exports the core domain models used throughout the application.
"""

from open_notebook.domain.invitation import Invitation

__all__: list[str] = ["Invitation"]
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p4_invitation_domain.py -q` — Expected: PASS (4 tests).

- [ ] **Step 5: Commit** — `git add open_notebook/domain/invitation.py open_notebook/domain/__init__.py tests/test_p4_invitation_domain.py && git commit -m "P4: add Invitation domain model"`

---

### Task 3: `api/email_service.py` — provider abstraction + shareable-link fallback

**Files:**
- Create: `api/email_service.py`
- Test: `tests/test_p4_email_service.py`

**Interfaces:**
- Consumes: `httpx` (already a dependency), stdlib `smtplib`, `os.getenv`.
- Produces: `async def send_invite_email(to_email, invite_url, workspace_name, project_name) ->
  bool` — returns `True` only when actually delivered; `console` (default) returns `False`
  (triggers the shareable-link fallback); a delivery failure is logged and returns `False`,
  never raises into the request path.

- [ ] **Step 1: Write the failing test** — `tests/test_p4_email_service.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api import email_service


@pytest.mark.asyncio
async def test_console_provider_returns_false(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    ok = await email_service.send_invite_email(
        "a@example.com", "http://localhost:3000/invite/tok", "Acme", None
    )
    assert ok is False  # not delivered -> caller falls back to a share link


@pytest.mark.asyncio
async def test_resend_provider_posts_and_returns_true(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@acme.test")

    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("api.email_service.httpx.AsyncClient", return_value=client):
        ok = await email_service.send_invite_email(
            "a@example.com", "http://localhost:3000/invite/tok", "Acme", "Roadmap"
        )
    assert ok is True
    client.post.assert_awaited_once()
    args, kwargs = client.post.call_args
    assert args[0] == "https://api.resend.com/emails"
    assert kwargs["json"]["to"] == ["a@example.com"]


@pytest.mark.asyncio
async def test_resend_failure_is_swallowed_and_returns_false(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "no-reply@acme.test")
    with patch("api.email_service.httpx.AsyncClient", side_effect=RuntimeError("boom")):
        ok = await email_service.send_invite_email(
            "a@example.com", "http://x/invite/t", "Acme", None
        )
    assert ok is False  # never raises into the request path
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p4_email_service.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'api.email_service'`.

- [ ] **Step 3: Write minimal implementation** — `api/email_service.py`:
```python
"""Invitation email delivery. Provider chosen by EMAIL_PROVIDER.

There is no email infrastructure elsewhere in Arteamis-fe, so `console` is the
default and it does NOT deliver: it returns False, which makes the invitation
endpoint return a copyable shareable link instead. `resend` and `smtp` do real
delivery. A delivery failure is logged and returns False (fall back to the link)
— it never raises into the request path.

Mirrors the provider-selection pattern of
arteamis-system/backend/app/auth/email_sender.py (there used for single-purpose
OTP delivery; here adapted to a generic invite email with a workspace/project
context line).
"""

import os
from typing import Optional

import httpx
from loguru import logger


def _provider() -> str:
    return os.getenv("EMAIL_PROVIDER", "console").strip().lower()


def _subject_and_body(workspace_name: str, project_name: Optional[str], invite_url: str) -> tuple[str, str]:
    where = f'the "{project_name}" project in {workspace_name}' if project_name else workspace_name
    subject = f"You're invited to {workspace_name} on Arteamis"
    body = (
        f"You have been invited to join {where} on Arteamis.\n\n"
        f"Accept your invitation here:\n{invite_url}\n\n"
        f"This link expires in 7 days. If you did not expect this, you can ignore this email."
    )
    return subject, body


async def _send_resend(to_email: str, subject: str, body: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}"},
            json={
                "from": os.getenv("EMAIL_FROM"),
                "to": [to_email],
                "subject": subject,
                "text": body,
            },
        )
        resp.raise_for_status()


async def _send_smtp(to_email: str, subject: str, body: str) -> None:
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = os.getenv("EMAIL_FROM", "")
    msg["To"] = to_email
    host = os.getenv("SMTP_HOST", "localhost")
    port = int(os.getenv("SMTP_PORT", "587"))
    # smtplib is blocking; acceptable for a low-volume invite send.
    with smtplib.SMTP(host, port) as server:
        server.starttls()
        user = os.getenv("SMTP_USER")
        if user:
            server.login(user, os.getenv("SMTP_PASSWORD", ""))
        server.send_message(msg)


async def send_invite_email(
    to_email: str,
    invite_url: str,
    workspace_name: str,
    project_name: Optional[str] = None,
) -> bool:
    """Return True only when the email was actually delivered."""
    provider = _provider()
    subject, body = _subject_and_body(workspace_name, project_name, invite_url)
    try:
        if provider == "resend":
            await _send_resend(to_email, subject, body)
            return True
        if provider == "smtp":
            await _send_smtp(to_email, subject, body)
            return True
        # console (default): do not deliver; only log the link in DEBUG dev.
        if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
            logger.info(f"[invite] {to_email} -> {invite_url}")
        return False
    except Exception as e:
        logger.warning(f"Invite email delivery failed for {to_email}: {e}")
        return False
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p4_email_service.py -q` — Expected: PASS (3 tests).

- [ ] **Step 5: Commit** — `git add api/email_service.py tests/test_p4_email_service.py && git commit -m "P4: add email_service with shareable-link fallback"`

---

### Task 4: `api/invitation_service.py` — token gen, create (with personal-workspace guard), accept state machine, revoke

**Files:**
- Create: `api/invitation_service.py`
- Test: `tests/test_p4_invitation_service.py`

**Interfaces:**
- Consumes: `Invitation` (Task 2); `Workspace`, `Membership` (P2
  `open_notebook/domain/workspace.py`); `User` (P1 `open_notebook/domain/user.py`,
  `get_by_email`); `Project`, `ProjectMember` (P3 `open_notebook/domain/notebook.py`);
  `repo_query`, `ensure_record_id` (repository); `NotFoundError`, `InvalidInputError`
  (`open_notebook.exceptions`).
- Produces:
  - `generate_token() -> tuple[str, str]` → `(raw, token_hash)`.
  - `hash_token(raw: str) -> str`.
  - `build_invite_url(raw_token: str) -> str`.
  - `async def _get_workspace(workspace_id: str) -> Workspace` (404 wrapper, independently
    mockable so the personal-workspace guard is unit-testable in isolation).
  - `async def create_invitation(workspace_id, inviter_user_id, email, role, project_id=None) ->
    tuple[Invitation, str]` — **403 if `workspace.kind != "company"`**, checked first.
  - `async def accept_invitation(raw_token: str, user_id: str) -> dict` → `{workspace_id, role,
    project_id, membership_status}`.
  - `async def revoke_invitation(workspace_id: str, invitation_id: str) -> Invitation`.
  - `async def preview_invitation(raw_token: str) -> dict` → sanitized preview (no secrets).
  - `async def list_invitations(workspace_id: str, status: Optional[str]) -> list[Invitation]`.

- [ ] **Step 1: Write the failing test** — `tests/test_p4_invitation_service.py`:
```python
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api import invitation_service as svc
from open_notebook.domain.invitation import Invitation


def _inv(**over):
    base = dict(
        id="invitation:1",
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        project=None,
        token_hash=svc.hash_token("raw-token"),
        status="pending",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    base.update(over)
    return Invitation(**base)


def _workspace(kind="company", id="workspace:acme"):
    return SimpleNamespace(id=id, kind=kind, name="Acme")


def test_generate_token_returns_raw_and_matching_sha256():
    raw, token_hash = svc.generate_token()
    assert raw and token_hash != raw
    assert token_hash == hashlib.sha256(raw.encode()).hexdigest()


def test_build_invite_url_uses_env(monkeypatch):
    monkeypatch.setenv("OPEN_NOTEBOOK_APP_URL", "https://app.test")
    assert svc.build_invite_url("abc") == "https://app.test/invite/abc"
    monkeypatch.delenv("OPEN_NOTEBOOK_APP_URL", raising=False)
    assert svc.build_invite_url("abc") == "http://localhost:3000/invite/abc"


@pytest.mark.asyncio
async def test_create_invite_into_personal_workspace_403(monkeypatch):
    """NEW v2 guard: a kind=personal workspace can never be invited into."""
    monkeypatch.setattr(
        svc, "_get_workspace", AsyncMock(return_value=_workspace(kind="personal", id="workspace:p1"))
    )
    existing_pending = AsyncMock()
    monkeypatch.setattr(svc, "_existing_pending", existing_pending)
    with pytest.raises(HTTPException) as ei:
        await svc.create_invitation("workspace:p1", "user:owner", "a@x.com", "member", None)
    assert ei.value.status_code == 403
    existing_pending.assert_not_called()  # short-circuits before any other work


@pytest.mark.asyncio
async def test_create_workspace_invite_persists_pending_with_hash(monkeypatch):
    monkeypatch.setattr(svc, "_get_workspace", AsyncMock(return_value=_workspace()))
    monkeypatch.setattr(svc, "_existing_pending", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_email_has_active_membership", AsyncMock(return_value=False))
    saved = {}

    async def fake_save(self):
        self.id = "invitation:new"
        saved["inv"] = self

    with patch.object(Invitation, "save", fake_save):
        inv, raw = await svc.create_invitation(
            "workspace:acme", "user:owner", "Alice@Example.com", "member", None
        )
    assert inv.status == "pending"
    assert inv.email == "alice@example.com"  # normalized lower-case
    assert inv.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert inv.token_hash != raw
    assert inv.project is None
    assert (inv.expires_at - datetime.now(timezone.utc)).days in (6, 7)


@pytest.mark.asyncio
async def test_create_workspace_invite_conflict_when_already_active_member(monkeypatch):
    monkeypatch.setattr(svc, "_get_workspace", AsyncMock(return_value=_workspace()))
    monkeypatch.setattr(svc, "_existing_pending", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_email_has_active_membership", AsyncMock(return_value=True))
    with pytest.raises(HTTPException) as ei:
        await svc.create_invitation("workspace:acme", "user:owner", "a@x.com", "member", None)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_create_rotates_existing_pending_invite(monkeypatch):
    monkeypatch.setattr(svc, "_get_workspace", AsyncMock(return_value=_workspace()))
    existing = _inv(token_hash="OLDHASH")
    monkeypatch.setattr(svc, "_existing_pending", AsyncMock(return_value=existing))
    monkeypatch.setattr(svc, "_email_has_active_membership", AsyncMock(return_value=False))
    with patch.object(Invitation, "save", AsyncMock()):
        inv, raw = await svc.create_invitation(
            "workspace:acme", "user:owner", "alice@example.com", "member", None
        )
    assert inv.id == "invitation:1"  # rotated the same row
    assert inv.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert inv.token_hash != "OLDHASH"


@pytest.mark.asyncio
async def test_accept_unknown_token_404(monkeypatch):
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=None))
    from open_notebook.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await svc.accept_invitation("raw-token", "user:alice")


@pytest.mark.asyncio
async def test_accept_non_pending_410(monkeypatch):
    monkeypatch.setattr(
        Invitation, "get_by_token_hash", AsyncMock(return_value=_inv(status="revoked"))
    )
    with pytest.raises(HTTPException) as ei:
        await svc.accept_invitation("raw-token", "user:alice")
    assert ei.value.status_code == 410


@pytest.mark.asyncio
async def test_accept_expired_flips_status_and_410(monkeypatch):
    inv = _inv(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))
    save = AsyncMock()
    monkeypatch.setattr(Invitation, "save", save)
    with pytest.raises(HTTPException) as ei:
        await svc.accept_invitation("raw-token", "user:alice")
    assert ei.value.status_code == 410
    assert inv.status == "expired"
    save.assert_awaited()  # lazily persisted the flip


@pytest.mark.asyncio
async def test_accept_email_mismatch_403(monkeypatch):
    inv = _inv(email="alice@example.com")
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))

    class _U:
        email = "bob@example.com"

    from open_notebook.domain import user as user_mod

    monkeypatch.setattr(user_mod.User, "get", AsyncMock(return_value=_U()))
    with pytest.raises(HTTPException) as ei:
        await svc.accept_invitation("raw-token", "user:bob")
    assert ei.value.status_code == 403
    assert inv.status == "pending"  # unchanged


@pytest.mark.asyncio
async def test_accept_workspace_invite_activates_membership(monkeypatch):
    inv = _inv(email="alice@example.com", role="admin")
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))

    class _U:
        email = "alice@example.com"

    from open_notebook.domain import user as user_mod

    monkeypatch.setattr(user_mod.User, "get", AsyncMock(return_value=_U()))
    upsert_m = AsyncMock()
    monkeypatch.setattr(svc, "_upsert_workspace_membership", upsert_m)
    monkeypatch.setattr(Invitation, "save", AsyncMock())

    result = await svc.accept_invitation("raw-token", "user:alice")
    upsert_m.assert_awaited_once_with("user:alice", "workspace:acme", "admin")
    assert result == {
        "workspace_id": "workspace:acme",
        "role": "admin",
        "project_id": None,
        "membership_status": "active",
    }
    assert inv.status == "accepted"


@pytest.mark.asyncio
async def test_accept_project_invite_activates_workspace_and_project_member(monkeypatch):
    inv = _inv(email="alice@example.com", role="admin", project="notebook:proj")
    monkeypatch.setattr(Invitation, "get_by_token_hash", AsyncMock(return_value=inv))

    class _U:
        email = "alice@example.com"

    from open_notebook.domain import user as user_mod

    monkeypatch.setattr(user_mod.User, "get", AsyncMock(return_value=_U()))
    upsert_m = AsyncMock()
    upsert_p = AsyncMock()
    monkeypatch.setattr(svc, "_upsert_workspace_membership", upsert_m)
    monkeypatch.setattr(svc, "_upsert_project_member", upsert_p)
    monkeypatch.setattr(Invitation, "save", AsyncMock())

    result = await svc.accept_invitation("raw-token", "user:alice")
    upsert_m.assert_awaited_once_with("user:alice", "workspace:acme", "member")  # shell access
    upsert_p.assert_awaited_once_with("user:alice", "notebook:proj", "admin")
    assert result["project_id"] == "notebook:proj"
    assert result["role"] == "admin"
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p4_invitation_service.py -q` — Expected: FAIL with `ModuleNotFoundError: No module named 'api.invitation_service'`.

- [ ] **Step 3: Write minimal implementation** — `api/invitation_service.py`:
```python
"""Invitation lifecycle: create (workspace/project), accept (state machine), revoke.

Routers stay thin (api/AGENTS.md); all validation and DB work lives here. Status
codes without a typed-exception mapping (403/409/410) are raised as HTTPException
per the P4 spec; 404/400 use the typed exceptions the global handlers already map.

v2 guard: invitations only ever target a kind="company" workspace. A
kind="personal" workspace always has exactly one member (its owner) and is never
invitable — create_invitation 403s before any other validation when the target
workspace is personal, regardless of the caller's role.
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.invitation import Invitation
from open_notebook.domain.notebook import Project, ProjectMember
from open_notebook.domain.user import User
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import InvalidInputError, NotFoundError

INVITE_TTL_DAYS = 7


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def build_invite_url(raw_token: str) -> str:
    base = os.getenv("OPEN_NOTEBOOK_APP_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/invite/{raw_token}"


async def _get_workspace(workspace_id: str) -> Workspace:
    try:
        return await Workspace.get(workspace_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found")


async def _existing_pending(workspace_id: str, email: str, project_id: Optional[str]) -> Optional[Invitation]:
    """The pending invite for the same (workspace, email, project) scope, if any."""
    result = await repo_query(
        """
        SELECT * FROM invitation
        WHERE workspace = $workspace AND email = $email AND project = $project AND status = 'pending'
        LIMIT 1
        """,
        {
            "workspace": ensure_record_id(workspace_id),
            "email": email,
            "project": ensure_record_id(project_id) if project_id else None,
        },
    )
    return Invitation(**result[0]) if result else None


async def _email_has_active_membership(workspace_id: str, email: str) -> bool:
    result = await repo_query(
        """
        SELECT id FROM membership
        WHERE workspace = $workspace AND status = 'active'
          AND user IN (SELECT VALUE id FROM user WHERE email = $email)
        LIMIT 1
        """,
        {"workspace": ensure_record_id(workspace_id), "email": email},
    )
    return bool(result)


async def _email_has_active_project_member(project_id: str, email: str) -> bool:
    result = await repo_query(
        """
        SELECT id FROM project_member
        WHERE project = $project AND status = 'active'
          AND user IN (SELECT VALUE id FROM user WHERE email = $email)
        LIMIT 1
        """,
        {"project": ensure_record_id(project_id), "email": email},
    )
    return bool(result)


async def create_invitation(
    workspace_id: str,
    inviter_user_id: str,
    email: str,
    role: str,
    project_id: Optional[str] = None,
) -> tuple[Invitation, str]:
    workspace = await _get_workspace(workspace_id)
    if workspace.kind != "company":
        # Personal workspaces are solo tenants (exactly one member, ever) — this
        # is a permanent data-model rule, not a role check, so it applies to
        # every caller including the personal workspace's own owner.
        raise HTTPException(
            status_code=403, detail="Cannot invite members into a personal workspace"
        )

    email = email.strip().lower()
    if role not in ("admin", "member"):
        raise InvalidInputError("role must be 'admin' or 'member'")

    if project_id is None:
        # Workspace invite.
        if await _email_has_active_membership(workspace_id, email):
            raise HTTPException(status_code=409, detail="User is already a member of this workspace")
    else:
        # Project invite: the project must belong to this workspace.
        try:
            project = await Project.get(project_id)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Project not found")
        if project.workspace != workspace_id:
            raise HTTPException(status_code=404, detail="Project not found")
        if await _email_has_active_project_member(project_id, email):
            raise HTTPException(status_code=409, detail="User is already a member of this project")

    raw, token_hash = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)

    existing = await _existing_pending(workspace_id, email, project_id)
    if existing is not None:
        # Rotate the token/expiry on the existing row (old raw token stops resolving).
        existing.token_hash = token_hash
        existing.expires_at = expires_at
        existing.role = role
        existing.invited_by = inviter_user_id
        existing.status = "pending"
        await existing.save()
        return existing, raw

    invitation = Invitation(
        workspace=workspace_id,
        email=email,
        role=role,
        project=project_id,
        token_hash=token_hash,
        status="pending",
        invited_by=inviter_user_id,
        expires_at=expires_at,
    )
    await invitation.save()
    return invitation, raw


async def _upsert_workspace_membership(user_id: str, workspace_id: str, role: str) -> None:
    rows = await repo_query(
        "SELECT * FROM membership WHERE user = $user AND workspace = $workspace LIMIT 1",
        {"user": ensure_record_id(user_id), "workspace": ensure_record_id(workspace_id)},
    )
    if not rows:
        await Membership(user=user_id, workspace=workspace_id, role=role, status="active").save()
        return
    membership = Membership(**rows[0])
    if membership.status != "active":
        membership.status = "active"
        if role == "admin" and membership.role == "member":
            membership.role = "admin"
        await membership.save()
    # Already active: idempotent — never downgrade an existing higher role.


async def _upsert_project_member(user_id: str, project_id: str, role: str) -> None:
    rows = await repo_query(
        "SELECT * FROM project_member WHERE user = $user AND project = $project LIMIT 1",
        {"user": ensure_record_id(user_id), "project": ensure_record_id(project_id)},
    )
    if not rows:
        await ProjectMember(user=user_id, project=project_id, role=role, status="active").save()
        return
    member = ProjectMember(**rows[0])
    member.status = "active"
    member.role = role
    await member.save()


async def accept_invitation(raw_token: str, user_id: str) -> dict:
    inv = await Invitation.get_by_token_hash(hash_token(raw_token))
    if inv is None:
        raise NotFoundError("Invitation not found")
    if inv.status != "pending":
        raise HTTPException(status_code=410, detail="This invitation is no longer valid")
    if inv.is_expired():
        inv.status = "expired"
        await inv.save()
        raise HTTPException(status_code=410, detail="This invitation has expired")

    user = await User.get(user_id)  # NotFoundError -> 404
    if (user.email or "").lower() != inv.email.lower():
        raise HTTPException(
            status_code=403, detail="This invitation was sent to a different email."
        )

    if inv.project is None:
        # Workspace invite: activate the workspace membership with the invited role.
        await _upsert_workspace_membership(user_id, inv.workspace, inv.role)
        result_role = inv.role
    else:
        # Project invite: ensure a workspace-shell membership, then the project member.
        await _upsert_workspace_membership(user_id, inv.workspace, "member")
        await _upsert_project_member(user_id, inv.project, inv.role)
        result_role = inv.role

    inv.status = "accepted"
    await inv.save()
    return {
        "workspace_id": inv.workspace,
        "role": result_role,
        "project_id": inv.project,
        "membership_status": "active",
    }


async def revoke_invitation(workspace_id: str, invitation_id: str) -> Invitation:
    try:
        inv = await Invitation.get(invitation_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.workspace != workspace_id:
        # Hide cross-tenant existence.
        raise HTTPException(status_code=404, detail="Invitation not found")
    inv.status = "revoked"
    await inv.save()
    return inv


async def list_invitations(workspace_id: str, status: Optional[str] = None) -> list[Invitation]:
    if status is not None and status not in ("pending", "accepted", "revoked", "expired"):
        raise InvalidInputError("Invalid status filter")
    if status:
        rows = await repo_query(
            "SELECT * FROM invitation WHERE workspace = $workspace AND status = $status ORDER BY created DESC",
            {"workspace": ensure_record_id(workspace_id), "status": status},
        )
    else:
        rows = await repo_query(
            "SELECT * FROM invitation WHERE workspace = $workspace ORDER BY created DESC",
            {"workspace": ensure_record_id(workspace_id)},
        )
    return [Invitation(**r) for r in rows]


async def preview_invitation(raw_token: str) -> dict:
    inv = await Invitation.get_by_token_hash(hash_token(raw_token))
    if inv is None:
        raise NotFoundError("Invitation not found")
    if inv.status != "pending" or inv.is_expired():
        # Never leak secrets (token_hash / invited_by); 410 = expired/revoked/used.
        raise HTTPException(status_code=410, detail="This invitation is no longer valid")

    workspace = await Workspace.get(inv.workspace)
    project_name = None
    if inv.project is not None:
        try:
            project_name = (await Project.get(inv.project)).name
        except NotFoundError:
            project_name = None
    return {
        "workspace_name": workspace.name,
        "role": inv.role,
        "email": inv.email,
        "project_name": project_name,
        "status": inv.status,
        "expired": False,
    }
```

> Import note: `Project`/`ProjectMember` come from `open_notebook/domain/notebook.py` (P3
> renamed `Notebook`→`Project` there, and added the `workspace` field). `Workspace`/`Membership`
> come from `open_notebook/domain/workspace.py` (P2). If P3 kept a `Notebook = Project` alias,
> the import above still resolves.

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p4_invitation_service.py -q` — Expected: PASS (12 tests).

- [ ] **Step 5: Commit** — `git add api/invitation_service.py tests/test_p4_invitation_service.py && git commit -m "P4: add invitation_service (create/accept/revoke state machine + personal-workspace guard)"`

---

### Task 5: Pydantic schemas + `api/routers/invitations.py` + wiring + public-path middleware

**Files:**
- Modify: `api/models.py` (append the invitation schemas)
- Create: `api/routers/invitations.py`
- Modify: `api/main.py` (import + `include_router(invitations.router, prefix="/api",
  tags=["invitations"])`)
- Modify: `api/auth.py` (add `/api/invitations/` public prefix to `JWTAuthMiddleware`)
- Test: `tests/test_p4_invitations_router.py`

**Interfaces:**
- Consumes: `invitation_service` (Task 4), `email_service` (Task 3),
  `require_role`/`get_identity`/`get_auth_context` (`api/deps.py`), `AuthContext`
  (`api/security.py`).
- Produces: endpoints `POST /api/workspaces/{workspace_id}/invitations`, `GET
  /api/workspaces/{workspace_id}/invitations`, `POST
  /api/workspaces/{workspace_id}/invitations/{invitation_id}/revoke`, `GET
  /api/invitations/{token}` (public), `POST /api/invitations/{token}/accept`. Schemas
  `InvitationCreate`, `InvitationResponse`, `InvitationCreateResponse`,
  `InvitationPreviewResponse`, `AcceptInvitationResponse`.

- [ ] **Step 1: Write the failing test** — `tests/test_p4_invitations_router.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api import deps
from api.security import AuthContext


def _owner_ctx():
    return AuthContext(user_id="user:owner", workspace_id="workspace:acme", role="owner")


def _member_ctx():
    return AuthContext(user_id="user:m", workspace_id="workspace:acme", role="member")


@pytest.fixture
def app():
    from api.main import app as fastapi_app

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


def _fake_inv(**over):
    from datetime import datetime, timedelta, timezone

    from open_notebook.domain.invitation import Invitation

    base = dict(
        id="invitation:1",
        workspace="workspace:acme",
        email="alice@example.com",
        role="member",
        project=None,
        token_hash="h",
        status="pending",
        invited_by="user:owner",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    base.update(over)
    return Invitation(**base)


def test_create_invite_owner_returns_share_url_when_email_not_sent(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.create_invitation", new_callable=AsyncMock) as create, \
         patch("api.routers.invitations.invitation_service.build_invite_url", return_value="http://localhost:3000/invite/RAW"), \
         patch("api.routers.invitations.email_service.send_invite_email", new_callable=AsyncMock) as send, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        create.return_value = (_fake_inv(), "RAW")
        send.return_value = False  # console provider -> not delivered
        pname.return_value = None
        client = TestClient(app)
        resp = client.post(
            "/api/workspaces/workspace:acme/invitations",
            json={"email": "alice@example.com", "role": "member"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email_sent"] is False
    assert body["share_url"] == "http://localhost:3000/invite/RAW"
    assert body["invitation"]["status"] == "pending"


def test_create_invite_email_sent_hides_share_url(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.create_invitation", new_callable=AsyncMock) as create, \
         patch("api.routers.invitations.invitation_service.build_invite_url", return_value="http://x/invite/RAW"), \
         patch("api.routers.invitations.email_service.send_invite_email", new_callable=AsyncMock) as send, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        create.return_value = (_fake_inv(), "RAW")
        send.return_value = True
        pname.return_value = None
        client = TestClient(app)
        resp = client.post(
            "/api/workspaces/workspace:acme/invitations",
            json={"email": "alice@example.com", "role": "member"},
        )
    assert resp.status_code == 201
    assert resp.json()["email_sent"] is True
    assert resp.json()["share_url"] is None


def test_create_invite_member_role_forbidden(app):
    # require_role("owner","admin") must 403 a workspace member.
    app.dependency_overrides[deps.get_auth_context] = _member_ctx
    client = TestClient(app)
    resp = client.post(
        "/api/workspaces/workspace:acme/invitations",
        json={"email": "a@x.com", "role": "member"},
    )
    assert resp.status_code == 403


def test_create_invite_into_personal_workspace_403(app):
    # RBAC passes (owner), but the service-level personal-workspace guard still 403s.
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch(
        "api.routers.invitations.invitation_service.create_invitation", new_callable=AsyncMock
    ) as create:
        create.side_effect = HTTPException(
            status_code=403, detail="Cannot invite members into a personal workspace"
        )
        client = TestClient(app)
        resp = client.post(
            "/api/workspaces/workspace:acme/invitations",
            json={"email": "a@x.com", "role": "member"},
        )
    assert resp.status_code == 403
    assert "personal workspace" in resp.json()["detail"]


def test_create_invite_cross_workspace_404(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx  # scoped to workspace:acme
    client = TestClient(app)
    resp = client.post(
        "/api/workspaces/workspace:other/invitations",
        json={"email": "a@x.com", "role": "member"},
    )
    assert resp.status_code == 404  # token's workspace != path workspace


def test_list_invites_owner(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.list_invitations", new_callable=AsyncMock) as lst, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        lst.return_value = [_fake_inv()]
        pname.return_value = None
        client = TestClient(app)
        resp = client.get("/api/workspaces/workspace:acme/invitations?status=pending")
    assert resp.status_code == 200
    assert resp.json()[0]["email"] == "alice@example.com"


def test_revoke_invite_owner(app):
    app.dependency_overrides[deps.get_auth_context] = _owner_ctx
    with patch("api.routers.invitations.invitation_service.revoke_invitation", new_callable=AsyncMock) as rev, \
         patch("api.routers.invitations._project_name", new_callable=AsyncMock) as pname:
        rev.return_value = _fake_inv(status="revoked")
        pname.return_value = None
        client = TestClient(app)
        resp = client.post("/api/workspaces/workspace:acme/invitations/invitation:1/revoke")
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


def test_preview_is_public_and_returns_no_secrets(app):
    with patch("api.routers.invitations.invitation_service.preview_invitation", new_callable=AsyncMock) as prev:
        prev.return_value = {
            "workspace_name": "Acme",
            "role": "member",
            "email": "alice@example.com",
            "project_name": None,
            "status": "pending",
            "expired": False,
        }
        client = TestClient(app)
        resp = client.get("/api/invitations/RAWTOKEN")
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_name"] == "Acme"
    assert "token_hash" not in body and "invited_by" not in body


def test_preview_expired_410(app):
    with patch("api.routers.invitations.invitation_service.preview_invitation", new_callable=AsyncMock) as prev:
        prev.side_effect = HTTPException(status_code=410, detail="This invitation is no longer valid")
        client = TestClient(app)
        resp = client.get("/api/invitations/RAWTOKEN")
    assert resp.status_code == 410


def test_accept_as_identity_user(app):
    app.dependency_overrides[deps.get_identity] = lambda: "user:alice"
    with patch("api.routers.invitations.invitation_service.accept_invitation", new_callable=AsyncMock) as acc:
        acc.return_value = {
            "workspace_id": "workspace:acme",
            "role": "member",
            "project_id": None,
            "membership_status": "active",
        }
        client = TestClient(app)
        resp = client.post("/api/invitations/RAWTOKEN/accept")
    assert resp.status_code == 200
    assert resp.json() == {
        "workspace_id": "workspace:acme",
        "role": "member",
        "project_id": None,
        "membership_status": "active",
    }
    acc.assert_awaited_once_with("RAWTOKEN", "user:alice")
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p4_invitations_router.py -q` — Expected: FAIL (`api.routers.invitations` does not exist; router not registered → 404s).

- [ ] **Step 3: Write minimal implementation** —

Append to `api/models.py` (near the other `*Create`/`*Response` schemas; `EmailStr` is available
once P1 added `email-validator` — `from pydantic import EmailStr` at top of the file with the
other pydantic imports):
```python
# --- Invitations (P4) ---
class InvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member"]
    project_id: Optional[str] = None


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    status: str
    invited_by: str
    expires_at: str
    created: str


class InvitationCreateResponse(BaseModel):
    invitation: InvitationResponse
    email_sent: bool
    share_url: Optional[str] = None


class InvitationPreviewResponse(BaseModel):
    workspace_name: str
    role: str
    email: str
    project_name: Optional[str] = None
    status: str
    expired: bool


class AcceptInvitationResponse(BaseModel):
    workspace_id: str
    role: str
    project_id: Optional[str] = None
    membership_status: str
```
Ensure `EmailStr` is imported at the top of `api/models.py`:
```python
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
```

`api/routers/invitations.py`:
```python
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from api import email_service, invitation_service
from api.deps import get_identity, require_role
from api.models import (
    AcceptInvitationResponse,
    InvitationCreate,
    InvitationCreateResponse,
    InvitationPreviewResponse,
    InvitationResponse,
)
from api.security import AuthContext
from open_notebook.domain.invitation import Invitation
from open_notebook.domain.notebook import Project
from open_notebook.exceptions import NotFoundError

router = APIRouter()


async def _project_name(project_id: Optional[str]) -> Optional[str]:
    if not project_id:
        return None
    try:
        return (await Project.get(project_id)).name
    except NotFoundError:
        return None


def _to_response(inv: Invitation, project_name: Optional[str]) -> InvitationResponse:
    return InvitationResponse(
        id=str(inv.id or ""),
        email=inv.email,
        role=inv.role,
        project_id=inv.project,
        project_name=project_name,
        status=inv.status,
        invited_by=inv.invited_by,
        expires_at=str(inv.expires_at),
        created=str(inv.created or ""),
    )


def _assert_workspace_scope(ctx: AuthContext, workspace_id: str) -> None:
    # The workspace-scoped token must match the path workspace; else hide existence.
    if ctx.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Workspace not found")


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=InvitationCreateResponse,
    status_code=201,
)
async def create_invitation(
    workspace_id: str,
    body: InvitationCreate,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    _assert_workspace_scope(ctx, workspace_id)
    invitation, raw_token = await invitation_service.create_invitation(
        workspace_id=workspace_id,
        inviter_user_id=ctx.user_id,
        email=body.email,
        role=body.role,
        project_id=body.project_id,
    )
    project_name = await _project_name(invitation.project)
    invite_url = invitation_service.build_invite_url(raw_token)
    email_sent = await email_service.send_invite_email(
        invitation.email, invite_url, ctx.workspace_id or "", project_name
    )
    return InvitationCreateResponse(
        invitation=_to_response(invitation, project_name),
        email_sent=email_sent,
        share_url=None if email_sent else invite_url,
    )


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=List[InvitationResponse],
)
async def list_invitations(
    workspace_id: str,
    status: Optional[str] = Query(None, description="Filter by status, e.g. pending"),
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    _assert_workspace_scope(ctx, workspace_id)
    invitations = await invitation_service.list_invitations(workspace_id, status)
    return [_to_response(inv, await _project_name(inv.project)) for inv in invitations]


@router.post(
    "/workspaces/{workspace_id}/invitations/{invitation_id}/revoke",
    response_model=InvitationResponse,
)
async def revoke_invitation(
    workspace_id: str,
    invitation_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin")),
):
    _assert_workspace_scope(ctx, workspace_id)
    inv = await invitation_service.revoke_invitation(workspace_id, invitation_id)
    return _to_response(inv, await _project_name(inv.project))


@router.get("/invitations/{token}", response_model=InvitationPreviewResponse)
async def preview_invitation(token: str):
    """Public: preview an invitation by its raw token (no secrets returned)."""
    data = await invitation_service.preview_invitation(token)
    return InvitationPreviewResponse(**data)


@router.post("/invitations/{token}/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(token: str, user_id: str = Depends(get_identity)):
    data = await invitation_service.accept_invitation(token, user_id)
    return AcceptInvitationResponse(**data)
```

In `api/main.py`, add `invitations` to the routers import block and register it. In the `from
api.routers import (...)` list add `invitations,` (alphabetical placement near `insights`), then
after `app.include_router(insights.router, ...)` add:
```python
app.include_router(invitations.router, prefix="/api", tags=["invitations"])
```

In `api/auth.py` (the `JWTAuthMiddleware` introduced by P1), make the public invitation-preview
reachable when auth is enabled. The middleware already skips exact-match `excluded_paths`; add a
prefix bypass so `/api/invitations/...` is public — the `accept` endpoint under it
re-authenticates via its own `Depends(get_identity)`, so this is safe. Add a module-level
constant and one guard in `dispatch` (place the guard right after the existing
`excluded_paths` check):
```python
# Public route prefixes (token-scoped, reachable before a workspace is active).
# `/api/invitations/{token}` preview is fully public; `/accept` under it
# re-checks auth via its own get_identity dependency.
PUBLIC_PATH_PREFIXES = ("/api/invitations/",)
```
```python
        if any(request.url.path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
            return await call_next(request)
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p4_invitations_router.py -q` — Expected: PASS (10 tests).

- [ ] **Step 5: Commit** — `git add api/models.py api/routers/invitations.py api/main.py api/auth.py tests/test_p4_invitations_router.py && git commit -m "P4: invitations router + schemas + public preview route"`

---

### Task 6: `GET /api/workspaces/{workspace_id}/members` (adds it since P2's spec does not ship it)

**Files:**
- Modify: `api/workspace_service.py` (add `list_members`; created by P2)
- Modify: `api/models.py` (add `MemberResponse`)
- Modify: `api/routers/invitations.py` (add the members route — cohabits with the invitations
  surface this phase owns)
- Test: `tests/test_p4_members_endpoint.py`

**Interfaces:**
- Consumes: `require_role` (`api/deps.py`), `repo_query`/`ensure_record_id`.
- Produces: `async def list_members(workspace_id: str) -> list[dict]` and `GET
  /api/workspaces/{workspace_id}/members -> List[MemberResponse]`.

> If P2 already shipped this exact endpoint, SKIP this task and point the frontend Members panel
> at P2's route instead. Confirm by grepping: `grep -rn "workspaces/{workspace_id}/members\|/members" api/routers/`.

- [ ] **Step 1: Write the failing test** — `tests/test_p4_members_endpoint.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.security import AuthContext


@pytest.fixture
def app():
    from api.main import app as fastapi_app

    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


def test_members_list_for_member(app):
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id="user:m", workspace_id="workspace:acme", role="member"
    )
    with patch("api.routers.invitations.workspace_service.list_members", new_callable=AsyncMock) as lm:
        lm.return_value = [
            {"user_id": "user:1", "email": "a@x.com", "display_name": "A", "role": "owner", "status": "active"}
        ]
        client = TestClient(app)
        resp = client.get("/api/workspaces/workspace:acme/members")
    assert resp.status_code == 200
    assert resp.json()[0]["role"] == "owner"


def test_members_cross_workspace_404(app):
    app.dependency_overrides[deps.get_auth_context] = lambda: AuthContext(
        user_id="user:m", workspace_id="workspace:acme", role="member"
    )
    client = TestClient(app)
    assert client.get("/api/workspaces/workspace:other/members").status_code == 404
```

- [ ] **Step 2: Run test, verify it fails** — Run: `uv run pytest tests/test_p4_members_endpoint.py -q` — Expected: FAIL (`workspace_service.list_members` missing / route 404).

- [ ] **Step 3: Write minimal implementation** —

In `api/models.py` add:
```python
class MemberResponse(BaseModel):
    user_id: str
    email: str
    display_name: Optional[str] = None
    role: str
    status: str
```

In `api/workspace_service.py` add (mirrors P2's `list_memberships` join shape, but scoped to one
workspace's active members rather than one user's memberships across workspaces):
```python
async def list_members(workspace_id: str) -> list[dict]:
    """Active members of a workspace, joined to their user for name/email."""
    from open_notebook.database.repository import ensure_record_id, repo_query

    rows = await repo_query(
        """
        SELECT user.id AS user_id, user.email AS email,
               user.display_name AS display_name, role, status
        FROM membership
        WHERE workspace = $workspace AND status = 'active'
        ORDER BY role
        FETCH user
        """,
        {"workspace": ensure_record_id(workspace_id)},
    )
    return [
        {
            "user_id": str(r.get("user_id", "")),
            "email": r.get("email", ""),
            "display_name": r.get("display_name"),
            "role": r.get("role", "member"),
            "status": r.get("status", "active"),
        }
        for r in rows
    ]
```

In `api/routers/invitations.py`, add the import and route:
```python
from api import workspace_service  # add to the existing `from api import ...` line group
from api.models import MemberResponse  # add to the existing api.models import
```
```python
@router.get("/workspaces/{workspace_id}/members", response_model=List[MemberResponse])
async def list_workspace_members(
    workspace_id: str,
    ctx: AuthContext = Depends(require_role("owner", "admin", "member")),
):
    _assert_workspace_scope(ctx, workspace_id)
    members = await workspace_service.list_members(workspace_id)
    return [MemberResponse(**m) for m in members]
```

- [ ] **Step 4: Run test, verify it passes** — Run: `uv run pytest tests/test_p4_members_endpoint.py -q` — Expected: PASS (2 tests).

- [ ] **Step 5: Commit** — `git add api/workspace_service.py api/models.py api/routers/invitations.py tests/test_p4_members_endpoint.py && git commit -m "P4: GET workspace members endpoint"`

---

### Task 7: Frontend types + API module (`invitations.ts`)

**Files:**
- Modify: `frontend/src/lib/types/api.ts` (append invitation types)
- Create: `frontend/src/lib/api/invitations.ts`
- Test: `frontend/src/lib/api/invitations.test.ts`

**Interfaces:**
- Consumes: the single `apiClient` (`frontend/src/lib/api/client.ts`).
- Produces: `invitationsApi = { list, create, revoke, preview, accept, members }`; types
  `InvitationResponse`, `InvitationCreateResponse`, `InvitationPreviewResponse`,
  `AcceptInvitationResponse`, `MemberResponse`, `CreateInvitationRequest`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/api/invitations.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

import apiClient from './client'
import { invitationsApi } from './invitations'

const mocked = apiClient as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn> }

describe('invitationsApi', () => {
  beforeEach(() => {
    mocked.get.mockReset()
    mocked.post.mockReset()
  })

  it('create posts to the workspace invitations endpoint', async () => {
    mocked.post.mockResolvedValue({ data: { email_sent: false, share_url: 'http://x/invite/t', invitation: {} } })
    const res = await invitationsApi.create('workspace:acme', { email: 'a@x.com', role: 'member' })
    expect(mocked.post).toHaveBeenCalledWith('/workspaces/workspace:acme/invitations', {
      email: 'a@x.com',
      role: 'member',
    })
    expect(res.share_url).toBe('http://x/invite/t')
  })

  it('list requests with a status param', async () => {
    mocked.get.mockResolvedValue({ data: [] })
    await invitationsApi.list('workspace:acme', 'pending')
    expect(mocked.get).toHaveBeenCalledWith('/workspaces/workspace:acme/invitations', {
      params: { status: 'pending' },
    })
  })

  it('preview hits the public token endpoint', async () => {
    mocked.get.mockResolvedValue({ data: { workspace_name: 'Acme' } })
    await invitationsApi.preview('RAW')
    expect(mocked.get).toHaveBeenCalledWith('/invitations/RAW')
  })

  it('accept posts to the token accept endpoint', async () => {
    mocked.post.mockResolvedValue({ data: { workspace_id: 'workspace:acme' } })
    await invitationsApi.accept('RAW')
    expect(mocked.post).toHaveBeenCalledWith('/invitations/RAW/accept')
  })

  it('members lists workspace members', async () => {
    mocked.get.mockResolvedValue({ data: [] })
    await invitationsApi.members('workspace:acme')
    expect(mocked.get).toHaveBeenCalledWith('/workspaces/workspace:acme/members')
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run (inside `frontend/`): `npm run test -- src/lib/api/invitations.test.ts` — Expected: FAIL (cannot resolve `./invitations`).

- [ ] **Step 3: Write minimal implementation** —

Append to `frontend/src/lib/types/api.ts`:
```ts
// --- Invitations (P4) ---
export interface InvitationResponse {
  id: string
  email: string
  role: 'admin' | 'member'
  project_id: string | null
  project_name: string | null
  status: 'pending' | 'accepted' | 'revoked' | 'expired'
  invited_by: string
  expires_at: string
  created: string
}

export interface CreateInvitationRequest {
  email: string
  role: 'admin' | 'member'
  project_id?: string | null
}

export interface InvitationCreateResponse {
  invitation: InvitationResponse
  email_sent: boolean
  share_url: string | null
}

export interface InvitationPreviewResponse {
  workspace_name: string
  role: 'admin' | 'member'
  email: string
  project_name: string | null
  status: string
  expired: boolean
}

export interface AcceptInvitationResponse {
  workspace_id: string
  role: string
  project_id: string | null
  membership_status: string
}

export interface MemberResponse {
  user_id: string
  email: string
  display_name: string | null
  role: 'owner' | 'admin' | 'member'
  status: string
}
```

`frontend/src/lib/api/invitations.ts`:
```ts
import apiClient from './client'
import {
  InvitationResponse,
  CreateInvitationRequest,
  InvitationCreateResponse,
  InvitationPreviewResponse,
  AcceptInvitationResponse,
  MemberResponse,
} from '@/lib/types/api'

export const invitationsApi = {
  list: async (workspaceId: string, status?: string) => {
    const response = await apiClient.get<InvitationResponse[]>(
      `/workspaces/${workspaceId}/invitations`,
      { params: status ? { status } : undefined },
    )
    return response.data
  },

  create: async (workspaceId: string, data: CreateInvitationRequest) => {
    const response = await apiClient.post<InvitationCreateResponse>(
      `/workspaces/${workspaceId}/invitations`,
      data,
    )
    return response.data
  },

  revoke: async (workspaceId: string, invitationId: string) => {
    const response = await apiClient.post<InvitationResponse>(
      `/workspaces/${workspaceId}/invitations/${invitationId}/revoke`,
    )
    return response.data
  },

  preview: async (token: string) => {
    const response = await apiClient.get<InvitationPreviewResponse>(`/invitations/${token}`)
    return response.data
  },

  accept: async (token: string) => {
    const response = await apiClient.post<AcceptInvitationResponse>(
      `/invitations/${token}/accept`,
    )
    return response.data
  },

  members: async (workspaceId: string) => {
    const response = await apiClient.get<MemberResponse[]>(`/workspaces/${workspaceId}/members`)
    return response.data
  },
}
```

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- src/lib/api/invitations.test.ts` — Expected: PASS (5 tests).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/types/api.ts frontend/src/lib/api/invitations.ts frontend/src/lib/api/invitations.test.ts && git commit -m "P4: frontend invitations api module + types"`

---

### Task 8: Frontend hooks + query keys + 410 error mapping

**Files:**
- Modify: `frontend/src/lib/api/query-client.ts` (add `invitations` / `members` keys)
- Modify: `frontend/src/lib/utils/error-handler.ts` (map invite messages to i18n keys)
- Create: `frontend/src/lib/hooks/use-invitations.ts`
- Test: `frontend/src/lib/hooks/use-invitations.test.tsx`

**Interfaces:**
- Consumes: `invitationsApi` (Task 7), `QUERY_KEYS`, `useToast`, `useTranslation`,
  `getApiErrorKey`, `useSwitchWorkspace` (P2, `frontend/src/lib/hooks/use-workspaces.ts`).
- Produces: `useInvitations`, `useCreateInvitation`, `useRevokeInvitation`, `useMembers`,
  `useInvitationPreview`, `useAcceptInvitation`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/hooks/use-invitations.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('@/lib/api/invitations', () => ({
  invitationsApi: {
    create: vi.fn(),
    list: vi.fn(),
    revoke: vi.fn(),
    members: vi.fn(),
    preview: vi.fn(),
    accept: vi.fn(),
  },
}))
vi.mock('@/lib/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { invitationsApi } from '@/lib/api/invitations'
import { useCreateInvitation } from './use-invitations'

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useCreateInvitation', () => {
  beforeEach(() => vi.clearAllMocks())

  it('returns share_url from the mutation result', async () => {
    ;(invitationsApi.create as ReturnType<typeof vi.fn>).mockResolvedValue({
      email_sent: false,
      share_url: 'http://x/invite/t',
      invitation: { id: 'invitation:1' },
    })
    const { result } = renderHook(() => useCreateInvitation('workspace:acme'), { wrapper })
    const res = await result.current.mutateAsync({ email: 'a@x.com', role: 'member' })
    expect(res.share_url).toBe('http://x/invite/t')
    expect(invitationsApi.create).toHaveBeenCalledWith('workspace:acme', {
      email: 'a@x.com',
      role: 'member',
    })
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- src/lib/hooks/use-invitations.test.tsx` — Expected: FAIL (cannot resolve `./use-invitations`).

- [ ] **Step 3: Write minimal implementation** —

In `frontend/src/lib/api/query-client.ts`, add two keys to the `QUERY_KEYS` object (after
`notebook`):
```ts
  invitations: (workspaceId: string) => ['invitations', workspaceId] as const,
  members: (workspaceId: string) => ['members', workspaceId] as const,
```

In `frontend/src/lib/utils/error-handler.ts`, add three entries to `ERROR_MAP`:
```ts
  "This invitation has expired": "apiErrors.invitationExpired",
  "This invitation is no longer valid": "apiErrors.invitationExpired",
  "This invitation was sent to a different email.": "apiErrors.emailMismatch",
```

`frontend/src/lib/hooks/use-invitations.ts`:
```ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { invitationsApi } from '@/lib/api/invitations'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateInvitationRequest } from '@/lib/types/api'

export function useInvitations(workspaceId: string, status?: string) {
  return useQuery({
    queryKey: [...QUERY_KEYS.invitations(workspaceId), { status }],
    queryFn: () => invitationsApi.list(workspaceId, status),
    enabled: !!workspaceId,
  })
}

export function useMembers(workspaceId: string) {
  return useQuery({
    queryKey: QUERY_KEYS.members(workspaceId),
    queryFn: () => invitationsApi.members(workspaceId),
    enabled: !!workspaceId,
  })
}

export function useCreateInvitation(workspaceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: CreateInvitationRequest) => invitationsApi.create(workspaceId, data),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.invitations(workspaceId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.members(workspaceId) })
      toast({
        title: t('common.success'),
        // If the email wasn't sent, the dialog surfaces the copyable share link.
        description: res.email_sent ? t('invitations.emailedSuccess') : t('invitations.copyLinkTitle'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useRevokeInvitation(workspaceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (invitationId: string) => invitationsApi.revoke(workspaceId, invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.invitations(workspaceId) })
      toast({ title: t('common.success'), description: t('invitations.revokeSuccess') })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useInvitationPreview(token: string) {
  return useQuery({
    queryKey: ['invitation-preview', token],
    queryFn: () => invitationsApi.preview(token),
    enabled: !!token,
    retry: false,
  })
}

export function useAcceptInvitation() {
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (token: string) => invitationsApi.accept(token),
    onSuccess: () => {
      toast({ title: t('common.success'), description: t('invitations.acceptSuccess') })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}
```

> The accept page (Task 10) calls `useAcceptInvitation()` for the `POST /invitations/{token}/accept`
> call, then separately calls P2's `useSwitchWorkspace()` (`frontend/src/lib/hooks/use-workspaces.ts`)
> with the accept response's `workspace_id` to mint a workspace-scoped token and enter the
> workspace — that hook already applies the token to the auth store (`applyToken`), so this file
> does not duplicate that logic.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- src/lib/hooks/use-invitations.test.tsx` — Expected: PASS.

- [ ] **Step 5: Commit** — `git add frontend/src/lib/api/query-client.ts frontend/src/lib/utils/error-handler.ts frontend/src/lib/hooks/use-invitations.ts frontend/src/lib/hooks/use-invitations.test.tsx && git commit -m "P4: frontend invitation hooks + query keys + 410 mapping"`

---

### Task 9: Invite dialog + Members panel components

**Files:**
- Create: `frontend/src/components/members/invite-dialog.tsx`
- Create: `frontend/src/components/members/members-panel.tsx`
- Test: `frontend/src/components/members/invite-dialog.test.tsx`

**Interfaces:**
- Consumes: `ui/dialog`, `ui/input`, `ui/select`, `ui/button`, `ui/label`, `ui/badge`,
  `ui/alert-dialog` (`frontend/src/components/ui/`); hooks from Task 8; `useProjects` (P3,
  `frontend/src/lib/hooks/use-projects.ts`) for the project scope select; auth-store `role`.
- Produces: `<InviteDialog workspaceId open onOpenChange />`, `<MembersPanel workspaceId />`.
  Both are only ever mounted from a `kind="company"` workspace's settings surface (P2 gates the
  route; a personal workspace has no Members tab).

- [ ] **Step 1: Write the failing test** — `frontend/src/components/members/invite-dialog.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

const mutateAsync = vi.fn()
vi.mock('@/lib/hooks/use-invitations', () => ({
  useCreateInvitation: () => ({ mutateAsync, isPending: false }),
}))
vi.mock('@/lib/hooks/use-projects', () => ({ useProjects: () => ({ data: [] }) }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { InviteDialog } from './invite-dialog'

describe('InviteDialog', () => {
  it('shows the copy-link fallback body when a share_url is returned', async () => {
    render(
      <InviteDialog
        workspaceId="workspace:acme"
        open={true}
        onOpenChange={() => {}}
        initialShareUrl="http://localhost:3000/invite/RAW"
      />,
    )
    // The read-only URL + copy affordance render from the share-url branch.
    expect(screen.getByDisplayValue('http://localhost:3000/invite/RAW')).toBeTruthy()
    expect(screen.getByText('invitations.copyLink')).toBeTruthy()
  })

  it('renders the invite form when no share_url yet', () => {
    render(<InviteDialog workspaceId="workspace:acme" open={true} onOpenChange={() => {}} />)
    expect(screen.getByText('invitations.sendInvite')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- src/components/members/invite-dialog.test.tsx` — Expected: FAIL (cannot resolve `./invite-dialog`).

- [ ] **Step 3: Write minimal implementation** —

`frontend/src/components/members/invite-dialog.tsx`:
```tsx
'use client'

import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCreateInvitation } from '@/lib/hooks/use-invitations'
import { useProjects } from '@/lib/hooks/use-projects'
import { useTranslation } from '@/lib/hooks/use-translation'

interface InviteDialogProps {
  workspaceId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  // Test/seed hook: render the copy-link fallback body directly.
  initialShareUrl?: string
}

export function InviteDialog({ workspaceId, open, onOpenChange, initialShareUrl }: InviteDialogProps) {
  const { t } = useTranslation()
  const { data: projects } = useProjects()
  const createInvitation = useCreateInvitation(workspaceId)

  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'admin' | 'member'>('member')
  const [scopeToProject, setScopeToProject] = useState(false)
  const [projectId, setProjectId] = useState<string>('')
  const [shareUrl, setShareUrl] = useState<string | undefined>(initialShareUrl)
  const [copied, setCopied] = useState(false)

  // Dialogs don't auto-reset; the parent clears state on close (frontend AGENTS.md).
  const reset = () => {
    setEmail('')
    setRole('member')
    setScopeToProject(false)
    setProjectId('')
    setShareUrl(undefined)
    setCopied(false)
  }

  const handleClose = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }

  const handleSubmit = async () => {
    const res = await createInvitation.mutateAsync({
      email,
      role,
      project_id: scopeToProject && projectId ? projectId : null,
    })
    if (!res.email_sent && res.share_url) {
      setShareUrl(res.share_url)
    } else {
      handleClose(false)
    }
  }

  const handleCopy = async () => {
    if (shareUrl) {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{shareUrl ? t('invitations.copyLinkTitle') : t('invitations.title')}</DialogTitle>
        </DialogHeader>

        {shareUrl ? (
          <div className="space-y-3">
            <Input readOnly value={shareUrl} aria-label={t('invitations.copyLinkTitle')} />
            <Button type="button" onClick={handleCopy}>
              {copied ? t('invitations.copied') : t('invitations.copyLink')}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="invite-email">{t('invitations.emailLabel')}</Label>
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('invitations.roleLabel')}</Label>
              <Select value={role} onValueChange={(v) => setRole(v as 'admin' | 'member')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">{t('invitations.roleAdmin')}</SelectItem>
                  <SelectItem value="member">{t('invitations.roleMember')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={scopeToProject}
                  onChange={(e) => setScopeToProject(e.target.checked)}
                />
                {t('invitations.projectScopeToggle')}
              </label>
              {scopeToProject && (
                <Select value={projectId} onValueChange={setProjectId}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('invitations.projectLabel')} />
                  </SelectTrigger>
                  <SelectContent>
                    {(projects ?? []).map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                onClick={handleSubmit}
                disabled={!email || createInvitation.isPending}
              >
                {t('invitations.sendInvite')}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

`frontend/src/components/members/members-panel.tsx`:
```tsx
'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { InviteDialog } from './invite-dialog'
import { useInvitations, useMembers, useRevokeInvitation } from '@/lib/hooks/use-invitations'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useAuthStore } from '@/lib/stores/auth-store'

interface MembersPanelProps {
  workspaceId: string
}

export function MembersPanel({ workspaceId }: MembersPanelProps) {
  const { t } = useTranslation()
  const role = useAuthStore((s) => s.role)
  const canManage = role === 'owner' || role === 'admin'

  const { data: members } = useMembers(workspaceId)
  const { data: invitations } = useInvitations(workspaceId, 'pending')
  const revoke = useRevokeInvitation(workspaceId)
  const [inviteOpen, setInviteOpen] = useState(false)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('invitations.members')}</h2>
        {canManage && (
          <Button onClick={() => setInviteOpen(true)}>{t('invitations.inviteButton')}</Button>
        )}
      </div>

      <ul className="space-y-2">
        {(members ?? []).map((m) => (
          <li key={m.user_id} className="flex items-center justify-between rounded border p-3">
            <span>{m.display_name || m.email}</span>
            <Badge>{m.role}</Badge>
          </li>
        ))}
      </ul>

      {canManage && (invitations ?? []).length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground">{t('invitations.pending')}</h3>
          <ul className="space-y-2">
            {(invitations ?? []).map((inv) => (
              <li key={inv.id} className="flex items-center justify-between rounded border p-3">
                <span className="flex items-center gap-2">
                  {inv.email}
                  <Badge>{inv.role}</Badge>
                  {inv.project_name && <Badge>{inv.project_name}</Badge>}
                </span>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="destructive" size="sm">
                      {t('invitations.revoke')}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>{t('invitations.revoke')}</AlertDialogTitle>
                      <AlertDialogDescription>{t('invitations.revokeConfirm')}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                      <AlertDialogAction onClick={() => revoke.mutate(inv.id)}>
                        {t('invitations.revoke')}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </li>
            ))}
          </ul>
        </div>
      )}

      <InviteDialog workspaceId={workspaceId} open={inviteOpen} onOpenChange={setInviteOpen} />
    </div>
  )
}
```

> `useAuthStore` is the P2 store hook (`frontend/src/lib/stores/auth-store.ts`). If P2 exported
> it under a different name, adjust the import to match (the store must expose `role`). This
> panel is only ever rendered by a parent route already scoped to a `kind="company"` workspace
> (P2's workspace settings surface hides the Members tab entirely for a personal workspace) — it
> does not itself re-check `kind`.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- src/components/members/invite-dialog.test.tsx` — Expected: PASS (2 tests).

- [ ] **Step 5: Commit** — `git add frontend/src/components/members/ && git commit -m "P4: invite dialog + members panel"`

---

### Task 10: Public accept-invite page `/invite/[token]`

**Files:**
- Create: `frontend/src/app/(auth)/invite/[token]/page.tsx`
- Test: `frontend/src/app/(auth)/invite/[token]/page.test.tsx`

**Interfaces:**
- Consumes: `useInvitationPreview`, `useAcceptInvitation` (Task 8); auth-store
  `isAuthenticated` (P2); `useSwitchWorkspace` (P2, `frontend/src/lib/hooks/use-workspaces.ts`);
  `next/navigation` `useParams`/`useRouter`.
- Produces: the public accept page component (default export).

- [ ] **Step 1: Write the failing test** — `frontend/src/app/(auth)/invite/[token]/page.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

const push = vi.fn()
vi.mock('next/navigation', () => ({
  useParams: () => ({ token: 'RAW' }),
  useRouter: () => ({ push }),
}))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

const previewState = { data: undefined as unknown, isLoading: false, isError: false, error: undefined as unknown }
const switchWorkspace = { mutateAsync: vi.fn() }
vi.mock('@/lib/hooks/use-invitations', () => ({
  useInvitationPreview: () => previewState,
  useAcceptInvitation: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useSwitchWorkspace: () => switchWorkspace,
}))
const authState = { isAuthenticated: false }
vi.mock('@/lib/stores/auth-store', () => ({
  useAuthStore: (sel: (s: typeof authState) => unknown) => sel(authState),
}))

import InvitePage from './page'

describe('InvitePage', () => {
  it('shows the expired state on a 410 preview error', () => {
    previewState.isError = true
    previewState.error = { response: { status: 410 } }
    render(<InvitePage />)
    expect(screen.getByText('invitations.expiredTitle')).toBeTruthy()
  })

  it('offers sign-in / create-account when logged out', () => {
    previewState.isError = false
    previewState.error = undefined
    previewState.data = { workspace_name: 'Acme', role: 'member', email: 'a@x.com', project_name: null, status: 'pending', expired: false }
    authState.isAuthenticated = false
    render(<InvitePage />)
    expect(screen.getByText('invitations.createAccountCta')).toBeTruthy()
    expect(screen.getByText('invitations.signInCta')).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- "src/app/(auth)/invite/[token]/page.test.tsx"` — Expected: FAIL (cannot resolve `./page`).

- [ ] **Step 3: Write minimal implementation** — `frontend/src/app/(auth)/invite/[token]/page.tsx`:
```tsx
'use client'

import { useParams, useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { useInvitationPreview, useAcceptInvitation } from '@/lib/hooks/use-invitations'
import { useSwitchWorkspace } from '@/lib/hooks/use-workspaces'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useAuthStore } from '@/lib/stores/auth-store'

function statusOf(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}

export default function InvitePage() {
  const { t } = useTranslation()
  const router = useRouter()
  const params = useParams<{ token: string }>()
  const token = params?.token ?? ''

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  const { data, isLoading, isError, error } = useInvitationPreview(token)
  const accept = useAcceptInvitation()
  const switchWorkspace = useSwitchWorkspace()

  const nextUrl = `/invite/${token}`

  if (isLoading) {
    return <div className="p-8 text-center">{t('common.loading')}</div>
  }

  if (isError || !data) {
    // 410 (expired/revoked/used) or 404 -> the invitation cannot be accepted.
    const expired = statusOf(error) === 410 || statusOf(error) === 404
    return (
      <div className="mx-auto max-w-md p-8 text-center">
        <h1 className="mb-2 text-xl font-semibold">
          {expired ? t('invitations.expiredTitle') : t('common.error')}
        </h1>
        <p className="mb-4 text-muted-foreground">{t('invitations.expiredBody')}</p>
        <Button onClick={() => router.push('/login')}>{t('invitations.signInCta')}</Button>
      </div>
    )
  }

  const handleAccept = async () => {
    const res = await accept.mutateAsync(token)
    // Enter the workspace with a workspace-scoped token (P2's switch-workspace),
    // which internally applies the new token/role to the auth store.
    await switchWorkspace.mutateAsync(res.workspace_id)
    router.push('/projects')
  }

  return (
    <div className="mx-auto max-w-md p-8 text-center">
      <h1 className="mb-2 text-xl font-semibold">{t('invitations.acceptTitle')}</h1>
      <p className="mb-1">{data.workspace_name}</p>
      {data.project_name && <p className="mb-1 text-muted-foreground">{data.project_name}</p>}
      <p className="mb-4 text-muted-foreground">{data.role}</p>

      {isAuthenticated ? (
        <Button onClick={handleAccept} disabled={accept.isPending}>
          {t('invitations.acceptButton')}
        </Button>
      ) : (
        <div className="flex flex-col gap-2">
          <Button
            onClick={() =>
              router.push(
                `/signup?next=${encodeURIComponent(nextUrl)}&email=${encodeURIComponent(data.email)}`,
              )
            }
          >
            {t('invitations.createAccountCta')}
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              router.push(
                `/login?next=${encodeURIComponent(nextUrl)}&email=${encodeURIComponent(data.email)}`,
              )
            }
          >
            {t('invitations.signInCta')}
          </Button>
        </div>
      )}
    </div>
  )
}
```

> Depends on P1's `/login` and `/signup` honoring `?next=` (redirect back) and `?email=`
> (prefill/lock the email so the accepted account matches `inv.email`, avoiding the 403). If P1
> does not lock the email, accept still rejects mismatches with 403 (correct, degraded UX) — see
> spec risks. `useSwitchWorkspace` is P2's hook (`frontend/src/lib/hooks/use-workspaces.ts`); if
> P2 named it differently, swap this call for the matching hook — it must end by applying the
> returned token to the auth store the same way `useCreateWorkspace`/direct switch does.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- "src/app/(auth)/invite/[token]/page.test.tsx"` — Expected: PASS (2 tests).

- [ ] **Step 5: Commit** — `git add "frontend/src/app/(auth)/invite" && git commit -m "P4: public accept-invite page"`

---

### Task 11: i18n — `invitations` section + 2 apiErrors keys in all locales

**Files:**
- Modify: every locale file under `frontend/src/lib/locales/*/index.ts` (the parity test
  enforces all of them; the 7 ENFORCED are en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN — add
  to the rest too so `index.test.ts` stays green)
- Test: `frontend/src/lib/locales/index.test.ts` (existing parity + unused-key test; no new test
  file — this task makes it pass)

**Interfaces:**
- Consumes: nothing.
- Produces: `invitations.*` keys and `apiErrors.invitationExpired` / `apiErrors.emailMismatch`,
  referenced by Tasks 8–10.

- [ ] **Step 1: Write the failing test** — No new test. The existing
  `frontend/src/lib/locales/index.test.ts` already (a) fails if any locale is missing a key that
  en-US has (parity) and (b) fails if an en-US leaf key is not referenced anywhere in `src`
  (unused-key). Adding the `invitations.*` keys to en-US first (referenced by Tasks 8–10 code)
  makes the unused-key check pass; adding them to every other locale makes parity pass.

- [ ] **Step 2: Run test, verify it fails** — Run: `npm run test -- src/lib/locales/index.test.ts` — Expected: FAIL — either "Missing keys in <locale>: invitations.title, ..." (if en-US updated first) or an unused-key failure (if referenced-but-undefined). This confirms the parity guard is active.

- [ ] **Step 3: Write minimal implementation** — Add a top-level `invitations` block to each
locale's exported object (beside `notebooks`), and two keys to each locale's existing
`apiErrors` block. Use the exact key set below; translate the values per locale. Note the
`copyLinkTitle`/preview strings deliberately say "invitation" rather than "company invitation",
since the underlying entity is a `workspace` — no locale string should say "company" here.

en-US (`frontend/src/lib/locales/en-US/index.ts`) — add beside `notebooks:` and inside
`apiErrors:`:
```ts
  invitations: {
    title: "Invite a member",
    pending: "Pending invitations",
    members: "Members",
    inviteButton: "Invite",
    emailLabel: "Email address",
    roleLabel: "Role",
    roleAdmin: "Admin",
    roleMember: "Member",
    projectScopeToggle: "Invite to a specific project",
    projectLabel: "Project",
    sendInvite: "Send invitation",
    emailedSuccess: "Invitation emailed",
    copyLinkTitle: "Share this invite link",
    copyLink: "Copy link",
    copied: "Copied",
    revoke: "Revoke",
    revokeConfirm: "Revoke this invitation? The link will stop working.",
    revokeSuccess: "Invitation revoked",
    acceptTitle: "You've been invited",
    acceptButton: "Accept invitation",
    acceptSuccess: "Invitation accepted",
    emailMismatch: "This invitation was sent to a different email address.",
    expiredTitle: "Invitation expired or revoked",
    expiredBody: "This invitation is no longer valid. Ask an admin to send a new one.",
    createAccountCta: "Create account",
    signInCta: "Sign in",
  },
```
```ts
    // inside apiErrors:
    invitationExpired: "This invitation has expired or was revoked",
    emailMismatch: "This invitation was sent to a different email address",
```

Then replicate the same key structure with translated values in every other locale file.
Reference translations for the enforced set (values may be refined by a native speaker later):

pt-BR `invitations`: `title:"Convidar um membro", pending:"Convites pendentes", members:"Membros", inviteButton:"Convidar", emailLabel:"Endereço de e-mail", roleLabel:"Função", roleAdmin:"Administrador", roleMember:"Membro", projectScopeToggle:"Convidar para um projeto específico", projectLabel:"Projeto", sendInvite:"Enviar convite", emailedSuccess:"Convite enviado por e-mail", copyLinkTitle:"Compartilhe este link de convite", copyLink:"Copiar link", copied:"Copiado", revoke:"Revogar", revokeConfirm:"Revogar este convite? O link deixará de funcionar.", revokeSuccess:"Convite revogado", acceptTitle:"Você foi convidado", acceptButton:"Aceitar convite", acceptSuccess:"Convite aceito", emailMismatch:"Este convite foi enviado para outro e-mail.", expiredTitle:"Convite expirado ou revogado", expiredBody:"Este convite não é mais válido. Peça a um administrador para enviar um novo.", createAccountCta:"Criar conta", signInCta:"Entrar"`; `apiErrors.invitationExpired:"Este convite expirou ou foi revogado"`, `apiErrors.emailMismatch:"Este convite foi enviado para outro e-mail"`.

zh-CN `invitations`: `title:"邀请成员", pending:"待处理的邀请", members:"成员", inviteButton:"邀请", emailLabel:"电子邮箱", roleLabel:"角色", roleAdmin:"管理员", roleMember:"成员", projectScopeToggle:"邀请加入特定项目", projectLabel:"项目", sendInvite:"发送邀请", emailedSuccess:"邀请已通过邮件发送", copyLinkTitle:"分享此邀请链接", copyLink:"复制链接", copied:"已复制", revoke:"撤销", revokeConfirm:"撤销此邀请？链接将失效。", revokeSuccess:"邀请已撤销", acceptTitle:"您已被邀请", acceptButton:"接受邀请", acceptSuccess:"已接受邀请", emailMismatch:"此邀请发送至其他邮箱。", expiredTitle:"邀请已过期或被撤销", expiredBody:"此邀请已失效。请让管理员重新发送。", createAccountCta:"创建账户", signInCta:"登录"`; `apiErrors.invitationExpired:"此邀请已过期或被撤销"`, `apiErrors.emailMismatch:"此邀请发送至其他邮箱"`.

zh-TW `invitations`: `title:"邀請成員", pending:"待處理的邀請", members:"成員", inviteButton:"邀請", emailLabel:"電子郵件", roleLabel:"角色", roleAdmin:"管理員", roleMember:"成員", projectScopeToggle:"邀請加入特定專案", projectLabel:"專案", sendInvite:"傳送邀請", emailedSuccess:"邀請已透過電子郵件寄出", copyLinkTitle:"分享此邀請連結", copyLink:"複製連結", copied:"已複製", revoke:"撤銷", revokeConfirm:"撤銷此邀請？連結將失效。", revokeSuccess:"邀請已撤銷", acceptTitle:"您已被邀請", acceptButton:"接受邀請", acceptSuccess:"已接受邀請", emailMismatch:"此邀請寄送至其他電子郵件。", expiredTitle:"邀請已過期或被撤銷", expiredBody:"此邀請已失效。請聯絡管理員重新寄送。", createAccountCta:"建立帳戶", signInCta:"登入"`; `apiErrors.invitationExpired:"此邀請已過期或被撤銷"`, `apiErrors.emailMismatch:"此邀請寄送至其他電子郵件"`.

ja-JP `invitations`: `title:"メンバーを招待", pending:"保留中の招待", members:"メンバー", inviteButton:"招待", emailLabel:"メールアドレス", roleLabel:"ロール", roleAdmin:"管理者", roleMember:"メンバー", projectScopeToggle:"特定のプロジェクトに招待", projectLabel:"プロジェクト", sendInvite:"招待を送信", emailedSuccess:"招待メールを送信しました", copyLinkTitle:"この招待リンクを共有", copyLink:"リンクをコピー", copied:"コピーしました", revoke:"取り消し", revokeConfirm:"この招待を取り消しますか？リンクは無効になります。", revokeSuccess:"招待を取り消しました", acceptTitle:"招待されています", acceptButton:"招待を承認", acceptSuccess:"招待を承認しました", emailMismatch:"この招待は別のメールアドレス宛です。", expiredTitle:"招待の有効期限切れまたは取り消し済み", expiredBody:"この招待は無効です。管理者に再送を依頼してください。", createAccountCta:"アカウントを作成", signInCta:"サインイン"`; `apiErrors.invitationExpired:"この招待は期限切れまたは取り消されました"`, `apiErrors.emailMismatch:"この招待は別のメールアドレス宛です"`.

ru-RU `invitations`: `title:"Пригласить участника", pending:"Ожидающие приглашения", members:"Участники", inviteButton:"Пригласить", emailLabel:"Адрес эл. почты", roleLabel:"Роль", roleAdmin:"Администратор", roleMember:"Участник", projectScopeToggle:"Пригласить в конкретный проект", projectLabel:"Проект", sendInvite:"Отправить приглашение", emailedSuccess:"Приглашение отправлено по эл. почте", copyLinkTitle:"Поделитесь этой ссылкой-приглашением", copyLink:"Копировать ссылку", copied:"Скопировано", revoke:"Отозвать", revokeConfirm:"Отозвать приглашение? Ссылка перестанет работать.", revokeSuccess:"Приглашение отозвано", acceptTitle:"Вас пригласили", acceptButton:"Принять приглашение", acceptSuccess:"Приглашение принято", emailMismatch:"Это приглашение отправлено на другой адрес эл. почты.", expiredTitle:"Приглашение истекло или отозвано", expiredBody:"Это приглашение больше не действительно. Попросите администратора отправить новое.", createAccountCta:"Создать аккаунт", signInCta:"Войти"`; `apiErrors.invitationExpired:"Срок действия приглашения истёк или оно отозвано"`, `apiErrors.emailMismatch:"Это приглашение отправлено на другой адрес эл. почты"`.

bn-IN `invitations`: `title:"একজন সদস্যকে আমন্ত্রণ জানান", pending:"অপেক্ষমাণ আমন্ত্রণ", members:"সদস্যরা", inviteButton:"আমন্ত্রণ", emailLabel:"ইমেল ঠিকানা", roleLabel:"ভূমিকা", roleAdmin:"অ্যাডমিন", roleMember:"সদস্য", projectScopeToggle:"একটি নির্দিষ্ট প্রকল্পে আমন্ত্রণ", projectLabel:"প্রকল্প", sendInvite:"আমন্ত্রণ পাঠান", emailedSuccess:"আমন্ত্রণ ইমেল করা হয়েছে", copyLinkTitle:"এই আমন্ত্রণ লিঙ্কটি শেয়ার করুন", copyLink:"লিঙ্ক কপি করুন", copied:"কপি করা হয়েছে", revoke:"প্রত্যাহার", revokeConfirm:"এই আমন্ত্রণটি প্রত্যাহার করবেন? লিঙ্কটি আর কাজ করবে না।", revokeSuccess:"আমন্ত্রণ প্রত্যাহার করা হয়েছে", acceptTitle:"আপনাকে আমন্ত্রণ জানানো হয়েছে", acceptButton:"আমন্ত্রণ গ্রহণ করুন", acceptSuccess:"আমন্ত্রণ গৃহীত হয়েছে", emailMismatch:"এই আমন্ত্রণটি অন্য একটি ইমেলে পাঠানো হয়েছিল।", expiredTitle:"আমন্ত্রণ মেয়াদোত্তীর্ণ বা প্রত্যাহৃত", expiredBody:"এই আমন্ত্রণটি আর বৈধ নয়। একজন অ্যাডমিনকে নতুন একটি পাঠাতে বলুন।", createAccountCta:"অ্যাকাউন্ট তৈরি করুন", signInCta:"সাইন ইন"`; `apiErrors.invitationExpired:"এই আমন্ত্রণের মেয়াদ শেষ হয়েছে বা প্রত্যাহার করা হয়েছে"`, `apiErrors.emailMismatch:"এই আমন্ত্রণটি অন্য একটি ইমেলে পাঠানো হয়েছিল"`.

For the remaining non-enforced locale files present in the folder (`ca-ES`, `de-DE`, `es-ES`,
`fr-FR`, `it-IT`, `pl-PL`, `tr-TR`), the parity test still requires the keys — copy the en-US
`invitations` block and the two `apiErrors` keys into each (English values are acceptable there
since these locales are outside the enforced set; a native pass can follow). Confirm the
folder's exact list first with `ls frontend/src/lib/locales/`.

- [ ] **Step 4: Run test, verify it passes** — Run: `npm run test -- src/lib/locales/index.test.ts` — Expected: PASS (parity across all 14 locale files; no unused/missing keys).

- [ ] **Step 5: Commit** — `git add frontend/src/lib/locales && git commit -m "P4: invitations i18n keys across all 14 locales"`

---

### Task 12: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Backend suite** — Run: `uv run pytest tests/test_p4_migration_22.py tests/test_p4_invitation_domain.py tests/test_p4_email_service.py tests/test_p4_invitation_service.py tests/test_p4_invitations_router.py tests/test_p4_members_endpoint.py -q` — Expected: all PASS.
- [ ] **Step 2: Full backend suite (no regressions)** — Run: `uv run pytest tests/ -q` — Expected: PASS (P1–P3 suites included).
- [ ] **Step 3: Backend lint/type** — Run: `ruff check api/ open_notebook/ --fix && uv run python -m mypy api/invitation_service.py api/email_service.py api/routers/invitations.py open_notebook/domain/invitation.py` — Expected: clean.
- [ ] **Step 4: Frontend checks** — Run (inside `frontend/`): `npm run lint && npm run test && npm run build` — Expected: PASS (lint clean, all vitest green incl. locale parity, production build succeeds).
- [ ] **Step 5: Commit any lint fixups** — `git add -A && git commit -m "P4: lint/type fixups"` (skip if nothing changed).

---

## Self-review

**1. Spec coverage — every spec section maps to a task:**
- Data model / migration 22 (`invitation.workspace`, not `.company`) + `_down` +
  `async_migrate.py` registration → Task 1. ✅
- `Invitation` domain model (`workspace` field, `nullable_fields={"project"}`, `is_expired`,
  `get_by_token_hash`) → Task 2. ✅
- `email_service` (console/resend/smtp + shareable-link fallback, never raises,
  `workspace_name` param) → Task 3. ✅
- `invitation_service` (`generate_token` sha256, `build_invite_url` env, **`_get_workspace` +
  the personal-workspace `kind` guard checked first and unconditionally**, `create_invitation`
  workspace/project branch + rotation + 409, `accept_invitation` state machine incl.
  new-vs-existing user, email-mismatch 403, 410 expired/revoked/used, `revoke`,
  `expire_if_needed` via lazy flip, `preview_invitation` no secrets) → Task 4. ✅
- Schemas (`InvitationCreate/Response/CreateResponse/PreviewResponse/AcceptInvitationResponse`,
  all workspace-named) + router (6 endpoints incl. members, RBAC via `require_role` +
  service-level kind guard, public preview via middleware prefix) + `main.py` wiring → Task 5. ✅
- `GET /workspaces/{id}/members` (added since P2's spec does not ship it) → Task 6. ✅
- Frontend api module + types → Task 7; hooks + query keys + 410 mapping (using
  `useSwitchWorkspace`) → Task 8; invite dialog (copy-link fallback) + members panel (revoke via
  alert-dialog, owner/admin gate) → Task 9; public `/invite/[token]` accept page (logged-in vs
  logged-out branches, expired state, `useAcceptInvitation` + `useSwitchWorkspace` handoff) →
  Task 10. ✅
- i18n `invitations.*` + `apiErrors.invitationExpired`/`emailMismatch` in all **14** locales →
  Task 11. ✅
- Testing cases 1–11 (backend) mapped: create+hash (T4/T5), **personal-workspace-invite 403
  (T4/T5 — `test_create_invite_into_personal_workspace_403` at both the service and router
  layers)**, email_sent/share_url + resend mock (T3/T5), RBAC 403 + cross-tenant 404 (T5),
  accept new user membership (T4), email mismatch 403 (T4), expired/revoked/double-accept 410
  (T4), project invite dual membership + duplicate 409 (T4), rotation (T4), preview no-secrets
  (T4/T5), tenant-leakage cross-workspace (T5/T6). Frontend cases (dialog copy-link, accept
  expired, logged-out routing) → T9/T10. ✅

**2. Placeholder scan:** no "TBD/implement later/add error handling"; every code step is
complete and runnable; test bodies are full. The two documented soft-dependencies (P1
`?next=`/`?email=` login locking; the exact frontend hook name for switching workspace) are
stated with concrete fallbacks, not blanks — per PLAN_FORMAT's "smallest reasonable concrete
choice and state it".

**3. Type consistency:** `AuthContext(user_id, workspace_id, role)` used identically in Task
5/6 tests and router. `Invitation` field set (`workspace`, not `company`) is identical across
Tasks 2/4/5. Service returns the exact dict shape (`workspace_id, role, project_id,
membership_status`) that `AcceptInvitationResponse` (Task 5) and the accept page (Task 10)
consume. `invitationsApi` method names (`list/create/revoke/preview/accept/members`) match the
hooks (Task 8) and are exercised in Task 7's tests. Query keys `invitations(workspaceId)`/
`members(workspaceId)` are defined once (Task 8) and referenced consistently. i18n keys
referenced in Tasks 8–10 are exactly the set defined in Task 11 (the locale unused-key test
cross-checks this).

**4. v2 guard verification (personal-workspace invites):** the 403 guard lives in exactly one
place — `invitation_service.create_invitation`, via `_get_workspace` + `workspace.kind !=
"company"` — checked before RBAC-adjacent validation (email/role/project checks) so it applies
unconditionally, even to the personal workspace's own owner. It is exercised at the service
layer (Task 4, `test_create_invite_into_personal_workspace_403`, asserting the short-circuit
via `_existing_pending.assert_not_called()`) and at the router layer (Task 5,
`test_create_invite_into_personal_workspace_403`, asserting the HTTPException propagates as a
403 response). No code path in `list_invitations`/`revoke_invitation`/`accept_invitation` needs
its own copy of this guard: listing/revoking only ever operate on rows that could only have been
created past the guard, and accept operates on an existing `invitation` row whose `workspace`
was already validated as `kind="company"` at creation time.

**Known cross-phase assumptions (must hold before execution):** P2 exports
`get_identity`/`get_auth_context`/`require_role` from `api/deps.py`, `AuthContext` (with
`workspace_id`, not `company_id`) from `api/security.py`, and `Workspace`/`Membership` from
`open_notebook/domain/workspace.py`; P2's frontend exposes `useAuthStore` with `role`,
`isAuthenticated`, and a `useSwitchWorkspace()` hook (`frontend/src/lib/hooks/use-workspaces.ts`)
that POSTs `/auth/switch-workspace/{id}` and applies the returned token to the auth store; P3
exports `Project`/`ProjectMember` from `open_notebook/domain/notebook.py` (with a `workspace`
field on `Project`) and a `useProjects` hook returning `{id, name}[]`; P1's `JWTAuthMiddleware`
lives in `api/auth.py` with an `excluded_paths` list and passes through when `JWT_SECRET` is
unset. Each is called out at its use site with a concrete fallback where the naming might
differ.
