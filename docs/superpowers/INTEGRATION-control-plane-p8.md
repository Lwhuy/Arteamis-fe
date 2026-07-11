# Integration guide: `integration/control-plane-p8` → `feat/auth-multitenancy`

This branch (`integration/control-plane-p8`, derived from the Arteamis
control-plane / governance work, P8.1–P8.5) is prepared to merge into
`feat/auth-multitenancy`. This document explains what was done to make the
merge collision-free on migrations, and how to resolve the remaining
conflicts a real 3-way merge will surface.

## 1. Migration renumber (already applied on this branch)

`feat/auth-multitenancy` already committed governance migrations **21–27**
(P3–P7, including the "brain" work) with content that is **different** from
this branch's migrations 21–25. If merged as-is, `git merge` would see two
different files claiming the same migration numbers — a guaranteed content
collision on `open_notebook/database/async_migrate.py` and silent semantic
collision on the `.surrealql` files themselves (same filename, unrelated
schema). `28` and above is confirmed free on `feat/auth-multitenancy`.

This branch renumbers its five governance migrations off the collision
range:

| Old (this branch) | New (this branch) | Content |
|---|---|---|
| 21 / 21_down | **28 / 28_down** | `visibility` field on `source` (private/company) |
| 22 / 22_down | **29 / 29_down** | governance tables: `proposal`, `belief`, `audit_event`, `derived_from`, `promotes_to` (Promotion Bridge, P8.2) |
| 23 / 23_down | **30 / 30_down** | `decision`, `rule`, `supports` edge (P8.3) |
| 24 / 24_down | **31 / 31_down** | `work_package`, `executes` edge (Handoff, P8.4) |
| 25 / 25_down | **32 / 32_down** | `trace`, `traced_by`, `learned_from`, `updates` (Trace + Learning loop closure, P8.5) |

What changed for each:

- `git mv` of both the up and down `.surrealql` files under
  `open_notebook/database/migrations/`.
- Self-referential comment headers inside each file (e.g. `-- Migration 22:
  ...` and cross-references like "mirrors migration 22's workspace-ready
  idiom") were updated to the new numbers.
- `open_notebook/database/async_migrate.py`: the `AsyncMigration.from_file(...)`
  entries for 21–25 were renumbered to 28–32, in both `up_migrations` and
  `down_migrations`, preserving list order (`…, 20, 28, 29, 30, 31, 32`).
- The five migration test files were renamed and their path-string /
  registration-substring assertions updated to match:
  `test_migration_21_visibility.py` → `test_migration_28_visibility.py`,
  `test_migration_22_governance.py` → `test_migration_29_governance.py`,
  `test_migration_23_decision_rule.py` → `test_migration_30_decision_rule.py`,
  `test_migration_24_work_package.py` → `test_migration_31_work_package.py`,
  `test_migration_25_trace.py` → `test_migration_32_trace.py`.

**Why a non-contiguous jump (…, 20, 28, 29, 30, 31, 32) is safe to run
standalone:** `AsyncMigrationRunner` tracks the applied version by the
**list position/count** in `_sbl_migrations`, not by the filename number
(see `run_all`/`run_one_up` in `async_migrate.py`, which index into
`self.up_migrations` by `current_version`). The filename numbers are purely
a human-readable label; nothing parses them. So this branch's migration list
(1..20, 28..32 = 25 entries) runs correctly on its own.

**After the merge**, `feat/auth-multitenancy`'s 21–27 and this branch's
28–32 combine into one contiguous `up_migrations`/`down_migrations` list of
32 entries (1..32). See §2 for how to combine the two `async_migrate.py`
lists — order matters (21–27 before 28–32) even though both branches'
individual lists currently work standalone.

## 2. Other files that will conflict on the 3-way merge

None of these should be resolved by picking "ours" or "theirs" outright —
each side added independent content that the other needs. Union / keep-both
is the correct resolution in every case.

### `open_notebook/database/async_migrate.py`
Both branches append entries to `up_migrations` and `down_migrations`.
Resolve by taking the union, in ascending numeric order, of both branches'
appended entries: `feat/auth-multitenancy`'s 21–27 immediately followed by
this branch's 28–32 (do this in **both** the `up_migrations` list and the
`down_migrations` list — they must stay parallel/same length). Do **not**
take one side wholesale; each side has entries the other lacks. After
merging, `len(up_migrations) == len(down_migrations) == 32`.

### `api/main.py`
Both branches add `app.include_router(...)` calls (this branch adds
`governance.router`; `feat/auth-multitenancy` adds its own — for the
"brain" work and whatever else P3–P7 introduced). Keep **both** sets of
`include_router` calls. There's no ordering dependency between routers
registered this way, so append is safe — just don't drop either side's
lines.

### `api/models.py`
This branch adds a `visibility: str = "private"` field (see the two
occurrences at the Source-model level, tagged `# 'private' | 'company'
(P8.1)`). Keep this field — `feat/auth-multitenancy` doesn't have it and
nothing on that branch should remove it during merge resolution.

### `frontend/src/lib/locales/*/index.ts` (14 files: bn-IN, ca-ES, de-DE,
en-US, es-ES, fr-FR, it-IT, ja-JP, pl-PL, pt-BR, ru-RU, tr-TR, zh-CN, zh-TW)
Both branches add new top-level keys to each locale object (this branch adds
`controlPlane.*` and `governance.*`, e.g. `en-US/index.ts:474` and `:1092`;
`feat/auth-multitenancy` adds its own keys for auth/multitenancy UI strings).
Union the added keys in each of the 14 files — do not replace one side's
additions with the other's. `frontend/src/lib/locales/index.ts` (the
aggregator, not per-locale) is unlikely to conflict but check it registers
all locales after merge.

### `frontend/src/components/layout/AppSidebar.tsx`
This branch adds a control-plane launcher nav entry:
```
{ name: t('controlPlane.launcher'), href: '/control-plane', icon: Sparkles },
```
Keep this entry alongside whatever nav items `feat/auth-multitenancy` adds
(workspace switcher, auth-related nav, etc.) — merge as a list union, don't
let one branch's nav array silently drop the other's items.

### `frontend/src/test/setup.ts`
This branch adds a `ResizeObserver` polyfill (jsdom doesn't implement it;
needed by Radix primitives used in control-plane components). Keep it —
union with whatever `feat/auth-multitenancy` added to the same setup file.

### `Makefile` + `api/workspace_service.py`
Two small dev-environment fixes on this branch, keep both:
- `Makefile`: `start-all` uses `docker compose up -d surrealdb` (no `-f`
  flag) — the `docker-compose.dev.yml` file referenced by the old `-f` flag
  doesn't exist; every other Makefile target already omits `-f`.
- `api/workspace_service.py` (`list_memberships`): `SELECT role, workspace,
  created FROM membership ...` — `created` must be projected because the
  query does `ORDER BY created ASC`, and SurrealDB 2.6.5 rejects `ORDER BY`
  on a non-projected field. Without this, `build_session_payload` (and thus
  register/login) breaks.

If `feat/auth-multitenancy` touched these same lines for unrelated reasons,
verify both fixes still hold after merge (re-run `make start-all` and
exercise register/login).

### New files — no conflict expected
All governance domain/service/router files (backend) and
`frontend/src/components/control-plane/*` (ArtifactReader, CompanyBrainSection,
ContextSidebar, ControlPlane, ControlPlaneChat, CreateDecisionButton,
CreateWorkPackageButton/Dialog, LineagePanel, LoopWidget, ProposeButton,
Rail, ReviewInbox, ScopeSwitch, SourcesSection, TopBar, TraceSection,
WorkPackagesSection, loop-steps, plus their `*.test.tsx`/`.test.ts` files)
are entirely new paths this branch introduces. `feat/auth-multitenancy` has
no files at these paths, so git will add them without conflict.

## 3. Verify after merge

Run all of these post-merge, in order:

1. `uv run pytest tests/` — expect the full merged suite green (this
   branch alone is 598 passed; `feat/auth-multitenancy`'s own suite plus
   this branch's should combine additively, modulo any shared fixtures).
2. `npm run test` (inside `frontend/`) — frontend unit/component tests,
   including the control-plane component tests listed above.
3. `npm run build` (inside `frontend/`) — catches locale-union mistakes
   (missing/duplicate keys) and TypeScript errors from the `AppSidebar.tsx`
   / `api/models.py`-consuming frontend code.
4. Re-run the isolated live-DB governance smoke test (start
   `make database && make api && make worker-start && make frontend`,
   confirm the merged migration list runs cleanly 1..32 against a fresh
   SurrealDB, and exercise the control-plane UI end-to-end: propose →
   accept → decision/rule → work package → trace).
