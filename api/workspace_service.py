"""Workspace + membership business logic (routers stay thin, per api/AGENTS.md).

Identity-plane: every read filters explicitly by the caller's user id — there is
no SurrealDB RLS to fall back on. A workspace is either kind="personal" (exactly
one per user, auto-provisioned by ensure_personal_workspace, never created via
the API) or kind="company" (explicitly created via create_workspace). P2 only
ever writes an `active` `owner` membership; `invited`/`revoked` and other roles
arrive with P4.
"""

import re
from typing import List, Optional, Tuple

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.domain.workspace import Membership, Workspace
from open_notebook.exceptions import DuplicateResourceError

_SLUG_SUB = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Human-readable slug: lower-case, non-alphanumeric -> '-', trimmed, <=40.

    Lifted from arteamis-system companies._slugify but WITHOUT the random uuid
    suffix — we keep slugs clean and let the unique index reject collisions (409).
    """
    base = _SLUG_SUB.sub("-", name.strip().lower()).strip("-")
    base = base[:40].strip("-")
    return base or "workspace"


def _personal_slug(user_id: str) -> str:
    """Deterministic, per-user slug for the auto-provisioned personal workspace.

    Tied 1:1 to the user's own record id (not the display name), so it can
    never collide across users and needs no random suffix.
    """
    local = user_id.split(":", 1)[1] if ":" in user_id else user_id
    return f"personal-{local}"[:40]


def _is_slug_conflict(error: Exception) -> bool:
    msg = str(error)
    return "idx_workspace_slug" in msg or "already contains" in msg


async def ensure_personal_workspace(user_id: str) -> Workspace:
    """Idempotent get-or-create for the caller's personal workspace + owner membership.

    Called on every login/register/refresh (via auth_service.build_session_payload)
    so a logged-in user ALWAYS has an active workspace-scoped token — this is the
    ONLY place a kind="personal" workspace is ever created; there is no API
    endpoint for it. A personal workspace's owner IS its sole member, so
    (owner, kind='personal') uniquely identifies it — no separate lookup table
    or flag on `user` is needed.
    """
    rows = await repo_query(
        "SELECT * FROM workspace WHERE owner = $user AND kind = 'personal' LIMIT 1",
        {"user": ensure_record_id(user_id)},
    )
    if rows:
        return Workspace(**rows[0])

    workspace = Workspace(
        name="Personal", slug=_personal_slug(user_id), kind="personal", owner=user_id
    )
    try:
        await workspace.save()
    except Exception as e:
        if not _is_slug_conflict(e):
            raise
        # Slug is deterministic per user, so a conflict here only means a
        # concurrent call for this SAME user already created it — re-fetch.
        rows = await repo_query(
            "SELECT * FROM workspace WHERE owner = $user AND kind = 'personal' LIMIT 1",
            {"user": ensure_record_id(user_id)},
        )
        if not rows:
            raise
        return Workspace(**rows[0])

    membership_rows = await repo_query(
        "SELECT * FROM membership WHERE user = $user AND workspace = $workspace LIMIT 1",
        {
            "user": ensure_record_id(user_id),
            "workspace": ensure_record_id(workspace.id or ""),
        },
    )
    if not membership_rows:
        membership = Membership(
            user=user_id, workspace=workspace.id or "", role="owner", status="active"
        )
        await membership.save()
    return workspace


async def create_workspace(
    user_id: str, name: str, slug: Optional[str] = None
) -> Tuple[Workspace, Membership]:
    """Create a kind="company" workspace + its owner membership. 409 on slug collision.

    There is no `kind` parameter — this function ONLY ever creates a company
    workspace; personal workspaces are exclusively created by
    ensure_personal_workspace. This is the enforcement point for "you cannot
    create/treat a personal workspace as a company via the API."
    """
    slug_value = slugify(slug) if slug else slugify(name)

    workspace = Workspace(name=name, slug=slug_value, kind="company", owner=user_id)
    try:
        await workspace.save()
    except Exception as e:
        if _is_slug_conflict(e):
            raise DuplicateResourceError("Workspace slug already exists")
        raise

    try:
        membership = Membership(
            user=user_id, workspace=workspace.id or "", role="owner", status="active"
        )
        await membership.save()
    except Exception:
        # Best-effort: avoid an orphan workspace if the membership write fails.
        try:
            await workspace.delete()
        except Exception as ce:  # pragma: no cover - cleanup best effort
            logger.warning(f"Failed to clean up orphan workspace {workspace.id}: {ce}")
        raise

    return workspace, membership


async def list_memberships(user_id: str) -> List[dict]:
    """Active memberships for a user, each with its workspace's name/slug/kind/role.

    Ordered by `created ASC`: because ensure_personal_workspace always runs
    before a user can create any company workspace, the personal workspace is
    always the first row — callers (build_session_payload, the switcher) can
    rely on this ordering without a separate `kind` filter.
    """
    rows = await repo_query(
        "SELECT role, workspace, created FROM membership "
        "WHERE user = $user AND status = 'active' "
        "ORDER BY created ASC FETCH workspace",
        {"user": ensure_record_id(user_id)},
    )
    result: List[dict] = []
    for row in rows:
        workspace = row.get("workspace")
        if not isinstance(workspace, dict):
            continue
        result.append(
            {
                "workspace_id": str(workspace.get("id", "")),
                "name": workspace.get("name", ""),
                "slug": workspace.get("slug", ""),
                "kind": workspace.get("kind", "company"),
                "role": row.get("role", "member"),
                "created": str(workspace.get("created", "")),
                "updated": str(workspace.get("updated", "")),
            }
        )
    return result


async def get_membership(user_id: str, workspace_id: str) -> Optional[Membership]:
    """Single-row membership lookup on the (user, workspace) unique index.

    Status is NOT filtered here — the caller (switch-workspace) inspects
    `membership.status` so it can distinguish 'not a member' from 'revoked'.
    Works identically whether workspace_id is the caller's personal workspace
    or a company workspace — there is no kind branch.
    """
    rows = await repo_query(
        "SELECT * FROM membership WHERE user = $user AND workspace = $workspace LIMIT 1",
        {
            "user": ensure_record_id(user_id),
            "workspace": ensure_record_id(workspace_id),
        },
    )
    if not rows:
        return None
    return Membership(**rows[0])


async def list_members(workspace_id: str) -> List[dict]:
    """Active members of a workspace, joined to their user for name/email."""
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
