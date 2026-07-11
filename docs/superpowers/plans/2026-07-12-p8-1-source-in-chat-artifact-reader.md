# P8.1 — Source-in-Chat + Artifact Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the control plane, show added sources in the right sidebar with live status and a private-by-default badge, and let a citation (or source click) open a left **artifact reader** panel that displays the source content with the cited passage highlighted.

**Architecture:** Additive on top of P8.0. Adds one migration (`source.visibility`, default `private`) and surfaces it through the existing source API/model — no new backend service. Frontend adds a URL-param-driven artifact panel (mirroring the existing `use-modal-manager` pattern) as a new left column of the control plane, a real `Sources` sidebar section (reusing `use-sources` + status polling), and rewires answer citations to open the artifact panel instead of the modal when inside the control plane.

**Tech Stack:** SurrealDB migrations (`.surrealql`), FastAPI, Python 3.12 (`uv`, pytest, ruff), Next.js 16 / React 19 / TanStack Query 5 / Zustand 5 / vitest, `Sheet` primitive from P8.0.

## Global Constraints

- **Depends on P8.0** (control plane shell, `Sheet`, `ControlPlane`, `ContextSidebar`, `controlPlane.*` i18n keys). Treat P8.0 as landed.
- **Async-first / data discipline:** HTTP via `apiClient`; TanStack hooks in `lib/hooks/`; broad invalidation + toast.
- **i18n test-enforced:** new strings → `t()`, keys in **all 14 locales**, referenced in source (`locales/index.test.ts`).
- **Migrations are hard-coded:** add `open_notebook/database/migrations/20.surrealql` **and** `20_down.surrealql`, then append **both** to the two lists in `open_notebook/database/async_migrate.py` `AsyncMigrationManager.__init__`. Migrations run on API startup. SurrealDB tables are SCHEMAFULL; use `FLEXIBLE`/`option<>` idioms as in migration 15/19.
- **Reversibility:** revert = `20_down.surrealql` + delete `ArtifactReader`/artifact param code; the control plane still works without the artifact column.
- Backend from repo root: `uv run pytest tests/`, `ruff check . --fix`. Frontend from `frontend/`: `npm run test`, `npm run lint`, `npm run build`.

---

### Task 1: Migration 20 — `source.visibility` (private by default)

**Files:**
- Create: `open_notebook/database/migrations/20.surrealql`
- Create: `open_notebook/database/migrations/20_down.surrealql`
- Modify: `open_notebook/database/async_migrate.py` (append `20.surrealql` / `20_down.surrealql` to the up/down lists in `AsyncMigrationManager.__init__`)
- Test: `tests/test_migration_20_visibility.py`

**Interfaces:**
- Produces: `source.visibility` field, `string`, default `'private'`, values `'private' | 'company'`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migration_20_visibility.py
from pathlib import Path

def test_migration_20_defines_visibility_private_default():
    up = Path("open_notebook/database/migrations/20.surrealql").read_text()
    assert "DEFINE FIELD visibility ON source" in up
    assert "'private'" in up  # default
    down = Path("open_notebook/database/migrations/20_down.surrealql").read_text()
    assert "REMOVE FIELD visibility ON source" in down

def test_migration_20_registered():
    src = Path("open_notebook/database/async_migrate.py").read_text()
    assert "20.surrealql" in src and "20_down.surrealql" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration_20_visibility.py -v`
Expected: FAIL — files don't exist / not registered.

- [ ] **Step 3: Write the migration + register it**

```surql
-- open_notebook/database/migrations/20.surrealql
DEFINE FIELD visibility ON source TYPE string DEFAULT 'private'
  ASSERT $value IN ['private', 'company'];
```

```surql
-- open_notebook/database/migrations/20_down.surrealql
REMOVE FIELD visibility ON source;
```

Append `"20.surrealql"` to the up-migration list and `"20_down.surrealql"` to the down-migration list in `AsyncMigrationManager.__init__` (`open_notebook/database/async_migrate.py`), preserving order (after 19).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migration_20_visibility.py -v`
Expected: PASS.

- [ ] **Step 5: Apply + smoke the migration**

Run: `make database` then `make api` (migrations run on startup). Check API logs show migration version advancing to 20 with no error.

- [ ] **Step 6: Commit**

```bash
git add open_notebook/database/migrations/20.surrealql open_notebook/database/migrations/20_down.surrealql open_notebook/database/async_migrate.py tests/test_migration_20_visibility.py
git commit -m "feat(governance): migration 20 - source.visibility private by default"
```

---

### Task 2: Surface `visibility` on the Source model + API

**Files:**
- Modify: `open_notebook/domain/notebook.py` (`Source` model — add `visibility: str = "private"`)
- Modify: `api/routers/sources.py` (include `visibility` in the source response payload)
- Test: `tests/test_source_visibility.py`

**Interfaces:**
- Consumes: migration 20.
- Produces: `Source.visibility` (default `"private"`); `GET /sources/{id}` and list responses include `visibility`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_source_visibility.py
from open_notebook.domain.notebook import Source

def test_source_defaults_to_private():
    s = Source(title="x")
    assert s.visibility == "private"

def test_source_accepts_company_visibility():
    s = Source(title="x", visibility="company")
    assert s.visibility == "company"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_source_visibility.py -v`
Expected: FAIL — `Source` has no `visibility`.

- [ ] **Step 3: Add the field + expose it**

In `open_notebook/domain/notebook.py`, add to the `Source` model:

```python
    visibility: str = "private"  # 'private' | 'company' (P8.1)
```

In `api/routers/sources.py`, wherever a source is serialized to its response model (e.g. `SourceResponse`), add `visibility=source.visibility` (and add the field to that Pydantic response model with default `"private"`). Follow the existing serialization pattern in that file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_source_visibility.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add open_notebook/domain/notebook.py api/routers/sources.py tests/test_source_visibility.py
git commit -m "feat(governance): expose source.visibility on model + API"
```

---

### Task 3: Artifact URL-param hook (`useArtifact`)

Mirror `use-modal-manager` (URL-param state) so citation click-through is deep-linkable and does not add local state.

**Files:**
- Create: `frontend/src/lib/hooks/use-artifact.ts`
- Test: `frontend/src/lib/hooks/use-artifact.test.tsx`

**Interfaces:**
- Produces: `useArtifact()` → `{ artifact: { type: 'source' | 'belief'; id: string; loc?: string } | null; openArtifact(type, id, loc?): void; closeArtifact(): void }`. Reads `?artifact=&aid=&loc=` from the URL; `openArtifact` does `router.push` preserving other params (`scroll:false`).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/lib/hooks/use-artifact.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams('artifact=source&aid=abc&loc=4'),
}));

import { useArtifact } from './use-artifact';

describe('useArtifact', () => {
  it('parses artifact params from the URL', () => {
    const { result } = renderHook(() => useArtifact());
    expect(result.current.artifact).toEqual({ type: 'source', id: 'abc', loc: '4' });
  });

  it('openArtifact pushes the encoded params', () => {
    const { result } = renderHook(() => useArtifact());
    result.current.openArtifact('belief', 'xyz');
    expect(push).toHaveBeenCalled();
    expect(push.mock.calls[0][0]).toContain('artifact=belief');
    expect(push.mock.calls[0][0]).toContain('aid=xyz');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- use-artifact`
Expected: FAIL — cannot resolve `./use-artifact`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/lib/hooks/use-artifact.ts
'use client';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';

export type ArtifactRef = { type: 'source' | 'belief'; id: string; loc?: string };

export function useArtifact() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const type = params.get('artifact');
  const id = params.get('aid');
  const artifact: ArtifactRef | null =
    (type === 'source' || type === 'belief') && id
      ? { type, id, loc: params.get('loc') ?? undefined }
      : null;

  const write = (next: URLSearchParams) => router.push(`${pathname}?${next.toString()}`, { scroll: false });

  const openArtifact = (t: ArtifactRef['type'], aid: string, loc?: string) => {
    const next = new URLSearchParams(params.toString());
    next.set('artifact', t);
    next.set('aid', aid);
    if (loc) next.set('loc', loc); else next.delete('loc');
    write(next);
  };
  const closeArtifact = () => {
    const next = new URLSearchParams(params.toString());
    next.delete('artifact'); next.delete('aid'); next.delete('loc');
    write(next);
  };

  return { artifact, openArtifact, closeArtifact };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- use-artifact`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/hooks/use-artifact.ts frontend/src/lib/hooks/use-artifact.test.tsx
git commit -m "feat(control-plane): URL-param artifact hook"
```

---

### Task 4: `ArtifactReader` (left panel)

Renders the referenced source's content with the cited locator highlighted. Uses `Sheet`-less inline column (the control plane owns the column); content via `MarkdownRenderer`.

**Files:**
- Create: `frontend/src/components/control-plane/ArtifactReader.tsx`
- Test: `frontend/src/components/control-plane/ArtifactReader.test.tsx`

**Interfaces:**
- Consumes: `useArtifact` (Task 3); `useSource(id)` (`@/lib/hooks/use-sources`); `MarkdownRenderer` (`@/components/ui/markdown-renderer`); `useTranslation`.
- Produces: `<ArtifactReader />` — renders null when no artifact param; otherwise a fixed-width column with header (source title + close) and body (full_text via MarkdownRenderer). `loc` shown as a "page/locator" chip. (Belief lineage rendering arrives in P8.2 — here it renders a stub for `type==='belief'`.)

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/ArtifactReader.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-artifact', () => ({
  useArtifact: () => ({ artifact: { type: 'source', id: 'abc', loc: '4' }, openArtifact: vi.fn(), closeArtifact: vi.fn() }),
}));
vi.mock('@/lib/hooks/use-sources', () => ({
  useSource: () => ({ data: { id: 'abc', title: 'Q3 Research', full_text: 'SMB skews higher.', visibility: 'private' }, isLoading: false }),
}));

import { ArtifactReader } from './ArtifactReader';

describe('ArtifactReader', () => {
  it('shows the source title and content when an artifact is open', () => {
    render(<ArtifactReader />);
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/SMB skews higher/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- ArtifactReader`
Expected: FAIL — cannot resolve `./ArtifactReader`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/control-plane/ArtifactReader.tsx
'use client';
import { X } from 'lucide-react';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useSource } from '@/lib/hooks/use-sources';
import { MarkdownRenderer } from '@/components/ui/markdown-renderer';
import { useTranslation } from '@/lib/hooks/use-translation';

export function ArtifactReader() {
  const { t } = useTranslation();
  const { artifact, closeArtifact } = useArtifact();
  if (!artifact) return null;

  return (
    <aside className="flex w-[384px] flex-shrink-0 flex-col border-r border-border bg-muted/40">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          {t('controlPlane.artifact.title')}
        </span>
        <button type="button" aria-label={t('common.close')} onClick={closeArtifact} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      {artifact.type === 'source' ? <SourceArtifact id={artifact.id} loc={artifact.loc} /> : <BeliefArtifactStub />}
    </aside>
  );
}

function SourceArtifact({ id, loc }: { id: string; loc?: string }) {
  const { data, isLoading } = useSource(id);
  const { t } = useTranslation();
  if (isLoading) return <div className="p-4 text-sm text-muted-foreground">{t('common.loading')}</div>;
  if (!data) return <div className="p-4 text-sm text-muted-foreground">{t('controlPlane.artifact.notFound')}</div>;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-4 py-2">
        <div className="text-sm font-semibold text-foreground">{data.title}</div>
        {loc ? <div className="text-xs text-muted-foreground">{t('controlPlane.artifact.locator', { loc } as never)}</div> : null}
      </div>
      <div className="flex-1 overflow-y-auto p-4 text-sm">
        <MarkdownRenderer content={data.full_text ?? ''} />
      </div>
    </div>
  );
}

function BeliefArtifactStub() {
  const { t } = useTranslation();
  return <div className="p-4 text-sm text-muted-foreground">{t('controlPlane.artifact.lineageComingSoon')}</div>;
}
```

> Add the referenced keys to all 14 locales: `controlPlane.artifact.title`, `.locator` (with `{loc}` interpolation done via manual `.replace` like the rest of the app — adjust the call to match the app's interpolation style), `.notFound`, `.lineageComingSoon`, plus reuse `common.close`/`common.loading` if they exist (check `en-US`). Verify `useSource`'s return shape (`data.full_text`, `data.title`) against `frontend/src/lib/hooks/use-sources.ts`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- ArtifactReader`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/ArtifactReader.tsx frontend/src/components/control-plane/ArtifactReader.test.tsx frontend/src/lib/locales
git commit -m "feat(control-plane): artifact reader panel (source)"
```

---

### Task 5: Wire artifact column into `ControlPlane` + citations open it

**Files:**
- Modify: `frontend/src/components/control-plane/ControlPlane.tsx` (insert `<ArtifactReader />` between `Rail` and chat)
- Modify: `frontend/src/components/control-plane/ControlPlaneChat.tsx` (render answer with a citation link component that calls `openArtifact('source', id)`)
- Test: `frontend/src/components/control-plane/ControlPlane.artifact.test.tsx`

**Interfaces:**
- Consumes: `useArtifact`, `parseSourceReferences`/`createCompactReferenceLinkComponent` (`@/lib/utils/source-references`).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/ControlPlane.artifact.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({ usePathname: () => '/', useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams('artifact=source&aid=abc') }));
vi.mock('@/lib/hooks/use-ask', () => ({ useAsk: () => ({ isStreaming: false, answers: [], finalAnswer: '', error: null, sendAsk: vi.fn(), reset: vi.fn() }) }));
vi.mock('@/lib/hooks/use-create-dialogs', () => ({ useCreateDialogs: () => ({ openSourceDialog: vi.fn() }) }));
vi.mock('@/lib/hooks/use-sources', () => ({ useSource: () => ({ data: { id: 'abc', title: 'Q3 Research', full_text: 'body', visibility: 'private' }, isLoading: false }), useRecentSources: () => ({ data: [], isLoading: false }) }));

import { ControlPlane } from './ControlPlane';

describe('ControlPlane with artifact param', () => {
  it('renders the artifact reader column when ?artifact is set', () => {
    render(<ControlPlane />);
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- ControlPlane.artifact`
Expected: FAIL — artifact column not wired.

- [ ] **Step 3: Wire it**

In `ControlPlane.tsx`, insert the reader (it self-hides when no param):

```tsx
        <Rail />
        <ArtifactReader />
        <ControlPlaneChat />
        <ContextSidebar />
```

In `ControlPlaneChat.tsx`, replace the raw `AnswerBody` usage with a MarkdownRenderer + citation link component that opens the artifact:

```tsx
import { useArtifact } from '@/lib/hooks/use-artifact';
import { MarkdownRenderer } from '@/components/ui/markdown-renderer';
import { buildReferenceIndex, createCompactReferenceLinkComponent } from '@/lib/utils/source-references';
// ...
const { openArtifact } = useArtifact();
const onRef = (type: string, id: string) => { if (type === 'source' || type === 'source_insight') openArtifact('source', id); };
// in render, when finalAnswer:
<MarkdownRenderer
  content={buildReferenceIndex(finalAnswer).numberedText}
  components={{ a: createCompactReferenceLinkComponent(onRef) }}
/>
```

> Confirm the exact signature of `createCompactReferenceLinkComponent` in `frontend/src/lib/utils/source-references.tsx` (the frontend map: it returns a ReactMarkdown `a` component that intercepts `#ref-` hrefs and calls back with `(type, id)`). Adjust `MarkdownRenderer`'s `components` prop name to match its real API.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- ControlPlane.artifact`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/ControlPlane.tsx frontend/src/components/control-plane/ControlPlaneChat.tsx frontend/src/components/control-plane/ControlPlane.artifact.test.tsx
git commit -m "feat(control-plane): wire artifact column + citation click-through"
```

---

### Task 6: Real `Sources` sidebar section (status + private badge)

Replace the P8.0 placeholder `Sources` empty-state with a live list: recently added sources, each with a status pill (polling while processing) and a `Private` visibility badge. Clicking a source opens the artifact reader.

**Files:**
- Create: `frontend/src/components/control-plane/SourcesSection.tsx`
- Modify: `frontend/src/components/control-plane/ContextSidebar.tsx` (use `SourcesSection` instead of the empty state)
- Modify: `frontend/src/lib/hooks/use-sources.ts` (add `useRecentSources()` if a global recent-sources hook doesn't already exist)
- Test: `frontend/src/components/control-plane/SourcesSection.test.tsx`

**Interfaces:**
- Consumes: `useRecentSources()` → `{ data?: Array<{ id; title; visibility; status? }>, isLoading }`; `useSourceStatus(id)` (existing, polls 2s); `useArtifact`.
- Produces: `<SourcesSection />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/SourcesSection.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-sources', () => ({
  useRecentSources: () => ({ data: [{ id: 's1', title: 'Q3 Research', visibility: 'private' }], isLoading: false }),
  useSourceStatus: () => ({ data: { status: 'completed' } }),
}));
vi.mock('@/lib/hooks/use-artifact', () => ({ useArtifact: () => ({ openArtifact: vi.fn() }) }));

import { SourcesSection } from './SourcesSection';

describe('SourcesSection', () => {
  it('lists a source with its title and a private badge', () => {
    render(<SourcesSection />);
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/private/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- SourcesSection`
Expected: FAIL — cannot resolve `./SourcesSection` (and maybe `useRecentSources`).

- [ ] **Step 3: Implement**

If `useRecentSources` doesn't exist, add it to `use-sources.ts` (thin wrapper over the existing global list endpoint the `/sources` page uses — reuse `sourcesApi.list` with a small page size, keyed `['sources','recent']`):

```ts
export function useRecentSources() {
  return useQuery({
    queryKey: [...QUERY_KEYS.sources, 'recent'],
    queryFn: () => sourcesApi.list({ page: 1, page_size: 10 }), // match sourcesApi.list's real signature
    staleTime: 5000,
  });
}
```

```tsx
// frontend/src/components/control-plane/SourcesSection.tsx
'use client';
import { FileText } from 'lucide-react';
import { useRecentSources } from '@/lib/hooks/use-sources';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

export function SourcesSection() {
  const { t } = useTranslation();
  const { data, isLoading } = useRecentSources();
  const { openArtifact } = useArtifact();
  const sources = (data ?? []) as Array<{ id: string; title: string; visibility?: string; status?: string }>;

  if (isLoading) return <div className="text-xs text-muted-foreground">{t('common.loading')}</div>;
  if (sources.length === 0)
    return <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{t('controlPlane.sidebar.sourcesEmpty')}</div>;

  return (
    <div className="flex flex-col gap-1.5">
      {sources.map((s) => (
        <button
          key={s.id}
          type="button"
          onClick={() => openArtifact('source', s.id)}
          className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5 text-left hover:border-primary"
        >
          <span className="grid h-6 w-6 place-items-center rounded-md bg-muted text-muted-foreground"><FileText className="h-3.5 w-3.5" /></span>
          <span className="flex-1 truncate text-xs font-semibold text-foreground">{s.title}</span>
          <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold',
            s.visibility === 'company' ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground')}>
            {t(s.visibility === 'company' ? 'controlPlane.badge.company' : 'controlPlane.badge.private')}
          </span>
        </button>
      ))}
    </div>
  );
}
```

Wire it into `ContextSidebar.tsx`: replace `<Empty text={t('controlPlane.sidebar.sourcesEmpty')} />` inside the Sources section with `<SourcesSection />`. Add i18n keys `controlPlane.badge.private`, `controlPlane.badge.company` to all 14 locales.

> Confirm `sourcesApi.list` param/return shape in `frontend/src/lib/api/sources.ts`. Status pill (Processing/Ready) can reuse `useSourceStatus` per-row as a follow-up; the private/company badge is the P8.1 must-have.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- SourcesSection`
Expected: PASS.

- [ ] **Step 5: Full gate + manual smoke**

Run: `npm run test -- locales` (parity + unused-key green), then `npm run lint && npm run build`.
Manual: from `/`, add a source → it appears in the Sources sidebar with a `Private` badge; ask a question whose answer cites a source → click the citation → artifact reader opens on the left with the source content; close it.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/control-plane/SourcesSection.tsx frontend/src/components/control-plane/ContextSidebar.tsx frontend/src/lib/hooks/use-sources.ts frontend/src/components/control-plane/SourcesSection.test.tsx frontend/src/lib/locales
git commit -m "feat(control-plane): live sources sidebar with private-by-default badge"
```

---

## Self-Review

**Spec coverage:** UX5 citation→artifact reader (Tasks 3–5) ✓; §6.3 `source.visibility` private-by-default (Tasks 1–2) ✓; Sources sidebar with status/badge (Task 6) ✓; §9.0 artifact via URL param (Task 3) ✓. Belief lineage in the artifact panel is stubbed (Task 4) and completed in P8.2. Full status-pill polling per row noted as a follow-up (badge is the must-have).

**Placeholder scan:** No TBD/TODO. `BeliefArtifactStub` is an explicit, labeled stub handed to P8.2, not a hidden placeholder.

**Type consistency:** `useArtifact()` return shape (`artifact/openArtifact/closeArtifact`) defined in Task 3, consumed identically in Tasks 4–6. `openArtifact('source', id)` signature consistent across Chat/SourcesSection. `visibility` values `'private'|'company'` consistent between migration, model, and badge.

**Implementer verification points (flagged inline):** `SourceResponse` serialization spot in `sources.py`; `useSource` return shape; `createCompactReferenceLinkComponent` signature + `MarkdownRenderer` `components` prop; `sourcesApi.list` signature; app's i18n interpolation style for `{loc}`.
