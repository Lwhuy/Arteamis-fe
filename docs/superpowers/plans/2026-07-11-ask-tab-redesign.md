# Ask Tab Quelvio-Style Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle Open Notebook's Ask tab to match the Quelvio reference — question-as-title, borderless answer, feedback row, a merged collapsible strategy disclosure, a bottom-docked follow-up bar, and a right-side Sources panel — reusing existing ask/streaming/citation logic. Search tab untouched.

**Architecture:** All work is in the Next.js frontend. The `/search` page keeps its `useAsk` streaming hook and `Tabs`; only the **Ask** `TabsContent` is re-laid-out into a two-column shell (answer left, Sources panel right) with the question rendered as a heading and the input relocated to a docked follow-up bar that calls the same stateless `handleAsk`. A new pure util `buildReferenceIndex` produces both the numbered inline citations and the ordered unique reference list so the answer's `[1][2]` markers and the Sources panel numbering are guaranteed consistent. The Sources panel fetches each cited item via TanStack `useQueries`, reusing the existing per-item query keys/APIs.

**Tech Stack:** Next.js 16 (App Router), React, TanStack Query (`useQueries`), shadcn/ui (Card/Collapsible/Button/Badge), lucide-react icons, i18next (14 locales), vitest + @testing-library/react, sonner toasts.

---

## Spec

Source spec: `docs/superpowers/specs/2026-07-11-ask-tab-redesign-design.md`

## Pinned implementation decisions (resolved during planning)

- **Snippet rule:** first 150 characters of the item's text field (`full_text` for source, `content` for note, `content` for insight), whitespace-collapsed and trimmed; append `…` only if the source string was longer than 150 chars. No chunk-level matching exists today, so always use the full-content field.
- **Detail-fetch failure fallback:** if a cited item's query errors or returns nothing (deleted item, network error), the Sources panel still renders that entry's row with its number, type icon, and a localized "Reference unavailable" line instead of a snippet — so the numbers stay aligned with the inline `[n]` citations. Never silently drop a cited reference.
- **Hook reuse:** do NOT call `useSource`/`useNote`/`useInsight` in a loop (violates Rules of Hooks for a dynamic list). Use `useQueries`, reconstructing each query from the reference type: `sourcesApi.get` / `notesApi.get` / `insightsApi.get`, with query keys `['sources', fullId]` / `['notes', fullId]` / `['insights', fullId]` to share the cache with those hooks. `fullId = id.includes(':') ? id : \`${type}:${id}\`` (type `source_insight` keeps that prefix).
- **Save-to-Notebooks move:** the existing `{ask.finalAnswer && <Button>Save…</Button>}` + `SaveToNotebooksDialog` wiring moves verbatim into the new feedback row; the `showSaveDialog` state and dialog stay in `page.tsx`. Conditional (`ask.finalAnswer`) is preserved.
- **i18n:** there are **14** locale folders under `frontend/src/lib/locales/` (`bn-IN, ca-ES, de-DE, en-US, es-ES, fr-FR, it-IT, ja-JP, pl-PL, pt-BR, ru-RU, tr-TR, zh-CN, zh-TW`). `locales/index.test.ts` enforces (a) exact key parity with en-US across all 14 and (b) that every en-US leaf key is referenced somewhere in source. So: add each new key to all 14 files AND make sure it's used in code. Non-English locales may hold the English string as a placeholder (parity is by key, not translation quality).

## File structure

- **Modify** `frontend/src/lib/utils/source-references.tsx` — add `buildReferenceIndex(text)` (+ `truncateSnippet(text, max)` helper) as pure, exported functions.
- **Create** `frontend/src/lib/utils/source-references.test.tsx` — unit tests for the two new pure functions (co-located test; repo uses vitest).
- **Create** `frontend/src/components/search/AnswerFeedback.tsx` — feedback row: 👍/👎 (UI-only toast), Copy (real), and a `children` slot for the Save-to-Notebooks button.
- **Create** `frontend/src/components/search/AnswerFeedback.test.tsx`.
- **Create** `frontend/src/components/search/SourcesPanel.tsx` — right-side panel; takes `references: ReferenceIndexEntry[]`, fetches via `useQueries`, renders numbered rows with title + snippet + click-to-open.
- **Create** `frontend/src/components/search/SourcesPanel.test.tsx`.
- **Modify** `frontend/src/components/search/StreamingResponse.tsx` — merge Strategy + Individual Answers into one collapsed-by-default disclosure; render the final answer borderless (no `Card`); switch citation rendering to `buildReferenceIndex` numbered links.
- **Modify** `frontend/src/app/(dashboard)/search/page.tsx` — Ask tab only: question-as-heading + "New Question" reset, two-column layout (answer + `SourcesPanel`), relocate model badges/Advanced + Ask button into a docked follow-up bar, mount `AnswerFeedback`.
- **Modify** all 14 `frontend/src/lib/locales/*/index.ts` — add new `searchPage.*` keys.

---

## Task 1: `buildReferenceIndex` + `truncateSnippet` pure utils

**Files:**
- Modify: `frontend/src/lib/utils/source-references.tsx`
- Test: `frontend/src/lib/utils/source-references.test.tsx` (create)

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/lib/utils/source-references.test.tsx
import { describe, it, expect } from 'vitest'
import { buildReferenceIndex, truncateSnippet } from './source-references'

describe('buildReferenceIndex', () => {
  it('numbers unique references in first-appearance order and dedups repeats', () => {
    const { numberedText, references } = buildReferenceIndex(
      'See [source:a] and [note:b]. Also [source:a] again.'
    )
    expect(references).toEqual([
      { number: 1, type: 'source', id: 'a' },
      { number: 2, type: 'note', id: 'b' },
    ])
    // first source:a -> [1], note:b -> [2], second source:a -> [1]
    expect(numberedText).toContain('[1](#ref-source-a)')
    expect(numberedText).toContain('[2](#ref-note-b)')
    // does NOT append a "References:" text list (panel replaces it)
    expect(numberedText).not.toMatch(/References:/)
  })

  it('normalizes the insight: alias to source_insight', () => {
    const { references } = buildReferenceIndex('Per [insight:z].')
    expect(references).toEqual([{ number: 1, type: 'source_insight', id: 'z' }])
  })

  it('returns empty references and unchanged text when there are none', () => {
    const { numberedText, references } = buildReferenceIndex('no refs here')
    expect(references).toEqual([])
    expect(numberedText).toBe('no refs here')
  })
})

describe('truncateSnippet', () => {
  it('collapses whitespace and trims', () => {
    expect(truncateSnippet('  a\n\n  b  ', 100)).toBe('a b')
  })
  it('truncates with an ellipsis only when longer than max', () => {
    expect(truncateSnippet('abcdef', 3)).toBe('abc…')
    expect(truncateSnippet('abc', 3)).toBe('abc')
  })
  it('handles empty/nullish input', () => {
    expect(truncateSnippet('', 10)).toBe('')
    expect(truncateSnippet(null as unknown as string, 10)).toBe('')
  })
})
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd frontend && npm run test -- src/lib/utils/source-references.test.tsx`
Expected: FAIL — `buildReferenceIndex`/`truncateSnippet` not exported.

- [ ] **Step 3: Implement the utils**

Add to `frontend/src/lib/utils/source-references.tsx` (reuse existing `parseSourceReferences` and the `#ref-{type}-{id}` href convention already used by `createCompactReferenceLinkComponent`):

```tsx
export interface ReferenceIndexEntry {
  number: number
  type: ReferenceType
  id: string
}

export interface ReferenceIndex {
  /** Answer text with each inline ref replaced by [n](#ref-type-id); NO appended list. */
  numberedText: string
  /** Unique references in first-appearance order, numbered to match numberedText. */
  references: ReferenceIndexEntry[]
}

/**
 * Build a consistent numbering for all references in `text`, returning both the
 * numbered inline markdown (for the answer body) and the ordered unique reference
 * list (for the Sources panel). Numbers are shared so [n] markers and panel rows align.
 */
export function buildReferenceIndex(text: string): ReferenceIndex {
  const parsed = parseSourceReferences(text)
  if (parsed.length === 0) {
    return { numberedText: text, references: [] }
  }

  // Dedup by type:id, first-appearance order, assign numbers.
  const map = new Map<string, ReferenceIndexEntry>()
  let next = 1
  for (const ref of parsed) {
    const key = `${ref.type}:${ref.id}`
    if (!map.has(key)) {
      map.set(key, { number: next++, type: ref.type, id: ref.id })
    }
  }

  // Replace inline refs end-to-start to preserve indices. Absorb surrounding
  // single/double brackets like the existing compact converter does.
  let result = text
  for (let i = parsed.length - 1; i >= 0; i--) {
    const ref = parsed[i]
    const entry = map.get(`${ref.type}:${ref.id}`)!
    const start = ref.startIndex
    const end = ref.endIndex
    const before = result.substring(Math.max(0, start - 2), start)
    const after = result.substring(end, Math.min(result.length, end + 2))
    let replaceStart = start
    let replaceEnd = end
    if (before === '[[' && after.startsWith(']]')) {
      replaceStart = start - 2
      replaceEnd = end + 2
    } else if (before.endsWith('[') && after.startsWith(']')) {
      replaceStart = start - 1
      replaceEnd = end + 1
    }
    const link = `[${entry.number}](#ref-${ref.type}-${ref.id})`
    result = result.substring(0, replaceStart) + link + result.substring(replaceEnd)
  }

  return { numberedText: result, references: Array.from(map.values()) }
}

/** Collapse whitespace, trim, and truncate to `max` chars with a trailing ellipsis. */
export function truncateSnippet(text: string, max: number): string {
  if (!text) return ''
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > max ? `${clean.slice(0, max)}…` : clean
}
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd frontend && npm run test -- src/lib/utils/source-references.test.tsx`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/utils/source-references.tsx frontend/src/lib/utils/source-references.test.tsx
git commit -m "feat(search): add buildReferenceIndex + truncateSnippet utils"
```

---

## Task 2: i18n keys in all 14 locales

**Files:**
- Modify: all 14 `frontend/src/lib/locales/*/index.ts`

New keys under the existing `searchPage:` object. English values (put the same English string in every locale as a placeholder — parity is enforced by key, not translation):

| Key | en-US value |
|---|---|
| `searchPage.newQuestion` | `"New Question"` |
| `searchPage.askFollowUp` | `"Ask a follow-up..."` |
| `searchPage.sources` | `"Sources"` |
| `searchPage.referenceUnavailable` | `"Reference unavailable"` |
| `searchPage.helpfulYes` | `"Helpful"` |
| `searchPage.helpfulNo` | `"Not helpful"` |
| `searchPage.copyAnswer` | `"Copy"` |
| `searchPage.answerCopied` | `"Answer copied to clipboard"` |
| `searchPage.feedbackThanks` | `"Thanks for the feedback"` |
| `searchPage.strategyAndReasoning` | `"Strategy & reasoning"` |
| `searchPage.answerLabel` | `"Answer"` |

- [ ] **Step 1: Add keys to en-US**

Edit `frontend/src/lib/locales/en-US/index.ts`, inside the `searchPage: { ... }` object, add the 11 keys above. Keep trailing commas consistent with the file.

- [ ] **Step 2: Add the same keys to the other 13 locales**

For each of `bn-IN, ca-ES, de-DE, es-ES, fr-FR, it-IT, ja-JP, pl-PL, pt-BR, ru-RU, tr-TR, zh-CN, zh-TW`, add the same 11 keys inside their `searchPage:` object. Use the English string as the value (placeholder translation is acceptable and keeps parity green).

- [ ] **Step 3: Run the locale parity test**

Run: `cd frontend && npm run test -- src/lib/locales/index.test.ts`
Expected: The "Locale Parity" suite PASSES (no missing/extra keys). The "Unused Key Detection" test will FAIL for the new keys until they're referenced in code (Tasks 4–6). That's expected now — note it and proceed; it must pass by Task 7.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/locales
git commit -m "i18n(search): add keys for Ask tab redesign across all locales"
```

---

## Task 3: `AnswerFeedback` component

**Files:**
- Create: `frontend/src/components/search/AnswerFeedback.tsx`
- Test: `frontend/src/components/search/AnswerFeedback.test.tsx`

Component contract: renders 👍/👎 buttons (UI-only: click shows `toast.success(t('searchPage.feedbackThanks'))`), a Copy button (writes `answer` to clipboard via `navigator.clipboard.writeText`, then `toast.success(t('searchPage.answerCopied'))`), and renders `children` (the Save-to-Notebooks button slot) at the end of the row. Props: `{ answer: string; children?: React.ReactNode }`.

- [ ] **Step 1: Write failing test**

```tsx
// frontend/src/components/search/AnswerFeedback.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AnswerFeedback } from './AnswerFeedback'

vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))
const toastSuccess = vi.fn()
vi.mock('sonner', () => ({ toast: { success: (m: string) => toastSuccess(m) } }))

describe('AnswerFeedback', () => {
  beforeEach(() => {
    toastSuccess.mockClear()
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
  })

  it('copies the answer text and toasts on Copy', async () => {
    render(<AnswerFeedback answer="hello answer" />)
    fireEvent.click(screen.getByRole('button', { name: 'searchPage.copyAnswer' }))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('hello answer')
  })

  it('toasts thanks on thumbs up (no persistence)', () => {
    render(<AnswerFeedback answer="x" />)
    fireEvent.click(screen.getByRole('button', { name: 'searchPage.helpfulYes' }))
    expect(toastSuccess).toHaveBeenCalledWith('searchPage.feedbackThanks')
  })

  it('renders children slot (e.g. Save button)', () => {
    render(<AnswerFeedback answer="x"><button>Save</button></AnswerFeedback>)
    expect(screen.getByText('Save')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd frontend && npm run test -- src/components/search/AnswerFeedback.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/search/AnswerFeedback.tsx
'use client'

import { ThumbsUp, ThumbsDown, Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

interface AnswerFeedbackProps {
  answer: string
  children?: React.ReactNode
}

export function AnswerFeedback({ answer, children }: AnswerFeedbackProps) {
  const { t } = useTranslation()

  const thanks = () => toast.success(t('searchPage.feedbackThanks'))

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answer)
      toast.success(t('searchPage.answerCopied'))
    } catch {
      // clipboard can reject on insecure contexts; fail quietly
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="sm" onClick={thanks} aria-label={t('searchPage.helpfulYes')}>
        <ThumbsUp className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="sm" onClick={thanks} aria-label={t('searchPage.helpfulNo')}>
        <ThumbsDown className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="sm" onClick={copy} aria-label={t('searchPage.copyAnswer')}>
        <Copy className="h-4 w-4 mr-1" />
        {t('searchPage.copyAnswer')}
      </Button>
      {children ? <div className="ml-auto">{children}</div> : null}
    </div>
  )
}
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd frontend && npm run test -- src/components/search/AnswerFeedback.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/search/AnswerFeedback.tsx frontend/src/components/search/AnswerFeedback.test.tsx
git commit -m "feat(search): add AnswerFeedback row (thumbs UI-only, copy, save slot)"
```

---

## Task 4: `SourcesPanel` component

**Files:**
- Create: `frontend/src/components/search/SourcesPanel.tsx`
- Test: `frontend/src/components/search/SourcesPanel.test.tsx`

Contract: props `{ references: ReferenceIndexEntry[] }`. For each reference, run a query via `useQueries` (fullId = `id.includes(':') ? id : \`${type}:${id}\``; queryKey/api per type as pinned above). Render a numbered row: `#{number}` badge, type icon (FileText/FileEdit/Lightbulb), title (source/note `title` or, for insight, `insight_type`; fall back to the ref id), and `truncateSnippet(full_text|content, 150)`. On query error/empty → show `t('searchPage.referenceUnavailable')` instead of a snippet. Clicking a row calls `openModal(modalType, id)` (`source_insight`→`insight`). Render nothing if `references` is empty.

- [ ] **Step 1: Write failing test** (mock `useQueries`, `useModalManager`, `useTranslation`)

```tsx
// frontend/src/components/search/SourcesPanel.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SourcesPanel } from './SourcesPanel'

vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('@/lib/hooks/use-modal-manager', () => ({ useModalManager: () => ({ openModal: vi.fn() }) }))

// Drive useQueries results per test via a mutable array.
let queryResults: Array<{ data?: unknown; isLoading: boolean; isError: boolean }> = []
vi.mock('@tanstack/react-query', () => ({
  useQueries: () => queryResults,
}))

describe('SourcesPanel', () => {
  it('renders nothing when there are no references', () => {
    queryResults = []
    const { container } = render(<SourcesPanel references={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a numbered row with title and truncated snippet', () => {
    queryResults = [{ isLoading: false, isError: false, data: { title: 'My Source', full_text: 'hello world content' } }]
    render(<SourcesPanel references={[{ number: 1, type: 'source', id: 'a' }]} />)
    expect(screen.getByText('My Source')).toBeInTheDocument()
    expect(screen.getByText(/hello world content/)).toBeInTheDocument()
  })

  it('shows referenceUnavailable when a query errors', () => {
    queryResults = [{ isLoading: false, isError: true }]
    render(<SourcesPanel references={[{ number: 1, type: 'note', id: 'x' }]} />)
    expect(screen.getByText('searchPage.referenceUnavailable')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd frontend && npm run test -- src/components/search/SourcesPanel.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/search/SourcesPanel.tsx
'use client'

import { useQueries } from '@tanstack/react-query'
import { FileText, FileEdit, Lightbulb } from 'lucide-react'
import { sourcesApi } from '@/lib/api/sources'
import { notesApi } from '@/lib/api/notes'
import { insightsApi } from '@/lib/api/insights'
import { useModalManager, type ModalType } from '@/lib/hooks/use-modal-manager'
import { useTranslation } from '@/lib/hooks/use-translation'
import { truncateSnippet, type ReferenceIndexEntry } from '@/lib/utils/source-references'

interface SourcesPanelProps {
  references: ReferenceIndexEntry[]
}

const SNIPPET_MAX = 150

function fullId(type: string, id: string) {
  return id.includes(':') ? id : `${type}:${id}`
}

export function SourcesPanel({ references }: SourcesPanelProps) {
  const { t } = useTranslation()
  const { openModal } = useModalManager()

  const results = useQueries({
    queries: references.map((ref) => {
      const fid = fullId(ref.type, ref.id)
      if (ref.type === 'note') {
        return { queryKey: ['notes', fid], queryFn: () => notesApi.get(fid) }
      }
      if (ref.type === 'source_insight') {
        return { queryKey: ['insights', fid], queryFn: () => insightsApi.get(fid) }
      }
      return { queryKey: ['sources', fid], queryFn: () => sourcesApi.get(fid) }
    }),
  })

  if (references.length === 0) return null

  return (
    <aside className="w-full lg:w-64 shrink-0 space-y-3" aria-label={t('searchPage.sources')}>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t('searchPage.sources')} ({references.length})
      </p>
      {references.map((ref, i) => {
        const q = results[i]
        const data = q?.data as
          | { title?: string | null; full_text?: string; content?: string | null; insight_type?: string }
          | undefined

        const Icon = ref.type === 'source' ? FileText : ref.type === 'note' ? FileEdit : Lightbulb
        const modalType: ModalType = ref.type === 'source_insight' ? 'insight' : (ref.type as ModalType)

        const title =
          data?.title ?? data?.insight_type ?? `${ref.type}:${ref.id}`
        const rawSnippet = data?.full_text ?? data?.content ?? ''
        const unavailable = q?.isError || (!q?.isLoading && !data)

        return (
          <button
            key={`${ref.type}:${ref.id}`}
            onClick={() => openModal(modalType, ref.id)}
            className="w-full text-left rounded-md border p-3 hover:bg-muted transition-colors"
          >
            <div className="flex items-center gap-2 text-sm font-medium">
              <span className="text-xs text-muted-foreground">{ref.number}</span>
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{title}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {unavailable
                ? t('searchPage.referenceUnavailable')
                : truncateSnippet(rawSnippet, SNIPPET_MAX)}
            </p>
          </button>
        )
      })}
    </aside>
  )
}
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd frontend && npm run test -- src/components/search/SourcesPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/search/SourcesPanel.tsx frontend/src/components/search/SourcesPanel.test.tsx
git commit -m "feat(search): add SourcesPanel with useQueries + unavailable fallback"
```

---

## Task 5: Restyle `StreamingResponse` (merged disclosure, borderless answer, numbered citations)

**Files:**
- Modify: `frontend/src/components/search/StreamingResponse.tsx`

Changes:
1. Merge the two `Collapsible` cards (Strategy + Individual Answers) into ONE collapsible titled `t('searchPage.strategyAndReasoning')`, collapsed by default, containing the reasoning, search terms, AND (if any) the individual answers underneath.
2. Render the final answer **borderless** — replace the `<Card className="border-primary">…</Card>` wrapper with a plain `<div>` block; keep an `t('searchPage.answerLabel')` uppercase label above the markdown.
3. Switch `FinalAnswerContent` to use `buildReferenceIndex(finalAnswer).numberedText` with `createCompactReferenceLinkComponent` (import from `source-references`) so citations render as clickable `[1] [2]`. Remove the `convertReferencesToMarkdownLinks` + `createReferenceLinkComponent` usage.
4. Keep the streaming loading indicator and all `aria-*` attributes.

- [ ] **Step 1: Edit the component** per the four changes above. Import `buildReferenceIndex, createCompactReferenceLinkComponent`. Collapse default: `useState(false)` for the single disclosure.

- [ ] **Step 2: Typecheck + existing tests**

Run: `cd frontend && npm run lint && npm run test -- src/components/search`
Expected: lint clean; no test references the old two-card structure (there are no existing StreamingResponse tests, confirmed). PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/search/StreamingResponse.tsx
git commit -m "refactor(search): merge strategy disclosure, borderless answer, numbered citations"
```

---

## Task 6: Rework the Ask tab in `page.tsx`

**Files:**
- Modify: `frontend/src/app/(dashboard)/search/page.tsx` (Ask `TabsContent` only; leave the Search `TabsContent` and all search state/handlers untouched)

Structural changes inside `<TabsContent value="ask">`:
1. **Empty state (no `ask.finalAnswer` and not streaming):** keep the current "Ask Your Knowledge Base" `Card` with the question `Textarea`, embedding-model warning, model badges, and Ask button, exactly as today.
2. **Answered/streaming state:** render a two-column flex (`flex flex-col lg:flex-row gap-6`):
   - **Left (`flex-1 min-w-0`):**
     - A header row: the submitted question as `<h2 className="text-xl font-semibold">` + a "New Question" `Button` (ghost) that calls `ask.reset()` and clears `askQuestion`.
     - `<StreamingResponse ... />` (now borderless answer + merged disclosure).
     - When `ask.finalAnswer`: `<AnswerFeedback answer={ask.finalAnswer}>` wrapping the existing Save-to-Notebooks `Button` (moved here) as its child.
     - **Follow-up bar** (docked below): a bordered container with the `Textarea` (reuse `askQuestion`/`handleAsk`; placeholder `t('searchPage.askFollowUp')`), the model badges + Advanced button (relocated from the empty-state block), and the Ask/Run button. Submitting calls the same `handleAsk` (stateless fresh ask — this replaces the prior answer, matching current `useAsk` reset behavior).
   - **Right:** `<SourcesPanel references={buildReferenceIndex(ask.finalAnswer ?? '').references} />` (renders nothing until there's an answer).
3. Keep `AdvancedModelsDialog` and `SaveToNotebooksDialog` mounts where they are (they're portals; only the trigger button moves).
4. Import `AnswerFeedback`, `SourcesPanel`, `buildReferenceIndex`.

- [ ] **Step 1: Implement the layout changes** in the Ask `TabsContent`. Preserve all existing state, `handleAsk`, URL-param auto-trigger effects, and the embedding-model warning.

- [ ] **Step 2: Lint + typecheck + full test suite (incl. locale unused-key test)**

Run: `cd frontend && npm run lint && npm run test`
Expected: lint clean; **all** tests pass — including `locales/index.test.ts` "Unused Key Detection" (every new key is now referenced across Tasks 3–6) and "Locale Parity".

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/(dashboard)/search/page.tsx
git commit -m "feat(search): Quelvio-style Ask tab layout (title, sources panel, follow-up bar)"
```

---

## Task 7: Manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1:** Ensure DB+API+worker+frontend are up (`make status` or the individual servers). Confirm an embedded source exists (the `LLM-WIKI` source is embedded).

- [ ] **Step 2:** Use the `verify` skill (or drive a browser via Playwright as in prior sessions) to: open the Ask tab, submit a question that hits the embedded source, and confirm: question renders as a heading; answer is borderless with `[1]`-style citations; feedback row (thumbs toast, copy works); strategy disclosure is collapsed by default and expands; right-side Sources panel lists the cited items with title + snippet and opens the modal on click; the follow-up bar submits a fresh question; "New Question" resets to the empty state. Screenshot and eyeball it against the reference.

- [ ] **Step 3:** If everything works, the feature is done. Consider `superpowers:finishing-a-development-branch` for merge/PR handling.

---

## Notes / risks

- **Streaming vs. numbered citations:** citations only get numbered once `finalAnswer` exists (that's when `buildReferenceIndex` runs). During streaming, partial `answers[]` are shown inside the collapsed disclosure without numbering — acceptable, matches "strategy & reasoning" being process detail.
- **`useQueries` in `SourcesPanel`:** it re-runs when `references` identity changes. `buildReferenceIndex(ask.finalAnswer ?? '')` is recomputed each render; if this causes needless refetches, memoize it in `page.tsx` with `useMemo(() => buildReferenceIndex(ask.finalAnswer ?? ''), [ask.finalAnswer])` and pass `.references` down. (Cheap pure fn, but memo avoids new array identity each render.)
- **Locale placeholder translations:** non-English files carry the English string. That's fine for parity/CI; a later native-translation pass is out of scope for this plan.
