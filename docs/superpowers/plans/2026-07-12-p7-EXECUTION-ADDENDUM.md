# P7 Execution Addendum — reconcile plans with the LANDED codebase

> Read this BEFORE executing any P7.1–P7.4 task. The plans were written assuming
> P6's `CtxDep` / `ScopedRepository` abstraction. That abstraction did **not**
> land; instead P2/P3/P4/P5 routers scope with `get_auth_context` + manual
> `WHERE workspace = $ws` filtering. P7 MUST follow the real, landed pattern
> below. Where a plan step says `CtxDep`/`ScopedRepository`, apply this mapping.

## Base branch
Branch off `feat/auth-multitenancy` (has P2 workspace/RBAC, P3 project rename,
P4 invitations; P5 source-permissions on `feat/auth-mt-p5*`). P6 abstraction is
absent — do not wait for it.

## Mapping: plan assumption → landed reality

| Plan says | Use instead (landed) |
|---|---|
| `from api.deps import CtxDep` | `from api.deps import get_auth_context, require_role` |
| `ctx: ... = CtxDep` in a route | `ctx: AuthContext = Depends(get_auth_context)` (`from api.security import AuthContext`) |
| `get_request_context` / `RequestContext` | `AuthContext` — fields `.workspace_id: str`, `.user_id: str`, `.role: str`; helper `await ctx.project_role(project_id)` (see `api/routers/sources.py`) |
| `ScopedRepository(...)` auto-filtering | Manual `WHERE workspace = $ws` in `repo_query(...)`, exactly like `api/routers/projects.py::list_projects`. Pass `{"ws": ensure_record_id(ctx.workspace_id)}`. |
| service takes `ctx` and calls ScopedRepository | service takes explicit `workspace_id: str` (and `user_id`/`role` where needed); the router extracts them from `ctx` and passes them in |
| owner/admin gate via P6 | `require_role("owner", "admin")` from `api.deps` (already used by `projects.py`) |
| `Project` / `Source` domain | `from open_notebook.domain.notebook import Project, Source` (Source/Project already carry a `workspace` column) |

## Migration numbers (disk is at 23; 20=workspace, 21=project, 22/23 later phases)
- P7.1 `entity` / `mentions` / `part_of` → migration **24** (`24.surrealql` + `24_down.surrealql`).
- P7.2 `relates` → migration **25**.
- Confirm the next free integer at execution time (`ls open_notebook/database/migrations`) and register each in `AsyncMigrationManager` (hard-coded, not auto-discovered).

## Scoping is still MANDATORY
Every brain query (entity/mentions/part_of/relates read or write, graph API,
status, ask) filters by `workspace = ctx.workspace_id`. The leakage tests still
apply — they just assert the manual filter, not a ScopedRepository. Model the
tests on the existing tenant-isolation tests for projects/sources.

## Everything else in the plans stands
Table shapes, `Entity` model + dedup, command names, prompt paths, API response
models (`api/brain_models.py`), frontend types/hooks/store/components,
`react-force-graph-2d`, TDD RED→GREEN→REFACTOR — all unchanged.
