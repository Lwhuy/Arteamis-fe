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

# NOTE on `command` (surreal-commands' own job-queue table): deliberately NOT
# listed in GLOBAL_TABLES, NATIVE_WORKSPACE_TABLES, or
# INHERITED_WORKSPACE_TABLES above -- it doesn't fit this module's model at
# all. It has no native `workspace` column (so it can't go through
# ScopedRepository's generic get/list), but unlike a true global table its
# `result` field carries real per-tenant job output for some producers
# (podcast generation's transcript/outline/audio_file_path) -- treating it as
# purely global let ANY caller read another workspace's job result by
# guessing its job_id (the last leak found in the rollout review). Fixed at
# the service layer instead of here: the submitting workspace is stamped
# into the command row's `context` field at submission
# (api/command_service.py's submit_command_job) and checked on every
# job-status read via CommandService.get_command_status_for_workspace (used
# by GET /commands/jobs/{job_id} and GET /podcasts/jobs/{job_id}), 404ing on
# any mismatch or missing stamp. This is a bespoke context-field check, NOT a
# ScopedRepository path -- `command` still does not belong in
# NATIVE_WORKSPACE_TABLES (it has no native `workspace` column for the
# generic methods to filter on).

# Tenant/content plane — every row belongs to exactly one workspace (personal OR
# company — the filter is identical either way) and MUST be filtered by
# workspace_id on every read/write/delete. NOTE: the project table is
# PHYSICALLY named `notebook` (P3 repurpose-in-place, exposed as "project" at
# the API/UI); record ids are `notebook:<id>` and ScopedRepository derives the
# table from that prefix.
#
# This plane splits into two disjoint subsets because the generic get/list/
# create/update/delete methods below build `WHERE workspace = $workspace_id`
# directly against the table — that ONLY works for a table with a NATIVE
# `workspace` column.
#
# NATIVE_WORKSPACE_TABLES — `notebook`, `project_member`, `invitation` carry a
# real `workspace` column (`project_member`/`invitation` rows simply never
# exist for a personal workspace — a data-shape fact enforced by P3/P4
# upstream, not by this filter). Safe for the generic methods. `episode`
# (P6 rollout, migration 24) also carries a native `workspace` column, but
# unlike the other three it is OPTIONAL and NULL on every episode generated
# before migration 24 (no backfill was possible — see migration 24's own
# comment) — the generic get/list methods' `WHERE workspace = $workspace_id`
# simply never matches a NULL row, which fails closed (invisible to every
# workspace) rather than open, so this is still safe for the generic path.
#
# INHERITED_WORKSPACE_TABLES — `source`, `note`, `chat_session`,
# `source_insight`, `source_embedding` have NO native `workspace` column
# (verified against migrations 1-23: none ever adds one). They inherit
# workspace transitively via a parent: `source`/`note` via the
# `reference`/`artifact` edge to a `notebook`; `source_insight`/
# `source_embedding` via their `source`. Calling a generic method against one
# of these would build `WHERE workspace = $workspace_id` on a column that
# doesn't exist on the table — silently always-empty or erroring, never a
# correct filter. `_assert_scoped` rejects these from the generic path
# fail-closed; the caller MUST use `.raw()` with an explicit parent-join
# filter instead (see `_get_owned_source` in `api/routers/projects.py` for the
# reference-edge join pattern).
NATIVE_WORKSPACE_TABLES: frozenset[str] = frozenset(
    {"notebook", "project_member", "invitation", "episode"}
)
INHERITED_WORKSPACE_TABLES: frozenset[str] = frozenset(
    {"source", "note", "chat_session", "source_insight", "source_embedding"}
)
WORKSPACE_SCOPED_TABLES: frozenset[str] = NATIVE_WORKSPACE_TABLES | INHERITED_WORKSPACE_TABLES


def _table_of(record_id: str) -> str:
    """Table name is the record-id prefix (everything before the first ':')."""
    return record_id.split(":")[0] if ":" in record_id else record_id


def _assert_scoped(table: str) -> None:
    """Fail closed: a table must be an explicitly-classified NATIVE table to go
    through the generic get/list/create/update/delete path.

    - GLOBAL tables are rejected (never workspace-scoped).
    - INHERITED tables are rejected too — the generic path would build
      `WHERE workspace = $workspace_id` against a column that doesn't exist
      on the table. Rejected with a clear, actionable error rather than
      silently returning an empty/erroring result.
    - Unknown tables are rejected (fail closed on a new/misspelled table).
    """
    if table in GLOBAL_TABLES:
        raise InvalidInputError(
            f"{table!r} is a GLOBAL table — use raw repo_* helpers, not ScopedRepository"
        )
    if table in INHERITED_WORKSPACE_TABLES:
        raise InvalidInputError(
            f"Table {table!r} is workspace-inherited (no native `workspace` "
            "column — it inherits workspace via a parent record); the generic "
            "ScopedRepository get/list/create/update/delete methods cannot "
            "safely filter it. Use ScopedRepository.raw() with an explicit "
            "parent-join filter instead — see `_get_owned_source` in "
            "api/routers/projects.py for the reference-edge join pattern."
        )
    if table not in NATIVE_WORKSPACE_TABLES:
        raise InvalidInputError(
            f"Unknown table {table!r}; add it to NATIVE_WORKSPACE_TABLES, "
            "INHERITED_WORKSPACE_TABLES, or GLOBAL_TABLES"
        )


class ScopedRepository:
    """Workspace-scoped view over the SurrealDB repo_* helpers — uniform for a
    personal workspace (solo tenant) and a company workspace (multi-member
    tenant) alike. There is deliberately NO `kind` constructor argument: this
    class cannot distinguish personal from company even if asked to.

    Construct once per request via api.deps.get_request_context. Every method
    injects the workspace filter; there is no method that touches a scoped
    table without it.

    IMPORTANT — two different kinds of scoped table: the generic get/list/
    create/update/delete methods only work for NATIVE_WORKSPACE_TABLES
    (`notebook`, `project_member`, `invitation`, `episode`), which carry a
    real `workspace` column. INHERITED_WORKSPACE_TABLES (`source`, `note`,
    `chat_session`, `source_insight`, `source_embedding`) have NO native
    `workspace` column — they inherit it via a parent record (e.g. `source`
    via the `reference` edge to a `notebook`) — and are REJECTED by the
    generic methods with a clear error. For those, use `.raw()` with an
    explicit parent-join filter; `raw()` is the audited escape hatch for both
    kinds of table (it never table-checks).
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
