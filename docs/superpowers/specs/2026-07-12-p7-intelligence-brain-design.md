# P7 — Intelligence (Knowledge Graph "Brain") + Ask-the-Brain — Design Spec
Date: 2026-07-12 · Branch: feat/intelligence-brain · Status: Draft

## Goal
Add an **Intelligence** surface: a per-workspace **knowledge graph ("brain")** that
visualizes the workspace's knowledge base as a force-directed graph of typed nodes
(Domain / Topic / Person-decision / Source) connected by typed relationships
(**Supersedes / Disagrees / Complements / Agrees**), plus a right-hand **Ask-the-Brain**
panel that answers questions with **graph-aware RAG** and highlights the cited nodes on the
canvas.

Each **workspace is one brain**: a user viewing their *personal* workspace sees their
*person brain*; switching to a *company* workspace (P6 switcher) shows the *company brain*.
The graph is **workspace-wide** — it aggregates sources across every project in the active
workspace.

Reference UI: the "Quelvio/Arteamis Intelligence" mockup (force-directed canvas, KEY legend,
"Ask the Brain" chat panel). The Ask panel reuses the existing `/search` ("Ask and Search")
answer experience.

## Depends on / Provides
**Depends on (treat as landed):**
- **P1 (auth):** `AuthContext`, token decode, frontend `auth-store`.
- **P2 (workspace + membership + roles):** `workspace` (`kind ∈ {personal, company}`),
  `api/deps.py` (`get_auth_context`, `require_role`), workspace switcher.
- **P3 (project):** `notebook`→`project` with `workspace` + `owner`.
- **P5 (source permissions):** `source.owner` / `source.scope`.
- **P6 (tenant scoping):** `ScopedRepository`, `require_workspace`, `get_request_context`
  (`CtxDep`), the tenant-leakage test suite. Every brain table is workspace-scoped through
  this same path — **no `kind` branching** in the scoping layer.

**Provides:**
- New SurrealDB brain tables + edges, an extraction worker, a graph read API, a graph-aware
  ask endpoint, and the Intelligence frontend surface.

## Non-goals (YAGNI)
- No manual node/edge editing by users in v1 (the graph is machine-derived; only "Rebuild").
- No per-project graph scoping / project filter in v1 (workspace-wide only).
- No new chat/agent framework — Ask-the-Brain extends the existing `ask` pipeline.
- No real-time collaborative graph editing.

---

## Architecture

Three-tier, matching the existing stack:

```
Next.js (app/(dashboard)/intelligence)
    → FastAPI (api/routers/brain.py)  [scoped by P6 ScopedRepository + role gating]
        → SurrealDB (entity nodes + mentions/part_of/relates edges; reuses source/source_embedding)
    ⇄ surreal_commands worker (commands/brain_commands.py)  [async extraction jobs]
```

Principles honored: **async-first** (all extraction is worker jobs via `submit_command`),
**API-first** (UI is a client of `/brain/*`), **provider-agnostic** (`model_manager` for all
LLM/embedding calls), **privacy** (every read/write is workspace-scoped).

---

## Data model (new migration, `.surrealql`, next sequential number)

Sources are **not** duplicated. The graph reuses `source` and `source_embedding`; we add:

| Object | Kind | Key fields |
|---|---|---|
| `entity` | node table | `workspace`, `kind ∈ {domain, topic, person, decision}`, `name`, `normalized_name`, `embedding`, `description`, `salience`, `created`, `updated` |
| `mentions` | edge `source → entity` | `confidence` |
| `part_of` | edge `entity(topic) → entity(domain)` | (hierarchy) |
| `relates` | edge `source → source` | `type ∈ {supersedes, disagrees, complements, agrees}`, `confidence`, `rationale`, `created` |

Notes:
- **Canvas nodes** = `entity` rows (domain/topic/person/decision) + `source` rows projected as
  nodes. **Canvas edges** = `part_of` (hierarchy), `mentions` (source↔topic), `relates` (the 4
  semantic relationship types from the mockup).
- `relates.type = supersedes` is **directed** (newer → older), oriented by `source.created`.
  The other three types are treated as undirected for rendering.
- Every new table carries a `workspace` column and is registered with `ScopedRepository`. The
  **P6 leakage suite is extended** to cover `entity` / `mentions` / `part_of` / `relates`,
  including a personal-vs-personal case.
- `_down.surrealql` drops the tables/edges.

### Entity deduplication
On upsert, an extracted entity is matched to an existing one within the **same workspace** by
`normalized_name` (case/whitespace-folded) first, then by embedding cosine similarity above a
threshold. A match updates `salience`/`description`; otherwise a new `entity` is created. This
prevents "engineering" appearing as N duplicate nodes.

---

## Extraction pipeline (`commands/brain_commands.py`)

Three `@command` jobs (surreal_commands), fire-and-forget via `submit_command`. Prompts live in
`prompts/` (existing convention). All LLM/embedding calls go through `model_manager`.

1. **`extract_source_entities`** — per source, submitted **after source ingest/embedding
   completes** (hook in `source_commands`).
   - LLM reads the source content → returns `[{kind, name, description}]` plus a suggested
     **domain path** (e.g. `engineering.ai`).
   - Upsert entities (dedup as above), `RELATE source->mentions->entity`, and build the
     `part_of` topic→domain hierarchy.
   - Failures are logged per-source and **do not block ingest**.

2. **`classify_relationships`** — per source, submitted after step 1.
   - Use `vector_search` to fetch the **top-K most similar *other* sources** in the workspace.
   - For each candidate pair, LLM classifies `type ∈ {supersedes, disagrees, complements,
     agrees, none}` + `confidence` + `rationale`.
   - `RELATE source->relates->source` for non-`none` results; dedup existing edges; orient
     `supersedes` by recency. **Linear in source count** (top-K per source), not O(n²).

3. **`rebuild_brain`** — workspace-level orchestration.
   - Backs the **"Rebuild brain"** action. **Incremental by default** (only new/changed
     sources); full rebuild is an explicit option.

Trigger flow: source ingest done → `submit_command(extract_source_entities)` →
`submit_command(classify_relationships)`. The worker is already required by the project
(`make worker-start`).

---

## API (`api/routers/brain.py`, all workspace-scoped via `CtxDep`)

| Endpoint | Role gate | Behavior |
|---|---|---|
| `GET /brain/graph?domain=&limit=` | any member | Returns `{nodes[], edges[]}` for the active workspace. Node: `{id, kind, label, salience}`. Edge: `{source, target, type}`. Optional `domain` narrows to a subtree; `limit` caps node count (salience-ranked). |
| `GET /brain/status` | any member | Extraction coverage (sources built / total) + running job state. Drives empty-state + "building…" UI. |
| `POST /brain/rebuild` | owner/admin | `submit_command(rebuild_brain)`; returns the command id. (Personal workspace role is always `owner`.) |
| `POST /brain/ask` | any member | **Graph-aware RAG, SSE streaming.** |

### `/brain/ask` — graph-aware RAG
Extends the existing `ask` pipeline (reuses `model_manager` + `ask_knowledge_base` infra),
differing in two ways:
1. After vector-retrieving candidate sources, **expand to the surrounding subgraph** (their
   entities + sources linked via `relates`) and inject relationship annotations
   ("source A *supersedes* source B", "A *disagrees* with C") into the answer context.
2. Stream events carry `cited_node_ids` so the frontend can **highlight cited nodes** on the
   canvas as the answer streams in.

Streaming shape mirrors the existing ask stream (`strategy → answers → finalAnswer`), with
`cited_node_ids` added to the relevant events. Stream errors (e.g. `402` model/credit) are
surfaced in the panel, never crash the page.

---

## Frontend

**Route:** `app/(dashboard)/intelligence/page.tsx`. **Nav:** add an **"Intelligence"** item to
`components/layout/AppSidebar.tsx` (lucide `Network`/`Brain` icon), placed near Notebooks /
Ask-and-Search. Layout matches the mockup: nav (left) · graph canvas (center) · Ask-the-Brain
panel (right, collapsible).

**New components — `components/intelligence/`:**
- `GraphCanvas` — force-directed via **`react-force-graph-2d`** (d3-force + canvas; smooth for a
  few hundred nodes). Node color by `kind` (Domain=orange, Source=white, Topic=grey,
  Person/decision=blue); edge style by `type` (Supersedes=dashed, Disagrees=red,
  Complements=blue, Agrees=neutral). Pan/zoom, click-to-select, hover labels.
- `GraphLegend` — the KEY panel (relationship + node-type legend) from the mockup.
- `NodeDetailPanel` — click a node → details + linked sources; deep-link to the source page.
- `AskTheBrainPanel` — **reuses** `useAsk` (extended to a `useBrainAsk` pointed at `/brain/ask`)
  plus `AnswerBody` / `SourcesPanel` / `StrategyDisclosure` / `AnswerFeedback`. Consumes
  `cited_node_ids` to highlight nodes on the canvas.

**State / data:**
- `useBrainGraph` (TanStack Query) — fetches `/brain/graph`; transforms API `{nodes, edges}`
  into the `react-force-graph` shape.
- `useBrainAsk` — extends `useAsk` for `/brain/ask`, exposes `citedNodeIds`.
- A small Zustand store for canvas UI state (selected node, highlight set, panel open/closed).
- **Empty state** when `GET /brain/status` shows nothing built → prompt + "Rebuild brain"
  button (owner/admin). **Building state** shows progress from `/brain/status`.

**New dependency:** `react-force-graph-2d` (+ its `d3-force` peer). Rendering is canvas-based;
lazy-load the component (client-only) to keep the route light.

---

## Error handling
- Extraction errors: logged per-source; ingest is never blocked; the canvas renders a partial
  graph.
- Ask stream errors (e.g. `Stream failed: 402`): shown inline in the panel; page stays alive.
- Missing/misconfigured models: reuse existing ask model-config guards (toast + disabled send).
- Empty brain: explicit empty-state, not an error.

---

## Testing

### Methodology — Test-Driven Development (mandatory)
Every phase is built **test-first**, one behavior at a time, following strict RED → GREEN →
REFACTOR:
1. **RED** — write a failing test for the next smallest behavior; run it and **confirm it fails
   for the right reason** (assertion, not an import/typo error).
2. **GREEN** — write the minimum code to make it pass; run and confirm green.
3. **REFACTOR** — clean up with the test staying green.

No production code is written without a failing test first. Each phase's plan (P7.1–P7.4) is
expressed as an ordered list of RED/GREEN cycles, not "write code then add tests". LLM- and
embedding-dependent code is made testable by **injecting/mocking `model_manager`** so tests are
deterministic and provider-agnostic. Coverage is a byproduct of the process, not a target bolted
on afterward. CI gates: `uv run pytest tests/` (backend) and `npm run test` (frontend) must be
green before a phase is considered done.

### What is covered
- **Backend (pytest):** entity dedup (name + embedding), `supersedes` orientation by recency,
  `relates` edge dedup, extraction determinism with a mocked LLM, `/brain/graph` shape, and an
  **extension of the P6 tenant-leakage suite** proving workspace A can never read workspace B's
  brain (including personal-vs-personal).
- **Frontend (vitest):** graph-data transform (API → force-graph shape), `useBrainGraph` /
  `useBrainAsk` hooks, legend/node-color mapping, empty/building states.
- **Manual / e2e:** canvas render, node select → detail, Ask → answer + node highlight.

---

## Delivery phases (writing-plans will detail each as its own plan)
1. **P7.1** — Schema + migration + ScopedRepository wiring + `GET /brain/graph` +
   `extract_source_entities` (entity / mentions / part_of) + ingest hook.
2. **P7.2** — `classify_relationships` (the 4 semantic edge types) + `rebuild_brain` +
   `POST /brain/rebuild` + `GET /brain/status`.
3. **P7.3** — Frontend Intelligence tab: nav item, route, `GraphCanvas`, `GraphLegend`,
   `NodeDetailPanel`, empty/building states.
4. **P7.4** — `POST /brain/ask` graph-aware RAG + `AskTheBrainPanel` (reusing search
   components) + `cited_node_ids` canvas highlighting.

Each phase is independently shippable: P7.1 yields a viewable (relationship-less) graph; P7.2
adds semantic edges; P7.3 adds the UI; P7.4 adds the chat.
