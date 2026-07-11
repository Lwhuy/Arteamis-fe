# P8.0 — Control Plane Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe the Arteamis-fe dashboard home into a single "control plane" — a 4-column shell (icon rail · collapsible left artifact panel · center chat wrapping the existing Ask pipeline · right context sidebar) with a Personal/Company scope switch — while leaving every existing Open Notebook page reachable and unchanged.

**Architecture:** Additive-first. A new `ControlPlane` screen becomes the `/` (dashboard index) route, replacing today's `redirect('/notebooks')`. It reuses the existing `useAsk` SSE hook for the chat brain, the existing `AddSourceDialog` (via `useCreateDialogs`) for capture, and existing nav targets for the rail. No governance, no backend, no migration in this plan — those arrive in P8.1/P8.2. Scope is a new persisted Zustand store folded into query keys later. A new Radix-Dialog-based `Sheet` primitive is added now because P8.1 needs it.

**Tech Stack:** Next.js 16 (App Router), React 19, TypeScript (strict), TanStack Query 5, Zustand 5 (`persist`), shadcn/ui (Radix), Tailwind v4, i18next (14 locales), sonner, vitest.

## Global Constraints

- **Async-first / data discipline:** all HTTP via `apiClient`; TanStack hooks in `lib/hooks/` keyed by `QUERY_KEYS`; mutations invalidate broadly + toast. (No HTTP in this plan.)
- **i18n is test-enforced:** every user-facing string goes through `t('section.key')`; every new key must exist in **all 14 locales** under `frontend/src/lib/locales/` (`en-US, pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN, ca-ES, es-ES, de-DE, fr-FR, it-IT, pl-PL, tr-TR`) **and** be referenced in source — the parity + unused-key tests in `frontend/src/lib/locales/index.test.ts` fail otherwise. `en-US` is the reference; English placeholder values are acceptable in other locales this iteration.
- **Zustand SSR gotcha:** persisted stores must expose `hasHydrated` and guard render on it.
- **Theme:** custom `useThemeStore` toggles the `dark` class on `documentElement`; style via Tailwind tokens (warm paper / coral / serif headings already in theme), never raw hex.
- **No `Sheet`/`Drawer`/`Resizable` primitive exists** — panel collapse uses manual flex-basis (pattern: `notebook-columns-store` + `CollapsibleColumn`).
- **Reversibility:** revert = restore `redirect('/notebooks')` in `app/(dashboard)/page.tsx` and delete `components/control-plane/`.
- Run from `frontend/`: `npm run test` (vitest), `npm run lint`, `npm run build` (truest typecheck).
- Path alias `@/*` → `frontend/src/*`.

---

### Task 1: Scope store (`useScopeStore`)

Persisted Personal/Company scope. Pure state; no UI. Later plans fold `scope` into query keys.

**Files:**
- Create: `frontend/src/lib/stores/scope-store.ts`
- Test: `frontend/src/lib/stores/scope-store.test.ts`

**Interfaces:**
- Produces: `useScopeStore` — Zustand store `{ scope: 'personal' | 'company'; setScope(s): void; toggle(): void; hasHydrated: boolean; setHasHydrated(b): void }`. Store name (localStorage key) `'scope-storage'`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/stores/scope-store.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { useScopeStore } from './scope-store';

describe('useScopeStore', () => {
  beforeEach(() => useScopeStore.setState({ scope: 'personal' }));

  it('defaults to personal', () => {
    expect(useScopeStore.getState().scope).toBe('personal');
  });

  it('setScope switches scope', () => {
    useScopeStore.getState().setScope('company');
    expect(useScopeStore.getState().scope).toBe('company');
  });

  it('toggle flips between personal and company', () => {
    useScopeStore.getState().toggle();
    expect(useScopeStore.getState().scope).toBe('company');
    useScopeStore.getState().toggle();
    expect(useScopeStore.getState().scope).toBe('personal');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- scope-store`
Expected: FAIL — cannot resolve `./scope-store`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/lib/stores/scope-store.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type Scope = 'personal' | 'company';

interface ScopeState {
  scope: Scope;
  hasHydrated: boolean;
  setScope: (s: Scope) => void;
  toggle: () => void;
  setHasHydrated: (b: boolean) => void;
}

export const useScopeStore = create<ScopeState>()(
  persist(
    (set, get) => ({
      scope: 'personal',
      hasHydrated: false,
      setScope: (scope) => set({ scope }),
      toggle: () => set({ scope: get().scope === 'personal' ? 'company' : 'personal' }),
      setHasHydrated: (hasHydrated) => set({ hasHydrated }),
    }),
    {
      name: 'scope-storage',
      partialize: (s) => ({ scope: s.scope }),
      onRehydrateStorage: () => (state) => state?.setHasHydrated(true),
    },
  ),
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- scope-store`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/stores/scope-store.ts frontend/src/lib/stores/scope-store.test.ts
git commit -m "feat(control-plane): add persisted scope store (personal/company)"
```

---

### Task 2: `Sheet` UI primitive (Radix Dialog)

Side-anchored sheet used by P8.1's artifact reader. Add now so the shell has it.

**Files:**
- Create: `frontend/src/components/ui/sheet.tsx`
- Test: `frontend/src/components/ui/sheet.test.tsx`

**Interfaces:**
- Produces: `Sheet`, `SheetTrigger`, `SheetContent` (prop `side?: 'left' | 'right'`, default `'right'`), `SheetHeader`, `SheetTitle`, `SheetClose` — Radix Dialog wrappers.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ui/sheet.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Sheet, SheetContent, SheetTitle } from './sheet';

describe('Sheet', () => {
  it('renders content and title when open', () => {
    render(
      <Sheet open>
        <SheetContent side="left">
          <SheetTitle>Artifact</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    expect(screen.getByText('Artifact')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- sheet`
Expected: FAIL — cannot resolve `./sheet`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/ui/sheet.tsx
'use client';
import * as React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

export const SheetContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { side?: 'left' | 'right' }
>(({ className, children, side = 'right', ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 data-[state=open]:animate-in data-[state=open]:fade-in" />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed z-50 flex h-full w-[24rem] max-w-[90vw] flex-col gap-2 border-border bg-background p-0 shadow-lg',
        side === 'left' ? 'left-0 top-0 border-r' : 'right-0 top-0 border-l',
        className,
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <X className="h-4 w-4" />
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = 'SheetContent';

export function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-1 border-b border-border p-4', className)} {...props} />;
}

export const SheetTitle = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title ref={ref} className={cn('text-base font-semibold text-foreground', className)} {...props} />
));
SheetTitle.displayName = 'SheetTitle';
```

> Note: match `bg-background`/`text-foreground`/`border-border` to the exact token names used in `frontend/src/components/ui/dialog.tsx`. If that file uses different names (e.g. `bg-popover`), copy those verbatim.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- sheet`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/sheet.tsx frontend/src/components/ui/sheet.test.tsx
git commit -m "feat(ui): add Radix Dialog-based Sheet primitive"
```

---

### Task 3: Loop step deriver (`deriveLoopSteps`)

Pure function producing the 8-step loop widget state. No React, fully unit-testable. Mirrors the existing `today/loop-steps.ts` pattern.

**Files:**
- Create: `frontend/src/components/control-plane/loop-steps.ts`
- Test: `frontend/src/components/control-plane/loop-steps.test.ts`

**Interfaces:**
- Produces:
  - `LOOP_STEPS: readonly { id: string; labelKey: string; hintKey: string }[]` (8 entries, ids: `capture, draft, propose, review, decision, rule, handoff, trace`; `propose`→`review` is the Personal‖Company boundary).
  - `type LoopStepState = { id: string; labelKey: string; hintKey: string; status: 'done' | 'current' | 'later' }`
  - `deriveLoopSteps(currentIndex: number): LoopStepState[]` — steps `< currentIndex` are `done`, `=== currentIndex` is `current`, `> currentIndex` is `later`. `currentIndex >= 8` → all `done` (loop complete).

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/control-plane/loop-steps.test.ts
import { describe, it, expect } from 'vitest';
import { LOOP_STEPS, deriveLoopSteps } from './loop-steps';

describe('deriveLoopSteps', () => {
  it('has 8 steps with propose before review', () => {
    expect(LOOP_STEPS).toHaveLength(8);
    const ids = LOOP_STEPS.map((s) => s.id);
    expect(ids.indexOf('propose')).toBeLessThan(ids.indexOf('review'));
  });

  it('marks done/current/later around currentIndex', () => {
    const steps = deriveLoopSteps(2);
    expect(steps[0].status).toBe('done');
    expect(steps[1].status).toBe('done');
    expect(steps[2].status).toBe('current');
    expect(steps[3].status).toBe('later');
  });

  it('index 0 => first is current, exactly one current', () => {
    const steps = deriveLoopSteps(0);
    expect(steps.filter((s) => s.status === 'current')).toHaveLength(1);
    expect(steps[0].status).toBe('current');
  });

  it('index >= 8 => all done, no current', () => {
    const steps = deriveLoopSteps(8);
    expect(steps.every((s) => s.status === 'done')).toBe(true);
    expect(steps.some((s) => s.status === 'current')).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- loop-steps`
Expected: FAIL — cannot resolve `./loop-steps`.

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/components/control-plane/loop-steps.ts
export const LOOP_STEPS = [
  { id: 'capture', labelKey: 'controlPlane.loop.capture', hintKey: 'controlPlane.loop.captureHint' },
  { id: 'draft', labelKey: 'controlPlane.loop.draft', hintKey: 'controlPlane.loop.draftHint' },
  { id: 'propose', labelKey: 'controlPlane.loop.propose', hintKey: 'controlPlane.loop.proposeHint' },
  { id: 'review', labelKey: 'controlPlane.loop.review', hintKey: 'controlPlane.loop.reviewHint' },
  { id: 'decision', labelKey: 'controlPlane.loop.decision', hintKey: 'controlPlane.loop.decisionHint' },
  { id: 'rule', labelKey: 'controlPlane.loop.rule', hintKey: 'controlPlane.loop.ruleHint' },
  { id: 'handoff', labelKey: 'controlPlane.loop.handoff', hintKey: 'controlPlane.loop.handoffHint' },
  { id: 'trace', labelKey: 'controlPlane.loop.trace', hintKey: 'controlPlane.loop.traceHint' },
] as const;

export type LoopStepState = {
  id: string;
  labelKey: string;
  hintKey: string;
  status: 'done' | 'current' | 'later';
};

export function deriveLoopSteps(currentIndex: number): LoopStepState[] {
  return LOOP_STEPS.map((s, i) => ({
    ...s,
    status: i < currentIndex ? 'done' : i === currentIndex ? 'current' : 'later',
  }));
}

/** Index of the Personal‖Company boundary (between propose[2] and review[3]). */
export const COMPANY_BOUNDARY_INDEX = 3;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- loop-steps`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/loop-steps.ts frontend/src/components/control-plane/loop-steps.test.ts
git commit -m "feat(control-plane): add pure deriveLoopSteps state machine"
```

---

### Task 4: i18n keys for the control plane

Add every `controlPlane.*` key the shell components will consume, to all 14 locales, so parity/unused-key tests stay green once components reference them. (Components in Tasks 5–8 reference these keys.)

**Files:**
- Modify: `frontend/src/lib/locales/en-US/index.ts` (add `controlPlane` section)
- Modify: the other 13 locale `index.ts` files (identical keys; English placeholder values allowed)

**Interfaces:**
- Produces: `t('controlPlane.*')` keys listed below.

- [ ] **Step 1: Add the `controlPlane` section to `en-US`**

Add this object as a new top-level section in `frontend/src/lib/locales/en-US/index.ts` (place alphabetically or after `chat`):

```ts
controlPlane: {
  title: 'Ask the Brain',
  personal: 'Personal',
  company: 'Company',
  personalSubtitle: 'Personal · your private brain',
  companySubtitle: 'Company · shared, reviewed knowledge',
  composerPlaceholder: 'Ask the brain, or give a command…',
  addSource: 'Add source',
  send: 'Send',
  rail: {
    chat: 'Chat',
    brain: 'Brain',
    legacy: 'Legacy',
    sources: 'Sources',
    podcasts: 'Podcasts',
    connections: 'Connections',
    settings: 'Settings',
  },
  sidebar: {
    context: 'Context',
    sources: 'Sources',
    loop: 'Loop',
    review: 'To review',
    brain: 'Company Brain',
    sourcesEmpty: 'No sources yet. Click “Add source”.',
    reviewEmpty: 'Nothing to review yet.',
    brainEmpty: 'Accepted beliefs will appear here.',
  },
  loop: {
    capture: 'Capture', captureHint: 'add a source',
    draft: 'Draft insight', draftHint: 'select & write',
    propose: 'Propose', proposeHint: 'send to company',
    review: 'Review', reviewHint: 'company approves',
    decision: 'Decision', decisionHint: 'decide',
    rule: 'Rule / Belief', ruleHint: 'into Company Brain',
    handoff: 'Handoff', handoffHint: 'assign to human/agent',
    trace: 'Trace + Learning', traceHint: 'outcome → learn',
    boundary: 'Personal · Company boundary',
  },
},
```

- [ ] **Step 2: Mirror the same keys into all 13 other locales**

For each of `pt-BR, zh-CN, zh-TW, ja-JP, ru-RU, bn-IN, ca-ES, es-ES, de-DE, fr-FR, it-IT, pl-PL, tr-TR` add an identical `controlPlane` object. English placeholder values are acceptable this iteration; the **keys** must match `en-US` exactly.

- [ ] **Step 3: Run the parity test**

Run: `npm run test -- locales`
Expected: The **Locale Parity** test passes (keys identical across 14). The **Unused Key Detection** test will still FAIL for these keys until Tasks 5–8 reference them — that is expected at this point. Note which keys it flags; they must all be consumed by the end of Task 8.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/locales
git commit -m "i18n(control-plane): add controlPlane.* keys across 14 locales"
```

---

### Task 5: `ScopeSwitch` + `TopBar`

Top bar with the Personal/Company segmented switch wired to `useScopeStore`.

**Files:**
- Create: `frontend/src/components/control-plane/ScopeSwitch.tsx`
- Create: `frontend/src/components/control-plane/TopBar.tsx`
- Test: `frontend/src/components/control-plane/ScopeSwitch.test.tsx`

**Interfaces:**
- Consumes: `useScopeStore` (Task 1); `useTranslation` (`t`, existing `@/lib/hooks/use-translation`).
- Produces: `<ScopeSwitch />`, `<TopBar />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/ScopeSwitch.test.tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ScopeSwitch } from './ScopeSwitch';
import { useScopeStore } from '@/lib/stores/scope-store';

// i18n: t returns the key by default in test setup (see existing tests e.g. AppSidebar.test.tsx)
describe('ScopeSwitch', () => {
  beforeEach(() => useScopeStore.setState({ scope: 'personal' }));

  it('clicking Company sets scope to company', () => {
    render(<ScopeSwitch />);
    fireEvent.click(screen.getByRole('button', { name: /company/i }));
    expect(useScopeStore.getState().scope).toBe('company');
  });

  it('reflects active scope via aria-pressed', () => {
    useScopeStore.setState({ scope: 'company' });
    render(<ScopeSwitch />);
    expect(screen.getByRole('button', { name: /company/i })).toHaveAttribute('aria-pressed', 'true');
  });
});
```

> Check how existing component tests mock `useTranslation` (see `frontend/src/app/(dashboard)/notebooks/components/ChatColumn.test.tsx` / `AppSidebar.test.tsx`). Match that setup so `t('controlPlane.company')` yields text matching `/company/i` — if the test harness returns the raw key, the key string `controlPlane.company` already contains "company".

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- ScopeSwitch`
Expected: FAIL — cannot resolve `./ScopeSwitch`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/control-plane/ScopeSwitch.tsx
'use client';
import { useScopeStore, type Scope } from '@/lib/stores/scope-store';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

export function ScopeSwitch() {
  const { t } = useTranslation();
  const scope = useScopeStore((s) => s.scope);
  const setScope = useScopeStore((s) => s.setScope);
  const opts: Scope[] = ['personal', 'company'];
  return (
    <div className="inline-flex rounded-lg border border-border bg-muted p-0.5" role="group">
      {opts.map((o) => (
        <button
          key={o}
          type="button"
          aria-pressed={scope === o}
          onClick={() => setScope(o)}
          className={cn(
            'rounded-md px-4 py-1.5 text-sm font-semibold text-muted-foreground transition-colors',
            scope === o && 'bg-background text-foreground shadow-sm',
          )}
        >
          {t(`controlPlane.${o}`)}
        </button>
      ))}
    </div>
  );
}
```

```tsx
// frontend/src/components/control-plane/TopBar.tsx
'use client';
import { ScopeSwitch } from './ScopeSwitch';
import { Logo } from '@/components/common/Logo';

export function TopBar() {
  return (
    <header className="flex h-14 flex-shrink-0 items-center gap-4 border-b border-border bg-background px-4">
      <Logo />
      <div className="mx-auto"><ScopeSwitch /></div>
    </header>
  );
}
```

> If `Logo` is not a default export or has required props, adapt the import to match `frontend/src/components/common/Logo.tsx`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- ScopeSwitch`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/ScopeSwitch.tsx frontend/src/components/control-plane/TopBar.tsx frontend/src/components/control-plane/ScopeSwitch.test.tsx
git commit -m "feat(control-plane): scope switch + top bar"
```

---

### Task 6: `Rail` (slim icon nav)

Slim left icon rail. Chat = home (active on `/`), Brain (points to `/search` for now — greenfield brain route arrives later), a divider, then legacy Open Notebook targets, Settings at the bottom. Reuses existing route hrefs.

**Files:**
- Create: `frontend/src/components/control-plane/Rail.tsx`
- Test: `frontend/src/components/control-plane/Rail.test.tsx`

**Interfaces:**
- Consumes: `useTranslation`; `next/link`; `next/navigation` `usePathname`.
- Produces: `<Rail />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/Rail.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Rail } from './Rail';

vi.mock('next/navigation', () => ({ usePathname: () => '/' }));

describe('Rail', () => {
  it('renders a Chat home link pointing to /', () => {
    render(<Rail />);
    const chat = screen.getByRole('link', { name: /chat/i });
    expect(chat).toHaveAttribute('href', '/');
  });

  it('renders a Sources legacy link', () => {
    render(<Rail />);
    expect(screen.getByRole('link', { name: /sources/i })).toHaveAttribute('href', '/sources');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- Rail`
Expected: FAIL — cannot resolve `./Rail`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/control-plane/Rail.tsx
'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MessageSquare, Network, FileText, Mic, Link2, Settings } from 'lucide-react';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

const primary = [
  { href: '/', labelKey: 'controlPlane.rail.chat', icon: MessageSquare },
  { href: '/search', labelKey: 'controlPlane.rail.brain', icon: Network },
];
const legacy = [
  { href: '/sources', labelKey: 'controlPlane.rail.sources', icon: FileText },
  { href: '/podcasts', labelKey: 'controlPlane.rail.podcasts', icon: Mic },
  { href: '/connections', labelKey: 'controlPlane.rail.connections', icon: Link2 },
];

function RailLink({ href, labelKey, icon: Icon }: { href: string; labelKey: string; icon: typeof MessageSquare }) {
  const { t } = useTranslation();
  const pathname = usePathname();
  const active = href === '/' ? pathname === '/' : pathname?.startsWith(href);
  return (
    <Link
      href={href}
      aria-label={t(labelKey)}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'grid h-11 w-11 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        active && 'bg-accent text-accent-foreground',
      )}
    >
      <Icon className="h-5 w-5" />
    </Link>
  );
}

export function Rail() {
  const { t } = useTranslation();
  return (
    <nav aria-label={t('controlPlane.rail.chat')} className="flex w-[66px] flex-shrink-0 flex-col items-center gap-1 border-r border-border bg-background py-3">
      {primary.map((i) => <RailLink key={i.href} {...i} />)}
      <div className="my-1.5 w-8 border-t border-dashed border-border pt-1.5 text-center text-[8px] uppercase tracking-wide text-muted-foreground">
        {t('controlPlane.rail.legacy')}
      </div>
      {legacy.map((i) => <RailLink key={i.href} {...i} />)}
      <div className="flex-1" />
      <RailLink href="/settings" labelKey="controlPlane.rail.settings" icon={Settings} />
    </nav>
  );
}
```

> `/connections` route may not exist yet (connectors is a plan). The link is harmless (404 until built); keep it to show the intended IA. If the reviewer prefers, drop the connections entry until that route lands.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- Rail`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/Rail.tsx frontend/src/components/control-plane/Rail.test.tsx
git commit -m "feat(control-plane): slim icon rail with legacy links"
```

---

### Task 7: `ContextSidebar` + `LoopWidget`

Right context sidebar with 4 sections. Sources/Review/Brain are placeholder empty-states in P8.0 (filled by P8.1/P8.2). `LoopWidget` renders `deriveLoopSteps` with the Personal‖Company boundary; in P8.0 it's driven by a static `currentIndex={0}` prop (later wired to loop state).

**Files:**
- Create: `frontend/src/components/control-plane/LoopWidget.tsx`
- Create: `frontend/src/components/control-plane/ContextSidebar.tsx`
- Test: `frontend/src/components/control-plane/LoopWidget.test.tsx`

**Interfaces:**
- Consumes: `deriveLoopSteps`, `COMPANY_BOUNDARY_INDEX` (Task 3); `useTranslation`; `useScopeStore` (Task 1).
- Produces: `<LoopWidget currentIndex={number} />`, `<ContextSidebar />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/LoopWidget.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LoopWidget } from './LoopWidget';

describe('LoopWidget', () => {
  it('renders all 8 step labels', () => {
    render(<LoopWidget currentIndex={0} />);
    // labels come through t(); with key-returning t, the capture label key is present
    expect(screen.getByText(/controlPlane\.loop\.capture|Capture/)).toBeInTheDocument();
    expect(screen.getByText(/controlPlane\.loop\.trace|Trace/)).toBeInTheDocument();
  });

  it('renders the Personal-Company boundary marker', () => {
    render(<LoopWidget currentIndex={0} />);
    expect(screen.getByText(/controlPlane\.loop\.boundary|boundary/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- LoopWidget`
Expected: FAIL — cannot resolve `./LoopWidget`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/control-plane/LoopWidget.tsx
'use client';
import { Check } from 'lucide-react';
import { deriveLoopSteps, COMPANY_BOUNDARY_INDEX } from './loop-steps';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

export function LoopWidget({ currentIndex }: { currentIndex: number }) {
  const { t } = useTranslation();
  const steps = deriveLoopSteps(currentIndex);
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      {steps.map((s, i) => (
        <div key={s.id}>
          {i === COMPANY_BOUNDARY_INDEX && (
            <div className="my-2 text-center text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
              {t('controlPlane.loop.boundary')}
            </div>
          )}
          <div className="flex items-center gap-3 py-1.5">
            <span
              className={cn(
                'grid h-5 w-5 place-items-center rounded-full border-2 text-[11px] font-bold',
                s.status === 'done' && 'border-green-600 bg-green-600 text-white',
                s.status === 'current' && 'border-primary bg-primary text-primary-foreground',
                s.status === 'later' && 'border-border text-muted-foreground',
              )}
            >
              {s.status === 'done' ? <Check className="h-3 w-3" /> : i + 1}
            </span>
            <span className={cn('text-xs', s.status === 'current' ? 'font-semibold text-foreground' : 'text-muted-foreground')}>
              {t(s.labelKey)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
```

```tsx
// frontend/src/components/control-plane/ContextSidebar.tsx
'use client';
import { useTranslation } from '@/lib/hooks/use-translation';
import { LoopWidget } from './LoopWidget';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-bold text-foreground">{title}</h3>
      {children}
    </section>
  );
}
function Empty({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{text}</div>;
}

export function ContextSidebar() {
  const { t } = useTranslation();
  return (
    <aside className="flex w-[372px] flex-shrink-0 flex-col gap-5 overflow-y-auto border-l border-border bg-background p-4">
      <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.sidebar.context')}</div>
      <Section title={t('controlPlane.sidebar.sources')}><Empty text={t('controlPlane.sidebar.sourcesEmpty')} /></Section>
      <Section title={t('controlPlane.sidebar.loop')}><LoopWidget currentIndex={0} /></Section>
      <Section title={t('controlPlane.sidebar.review')}><Empty text={t('controlPlane.sidebar.reviewEmpty')} /></Section>
      <Section title={t('controlPlane.sidebar.brain')}><Empty text={t('controlPlane.sidebar.brainEmpty')} /></Section>
    </aside>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- LoopWidget`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/control-plane/LoopWidget.tsx frontend/src/components/control-plane/ContextSidebar.tsx frontend/src/components/control-plane/LoopWidget.test.tsx
git commit -m "feat(control-plane): context sidebar + loop widget"
```

---

### Task 8: `ControlPlaneChat`, `ControlPlane`, and wire the `/` route

Center chat wraps the existing `useAsk` SSE hook; composer has a `+ Add source` button that opens the existing `AddSourceDialog` via `useCreateDialogs`. Assemble the 4-column `ControlPlane` and make it the dashboard index.

**Files:**
- Create: `frontend/src/components/control-plane/ControlPlaneChat.tsx`
- Create: `frontend/src/components/control-plane/ControlPlane.tsx`
- Modify: `frontend/src/app/(dashboard)/page.tsx` (replace `redirect('/notebooks')` with `<ControlPlane />`)
- Test: `frontend/src/components/control-plane/ControlPlane.test.tsx`

**Interfaces:**
- Consumes: `useAsk` (`@/lib/hooks/use-ask`), `AnswerBody` + citation rendering (`@/components/search/*`, `@/lib/utils/source-references`), `useCreateDialogs` (`@/lib/hooks/use-create-dialogs`), `TopBar`, `Rail`, `ContextSidebar`, `useScopeStore`.
- Produces: `<ControlPlane />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/control-plane/ControlPlane.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ControlPlane } from './ControlPlane';

vi.mock('next/navigation', () => ({ usePathname: () => '/', useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/hooks/use-ask', () => ({
  useAsk: () => ({ isStreaming: false, strategy: null, answers: [], finalAnswer: '', error: null, sendAsk: vi.fn(), reset: vi.fn() }),
}));
vi.mock('@/lib/hooks/use-create-dialogs', () => ({ useCreateDialogs: () => ({ openSourceDialog: vi.fn() }) }));

describe('ControlPlane', () => {
  it('renders rail, scope switch, chat composer and sidebar together', () => {
    render(<ControlPlane />);
    expect(screen.getByRole ? screen.getByRole('group') : screen.getByText(/personal/i)).toBeTruthy(); // scope switch
    expect(screen.getByRole('link', { name: /chat/i })).toBeInTheDocument();                            // rail
    expect(screen.getByPlaceholderText(/controlPlane\.composerPlaceholder|Ask the brain/i)).toBeInTheDocument(); // composer
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- ControlPlane`
Expected: FAIL — cannot resolve `./ControlPlane`.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/control-plane/ControlPlaneChat.tsx
'use client';
import { useState } from 'react';
import { Plus, Send } from 'lucide-react';
import { useAsk } from '@/lib/hooks/use-ask';
import { useCreateDialogs } from '@/lib/hooks/use-create-dialogs';
import { useScopeStore } from '@/lib/stores/scope-store';
import { useTranslation } from '@/lib/hooks/use-translation';
import { AnswerBody } from '@/components/search/AnswerBody';

export function ControlPlaneChat() {
  const { t } = useTranslation();
  const scope = useScopeStore((s) => s.scope);
  const { finalAnswer, isStreaming, sendAsk } = useAsk();
  const { openSourceDialog } = useCreateDialogs();
  const [q, setQ] = useState('');

  const submit = () => { if (q.trim()) { sendAsk(q, {}); setQ(''); } };

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="border-b border-border px-6 py-3">
        <h1 className="font-serif text-xl font-semibold text-foreground">{t('controlPlane.title')}</h1>
        <p className="text-xs text-muted-foreground">{t(scope === 'personal' ? 'controlPlane.personalSubtitle' : 'controlPlane.companySubtitle')}</p>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-2xl">
          {finalAnswer ? <AnswerBody finalAnswer={finalAnswer} isStreaming={isStreaming} /> : null}
        </div>
      </div>
      <div className="border-t border-border p-4">
        <div className="mx-auto flex max-w-2xl items-center gap-2 rounded-2xl border border-border bg-card p-2">
          <button type="button" onClick={() => openSourceDialog()} className="flex items-center gap-1.5 rounded-xl border border-dashed border-border px-3 py-2 text-xs font-semibold text-muted-foreground hover:text-foreground">
            <Plus className="h-4 w-4" /> {t('controlPlane.addSource')}
          </button>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
            placeholder={t('controlPlane.composerPlaceholder')}
            className="flex-1 bg-transparent text-sm outline-none"
          />
          <button type="button" aria-label={t('controlPlane.send')} onClick={submit} className="grid h-9 w-9 place-items-center rounded-xl bg-primary text-primary-foreground">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </section>
  );
}
```

```tsx
// frontend/src/components/control-plane/ControlPlane.tsx
'use client';
import { TopBar } from './TopBar';
import { Rail } from './Rail';
import { ControlPlaneChat } from './ControlPlaneChat';
import { ContextSidebar } from './ContextSidebar';

export function ControlPlane() {
  return (
    <div className="flex h-screen flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <Rail />
        {/* left artifact panel column is added in P8.1 (URL-param driven) */}
        <ControlPlaneChat />
        <ContextSidebar />
      </div>
    </div>
  );
}
```

Then modify the dashboard index route:

```tsx
// frontend/src/app/(dashboard)/page.tsx  (replace the redirect)
import { ControlPlane } from '@/components/control-plane/ControlPlane';

export default function DashboardHome() {
  return <ControlPlane />;
}
```

> Verify `AnswerBody`'s real prop names in `frontend/src/components/search/AnswerBody.tsx` and adjust the call (the frontend map notes it renders `buildReferenceIndex(finalAnswer)` — pass whatever prop it actually expects; if it needs the full ask state, pass the pieces from `useAsk`). Also confirm `useAsk`'s `sendAsk` signature (`sendAsk(question, { strategy, answer, finalAnswer })`) — pass `{}` to use defaults, or the models object if required.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- ControlPlane`
Expected: PASS.

- [ ] **Step 5: Verify unused-key test is now green + typecheck + build**

Run: `npm run test -- locales`
Expected: BOTH parity and unused-key tests PASS (all `controlPlane.*` keys are now referenced).
Run: `npm run lint && npm run build`
Expected: no TypeScript errors; `/` builds and renders `ControlPlane`.

- [ ] **Step 6: Manual smoke**

Start the stack (`make start-all` from repo root) and open `http://localhost:3000/`. Confirm: 4-region layout (rail · chat · sidebar), scope switch toggles Personal/Company (subtitle changes), `+ Add source` opens the existing add-source dialog, typing a question + Enter streams an answer, rail links navigate to `/sources`, `/podcasts`, `/search`, `/settings`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/control-plane/ControlPlaneChat.tsx frontend/src/components/control-plane/ControlPlane.tsx frontend/src/app/\(dashboard\)/page.tsx frontend/src/components/control-plane/ControlPlane.test.tsx
git commit -m "feat(control-plane): assemble control plane and make it the dashboard home"
```

---

## Self-Review

**Spec coverage (vs §5, §9 of the design spec):**
- UX1 control plane 4-col shell → Tasks 5–8. ✓ (left artifact column deferred to P8.1, noted in `ControlPlane.tsx`.)
- UX2 scope switch → Tasks 1, 5. ✓
- UX3 chat-is-home + legacy behind rail → Tasks 6, 8. ✓
- UX4 loop widget with Personal‖Company boundary → Tasks 3, 7. ✓
- F6 chat = streaming Ask → Task 8 (`useAsk`). ✓
- §9.0 add `Sheet` primitive → Task 2. ✓ (Hoisting `<AppShell>` out of all 9 pages is **not** done here — P8.0 is additive at `/` only; full hoist is optional and can be a later cleanup. Recorded as a deliberate scope choice.)
- i18n 14-locale parity → Task 4 + consumed by 5–8. ✓
- Governance / migration / visibility → **out of scope for P8.0** (P8.1/P8.2). ✓

**Placeholder scan:** No TBD/TODO. Empty-state sidebar sections are intentional P8.0 deliverables, not placeholders (filled in P8.1/P8.2). Every code step shows real code.

**Type consistency:** `useScopeStore` shape used identically in Tasks 5/7/8. `deriveLoopSteps(currentIndex)`/`COMPANY_BOUNDARY_INDEX` defined in Task 3, consumed in Task 7. `Sheet` exports (Task 2) unused within P8.0 (consumed in P8.1) — acceptable; it is a primitive, tested in isolation.

**Known verification points for the implementer** (flagged inline): exact Tailwind token names in `dialog.tsx`, `Logo` export shape, `AnswerBody` prop names, `useAsk.sendAsk` signature, whether `/connections` route exists. Each has a fallback noted.
