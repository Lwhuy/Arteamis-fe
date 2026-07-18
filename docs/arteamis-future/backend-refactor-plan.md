# Arteamis Backend Refactor & Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Arteamis backend into alignment with the "governed studio brain" product spec — fix the critical governance tenant-isolation vulnerability, quarantine off-strategy legacy features, reshape the governance data model to the spec vocabulary (lesson / team rule / playbook / handoff / trace), and build the missing outbound context-pack + MCP + governed-execution layer that is the product's actual differentiator.

**Architecture:** The backend is FastAPI (`api/`) → domain/services (`open_notebook/`) → SurrealDB, with LangGraph for AI workflows and `surreal-commands` for async jobs. The existing governance layer is a *promotion-provenance graph* (`proposal → belief → decision/rule → work_package → trace`). This plan reshapes it via a **full rename to the spec model** (`lesson → accepted lesson → team rule → playbook → handoff → trace`) and adds the outbound serving layer. Sequencing is **security-first**: the live cross-tenant vulnerability is fixed before any new surface is built on top of the governance plane.

**Tech Stack:** Python 3.x, FastAPI, SurrealDB (SurrealQL migrations), LangGraph/LangChain, `surreal-commands` worker, Pydantic, pytest. Encryption via `OPEN_NOTEBOOK_ENCRYPTION_KEY`.

---

## Source documents

- Product spec & vocabulary: `docs/arteamis-future/arteamis_UX_Design_EN.md`, `docs/arteamis-future/prd.arteamis.pdf`, `docs/arteamis-future/vision.arteamis.pdf`, `docs/arteamis-future/0714 arteamis meeting.pdf`, `docs/arteamis-future/UX-Design-Plan.pdf`.
- This plan is backend-only. The frontend consumes the governance API; the rename in Phase 2 and the new surfaces in Phases 3–4 ripple into the FE and require a **separate follow-up frontend plan** (noted at the end).

## Audit findings this plan responds to

1. **🔴 The governance plane has zero tenant isolation.** `api/routers/governance.py` is mounted (`api/main.py:412`) with no `require_workspace`/`get_request_context` dependency; it authenticates only via `_actor(request)` reading `request.state.user_id` (`governance.py:83-87`). `api/governance_service.py` never stamps or filters `workspace`. `list_beliefs_endpoint` runs `SELECT * FROM belief WHERE status='current'` across all tenants (`governance.py:139-146`). **Any authenticated user can read/accept/mutate any tenant's proposals, beliefs, rules, work packages, and audit events.**
2. **Accept gate is a status check only.** `accept_proposal` (`governance_service.py:89-106`) checks `status == "pending"` and nothing else — no source-read attestation, no author≠reviewer, no role check, no evidence-required. Rules/decisions activate instantly on create.
3. **Audit log is append-only by convention only.** `audit_event` (migration `29.surrealql:30-36`) has no immutability guard; `AuditEvent` inherits mutable `save()`/`delete()` from `ObjectModel` (`domain/base.py`).
4. **Governance model is mis-shaped vs spec.** Missing: trust tiers, rule tiers (convention vs evidence-backed), rule levels (company vs group), `tradeoff_accepted`/`owner`/`review_at`/`next_execution_step`, a real **Reject** action, **quarantine**, **personal rules**. Extra concept `belief` (≈ accepted lesson) and `decision` (not in target loop).
5. **Context Packs / MCP / handoff execution are greenfield.** No MCP server, no context-pack assembler, no executor. `work_package.agent_brief` is an inert JSON blob nothing runs. Building blocks exist: LangGraph runtime, `provision_langchain_model()`, `api/routers/context.py` context builder, `source_permissions.visible_source_ids`.
6. **Legacy features are clean bolt-ons.** Podcasts, transformations, connectors, brain-graph — core never imports them (arrows point feature→core). Quarantine = guard router registration + a few hooks. **Do not delete transformations** — the ingest graph hard-imports it (`graphs/source.py:15-16`, `source_commands.py:10,15`).
7. **Absent-but-claimed:** secrets scanning on ingest, prompt-injection guarding, per-call cost tracking, and 4 of the 5 abuse-category security tests.

---

## Target model (after Phase 2)

| Spec object | Table (renamed from) | Key fields |
|---|---|---|
| **Lesson** | `lesson` (was `proposal`) | `trust_level` (ai_drafted/human_asserted/source_backed), `visibility` (personal/group), `status` (pending/accepted/changes_requested/**rejected**/**quarantined**), optional source citation via `derived_from` edge, `workspace` |
| **Accepted lesson** | folded into `lesson` `status=accepted` (drops `belief`) | supersede/lineage edges move onto `lesson` |
| **Team Rule** | `team_rule` (was `rule`) | `tier` (convention/evidence_backed), `level` (company/group), `owner`, `tradeoff_accepted`, `next_execution_step`, `review_at`, evidence→accepted-lessons, `workspace` |
| **Personal Rule** | `personal_rule` (new) | instant, personal-agent scope, `owner`, `workspace` |
| **Playbook** | `playbook` (new) | allowed docs+spans, allowed rules, denied-context (paths/regex + reasons), skills/constraints, `workspace` |
| **Handoff** | `handoff` (was `work_package`) | `objective`, `playbook` ref, `write_mode` (propose_only/direct_write), `budget`/max_spend, `stop_condition`, `approval_gate`, `status`, `workspace` |
| **Trace** | `trace` (extend) | context_used, **context_denied+reasons**, actions, cost, safety_blocks, proposed_writes, approval_state, outcome |

**Open sub-decision (resolve at Phase 2 kickoff):** `decision` — recommendation is to fold it into the rule/knowledge model and keep a read-only "decision log" timeline view derived from `audit_event`. Confirm before writing the Phase 2 migration.

---

## Phase overview & sequencing

| Phase | Title | Depends on | Ships |
|---|---|---|---|
| **0** | 🔴 Critical governance security hardening | — | Tenant-isolated, gated, immutable-audit governance plane |
| **1** | Legacy quarantine behind feature flags | — (parallel with 0) | Podcasts/transformations/connectors/brain gated off the wedge |
| **2** | Governance reshape (rename to spec model) | 0 | `lesson/team_rule/handoff` model with all spec fields, states, personal rules |
| **3** | Playbooks + governed context assembler | 2 | Playbook entity + allowed/denied context bundle, secrets-deny |
| **4** | MCP export + governed handoff execution | 3 | MCP server serving packs; preflight→execute→trace→propose-only writes |

Phases 0 and 1 are independent and may run in parallel. Phase 0 and 1 below are specified in full bite-sized TDD detail. Phases 2–4 are specified at task level; **each gets its own detailed plan at kickoff** (they depend on decisions locked in by the prior phase and would be speculative to fully specify now).

---
---

# PHASE 0 — Critical governance security hardening

**Goal:** Make every governance endpoint tenant-isolated, enforce a real review gate, and make the audit log structurally immutable — without renaming anything (the rename is Phase 2; scoping added here carries through the rename mechanically).

**Approach:** Route the governance router through the existing `require_workspace` / `get_request_context` dependencies (`api/deps.py`) so it obtains `workspace_id` + `role` from the server-signed access token (never from client input). **Architecture decision (locked, not deferred):** route governance *node*-table reads/writes through `ScopedRepository` — every governance node table (`proposal`, `belief`, `decision`, `rule`, `work_package`, `trace`, `audit_event`) already carries a native `workspace record<workspace>` column (migrations 29–32), so `ScopedRepository`'s generic methods handle them once classified. The RELATION edge tables (`derived_from`, `promotes_to`, `supports`, `executes`, `traced_by`, `learned_from`, `updates`) cannot go through generic scoping — read them via `# scoped-raw` `repo_query` gated behind a workspace-checked parent object. Add gate checks to `accept`. Add a real `reject`. Make `audit_event` append-only **at the domain layer** (see Task 0.9 — the DB `PERMISSIONS` route is inert under the app's root DB auth; do not rely on it).

**Before starting:** read `open_notebook/database/scoping.py` (ScopedRepository, `_assert_scoped`), `api/deps.py` (`require_workspace`, `get_request_context`, `CtxDep`), and `tests/test_tenant_leakage.py` (the leakage-test pattern to mirror).

## Files touched in Phase 0

- Modify: `api/routers/governance.py` — add workspace/role dependency to every endpoint; add reject endpoint; pass attestation params.
- Modify: `api/governance_service.py` — accept `workspace_id`/`actor_role` params; stamp `workspace` on every create; filter every list/get by workspace; add gate checks; add `reject_proposal`.
- Modify: `open_notebook/domain/governance.py` — add `workspace` field **plus `workspace` RecordID coercion in `_prepare_save_data`** to `Proposal`, `Belief`, `Decision`, `Rule`, `WorkPackage`, `Trace`, `AuditEvent`; make `AuditEvent` immutable.
- Create: `open_notebook/database/migrations/33.surrealql` (+ `33_down.surrealql`) — add a `workspace` **index** to the governance tables (the `workspace` *column* already exists on all of them from migrations 29–32). No DB-level audit permission guard (see Task 0.9 rationale).
- Modify: `open_notebook/database/migrations/__init__.py` (or wherever `AsyncMigrationManager` hard-codes the list) — register migration 33.
- Modify: `open_notebook/database/scoping.py` — classify governance tables as workspace-scoped.
- Create: `tests/test_governance_tenant_leakage.py` — cross-tenant read/write/accept leakage tests.
- Create: `tests/test_governance_accept_gate.py` — gate-enforcement tests.
- Create: `tests/test_governance_audit_immutability.py` — audit append-only tests.

### Task 0.1: Failing test — cross-tenant proposal read is blocked

**Files:**
- Test: `tests/test_governance_tenant_leakage.py`

- [ ] **Step 1: Write the failing tests.** Mirror `tests/test_tenant_leakage.py` setup (two workspaces A and B, a user in each). Cover BOTH the negative (cross-tenant) and positive (own-workspace) paths — the positive assertion is essential because a RecordID-coercion bug (see Task 0.2) fails isolation *closed everywhere*, which a negative-only test would silently pass. Also cover `/beliefs`, the single most-cited cross-tenant leak.

```python
# See tests/test_tenant_leakage.py for the two-workspace fixture pattern.
async def test_proposal_isolation(client, ws_a_ctx, ws_b_ctx):
    created = await create_proposal_in(ws_a_ctx, title="A-only")
    # POSITIVE: A can still read its own proposal (guards against fail-closed-everywhere)
    own = await client.get(f"/api/proposals/{created['id']}", headers=ws_a_ctx.headers)
    assert own.status_code == 200
    # NEGATIVE: B cannot list or fetch A's proposal
    listed = await client.get("/api/proposals", headers=ws_b_ctx.headers)
    assert all(p["id"] != created["id"] for p in listed.json())
    got = await client.get(f"/api/proposals/{created['id']}", headers=ws_b_ctx.headers)
    assert got.status_code == 404  # no existence oracle

async def test_beliefs_list_isolation(client, ws_a_ctx, ws_b_ctx):
    # Accept a proposal in A to produce a belief, then assert B's /beliefs omits it.
    belief_id = await accept_a_proposal_in(ws_a_ctx)
    listed = await client.get("/api/beliefs", headers=ws_b_ctx.headers)
    assert all(b["id"] != belief_id for b in listed.json())
```

- [ ] **Step 2: Run to verify they fail.** `uv run pytest tests/test_governance_tenant_leakage.py -v` → FAIL (B currently sees A's proposal/belief; gets 200).

### Task 0.2: Add `workspace` to governance domain models

**Files:**
- Modify: `open_notebook/domain/governance.py`

- [ ] **Step 1:** Add `workspace: Optional[str] = None` to `Proposal`, `Belief`, `Decision`, `Rule`, `WorkPackage`, `Trace`, `AuditEvent`.
- [ ] **Step 2: Coerce `workspace` to a RecordID on save.** The `workspace` column is `record<workspace>`. In each model's `_prepare_save_data`, add `if data.get("workspace"): data["workspace"] = ensure_record_id(data["workspace"])` — follow the existing coercion pattern in `Connection._prepare_save_data` (`domain/connection.py:50-51`) and the `author`/record-field coercion already in `Proposal._prepare_save_data`. **This is critical:** if `workspace` is saved as a plain string but reads filter with `ensure_record_id(workspace_id)` (as `ScopedRepository`/`deps.py` do), nothing ever matches and isolation fails closed for the owner too.
- [ ] **Step 3:** Run `uv run python -m mypy .` → PASS.

### Task 0.3: Migration 33 — workspace columns + indexes + audit immutability

**Files:**
- Create: `open_notebook/database/migrations/33.surrealql`, `33_down.surrealql`
- Modify: `AsyncMigrationManager` registration (see `open_notebook/AGENTS.md` — migrations are hard-coded, not auto-discovered)

- [ ] **Step 1:** Write `33.surrealql`: all governance tables already carry `workspace option<record<workspace>>` (migration 29: proposal/belief/audit_event; 30: decision/rule; 31: work_package; 32: trace) — so add **only** `DEFINE INDEX` on `workspace` for each table that is listed/queried by workspace. Do NOT add a DB-level immutability guard on `audit_event`: the app connects as a SurrealDB root/system user (`open_notebook/database/repository.py:80-87`), and table `PERMISSIONS` clauses are bypassed for root/namespace/database auth — the guard would be inert. Immutability is enforced at the domain layer (Task 0.9).
- [ ] **Step 2:** Write `33_down.surrealql` to reverse the index additions.
- [ ] **Step 3:** Register migration 33 in `AsyncMigrationManager` (in `open_notebook/database/async_migrate.py`, where migrations 1–32 are registered — not `migrate.py`).
- [ ] **Step 4:** Run the API once against a dev DB (`make database` then `make api`) and confirm the migration applies cleanly in the startup logs. `make stop-all` after.
- [ ] **Step 5: Commit.** `git add open_notebook/database/migrations/33*.surrealql <manager file> open_notebook/domain/governance.py && git commit -m "feat(governance): add workspace field + audit immutability schema"`

### Task 0.4: Classify governance node tables as workspace-scoped

**Files:**
- Modify: `open_notebook/database/scoping.py`

- [ ] **Step 1:** Add the governance **node** tables (`proposal`, `belief`, `decision`, `rule`, `work_package`, `trace`, `audit_event`) to `NATIVE_WORKSPACE_TABLES` (or the equivalent classification the file uses) so `_assert_scoped` treats them as native-workspace-scoped. Do NOT classify the RELATION edge tables (`derived_from`, `promotes_to`, `supports`, `executes`, `traced_by`, `learned_from`, `updates`) — they have no native `workspace` column and are handled via `# scoped-raw` reads in Task 0.5.
- [ ] **Step 2:** Run `uv run pytest tests/test_scoping_unit.py tests/test_scoping_contract.py -v` → PASS.

> **Note:** this task is inert on its own — `_assert_scoped` only fires from `ScopedRepository` methods. It is a prerequisite of Task 0.5, which actually routes governance node reads/writes through `ScopedRepository`.

### Task 0.5: Route the service through `ScopedRepository` — writes stamp, reads filter

**Files:**
- Modify: `api/governance_service.py`

- [ ] **Step 1:** Add a required `workspace_id: str` parameter to every service function that creates or reads governance objects (`create_proposal`, `list_proposals`, `get_proposal`, `accept_proposal`, `_accept_belief_proposal`, `_accept_learning_proposal`, `request_changes`, `create_decision`, `list_decisions`, `get_decision`, `create_rule`, `list_rules`, `get_rule`, `create_work_package`, `list_work_packages`, `get_work_package`, `update_work_package_status`, `record_trace`, `list_traces_for_work_package`, `get_trace`, `create_learning_proposal`, `get_belief_lineage`, and the `_audit` helper). These functions take a `ScopedRepository` (or the `workspace_id` used to build queries) from the router.
- [ ] **Step 2: Node-table writes/reads.** For every `create`, set `workspace=workspace_id` on the model before `save()` (including `AuditEvent`; coercion handled by Task 0.2). For every node `get`, raise `NotFoundError` (from `open_notebook.exceptions` → 404, preserving no-oracle) if `obj.workspace != workspace_id`. For every node `list` — including the `Proposal.get_all()`-then-filter-in-Python paths — filter by `workspace` (route through `ScopedRepository` generic reads, which AND `WHERE workspace = $workspace_id`).
- [ ] **Step 3: Edge/lineage reads.** In `get_belief_lineage` and any `repo_query` over the relation tables, add an explicit `workspace = $workspace_id` bound filter on the anchoring node with a `# scoped-raw` comment (the pattern `PermissionContext.project_role` uses in `deps.py:137-152`). The lineage query must never return a node from another workspace.
- [ ] **Step 4:** Run `uv run pytest tests/test_governance_tenant_leakage.py -v` — still FAIL (router not yet passing workspace_id), but service unit tests (if any) should pass. `ruff check . --fix`.

### Task 0.6: Wire the router to the workspace dependency + fix `/beliefs`

**Files:**
- Modify: `api/routers/governance.py`

- [ ] **Step 1:** Replace `_actor(request)` usage: add `auth: AuthDep` / `ctx: CtxDep` from `api/deps.py` to every endpoint so `workspace_id`, `user_id`, and `role` come from the server-signed token. Pass `workspace_id=auth.workspace_id` (and actor/role where needed) into each service call. Remove the hand-rolled `_actor` 401 (the dependency now enforces auth + workspace).
- [ ] **Step 2: Fix the flagship leak.** Move the inline `SELECT * FROM belief WHERE status='current'` out of `list_beliefs_endpoint` (`governance.py:139-146`) into a workspace-filtered service function (`list_beliefs(workspace_id)`) that adds `AND workspace = $workspace_id` as a bound `# scoped-raw` query (or routes through `ScopedRepository`). The endpoint must pass `auth.workspace_id`.
- [ ] **Step 3:** Run `uv run pytest tests/test_governance_tenant_leakage.py -v` → PASS (both `/proposals` and `/beliefs` isolation + the positive-path assertion).
- [ ] **Step 4: Commit.** `git add api/governance_service.py api/routers/governance.py open_notebook/database/scoping.py tests/test_governance_tenant_leakage.py && git commit -m "fix(governance): enforce tenant isolation on the governance plane"`

### Task 0.7: Real Reject action

**Files:**
- Modify: `api/governance_service.py`, `api/routers/governance.py`
- Test: `tests/test_governance_accept_gate.py`

- [ ] **Step 1: Failing test.** Assert `POST /proposals/{id}/reject` sets status `rejected` and creates NO belief and mutates no canonical memory; and that a rejected proposal cannot later be accepted (409).
- [ ] **Step 2:** Run → FAIL (endpoint 404).
- [ ] **Step 3:** Add `reject_proposal(actor, workspace_id, proposal_id, reason)` to the service (pending→rejected, audit event, touches nothing else) and a `POST /proposals/{id}/reject` endpoint. The `rejected` status already exists in the migration-29 enum.
- [ ] **Step 4:** Run → PASS.

### Task 0.8: Harden the accept gate

**Files:**
- Modify: `api/governance_service.py`, `api/routers/governance.py`
- Test: `tests/test_governance_accept_gate.py`

- [ ] **Step 1: Failing tests.** (a) The proposal author cannot accept their own proposal (403). (b) Accept requires an explicit `source_read_confirmed=true` attestation when the proposal has `derived_from` source edges (422 if missing). (c) A caller whose token role is not reviewer-capable (define: `owner`/`admin`) cannot accept (403). (d) Accepting a proposal with zero evidence edges is rejected (422) — note in Phase 0, accept always produces a `Belief` via `_accept_belief_proposal` regardless of `kind`; the lightweight/convention-rule path (accept without evidence) is introduced in Phase 2, so require evidence for all accepts here.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement in `accept_proposal`: check author≠actor by comparing **coerced** values — `proposal.author` is a `record<user>` (coerced in `Proposal._prepare_save_data`) while `actor` is a string, so compare `str(proposal.author)` against the record form of `actor` (or normalize both via `ensure_record_id`), else the check never fires and self-accept is never blocked. Add a `source_read_confirmed: bool` param plumbed from an `AcceptBody`; require it when `derived_from` edges exist; check actor role via the token (`require_role`-style, or inspect `auth.role`); require ≥1 evidence edge. Keep the existing `status == pending` guard.
- [ ] **Step 4:** Run `uv run pytest tests/test_governance_accept_gate.py -v` → PASS.
- [ ] **Step 5: Commit.** `git add api/governance_service.py api/routers/governance.py tests/test_governance_accept_gate.py && git commit -m "feat(governance): enforce review gate (author≠reviewer, source-read, role, evidence) + reject"`

### Task 0.9: Audit immutability enforced at the domain layer (sole mechanism)

**Files:**
- Modify: `open_notebook/domain/governance.py`
- Test: `tests/test_governance_audit_immutability.py`

> The domain-layer guard is the **only** enforcement point — DB-level `PERMISSIONS` are bypassed under the app's root DB connection (see Task 0.3). All governance writes (including `_audit`) go through this domain layer, so this is sufficient in practice; note the residual risk that a future non-domain writer (raw `repo_query`) could bypass it, and mitigate by never writing `audit_event` via raw queries.

- [ ] **Step 1: Failing test.** Assert that calling `.save()` on an already-persisted `AuditEvent` raises, and `.delete()` raises — audit rows are append-only. (First insert must still succeed.)
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Override `save()` (allow only the initial insert — detect an already-set `id`) and `delete()` (always raise) on `AuditEvent` to raise a typed exception on mutation/deletion.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Full suite: `uv run pytest tests/ -q` and `ruff check .` and `uv run python -m mypy .` → all green.
- [ ] **Step 6: Commit.** `git add open_notebook/domain/governance.py tests/test_governance_audit_immutability.py && git commit -m "feat(governance): make audit log append-only (domain guard)"`

### Task 0.10: Verify end-to-end

- [ ] Use the `verify` skill: with a running stack (`make start-all`), drive the governance flow with two workspaces via the API and confirm cross-tenant reads 404, accept gate blocks author self-accept and missing attestation, reject leaves memory untouched, and audit rows resist update/delete. Record the observed responses.

---
---

# PHASE 1 — Legacy quarantine behind feature flags

**Goal:** Gate podcasts, transformations, inbound connectors, and brain-graph off the wedge behind feature flags, keeping all tables and modules resident (kept-but-hidden). No deletion. This shrinks the active surface before the Phase 2 reshape and removes always-on startup costs.

**Approach:** Introduce one small feature-flag helper read from env, then guard: router registration in `api/main.py`, the brain ingest hook, the podcast startup migration + command registration. Defaults: legacy flags **off**.

## Files touched in Phase 1

- Create: `open_notebook/config/__init__.py` (new package — directory does not exist yet) + `open_notebook/config/feature_flags.py` — tiny env-backed flag reader.
- Modify: `api/main.py` — guard router registration (including the podcast sub-routers `episode_profiles`/`speaker_profiles`) + podcast startup migration behind flags.
- Modify: `commands/source_commands.py:160` — guard the brain entity-extraction ingest hook.
- Modify: `commands/__init__.py` — guard the podcast command registration behind the flag without leaving a dangling `__all__` entry.
- Test: `tests/test_feature_flags.py`, `tests/test_legacy_quarantine.py`.

### Task 1.1: Feature-flag helper

**Files:**
- Create: `open_notebook/config/__init__.py` (empty — makes `config` an importable package), `open_notebook/config/feature_flags.py`
- Test: `tests/test_feature_flags.py`

- [ ] **Step 1: Failing test.** `is_enabled("podcasts")` returns False by default; returns True when `FEATURE_PODCASTS=1` in env. Same for `transformations`, `connectors`, `brain`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Create `open_notebook/config/__init__.py` (empty), then implement in `feature_flags.py` a `FEATURE_FLAGS` map and `is_enabled(name) -> bool` reading `os.environ.get(f"FEATURE_{name.upper()}", "0")` with truthy parsing. Default off.
- [ ] **Step 4:** Run → PASS. **Commit.**

### Task 1.2: Guard router registration

**Files:**
- Modify: `api/main.py` (router registration block ~`394-421`)
- Test: `tests/test_legacy_quarantine.py`

- [ ] **Step 1: Failing test.** With flags off (default), assert the app has no route matching `/podcasts`, `/episode-profiles`, `/speaker-profiles`, `/transformations`, `/connectors`, `/brain`; with the flag on, the routes exist. (Inspect `app.routes`.)
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Wrap each legacy `app.include_router(...)` in `if is_enabled("<feature>"):`. **Podcasts spans three routers** — `podcasts` (`main.py:414`), `episode_profiles` (`415`), `speaker_profiles` (`416`) — gate all three under the `podcasts` flag. Keep the imports at module top (harmless; modules stay resident).
- [ ] **Step 4:** Run → PASS. **Commit.**

### Task 1.3: Guard the brain ingest hook

**Files:**
- Modify: `commands/source_commands.py:158-160`
- Test: extend `tests/test_legacy_quarantine.py`

- [ ] **Step 1: Failing test.** Assert `process_source_command` does NOT call `_submit_entity_extraction` when the brain flag is off (patch/spy on `_submit_entity_extraction`).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Wrap the `await _submit_entity_extraction(...)` call (lines 158-160) in `if is_enabled("brain"):`. (Already dormant because `brain_commands` isn't worker-registered, but this stops orphan command rows on every ingest.)
- [ ] **Step 4:** Run → PASS. **Commit.**

### Task 1.4: Guard podcast startup migration + command registration

**Files:**
- Modify: `api/main.py:207-214` (the `migrate_podcast_profiles()` startup call), `commands/__init__.py` (podcast command import)

- [ ] **Step 1:** Wrap `migrate_podcast_profiles()` (`main.py:207-214`) in `if is_enabled("podcasts"):`. For `commands/__init__.py`, guard the surreal-commands **registration** of `generate_podcast_command` behind the flag rather than the import — or, if guarding the import, also conditionally build `__all__` so no dangling name breaks `from commands import *` / the worker's `--import-modules commands` introspection. Adjust `api/command_service.py` podcast priming import similarly if present.
- [ ] **Step 2:** Run full suite `uv run pytest tests/ -q` → PASS. `ruff check .` → clean.
- [ ] **Step 3: Commit.** `git commit -m "feat: quarantine legacy features (podcasts/transformations/connectors/brain) behind feature flags"`

### Task 1.5: Verify

- [ ] Boot the API with default env; confirm startup logs show no podcast-migration run and Swagger (`/docs`) lists none of the four legacy route groups. Flip `FEATURE_PODCASTS=1`, reboot, confirm podcasts reappear. Record output.

> **Note:** transformations modules must stay importable — `graphs/source.py:15-16` and `source_commands.py:10,15` hard-import them. This plan only hides the *routes*; the ingest graph continues to import the modules and passes `transformations=[]` (already the case on the retry path). Deleting transformations is explicitly out of scope.

---
---

# PHASE 2 — Governance reshape (rename to spec model)

**Goal:** Rename and extend the governance model to match the spec exactly. Because the product is pre-validation with no customer data, this is a mechanical rename + field additions + test rewrite, not a data-preserving migration.

**Kickoff prerequisite:** resolve the `decision` sub-decision (fold into rule + read-only decision-log view — recommended). This phase gets its own detailed bite-sized plan at kickoff; the task-level breakdown:

- **2.1 Migration(s):** rename tables `proposal→lesson`, `work_package→handoff`, `rule→team_rule`; drop `belief` (fold canonical state into `lesson.status=accepted`, moving `promotes_to`/`updates`/`derived_from` lineage onto `lesson`); fold/drop `decision`. Add fields per the Target Model table (`trust_level`, `visibility`, `tier`, `level`, `owner`, `tradeoff_accepted`, `next_execution_step`, `review_at`). Add `quarantined` status. Preserve the Phase 0 `workspace` columns/indexes and audit immutability.
- **2.2 New entity `personal_rule`** + personal-lesson→personal-rule conversion (instant, personal-agent scope).
- **2.3 Domain models** (`open_notebook/domain/governance.py`): rename classes, add fields, add `TrustLevel`/`RuleTier`/`RuleLevel` enums.
- **2.4 Service** (`api/governance_service.py`): rename functions, add trust-level derivation (source-backed if `derived_from` present, human_asserted if typed, ai_drafted if AI-generated), two rule tiers (convention = instant/no-evidence path vs evidence-backed = full gate), company vs group rule level, quarantine action, and extend `Trace` writes (context_denied, cost, safety_blocks, proposed_writes, approval_state).
- **2.5 Router** (`api/routers/governance.py`): rename endpoints to spec vocabulary (`/lessons`, `/team-rules`, `/personal-rules`, `/handoffs`), add quarantine + personal-rule endpoints, keep the Phase 0 gate/scoping.
- **2.6 Rewrite governance tests** to the new vocabulary; carry forward all Phase 0 leakage/gate/immutability tests under the renamed surface.
- **2.7** Flag the FE contract changes for the follow-up frontend plan.

---

# PHASE 3 — Playbooks + governed context assembler

**Goal:** Add the Playbook (Context Pack) entity and an assembler that fuses allowed docs+spans+rules and emits denied-context-with-reasons, with secrets automatically denied.

Task-level breakdown (own detailed plan at kickoff):

- **3.1 Migration + domain model `playbook`:** allowed docs (with span locators), allowed rules, denied-context (paths/regex + reasons), skills/constraints, `workspace`.
- **3.2 Playbook CRUD** service + router (`/playbooks`), workspace-scoped and gated like Phase 0.
- **3.3 Context assembler** (`open_notebook/` service): given a playbook, build the governed bundle — reuse `api/routers/context.py` + `Source.get_context()` for allowed docs+spans, `list_rules` for allowed rules; produce an explicit **denied list with reasons** (extend `source_permissions` which currently silently drops non-visible sources).
- **3.4 Secrets-deny on ingest + in packs:** add a secrets scan (evaluate `detect-secrets`/gitleaks-style) at `graphs/source.py` ingest and as a hard filter in the assembler. Closes audit gap #7 (secrets).
- **3.5 Pack preview endpoint** returning allowed + denied (with reasons) for UI/agent inspection.

---

# PHASE 4 — MCP export + governed handoff execution

**Goal:** Serve governed context packs to external agents (Claude Code/Cursor) via MCP, and execute on-platform handoffs through a governed loop.

Task-level breakdown (own detailed plan at kickoff):

- **4.1 MCP server:** add an MCP dependency + a read-only, workspace-scoped MCP surface exposing a playbook's governed pack (allowed context + rules; denied context with reasons; never leaks private/pending/denied). Authenticated + tenant-scoped.
- **4.2 Handoff executor:** consume `handoff.agent_brief` via a new LangGraph agent graph (`open_notebook/graphs/handoff.py`) — preflight (enforce `approval_gate` before run) → execute with tool-calling → enforce `write_mode` (propose_only ⇒ writes become learning proposals through Phase 0/2 review; direct_write gated by role) → enforce `budget`/`stop_condition`.
- **4.3 Trace pipeline:** populate `Trace` from real execution — context_used/denied, actions timeline, per-call cost (requires 4.4), safety_blocks, proposed_writes, approval_state. Wire the existing unused `Trace.command` link.
- **4.4 Per-call cost tracking:** capture LLM `usage_metadata` and persist per-call spend (`token_cost` in `utils/token_utils.py` exists but is never called). Feeds handoff budgets. Closes audit gap #7 (cost).
- **4.5 Prompt-injection guarding:** treat source content as hostile in ask/chat/source/handoff graphs (delimit untrusted data, add guard instructions). Closes audit gap #7 (injection).
- **4.6 Round out the security-eval suite:** add the missing 4 abuse categories (prompt injection, indirect injection, memory poisoning, excessive agency) as fail-closed tests, joining the existing tenant-leakage suite.

---

## Cross-cutting notes

- **Frontend follow-up:** Phases 2–4 change the API contract and add surfaces (lessons/team-rules/playbooks/handoffs/traces UI, two-brain namespace, trust badges, "propose to share" vocabulary from the UX plan). These need a **separate frontend plan** — do not attempt in this backend plan.
- **Conventions (from `open_notebook/AGENTS.md`):** routes→services→models; routers stay thin; raise typed exceptions from `open_notebook.exceptions` (not bare `HTTPException` for domain errors); every user-supplied URL through `validate_url()`; migrations are hard-coded in `AsyncMigrationManager` and run on startup; `RecordModel` singletons need `clear_instance()` in tests; all DB/AI calls are `await`-ed.
- **Testing:** `uv run pytest tests/`; lint `ruff check . --fix`; types `uv run python -m mypy .`. Mirror `tests/test_tenant_leakage.py` for all new leakage tests.
- **Commits:** frequent, one per task step group as noted.

## Risks

- **R1 — Phase 0 scoping architecture (RESOLVED in-plan):** governance node tables all carry a native `workspace` column, so they route through `ScopedRepository` generic methods (Tasks 0.4–0.5); only the relation edge tables need `# scoped-raw` workspace-filtered reads. This is the leakage-tested pattern and is not deferred. Residual watch-item: the `Proposal.get_all()`-in-Python list paths must be re-pointed at scoped reads, not left as-is.
- **R2 — Audit immutability is domain-layer only (not DB-level):** the app's root SurrealDB auth bypasses table `PERMISSIONS`, so DB-level guards are inert (Task 0.3). Task 0.9's domain override is the sole mechanism; the residual risk is a future raw-query writer bypassing it — mitigate by never writing `audit_event` via raw `repo_query`.
- **R4 — RecordID coercion on `workspace`:** the single highest-likelihood implementation bug. If `workspace` is stamped as a string but filtered as a RecordID, isolation fails closed for everyone. Task 0.2 Step 2 adds the coercion and Task 0.1 adds a positive-path assertion to catch it.
- **R3 — Phase 2 rename ripples to FE:** the FE currently calls `/proposals`, `/beliefs`, `/work-packages`. Coordinate the rename with the frontend follow-up plan or ship a temporary alias layer.
