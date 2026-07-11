# P7.3 — Intelligence Frontend (Graph Canvas) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to execute this plan. Work through the tasks in order. Each step is a checkbox (`- [ ]`) that must be checked off only after its command has been run and the stated expectation observed. Do not batch steps; follow the strict RED → GREEN → COMMIT rhythm exactly.

## Goal

Ship the **Intelligence** tab: a workspace-wide knowledge-graph ("brain") surface rendered as a force-directed canvas, with an empty/building/populated state machine, a node-detail panel, a KEY legend, and an owner/admin-gated "Rebuild brain" action. This phase consumes the already-built P7.1/P7.2 backend endpoints (`GET /brain/graph`, `GET /brain/status`, `POST /brain/rebuild`) and defines the **shared frontend contract** (types, api client, hooks, store, component file names, right-panel slot) that **P7.4** (Ask-the-Brain chat + `cited_node_ids` highlighting) will build on. No chat is built here — only a reserved right-panel slot.

## Architecture

Matches the existing three-tier client pattern:

```
app/(dashboard)/intelligence/page.tsx     ← route, layout, empty/building/populated states
  ├─ components/intelligence/GraphCanvas.tsx   ← next/dynamic({ssr:false}) wrapper over react-force-graph-2d
  │     └─ components/intelligence/graph-transform.ts  ← PURE, unit-tested transforms + color/style helpers
  ├─ components/intelligence/GraphLegend.tsx   ← static KEY panel (node kinds + edge types)
  ├─ components/intelligence/NodeDetailPanel.tsx ← selected-node detail + deep link to /sources/:id
  └─ [right-panel slot]                        ← reserved <aside> placeholder; P7.4 mounts AskTheBrainPanel here
        │
  lib/hooks/use-brain-graph.ts  (TanStack Query) → lib/api/brain.ts (axios apiClient) → GET/POST /brain/*
  lib/stores/brain-store.ts     (Zustand UI state: selectedNodeId, highlightedNodeIds, panelOpen)
  lib/types/brain.ts            (BrainNode, BrainEdge, BrainGraph, BrainStatus, ForceGraphData)
```

Server state (graph, status) lives in TanStack Query. UI/interaction state (which node is selected, which node ids are highlighted, is the right panel open) lives in the Zustand `brain-store`. The canvas library is DOM/canvas-only, so `GraphCanvas` is imported through `next/dynamic` with `{ ssr: false }`; its heavy render path is NOT unit-tested — instead the pure data-transform + color/style helpers are extracted into `graph-transform.ts` and tested directly, and the react-force-graph-2d default export is mocked in the `GraphCanvas` component test.

## Tech Stack

Next.js 16 (App Router, `app/(dashboard)/`), React 19, TanStack Query v5, Zustand v5, Radix/shadcn UI primitives (`@/components/ui/*`), Tailwind 4, i18next (`useTranslation`), axios via shared `apiClient` (`@/lib/api/client`), lucide-react icons, sonner toasts. Tests: vitest + @testing-library/react (jsdom, globals, `src/test/setup.ts`). New runtime dep: **`react-force-graph-2d`** (+ peer **`d3-force`**).

---

## Global Constraints

- **React 19 / Next 16 App Router.** All interactive files start with `'use client'`. The route file is `app/(dashboard)/intelligence/page.tsx`.
- **Server state → TanStack Query; UI state → Zustand.** Never store graph/status data in the Zustand store; never store `selectedNodeId`/`highlightedNodeIds`/`panelOpen` in query cache.
- **All HTTP goes through the shared `apiClient`** (`@/lib/api/client`). Never create a second axios instance. Auth token is auto-injected.
- **i18n is mandatory.** Every user-facing string uses `t('section.key')`. New keys go under the `navigation` and a new `intelligence` section in **every** locale `index.ts` present in `src/lib/locales/` (currently: `bn-IN, ca-ES, de-DE, en-US, es-ES, fr-FR, it-IT, ja-JP, pl-PL, pt-BR, ru-RU, tr-TR, zh-CN, zh-TW`). en-US is the source of truth; missing keys fall back to en-US.
- **TDD is mandatory** and **test-first**: write a failing vitest test, run it, confirm it fails for the right reason (assertion, not import error), then write the minimal COMPLETE implementation, run, confirm pass. No production code without a red test first.
- **The canvas lib is dynamic-imported `{ ssr: false }`.** `GraphCanvas` never renders react-force-graph-2d during SSR or in tests unless the default export is mocked.
- **Commands are run from `frontend/`:** `npm run test` (vitest run), `npm run test -- <file>` (single file), `npm run lint`, `npm run build`.
- **Role gating:** `POST /brain/rebuild` is owner/admin only. The frontend has no membership/role hook yet (P2/P6 role infra is backend-side; personal workspace role is always `owner`). Model the gate as a `canRebuild` boolean in the page that defaults to `true` (personal-workspace assumption) and is trivially swappable when a role hook lands. State this in the page so P7.4 / a later phase can wire real roles. The backend still enforces the gate regardless.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `frontend/src/lib/types/brain.ts` | `BrainNode`, `BrainEdge`, `BrainGraph`, `BrainStatus`, `ForceGraphData` type definitions (the shared contract). |
| `frontend/src/lib/api/brain.ts` | `brainApi` axios client: `getGraph`, `getStatus`, `rebuild`. |
| `frontend/src/lib/hooks/use-brain-graph.ts` | `useBrainGraph()`, `useBrainStatus()`, `useRebuildBrain()` TanStack hooks. |
| `frontend/src/lib/hooks/use-brain-graph.test.ts` | Hook behavior tests (mock `brainApi`). |
| `frontend/src/lib/stores/brain-store.ts` | Zustand `useBrainStore` UI state. |
| `frontend/src/lib/stores/brain-store.test.ts` | Store action tests. |
| `frontend/src/components/intelligence/graph-transform.ts` | Pure `toForceGraphData` transform + `nodeColor`/`nodeVal`/`edgeColor`/`edgeDashed` helpers. |
| `frontend/src/components/intelligence/graph-transform.test.ts` | Transform + color/style mapping tests. |
| `frontend/src/components/intelligence/GraphCanvas.tsx` | Dynamic `{ssr:false}` react-force-graph-2d wrapper; click→selectNode, hover labels, highlight ring. |
| `frontend/src/components/intelligence/GraphCanvas.test.tsx` | Component test with react-force-graph-2d default export mocked. |
| `frontend/src/components/intelligence/GraphLegend.tsx` | Static KEY panel (node kinds + edge types). |
| `frontend/src/components/intelligence/GraphLegend.test.tsx` | Legend render test. |
| `frontend/src/components/intelligence/NodeDetailPanel.tsx` | Selected-node detail + deep link to source. |
| `frontend/src/components/intelligence/NodeDetailPanel.test.tsx` | Detail panel render/link tests. |
| `frontend/src/app/(dashboard)/intelligence/page.tsx` | Route: layout, empty/building/populated states, rebuild button, right-panel slot. |
| `frontend/src/app/(dashboard)/intelligence/page.test.tsx` | State-machine tests (empty vs building vs populated). |

**Modified:**

| File | Change |
|---|---|
| `frontend/src/components/layout/AppSidebar.tsx` | Add `Network` (lucide) nav item → `/intelligence`, label `t('navigation.intelligence')`, in the "Process" section. |
| `frontend/src/lib/locales/*/index.ts` (all 14) | Add `navigation.intelligence` + a new `intelligence.*` string block. |
| `frontend/package.json` | Add `react-force-graph-2d` + `d3-force` deps. |

---

### Task 1: Install the canvas dependency

**Files:** `frontend/package.json`, `frontend/package-lock.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `react-force-graph-2d` (+ `d3-force` peer) available to import.

- [ ] **Step 1** — Install the dependency. Run from `frontend/`:
  ```
  npm install react-force-graph-2d d3-force
  ```
  Then confirm both appear under `dependencies` in `frontend/package.json`.
- [ ] **Step 2** — Sanity build check that the install did not break resolution. Run:
  ```
  npm run build
  ```
  Expected: build **succeeds** (route set unchanged; the lib is not yet imported). If it fails, do not proceed — fix resolution first.
- [ ] **Step 3** — Commit:
  ```
  git add frontend/package.json frontend/package-lock.json && git commit -m "P7.3: add react-force-graph-2d + d3-force deps"
  ```

---

### Task 2: Brain types (shared contract)

**Files:** `frontend/src/lib/types/brain.ts`

**Interfaces:**
- Consumes: the P7.1/P7.2 `GET /brain/graph` and `GET /brain/status` JSON shapes.
- Produces (VERBATIM — P7.4 depends): `BrainNode`, `BrainEdge`, `BrainGraph`, `BrainStatus`, `ForceGraphData`.

There is no behavior to unit-test in a pure type file; type correctness is enforced by the transform tests in Task 6 and the build. Write the file directly, then let Task 6's red test drive the first consumer.

- [ ] **Step 1** — Write the types file:
  ```ts
  // frontend/src/lib/types/brain.ts
  export type BrainNodeKind = 'domain' | 'topic' | 'person' | 'decision' | 'source'

  export type BrainEdgeType =
    | 'part_of'
    | 'mentions'
    | 'supersedes'
    | 'disagrees'
    | 'complements'
    | 'agrees'

  export interface BrainNode {
    id: string
    kind: BrainNodeKind
    label: string
    salience: number
  }

  export interface BrainEdge {
    source: string
    target: string
    type: BrainEdgeType
  }

  export interface BrainGraph {
    nodes: BrainNode[]
    edges: BrainEdge[]
  }

  export interface BrainStatus {
    total_sources: number
    built_sources: number
    running: boolean
  }

  /** Shape consumed by react-force-graph-2d. `val` scales node radius. */
  export interface ForceGraphNode {
    id: string
    kind: BrainNodeKind
    label: string
    val: number
  }

  export interface ForceGraphLink {
    source: string
    target: string
    type: BrainEdgeType
  }

  export interface ForceGraphData {
    nodes: ForceGraphNode[]
    links: ForceGraphLink[]
  }
  ```
- [ ] **Step 2** — Typecheck via build-adjacent lint. Run:
  ```
  npm run lint
  ```
  Expected: **no errors** for `brain.ts`.
- [ ] **Step 3** — Commit:
  ```
  git add frontend/src/lib/types/brain.ts && git commit -m "P7.3: add brain types (BrainNode/Edge/Graph/Status/ForceGraphData)"
  ```

---

### Task 3: brainApi axios client

**Files:** `frontend/src/lib/api/brain.ts`, `frontend/src/lib/api/brain.test.ts`

**Interfaces:**
- Consumes: `GET /brain/graph?domain=&limit=`, `GET /brain/status`, `POST /brain/rebuild` (body `{mode}`) via shared `apiClient`.
- Produces (VERBATIM): `brainApi.getGraph(params?)`, `brainApi.getStatus()`, `brainApi.rebuild(mode)`.

- [ ] **Step 1** — Write the failing test `frontend/src/lib/api/brain.test.ts`:
  ```ts
  import { describe, it, expect, vi, beforeEach } from 'vitest'

  const get = vi.fn()
  const post = vi.fn()
  vi.mock('./client', () => ({ default: { get, post } }))

  import { brainApi } from './brain'

  describe('brainApi', () => {
    beforeEach(() => { get.mockReset(); post.mockReset() })

    it('getGraph calls GET /brain/graph with params and returns data', async () => {
      get.mockResolvedValue({ data: { nodes: [], edges: [] } })
      const result = await brainApi.getGraph({ domain: 'engineering', limit: 50 })
      expect(get).toHaveBeenCalledWith('/brain/graph', { params: { domain: 'engineering', limit: 50 } })
      expect(result).toEqual({ nodes: [], edges: [] })
    })

    it('getGraph works with no params', async () => {
      get.mockResolvedValue({ data: { nodes: [], edges: [] } })
      await brainApi.getGraph()
      expect(get).toHaveBeenCalledWith('/brain/graph', { params: undefined })
    })

    it('getStatus calls GET /brain/status', async () => {
      get.mockResolvedValue({ data: { total_sources: 3, built_sources: 1, running: true } })
      const result = await brainApi.getStatus()
      expect(get).toHaveBeenCalledWith('/brain/status')
      expect(result.running).toBe(true)
    })

    it('rebuild POSTs the mode and returns command_id', async () => {
      post.mockResolvedValue({ data: { command_id: 'cmd-1' } })
      const result = await brainApi.rebuild('full')
      expect(post).toHaveBeenCalledWith('/brain/rebuild', { mode: 'full' })
      expect(result.command_id).toBe('cmd-1')
    })
  })
  ```
- [ ] **Step 2** — Run it, expect **FAIL** (module `./brain` does not exist → import error is acceptable here only because the file is absent; the assertions cannot run yet):
  ```
  npm run test -- src/lib/api/brain.test.ts
  ```
- [ ] **Step 3** — Write the minimal complete implementation `frontend/src/lib/api/brain.ts`:
  ```ts
  import apiClient from './client'
  import type { BrainGraph, BrainStatus } from '@/lib/types/brain'

  export const brainApi = {
    getGraph: async (params?: { domain?: string; limit?: number }): Promise<BrainGraph> => {
      const response = await apiClient.get<BrainGraph>('/brain/graph', { params })
      return response.data
    },

    getStatus: async (): Promise<BrainStatus> => {
      const response = await apiClient.get<BrainStatus>('/brain/status')
      return response.data
    },

    rebuild: async (mode: 'incremental' | 'full'): Promise<{ command_id: string }> => {
      const response = await apiClient.post<{ command_id: string }>('/brain/rebuild', { mode })
      return response.data
    },
  }
  ```
- [ ] **Step 4** — Run it, expect **PASS**:
  ```
  npm run test -- src/lib/api/brain.test.ts
  ```
- [ ] **Step 5** — Commit:
  ```
  git add frontend/src/lib/api/brain.ts frontend/src/lib/api/brain.test.ts && git commit -m "P7.3: add brainApi client (getGraph/getStatus/rebuild)"
  ```

---

### Task 4: TanStack Query hooks

**Files:** `frontend/src/lib/hooks/use-brain-graph.ts`, `frontend/src/lib/hooks/use-brain-graph.test.ts`

**Interfaces:**
- Consumes: `brainApi.getGraph/getStatus/rebuild`.
- Produces (VERBATIM): `useBrainGraph()` (queryKey `['brain','graph']`, returns `{ graph, isLoading, ... }`), `useBrainStatus()` (queryKey `['brain','status']`), `useRebuildBrain()` (mutation, invalidates `['brain']`, toasts).

- [ ] **Step 1** — Write the failing test `frontend/src/lib/hooks/use-brain-graph.test.ts`. Use a real `QueryClient` wrapper and mock `brainApi` + sonner:
  ```ts
  import { describe, it, expect, vi, beforeEach } from 'vitest'
  import { renderHook, waitFor, act } from '@testing-library/react'
  import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
  import React from 'react'

  const getGraph = vi.fn()
  const getStatus = vi.fn()
  const rebuild = vi.fn()
  vi.mock('@/lib/api/brain', () => ({ brainApi: { getGraph, getStatus, rebuild } }))
  vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

  import { useBrainGraph, useBrainStatus, useRebuildBrain } from './use-brain-graph'

  function wrapper() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    return ({ children }: { children: React.ReactNode }) =>
      React.createElement(QueryClientProvider, { client }, children)
  }

  describe('brain hooks', () => {
    beforeEach(() => { getGraph.mockReset(); getStatus.mockReset(); rebuild.mockReset() })

    it('useBrainGraph fetches the graph and exposes graph + isLoading', async () => {
      getGraph.mockResolvedValue({ nodes: [{ id: 'a', kind: 'domain', label: 'Eng', salience: 1 }], edges: [] })
      const { result } = renderHook(() => useBrainGraph(), { wrapper: wrapper() })
      expect(result.current.isLoading).toBe(true)
      await waitFor(() => expect(result.current.isLoading).toBe(false))
      expect(result.current.graph?.nodes).toHaveLength(1)
      expect(getGraph).toHaveBeenCalled()
    })

    it('useBrainStatus fetches status', async () => {
      getStatus.mockResolvedValue({ total_sources: 5, built_sources: 2, running: false })
      const { result } = renderHook(() => useBrainStatus(), { wrapper: wrapper() })
      await waitFor(() => expect(result.current.data?.total_sources).toBe(5))
    })

    it('useRebuildBrain calls brainApi.rebuild with the mode', async () => {
      rebuild.mockResolvedValue({ command_id: 'cmd-9' })
      const { result } = renderHook(() => useRebuildBrain(), { wrapper: wrapper() })
      await act(async () => { await result.current.mutateAsync('incremental') })
      expect(rebuild).toHaveBeenCalledWith('incremental')
    })
  })
  ```
- [ ] **Step 2** — Run, expect **FAIL** (no `./use-brain-graph`):
  ```
  npm run test -- src/lib/hooks/use-brain-graph.test.ts
  ```
- [ ] **Step 3** — Write `frontend/src/lib/hooks/use-brain-graph.ts`:
  ```ts
  import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
  import { toast } from 'sonner'
  import { brainApi } from '@/lib/api/brain'
  import { useTranslation } from '@/lib/hooks/use-translation'
  import { getApiErrorKey } from '@/lib/utils/error-handler'

  export function useBrainGraph(params?: { domain?: string; limit?: number }) {
    const query = useQuery({
      queryKey: ['brain', 'graph', params ?? {}],
      queryFn: () => brainApi.getGraph(params),
      staleTime: 30 * 1000,
    })
    return { graph: query.data, isLoading: query.isLoading, isError: query.isError, refetch: query.refetch }
  }

  export function useBrainStatus() {
    return useQuery({
      queryKey: ['brain', 'status'],
      queryFn: () => brainApi.getStatus(),
      refetchInterval: (query) => (query.state.data?.running ? 3000 : false),
      staleTime: 0,
    })
  }

  export function useRebuildBrain() {
    const queryClient = useQueryClient()
    const { t } = useTranslation()
    return useMutation({
      mutationFn: (mode: 'incremental' | 'full') => brainApi.rebuild(mode),
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ['brain'] })
        toast.success(t('intelligence.rebuildStarted'))
      },
      onError: (error: Error) => {
        toast.error(t(getApiErrorKey(error.message)))
      },
    })
  }
  ```
  Note: the base query key is `['brain','graph']` (params appended for cache-keying); `['brain','status']` for status. `invalidateQueries({ queryKey: ['brain'] })` refreshes both after a rebuild — matching the contract.
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- src/lib/hooks/use-brain-graph.test.ts
  ```
- [ ] **Step 5** — Commit:
  ```
  git add frontend/src/lib/hooks/use-brain-graph.ts frontend/src/lib/hooks/use-brain-graph.test.ts && git commit -m "P7.3: add useBrainGraph/useBrainStatus/useRebuildBrain hooks"
  ```

---

### Task 5: Zustand brain-store (UI state)

**Files:** `frontend/src/lib/stores/brain-store.ts`, `frontend/src/lib/stores/brain-store.test.ts`

**Interfaces:**
- Consumes: nothing (pure UI state).
- Produces (VERBATIM): `useBrainStore` with `{ selectedNodeId: string|null; highlightedNodeIds: string[]; panelOpen: boolean; selectNode(id); setHighlighted(ids); togglePanel() }`. `highlightedNodeIds` is written by P7.4 (Ask-the-Brain sets cited node ids here); this phase only reads it in `GraphCanvas` to draw a ring.

- [ ] **Step 1** — Write the failing test `frontend/src/lib/stores/brain-store.test.ts`:
  ```ts
  import { describe, it, expect, beforeEach } from 'vitest'
  import { useBrainStore } from './brain-store'

  describe('useBrainStore', () => {
    beforeEach(() => {
      useBrainStore.setState({ selectedNodeId: null, highlightedNodeIds: [], panelOpen: false })
    })

    it('has correct initial state', () => {
      const s = useBrainStore.getState()
      expect(s.selectedNodeId).toBeNull()
      expect(s.highlightedNodeIds).toEqual([])
      expect(s.panelOpen).toBe(false)
    })

    it('selectNode sets the selected id', () => {
      useBrainStore.getState().selectNode('entity:1')
      expect(useBrainStore.getState().selectedNodeId).toBe('entity:1')
    })

    it('selectNode(null) clears selection', () => {
      useBrainStore.getState().selectNode('entity:1')
      useBrainStore.getState().selectNode(null)
      expect(useBrainStore.getState().selectedNodeId).toBeNull()
    })

    it('setHighlighted replaces the highlighted set', () => {
      useBrainStore.getState().setHighlighted(['a', 'b'])
      expect(useBrainStore.getState().highlightedNodeIds).toEqual(['a', 'b'])
    })

    it('togglePanel flips panelOpen', () => {
      useBrainStore.getState().togglePanel()
      expect(useBrainStore.getState().panelOpen).toBe(true)
      useBrainStore.getState().togglePanel()
      expect(useBrainStore.getState().panelOpen).toBe(false)
    })
  })
  ```
- [ ] **Step 2** — Run, expect **FAIL**:
  ```
  npm run test -- src/lib/stores/brain-store.test.ts
  ```
- [ ] **Step 3** — Write `frontend/src/lib/stores/brain-store.ts` (no `persist` — UI state is ephemeral, avoids the hydration gotcha):
  ```ts
  import { create } from 'zustand'

  interface BrainState {
    selectedNodeId: string | null
    highlightedNodeIds: string[]
    panelOpen: boolean
    selectNode: (id: string | null) => void
    setHighlighted: (ids: string[]) => void
    togglePanel: () => void
  }

  export const useBrainStore = create<BrainState>((set) => ({
    selectedNodeId: null,
    highlightedNodeIds: [],
    panelOpen: false,
    selectNode: (id) => set({ selectedNodeId: id }),
    setHighlighted: (ids) => set({ highlightedNodeIds: ids }),
    togglePanel: () => set((state) => ({ panelOpen: !state.panelOpen })),
  }))
  ```
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- src/lib/stores/brain-store.test.ts
  ```
- [ ] **Step 5** — Commit:
  ```
  git add frontend/src/lib/stores/brain-store.ts frontend/src/lib/stores/brain-store.test.ts && git commit -m "P7.3: add brain-store (selectedNodeId/highlightedNodeIds/panelOpen)"
  ```

---

### Task 6: Pure graph transform + color/style helpers

**Files:** `frontend/src/components/intelligence/graph-transform.ts`, `frontend/src/components/intelligence/graph-transform.test.ts`

**Interfaces:**
- Consumes: `BrainGraph` (`{nodes, edges}`) from the API.
- Produces: `toForceGraphData(graph): ForceGraphData`; `nodeColor(kind): string`; `nodeVal(salience): number`; `edgeColor(type): string`; `edgeDashed(type): boolean`. These are the testable core extracted out of `GraphCanvas` (which is canvas-only and not unit-tested).

Visual encoding (from spec): node color by kind — `domain #e0651f`, `source #e6e6e6`, `topic #8a8a8a`, `person`/`decision` `#2f7bf0`. Edge style by type — `supersedes` dashed neutral, `disagrees #e23b3b`, `complements #2f7bf0`, `agrees` neutral solid, `part_of`/`mentions` faint grey.

- [ ] **Step 1** — Write the failing test `frontend/src/components/intelligence/graph-transform.test.ts`:
  ```ts
  import { describe, it, expect } from 'vitest'
  import { toForceGraphData, nodeColor, nodeVal, edgeColor, edgeDashed } from './graph-transform'
  import type { BrainGraph } from '@/lib/types/brain'

  describe('toForceGraphData', () => {
    it('maps BrainGraph nodes/edges into force-graph nodes/links', () => {
      const graph: BrainGraph = {
        nodes: [
          { id: 'd1', kind: 'domain', label: 'Engineering', salience: 4 },
          { id: 's1', kind: 'source', label: 'Doc', salience: 1 },
        ],
        edges: [{ source: 's1', target: 'd1', type: 'mentions' }],
      }
      const result = toForceGraphData(graph)
      expect(result.nodes).toEqual([
        { id: 'd1', kind: 'domain', label: 'Engineering', val: nodeVal(4) },
        { id: 's1', kind: 'source', label: 'Doc', val: nodeVal(1) },
      ])
      expect(result.links).toEqual([{ source: 's1', target: 'd1', type: 'mentions' }])
    })

    it('handles an empty graph', () => {
      expect(toForceGraphData({ nodes: [], edges: [] })).toEqual({ nodes: [], links: [] })
    })
  })

  describe('nodeColor', () => {
    it('maps each kind to its spec color', () => {
      expect(nodeColor('domain')).toBe('#e0651f')
      expect(nodeColor('source')).toBe('#e6e6e6')
      expect(nodeColor('topic')).toBe('#8a8a8a')
      expect(nodeColor('person')).toBe('#2f7bf0')
      expect(nodeColor('decision')).toBe('#2f7bf0')
    })
  })

  describe('nodeVal', () => {
    it('scales radius by salience and is monotonic', () => {
      expect(nodeVal(4)).toBeGreaterThan(nodeVal(1))
    })
    it('never returns below the floor for zero/negative salience', () => {
      expect(nodeVal(0)).toBeGreaterThan(0)
      expect(nodeVal(-5)).toBe(nodeVal(0))
    })
  })

  describe('edge styling', () => {
    it('maps edge type to color', () => {
      expect(edgeColor('disagrees')).toBe('#e23b3b')
      expect(edgeColor('complements')).toBe('#2f7bf0')
      expect(edgeColor('supersedes')).toBe('#9a9a9a')
      expect(edgeColor('agrees')).toBe('#9a9a9a')
      expect(edgeColor('part_of')).toBe('#d4d4d4')
      expect(edgeColor('mentions')).toBe('#d4d4d4')
    })
    it('only supersedes is dashed', () => {
      expect(edgeDashed('supersedes')).toBe(true)
      expect(edgeDashed('agrees')).toBe(false)
      expect(edgeDashed('disagrees')).toBe(false)
    })
  })
  ```
- [ ] **Step 2** — Run, expect **FAIL**:
  ```
  npm run test -- src/components/intelligence/graph-transform.test.ts
  ```
- [ ] **Step 3** — Write `frontend/src/components/intelligence/graph-transform.ts`:
  ```ts
  import type {
    BrainGraph,
    BrainNodeKind,
    BrainEdgeType,
    ForceGraphData,
  } from '@/lib/types/brain'

  const NODE_COLORS: Record<BrainNodeKind, string> = {
    domain: '#e0651f',
    source: '#e6e6e6',
    topic: '#8a8a8a',
    person: '#2f7bf0',
    decision: '#2f7bf0',
  }

  const NEUTRAL = '#9a9a9a'
  const FAINT = '#d4d4d4'
  const EDGE_COLORS: Record<BrainEdgeType, string> = {
    supersedes: NEUTRAL,
    agrees: NEUTRAL,
    disagrees: '#e23b3b',
    complements: '#2f7bf0',
    part_of: FAINT,
    mentions: FAINT,
  }

  export function nodeColor(kind: BrainNodeKind): string {
    return NODE_COLORS[kind]
  }

  /** Radius scales with sqrt(salience) so area ~ salience; floored so tiny nodes stay clickable. */
  export function nodeVal(salience: number): number {
    const s = Math.max(0, salience)
    return 1 + Math.sqrt(s)
  }

  export function edgeColor(type: BrainEdgeType): string {
    return EDGE_COLORS[type]
  }

  export function edgeDashed(type: BrainEdgeType): boolean {
    return type === 'supersedes'
  }

  export function toForceGraphData(graph: BrainGraph): ForceGraphData {
    return {
      nodes: graph.nodes.map((n) => ({
        id: n.id,
        kind: n.kind,
        label: n.label,
        val: nodeVal(n.salience),
      })),
      links: graph.edges.map((e) => ({
        source: e.source,
        target: e.target,
        type: e.type,
      })),
    }
  }
  ```
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- src/components/intelligence/graph-transform.test.ts
  ```
- [ ] **Step 5** — Commit:
  ```
  git add frontend/src/components/intelligence/graph-transform.ts frontend/src/components/intelligence/graph-transform.test.ts && git commit -m "P7.3: add graph-transform (toForceGraphData + color/style helpers)"
  ```

---

### Task 7: GraphLegend (KEY panel)

**Files:** `frontend/src/components/intelligence/GraphLegend.tsx`, `frontend/src/components/intelligence/GraphLegend.test.tsx`

**Interfaces:**
- Consumes: `nodeColor`/`edgeColor`/`edgeDashed` helpers; i18n `intelligence.legend.*` keys.
- Produces: `GraphLegend` component rendering the node-kind + edge-type KEY.

- [ ] **Step 1** — Write the failing test `frontend/src/components/intelligence/GraphLegend.test.tsx`:
  ```ts
  import { describe, it, expect } from 'vitest'
  import { render, screen } from '@testing-library/react'
  import { GraphLegend } from './GraphLegend'

  describe('GraphLegend', () => {
    it('renders a KEY heading and all node kinds', () => {
      render(<GraphLegend />)
      expect(screen.getByText('intelligence.legend.title')).toBeInTheDocument()
      expect(screen.getByText('intelligence.legend.domain')).toBeInTheDocument()
      expect(screen.getByText('intelligence.legend.topic')).toBeInTheDocument()
      expect(screen.getByText('intelligence.legend.person')).toBeInTheDocument()
      expect(screen.getByText('intelligence.legend.source')).toBeInTheDocument()
    })

    it('renders all four semantic edge types', () => {
      render(<GraphLegend />)
      expect(screen.getByText('intelligence.legend.supersedes')).toBeInTheDocument()
      expect(screen.getByText('intelligence.legend.disagrees')).toBeInTheDocument()
      expect(screen.getByText('intelligence.legend.complements')).toBeInTheDocument()
      expect(screen.getByText('intelligence.legend.agrees')).toBeInTheDocument()
    })
  })
  ```
  (`useTranslation` is globally mocked in `src/test/setup.ts` to return the key as the string.)
- [ ] **Step 2** — Run, expect **FAIL**:
  ```
  npm run test -- src/components/intelligence/GraphLegend.test.tsx
  ```
- [ ] **Step 3** — Write `frontend/src/components/intelligence/GraphLegend.tsx`:
  ```tsx
  'use client'

  import { useTranslation } from '@/lib/hooks/use-translation'
  import { nodeColor, edgeColor } from './graph-transform'
  import type { BrainNodeKind, BrainEdgeType } from '@/lib/types/brain'

  const NODE_KINDS: BrainNodeKind[] = ['domain', 'topic', 'person', 'source']
  const EDGE_TYPES: BrainEdgeType[] = ['supersedes', 'disagrees', 'complements', 'agrees']

  export function GraphLegend() {
    const { t } = useTranslation()
    return (
      <div className="rounded-lg border bg-card p-3 text-xs space-y-3">
        <h3 className="font-semibold uppercase tracking-wide text-muted-foreground">
          {t('intelligence.legend.title')}
        </h3>
        <div className="space-y-1.5">
          <p className="text-muted-foreground">{t('intelligence.legend.nodes')}</p>
          {NODE_KINDS.map((kind) => (
            <div key={kind} className="flex items-center gap-2">
              <span
                className="inline-block h-3 w-3 rounded-full"
                style={{ backgroundColor: nodeColor(kind) }}
                aria-hidden
              />
              <span>{t(`intelligence.legend.${kind}`)}</span>
            </div>
          ))}
        </div>
        <div className="space-y-1.5">
          <p className="text-muted-foreground">{t('intelligence.legend.relationships')}</p>
          {EDGE_TYPES.map((type) => (
            <div key={type} className="flex items-center gap-2">
              <span
                className="inline-block h-0.5 w-5"
                style={{
                  backgroundColor: edgeColor(type),
                  borderTop: type === 'supersedes' ? `2px dashed ${edgeColor(type)}` : undefined,
                  height: type === 'supersedes' ? 0 : undefined,
                }}
                aria-hidden
              />
              <span>{t(`intelligence.legend.${type}`)}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  ```
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- src/components/intelligence/GraphLegend.test.tsx
  ```
- [ ] **Step 5** — Commit:
  ```
  git add frontend/src/components/intelligence/GraphLegend.tsx frontend/src/components/intelligence/GraphLegend.test.tsx && git commit -m "P7.3: add GraphLegend KEY panel"
  ```

---

### Task 8: NodeDetailPanel

**Files:** `frontend/src/components/intelligence/NodeDetailPanel.tsx`, `frontend/src/components/intelligence/NodeDetailPanel.test.tsx`

**Interfaces:**
- Consumes: `useBrainStore` (`selectedNodeId`), the current `graph` (passed as a prop from the page so the panel can look up the node), i18n `intelligence.detail.*`.
- Produces: `NodeDetailPanel` — shows the selected node's label/kind/salience; for a `source` node, renders a deep link to `/sources/:id` (id derived by stripping the `source:` prefix).

- [ ] **Step 1** — Write the failing test `frontend/src/components/intelligence/NodeDetailPanel.test.tsx`:
  ```ts
  import { describe, it, expect, beforeEach } from 'vitest'
  import { render, screen } from '@testing-library/react'
  import { NodeDetailPanel } from './NodeDetailPanel'
  import { useBrainStore } from '@/lib/stores/brain-store'
  import type { BrainGraph } from '@/lib/types/brain'

  const graph: BrainGraph = {
    nodes: [
      { id: 'domain:eng', kind: 'domain', label: 'Engineering', salience: 3 },
      { id: 'source:abc', kind: 'source', label: 'Design Doc', salience: 1 },
    ],
    edges: [],
  }

  describe('NodeDetailPanel', () => {
    beforeEach(() => {
      useBrainStore.setState({ selectedNodeId: null, highlightedNodeIds: [], panelOpen: false })
    })

    it('shows an empty prompt when no node is selected', () => {
      render(<NodeDetailPanel graph={graph} />)
      expect(screen.getByText('intelligence.detail.empty')).toBeInTheDocument()
    })

    it('shows the selected node label and kind', () => {
      useBrainStore.setState({ selectedNodeId: 'domain:eng' })
      render(<NodeDetailPanel graph={graph} />)
      expect(screen.getByText('Engineering')).toBeInTheDocument()
      expect(screen.getByText('intelligence.detail.kind.domain')).toBeInTheDocument()
    })

    it('renders a source deep link for a source node', () => {
      useBrainStore.setState({ selectedNodeId: 'source:abc' })
      render(<NodeDetailPanel graph={graph} />)
      const link = screen.getByRole('link', { name: 'intelligence.detail.viewSource' })
      expect(link).toHaveAttribute('href', '/sources/abc')
    })
  })
  ```
- [ ] **Step 2** — Run, expect **FAIL**:
  ```
  npm run test -- src/components/intelligence/NodeDetailPanel.test.tsx
  ```
- [ ] **Step 3** — Write `frontend/src/components/intelligence/NodeDetailPanel.tsx`:
  ```tsx
  'use client'

  import Link from 'next/link'
  import { useTranslation } from '@/lib/hooks/use-translation'
  import { useBrainStore } from '@/lib/stores/brain-store'
  import type { BrainGraph } from '@/lib/types/brain'

  interface NodeDetailPanelProps {
    graph?: BrainGraph
  }

  export function NodeDetailPanel({ graph }: NodeDetailPanelProps) {
    const { t } = useTranslation()
    const selectedNodeId = useBrainStore((s) => s.selectedNodeId)
    const node = graph?.nodes.find((n) => n.id === selectedNodeId)

    if (!node) {
      return (
        <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
          {t('intelligence.detail.empty')}
        </div>
      )
    }

    const sourceId = node.kind === 'source' ? node.id.replace(/^source:/, '') : null

    return (
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {t(`intelligence.detail.kind.${node.kind}`)}
          </p>
          <h3 className="text-lg font-semibold">{node.label}</h3>
        </div>
        <p className="text-sm text-muted-foreground">
          {t('intelligence.detail.salience')}: {node.salience.toFixed(2)}
        </p>
        {sourceId && (
          <Link
            href={`/sources/${sourceId}`}
            className="inline-block text-sm text-primary hover:underline"
          >
            {t('intelligence.detail.viewSource')}
          </Link>
        )}
      </div>
    )
  }
  ```
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- src/components/intelligence/NodeDetailPanel.test.tsx
  ```
- [ ] **Step 5** — Commit:
  ```
  git add frontend/src/components/intelligence/NodeDetailPanel.tsx frontend/src/components/intelligence/NodeDetailPanel.test.tsx && git commit -m "P7.3: add NodeDetailPanel with source deep link"
  ```

---

### Task 9: GraphCanvas (dynamic, react-force-graph-2d)

**Files:** `frontend/src/components/intelligence/GraphCanvas.tsx`, `frontend/src/components/intelligence/GraphCanvas.test.tsx`

**Interfaces:**
- Consumes: `graph: BrainGraph` prop, `toForceGraphData`/`nodeColor`/`edgeColor`/`edgeDashed`, `useBrainStore` (`selectNode`, `highlightedNodeIds`).
- Produces: `GraphCanvas` — renders the force graph; wires `onNodeClick → selectNode(node.id)`; passes `nodeColor`, `nodeVal`, link color/dash into the lib; reads `highlightedNodeIds` to draw a ring (via `nodeCanvasObjectMode`/`nodeCanvasObject`). The default export of `react-force-graph-2d` is DOM/canvas-only and mocked in the test.

**Why this split:** the heavy canvas render is not meaningfully unit-testable in jsdom; Task 6 tests the pure transforms. Here we mock `react-force-graph-2d`'s default export with a stub that (a) proves the transformed data is passed in and (b) exposes `onNodeClick` so we can assert it calls `selectNode`.

- [ ] **Step 1** — Write the failing test `frontend/src/components/intelligence/GraphCanvas.test.tsx`. Mock the lib default export with a stub that renders the node count and fires `onNodeClick`:
  ```tsx
  import { describe, it, expect, beforeEach, vi } from 'vitest'
  import { render, screen, fireEvent } from '@testing-library/react'
  import { useBrainStore } from '@/lib/stores/brain-store'
  import type { BrainGraph } from '@/lib/types/brain'

  // Mock next/dynamic so the { ssr:false } import resolves to the mocked lib synchronously.
  vi.mock('next/dynamic', () => ({
    default: (loader: () => Promise<{ default: React.ComponentType }>) => {
      const mod = require('react-force-graph-2d')
      return mod.default
    },
  }))

  // Stub the canvas-only lib: render node count, expose a button that triggers onNodeClick.
  vi.mock('react-force-graph-2d', () => ({
    default: ({ graphData, onNodeClick }: {
      graphData: { nodes: { id: string }[] }
      onNodeClick: (n: { id: string }) => void
    }) => (
      <div data-testid="force-graph">
        <span data-testid="node-count">{graphData.nodes.length}</span>
        <button data-testid="fire-click" onClick={() => onNodeClick({ id: graphData.nodes[0].id })}>
          click-node
        </button>
      </div>
    ),
  }))

  import { GraphCanvas } from './GraphCanvas'

  const graph: BrainGraph = {
    nodes: [
      { id: 'domain:eng', kind: 'domain', label: 'Engineering', salience: 3 },
      { id: 'source:abc', kind: 'source', label: 'Doc', salience: 1 },
    ],
    edges: [{ source: 'source:abc', target: 'domain:eng', type: 'mentions' }],
  }

  describe('GraphCanvas', () => {
    beforeEach(() => {
      useBrainStore.setState({ selectedNodeId: null, highlightedNodeIds: [], panelOpen: false })
    })

    it('passes transformed node data into the force graph', () => {
      render(<GraphCanvas graph={graph} />)
      expect(screen.getByTestId('node-count')).toHaveTextContent('2')
    })

    it('clicking a node selects it in the store', () => {
      render(<GraphCanvas graph={graph} />)
      fireEvent.click(screen.getByTestId('fire-click'))
      expect(useBrainStore.getState().selectedNodeId).toBe('domain:eng')
    })
  })
  ```
- [ ] **Step 2** — Run, expect **FAIL** (no `GraphCanvas`):
  ```
  npm run test -- src/components/intelligence/GraphCanvas.test.tsx
  ```
- [ ] **Step 3** — Write `frontend/src/components/intelligence/GraphCanvas.tsx`. Use `next/dynamic({ ssr:false })` and drive all encoding through the pure helpers:
  ```tsx
  'use client'

  import { useMemo } from 'react'
  import dynamic from 'next/dynamic'
  import { useBrainStore } from '@/lib/stores/brain-store'
  import {
    toForceGraphData,
    nodeColor,
    edgeColor,
    edgeDashed,
  } from './graph-transform'
  import type { BrainGraph, ForceGraphNode, ForceGraphLink } from '@/lib/types/brain'

  // Canvas/DOM-only lib — must never render on the server.
  const ForceGraph2D = dynamic(() => import('react-force-graph-2d'), { ssr: false })

  interface GraphCanvasProps {
    graph: BrainGraph
  }

  export function GraphCanvas({ graph }: GraphCanvasProps) {
    const selectNode = useBrainStore((s) => s.selectNode)
    const highlightedNodeIds = useBrainStore((s) => s.highlightedNodeIds)

    const data = useMemo(() => toForceGraphData(graph), [graph])
    const highlighted = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds])

    return (
      <ForceGraph2D
        graphData={data}
        nodeId="id"
        nodeVal={(n: ForceGraphNode) => n.val}
        nodeLabel={(n: ForceGraphNode) => n.label}
        nodeColor={(n: ForceGraphNode) => nodeColor(n.kind)}
        linkColor={(l: ForceGraphLink) => edgeColor(l.type)}
        linkLineDash={(l: ForceGraphLink) => (edgeDashed(l.type) ? [4, 4] : [])}
        onNodeClick={(n: ForceGraphNode) => selectNode(n.id)}
        nodeCanvasObjectMode={(n: ForceGraphNode) =>
          highlighted.has(n.id) ? 'before' : undefined
        }
        nodeCanvasObject={(n: ForceGraphNode & { x?: number; y?: number }, ctx: CanvasRenderingContext2D) => {
          // Draw a highlight ring for cited nodes (P7.4 populates highlightedNodeIds).
          if (n.x == null || n.y == null) return
          ctx.beginPath()
          ctx.arc(n.x, n.y, n.val + 4, 0, 2 * Math.PI)
          ctx.strokeStyle = '#2f7bf0'
          ctx.lineWidth = 2
          ctx.stroke()
        }}
      />
    )
  }
  ```
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- src/components/intelligence/GraphCanvas.test.tsx
  ```
- [ ] **Step 5** — Commit:
  ```
  git add frontend/src/components/intelligence/GraphCanvas.tsx frontend/src/components/intelligence/GraphCanvas.test.tsx && git commit -m "P7.3: add GraphCanvas (dynamic ssr:false react-force-graph-2d)"
  ```

---

### Task 10: Intelligence route/page (state machine + rebuild + right-panel slot)

**Files:** `frontend/src/app/(dashboard)/intelligence/page.tsx`, `frontend/src/app/(dashboard)/intelligence/page.test.tsx`

**Interfaces:**
- Consumes: `useBrainStatus`, `useBrainGraph`, `useRebuildBrain`, `GraphCanvas`, `GraphLegend`, `NodeDetailPanel`, `AppShell`.
- Produces: the `/intelligence` page. Three states driven by `useBrainStatus`: **empty** (`built_sources === 0 && !running`) → prompt + gated "Rebuild brain" button; **building** (`running` or `built_sources < total_sources`) → progress; **populated** → canvas center + `GraphLegend` + a reserved **right-panel `<aside data-testid="brain-right-panel">`** placeholder (P7.4 mounts `AskTheBrainPanel` here). `NodeDetailPanel` renders inside the right panel slot region.

**Right-panel slot location (for P7.4):** the `<aside data-testid="brain-right-panel">` inside the populated-state layout in `page.tsx`. P7.4 replaces the placeholder `<p>` inside it with `<AskTheBrainPanel />`; `NodeDetailPanel` stays above/below it.

- [ ] **Step 1** — Write the failing test `frontend/src/app/(dashboard)/intelligence/page.test.tsx`. Mock the hooks and child components (so canvas/lib never load):
  ```tsx
  import { describe, it, expect, vi, beforeEach } from 'vitest'
  import { render, screen, fireEvent } from '@testing-library/react'

  const useBrainStatus = vi.fn()
  const useBrainGraph = vi.fn()
  const rebuildMutate = vi.fn()
  vi.mock('@/lib/hooks/use-brain-graph', () => ({
    useBrainStatus: () => useBrainStatus(),
    useBrainGraph: () => useBrainGraph(),
    useRebuildBrain: () => ({ mutate: rebuildMutate, isPending: false }),
  }))
  vi.mock('@/components/intelligence/GraphCanvas', () => ({ GraphCanvas: () => <div data-testid="graph-canvas" /> }))
  vi.mock('@/components/intelligence/GraphLegend', () => ({ GraphLegend: () => <div data-testid="legend" /> }))
  vi.mock('@/components/intelligence/NodeDetailPanel', () => ({ NodeDetailPanel: () => <div data-testid="detail" /> }))
  vi.mock('@/components/layout/AppShell', () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }))

  import IntelligencePage from './page'

  describe('IntelligencePage', () => {
    beforeEach(() => { rebuildMutate.mockReset() })

    it('shows the empty state with a rebuild button when nothing is built', () => {
      useBrainStatus.mockReturnValue({ data: { total_sources: 3, built_sources: 0, running: false }, isLoading: false })
      useBrainGraph.mockReturnValue({ graph: { nodes: [], edges: [] }, isLoading: false })
      render(<IntelligencePage />)
      expect(screen.getByText('intelligence.empty.title')).toBeInTheDocument()
      expect(screen.queryByTestId('graph-canvas')).not.toBeInTheDocument()
    })

    it('rebuild button triggers the mutation', () => {
      useBrainStatus.mockReturnValue({ data: { total_sources: 3, built_sources: 0, running: false }, isLoading: false })
      useBrainGraph.mockReturnValue({ graph: { nodes: [], edges: [] }, isLoading: false })
      render(<IntelligencePage />)
      fireEvent.click(screen.getByRole('button', { name: 'intelligence.rebuild' }))
      expect(rebuildMutate).toHaveBeenCalledWith('incremental')
    })

    it('shows the building state while running', () => {
      useBrainStatus.mockReturnValue({ data: { total_sources: 4, built_sources: 1, running: true }, isLoading: false })
      useBrainGraph.mockReturnValue({ graph: { nodes: [], edges: [] }, isLoading: false })
      render(<IntelligencePage />)
      expect(screen.getByText('intelligence.building.title')).toBeInTheDocument()
    })

    it('shows the canvas, legend and right-panel slot when populated', () => {
      useBrainStatus.mockReturnValue({ data: { total_sources: 4, built_sources: 4, running: false }, isLoading: false })
      useBrainGraph.mockReturnValue({
        graph: { nodes: [{ id: 'd', kind: 'domain', label: 'Eng', salience: 1 }], edges: [] },
        isLoading: false,
      })
      render(<IntelligencePage />)
      expect(screen.getByTestId('graph-canvas')).toBeInTheDocument()
      expect(screen.getByTestId('legend')).toBeInTheDocument()
      expect(screen.getByTestId('brain-right-panel')).toBeInTheDocument()
    })
  })
  ```
- [ ] **Step 2** — Run, expect **FAIL**:
  ```
  npm run test -- "src/app/(dashboard)/intelligence/page.test.tsx"
  ```
- [ ] **Step 3** — Write `frontend/src/app/(dashboard)/intelligence/page.tsx`:
  ```tsx
  'use client'

  import { useTranslation } from '@/lib/hooks/use-translation'
  import { AppShell } from '@/components/layout/AppShell'
  import { Button } from '@/components/ui/button'
  import { LoadingSpinner } from '@/components/common/LoadingSpinner'
  import { GraphCanvas } from '@/components/intelligence/GraphCanvas'
  import { GraphLegend } from '@/components/intelligence/GraphLegend'
  import { NodeDetailPanel } from '@/components/intelligence/NodeDetailPanel'
  import { useBrainStatus, useBrainGraph, useRebuildBrain } from '@/lib/hooks/use-brain-graph'

  export default function IntelligencePage() {
    const { t } = useTranslation()
    const { data: status, isLoading: statusLoading } = useBrainStatus()
    const { graph, isLoading: graphLoading } = useBrainGraph()
    const rebuild = useRebuildBrain()

    // TODO(role): swap for a real membership/role hook once P2/P6 role infra is
    // surfaced on the frontend. Personal workspace role is always `owner`, so the
    // gate defaults open; the backend still enforces owner/admin on /brain/rebuild.
    const canRebuild = true

    const isRunning = !!status?.running
    const built = status?.built_sources ?? 0
    const total = status?.total_sources ?? 0
    const isBuilding = isRunning || (total > 0 && built < total && built > 0)
    const isEmpty = !statusLoading && built === 0 && !isRunning

    const rebuildButton = canRebuild ? (
      <Button
        onClick={() => rebuild.mutate('incremental')}
        disabled={rebuild.isPending || isRunning}
      >
        {t('intelligence.rebuild')}
      </Button>
    ) : null

    return (
      <AppShell>
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* Center: canvas / state */}
          <div className="flex-1 min-w-0 flex flex-col p-4 md:p-6">
            <div className="mb-4 flex items-center justify-between gap-2">
              <h1 className="text-xl md:text-2xl font-bold">{t('intelligence.title')}</h1>
              {!isEmpty && rebuildButton}
            </div>

            {statusLoading || graphLoading ? (
              <div className="flex flex-1 items-center justify-center">
                <LoadingSpinner />
              </div>
            ) : isEmpty ? (
              <div className="flex flex-1 flex-col items-center justify-center text-center gap-3">
                <h2 className="text-lg font-semibold">{t('intelligence.empty.title')}</h2>
                <p className="max-w-md text-sm text-muted-foreground">
                  {t('intelligence.empty.description')}
                </p>
                {rebuildButton}
              </div>
            ) : isBuilding ? (
              <div className="flex flex-1 flex-col items-center justify-center text-center gap-3">
                <LoadingSpinner />
                <h2 className="text-lg font-semibold">{t('intelligence.building.title')}</h2>
                <p className="text-sm text-muted-foreground">
                  {t('intelligence.building.progress')
                    .replace('{built}', String(built))
                    .replace('{total}', String(total))}
                </p>
              </div>
            ) : (
              <div className="relative flex-1 min-h-0 rounded-lg border overflow-hidden">
                {graph && <GraphCanvas graph={graph} />}
                <div className="absolute bottom-3 left-3 z-10">
                  <GraphLegend />
                </div>
              </div>
            )}
          </div>

          {/* Right panel slot: NodeDetailPanel now; P7.4 mounts AskTheBrainPanel here. */}
          <aside
            data-testid="brain-right-panel"
            className="hidden lg:flex w-80 flex-col gap-4 border-l p-4 overflow-y-auto"
          >
            <NodeDetailPanel graph={graph} />
            {/* P7.4: <AskTheBrainPanel /> mounts below the detail panel. */}
            <p className="text-xs text-muted-foreground">{t('intelligence.askPlaceholder')}</p>
          </aside>
        </div>
      </AppShell>
    )
  }
  ```
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- "src/app/(dashboard)/intelligence/page.test.tsx"
  ```
- [ ] **Step 5** — Commit:
  ```
  git add "frontend/src/app/(dashboard)/intelligence/page.tsx" "frontend/src/app/(dashboard)/intelligence/page.test.tsx" && git commit -m "P7.3: add /intelligence page (empty/building/populated + right-panel slot)"
  ```

---

### Task 11: Sidebar nav item + i18n keys

**Files:** `frontend/src/components/layout/AppSidebar.tsx`, `frontend/src/components/layout/AppSidebar.test.tsx` (new), all `frontend/src/lib/locales/*/index.ts`

**Interfaces:**
- Consumes: `navigation.intelligence` + `intelligence.*` i18n keys.
- Produces: an "Intelligence" nav item (`Network` icon, `href='/intelligence'`) in the "Process" section of `AppSidebar`.

- [ ] **Step 1** — Write the failing test `frontend/src/components/layout/AppSidebar.test.tsx`. (`use-translation`, `use-auth`, `sidebar-store`, `use-create-dialogs`, `next/navigation` are already mocked in `src/test/setup.ts`.)
  ```tsx
  import { describe, it, expect } from 'vitest'
  import { render, screen } from '@testing-library/react'
  import { AppSidebar } from './AppSidebar'

  describe('AppSidebar', () => {
    it('renders an Intelligence nav link to /intelligence', () => {
      render(<AppSidebar />)
      const links = screen.getAllByRole('link')
      const intel = links.find((l) => l.getAttribute('href') === '/intelligence')
      expect(intel).toBeDefined()
      expect(screen.getByText('navigation.intelligence')).toBeInTheDocument()
    })
  })
  ```
- [ ] **Step 2** — Run, expect **FAIL**:
  ```
  npm run test -- src/components/layout/AppSidebar.test.tsx
  ```
- [ ] **Step 3** — Edit `frontend/src/components/layout/AppSidebar.tsx`: add `Network` to the lucide import block, and add the nav item to the `process` section:
  ```tsx
  // in the lucide-react import list, add: Network
  {
    title: t('navigation.process'),
    items: [
      { name: t('navigation.notebooks'), href: '/notebooks', icon: Book },
      { name: t('navigation.askAndSearch'), href: '/search', icon: Search },
      { name: t('navigation.intelligence'), href: '/intelligence', icon: Network },
    ],
  },
  ```
- [ ] **Step 4** — Run, expect **PASS**:
  ```
  npm run test -- src/components/layout/AppSidebar.test.tsx
  ```
- [ ] **Step 5** — Add i18n keys to **every** locale `index.ts` in `src/lib/locales/`. In en-US, add `intelligence: "Intelligence"` to the `navigation` block, and add a new top-level `intelligence` block:
  ```ts
  // navigation: { ... intelligence: "Intelligence", }
  intelligence: {
    title: "Intelligence",
    rebuild: "Rebuild brain",
    rebuildStarted: "Brain rebuild started",
    askPlaceholder: "Ask the Brain (coming soon)",
    empty: {
      title: "No knowledge graph yet",
      description: "Build your workspace brain to visualize how your sources connect.",
    },
    building: {
      title: "Building your brain…",
      progress: "{built} of {total} sources processed",
    },
    legend: {
      title: "Key",
      nodes: "Node types",
      relationships: "Relationships",
      domain: "Domain",
      topic: "Topic",
      person: "Person / decision",
      source: "Source",
      supersedes: "Supersedes",
      disagrees: "Disagrees",
      complements: "Complements",
      agrees: "Agrees",
    },
    detail: {
      empty: "Select a node to see details",
      salience: "Salience",
      viewSource: "View source",
      kind: {
        domain: "Domain",
        topic: "Topic",
        person: "Person",
        decision: "Decision",
        source: "Source",
      },
    },
  },
  ```
  For the other 13 locales, mirror the same key structure (translate `navigation.intelligence` + the `intelligence` block; en-US values are an acceptable fallback where a translation is not yet available — but the KEYS must exist in all locales so no key is missing). Preserve each file's existing formatting.
- [ ] **Step 6** — Verify the whole suite is green and the app builds. Run:
  ```
  npm run test
  npm run lint
  npm run build
  ```
  Expected: all tests **PASS**, lint clean, build succeeds with `/intelligence` in the route list.
- [ ] **Step 7** — Commit:
  ```
  git add "frontend/src/components/layout/AppSidebar.tsx" "frontend/src/components/layout/AppSidebar.test.tsx" "frontend/src/lib/locales" && git commit -m "P7.3: add Intelligence sidebar nav item + i18n keys (all locales)"
  ```

---

## Self-Review

**Spec coverage (P7.3 scope):**

- ✅ **brain types** — `lib/types/brain.ts` exports `BrainNode`, `BrainEdge`, `BrainGraph`, `BrainStatus`, and the `ForceGraphData` shape (Task 2), VERBATIM per the shared contract.
- ✅ **brainApi client** — `lib/api/brain.ts` `getGraph`/`getStatus`/`rebuild` via shared `apiClient` (Task 3), matching the P7.1/P7.2 endpoints and signatures.
- ✅ **hooks** — `useBrainGraph` (`['brain','graph']`), `useBrainStatus` (`['brain','status']`, polls while running), `useRebuildBrain` (mutation, invalidates `['brain']`, toasts) (Task 4).
- ✅ **brain-store** — Zustand `useBrainStore` with `selectedNodeId`/`highlightedNodeIds`/`panelOpen`/`selectNode`/`setHighlighted`/`togglePanel` (Task 5); `highlightedNodeIds` reserved for P7.4.
- ✅ **GraphCanvas** — `react-force-graph-2d` via `next/dynamic({ssr:false})`, color/edge encoding through pure helpers, click→`selectNode`, hover labels (`nodeLabel`), `highlightedNodeIds` ring (Task 9). Heavy render untested by design; **pure transforms + color/style helpers extracted to `graph-transform.ts` and unit-tested** (Task 6); lib default export mocked in the component test.
- ✅ **GraphLegend** — node-kind + edge-type KEY, colors from the shared helpers (Task 7).
- ✅ **NodeDetailPanel** — selected-node details + deep link to `/sources/:id` (Task 8).
- ✅ **intelligence page** — canvas center, empty/building/populated states from `useBrainStatus`, role-gated "Rebuild brain" button, reserved right-panel `<aside data-testid="brain-right-panel">` slot (Task 10).
- ✅ **AppSidebar nav item + i18n** — `Network` icon, `/intelligence`, `navigation.intelligence` + `intelligence.*` in all locales (Task 11).
- ✅ **dependency** — `react-force-graph-2d` + `d3-force` installed (Task 1).
- ✅ **Tests** — API→ForceGraphData transform (T6), hook behavior with mocked `brainApi` (T4), node-color/edge-style mapping (T6), empty vs building vs populated states (T10), legend render (T7), store actions (T5), plus API client (T3), detail panel (T8), canvas click→select with mocked lib (T9), sidebar nav (T11).

**Visual encoding verified against spec:** node colors `domain #e0651f` / `source #e6e6e6` / `topic #8a8a8a` / `person`+`decision` `#2f7bf0`; radius scaled by salience (`nodeVal`); edges `supersedes` dashed neutral, `disagrees #e23b3b`, `complements #2f7bf0`, `agrees` neutral solid, `part_of`/`mentions` faint grey — asserted in `graph-transform.test.ts`.

**Out of scope (correctly deferred to P7.4):** `POST /brain/ask`, `AskTheBrainPanel`, `cited_node_ids` streaming/highlighting wiring. This plan only reserves the right-panel slot and the `highlightedNodeIds` store field the panel will write to.

**Constraints honored:** TanStack Query for server state, Zustand for UI state; every string i18n'd; TDD test-first throughout; canvas lib dynamic-imported `ssr:false`; all requests via shared `apiClient`; commands run from `frontend/`.
