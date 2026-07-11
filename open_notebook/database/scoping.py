# open_notebook/database/scoping.py
"""Application-layer tenant scoping (the SurrealDB analogue of Postgres RLS).

SurrealDB has no row-level security, so tenant isolation is enforced here. A
ScopedRepository is constructed once per request from the caller's access-token
workspace_id (via api.deps.get_request_context) and is the ONLY sanctioned entry
point for reads/writes/deletes against workspace-scoped tables. Every read AND-s
`WHERE workspace = $workspace_id`; every write stamps `workspace`; a guessed
cross-workspace id resolves to NotFoundError (404) — never the other workspace's
row.

Uniform scoping (Option A): a workspace is either a solo (personal) tenant or
a multi-member (company) tenant. This module NEVER reads or
branches on `kind` — it only ever sees a workspace_id. That is deliberate: one
code path covers both, so there is exactly one leak surface to test, not two.
See tests/test_scoping_unit.py::test_scoped_repository_has_no_kind_parameter
for the structural guard.
"""
from typing import Any, List, Optional

from loguru import logger

from open_notebook.database.repository import (
    ensure_record_id,
    repo_create,
    repo_delete,
    repo_query,
    repo_update,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError

# ── Table-plane policy (single source of truth) ────────────────────────────────
# Identity plane — GLOBAL, never workspace-scoped. Login/workspace selection
# must read these BEFORE a workspace is active, so they can never carry a
# workspace filter. `workspace` itself is global (you don't scope a workspace
# row BY a workspace_id — that's circular); `membership` resolves which
# workspaces a user can see, via P2's own non-scoped endpoints.
GLOBAL_TABLES: frozenset[str] = frozenset(
    {"user", "auth_identity", "workspace", "membership"}
)

# Tenant/content plane — every row belongs to exactly one workspace (personal OR
# company — the filter is identical either way) and MUST be filtered by
# workspace_id on every read/write/delete. NOTE: the project table is
# PHYSICALLY named `notebook` (P3 repurpose-in-place, exposed as "project" at
# the API/UI); record ids are `notebook:<id>` and ScopedRepository derives the
# table from that prefix. `notebook`, `project_member`, `invitation` carry a
# NATIVE `workspace` column (`project_member`/`invitation` rows simply never
# exist for a personal workspace — a data-shape fact enforced by P3/P4
# upstream, not by this filter). `source`, `note`, `chat_session`,
# `source_insight`, `source_embedding` inherit workspace via their parent
# project/source and are scoped through a parent join via `raw()` (see spec
# "Data model changes").
WORKSPACE_SCOPED_TABLES: frozenset[str] = frozenset(
    {
        "notebook",  # exposed as "project"
        "source",
        "note",
        "chat_session",
        "source_insight",
        "source_embedding",
        "project_member",
        "invitation",
    }
)


def _table_of(record_id: str) -> str:
    """Table name is the record-id prefix (everything before the first ':')."""
    return record_id.split(":")[0] if ":" in record_id else record_id


def _assert_scoped(table: str) -> None:
    """Fail closed: a table must be an explicitly-classified scoped table."""
    if table in GLOBAL_TABLES:
        raise InvalidInputError(
            f"{table!r} is a GLOBAL table — use raw repo_* helpers, not ScopedRepository"
        )
    if table not in WORKSPACE_SCOPED_TABLES:
        raise InvalidInputError(
            f"Unknown table {table!r}; add it to WORKSPACE_SCOPED_TABLES or GLOBAL_TABLES"
        )


class ScopedRepository:
    """Workspace-scoped view over the SurrealDB repo_* helpers — uniform for a
    personal workspace (solo tenant) and a company workspace (multi-member
    tenant) alike. There is deliberately NO `kind` constructor argument: this
    class cannot distinguish personal from company even if asked to.

    Construct once per request via api.deps.get_request_context. Every method
    injects the workspace filter; there is no method that touches a scoped
    table without it. `raw()` is the audited escape hatch.
    """

    def __init__(self, workspace_id: str, user_id: str, role: Optional[str]):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.role = role

    @property
    def _workspace_rid(self):
        return ensure_record_id(self.workspace_id)

    # ---- reads --------------------------------------------------------------
    async def list(
        self,
        table: str,
        *,
        where: str = "",
        vars: Optional[dict] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        _assert_scoped(table)
        clauses = ["workspace = $workspace_id"]
        if where:
            clauses.append(f"({where})")  # caller predicate AND-ed, never replaces the scope
        q = f"SELECT * FROM {table} WHERE {' AND '.join(clauses)}"
        if order_by:
            q += f" ORDER BY {order_by}"  # caller MUST pre-validate via ObjectModel._validate_order_by
        if limit is not None:
            q += " LIMIT $limit"
        params: dict[str, Any] = {"workspace_id": self._workspace_rid, **(vars or {})}
        if limit is not None:
            params["limit"] = limit
        return await repo_query(q, params)

    async def get(self, record_id: str) -> dict:
        """Fetch one row by id AND workspace. A cross-workspace id → NotFoundError
        (404), deliberately indistinguishable from a genuinely missing id (no
        oracle) — including when the "other" workspace is a different user's
        personal workspace."""
        table = _table_of(record_id)
        _assert_scoped(table)
        rows = await repo_query(
            "SELECT * FROM $rid WHERE workspace = $workspace_id",
            {"rid": ensure_record_id(record_id), "workspace_id": self._workspace_rid},
        )
        if not rows:
            logger.warning(
                f"Scoped get miss: record_id={record_id} workspace_id={self.workspace_id} "
                f"user_id={self.user_id} (missing or cross-workspace)"
            )
            raise NotFoundError(f"{table} {record_id} not found")
        return rows[0]

    async def exists(self, record_id: str) -> bool:
        try:
            await self.get(record_id)
            return True
        except NotFoundError:
            return False

    # ---- writes -------------------------------------------------------------
    async def create(self, table: str, data: dict) -> dict:
        _assert_scoped(table)
        data = {**data, "workspace": self._workspace_rid}  # server-set; client workspace overwritten
        result = await repo_create(table, data)
        # repo_create's runtime return shape is inconsistent (a bare dict in some
        # SurrealDB client versions, a one-element list in others) — normalize the
        # same defensive way open_notebook.domain.base.ObjectModel.save() already
        # does, rather than assume callers get a dict back.
        if isinstance(result, list):
            return result[0]
        return result

    async def update(self, record_id: str, data: dict) -> List[dict]:
        table = _table_of(record_id)
        _assert_scoped(table)
        await self.get(record_id)  # ownership check first → 404 on cross-workspace
        data = {k: v for k, v in data.items() if k != "workspace"}  # workspace immutable post-create
        return await repo_update(table, record_id, data)

    async def delete(self, record_id: str) -> bool:
        table = _table_of(record_id)
        _assert_scoped(table)
        await self.get(record_id)  # ownership check first → 404 on cross-workspace
        await repo_delete(record_id)
        return True

    # ---- raw escape hatch (AUDITED) ----------------------------------------
    async def raw(self, query: str, vars: Optional[dict] = None) -> List[dict]:
        """For multi-table joins the helpers can't express (e.g. count(<-reference.in)).
        The caller MUST include `workspace = $workspace_id` in the query themselves;
        $workspace_id is always injected into vars. Every call site needs a
        `# scoped-raw: <reason>` comment and its own leakage test."""
        params = {"workspace_id": self._workspace_rid, **(vars or {})}
        return await repo_query(query, params)
