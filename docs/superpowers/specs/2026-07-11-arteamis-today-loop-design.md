# Arteamis-style "Today" Loop Landing — Design

**Date:** 2026-07-11
**Status:** Approved (brainstorm), pending spec review
**Author:** pairing session

## Summary

Bring the Arteamis "Today" landing experience — a single next-action hero and a
horizontal step "loop rail" — into the Open Notebook frontend, driven by Open
Notebook's **real data**. The loop steps are remapped from Arteamis's governance
vocabulary to Open Notebook's actual research workflow, and each step's
done/current/later state is derived from live counts for one focused notebook.

This is a **faithful re-build using Open Notebook's own primitives** (shadcn/ui
`Card`/`Badge`/`Button`, the `cn` helper, `t()` i18n, TanStack Query hooks) — not
a file copy of Arteamis components (which hard-code colors and skip i18n).

## Goals

- A new `/today` page that becomes the default dashboard landing.
- An Arteamis-style **NextActionCard** hero: eyebrow, big next-action headline,
  status badges, an `X/Y done` pill, and exactly one primary CTA.
- An Arteamis-style **horizontal LoopStepRail** of numbered step chips with three
  visual states (done / current / later).
- Loop step states derived from **real Open Notebook data** for the
  most-recently-updated notebook, with a picker to switch the tracked notebook.

## Non-Goals

- No new backend endpoints, DB schema, or workers. Frontend-only.
- No reskin of the existing sidebar chrome (only a new "Today" nav entry).
- No port of Arteamis's governance objects (lesson proposals, team rules, work
  handoffs, agent checks) — those have no equivalent in Open Notebook.
- No Simple/Expert mode toggle or `plainLanguage` relabeling engine.

## Decisions (locked defaults)

1. **Accent color:** match Open Notebook's existing theme tokens (works in light
   and dark), NOT Arteamis's orange `protocol` accent.
2. **Loop length:** lean **4-step** loop. A 5th "Transform a source / insights"
   step is deliberately excluded because insights are per-source
   (`insightsApi.listForSource(sourceId)`), so detecting them notebook-wide would
   cost N calls. Every included step is a single cheap count.
3. **Sidebar:** add a "Today" entry as the first nav group; do not restyle the
   rest of the sidebar.
4. **Loop scope:** the loop tracks **one notebook** — the most-recently-updated by
   default (`useNotebooks()` is already ordered `updated desc`), switchable via a
   picker; the selected notebook id persists to `localStorage`.

## The Loop (remapped to Open Notebook)

Exactly one primary CTA is shown: the **next action = the first incomplete step**.

| # | Step label (i18n key)        | "Done" when                          | CTA target            |
|---|------------------------------|--------------------------------------|-----------------------|
| 0 | Create a notebook            | `notebooks.length > 0`               | `/notebooks`          |
| 1 | Add a source                 | active notebook has ≥ 1 source       | `/notebooks/[id]`     |
| 2 | Ask & save a note            | active notebook has ≥ 1 note         | `/notebooks/[id]`     |
| 3 | Generate a podcast           | ≥ 1 **completed** podcast episode    | `/podcasts`           |

When all steps are done, the hero shows a "loop complete — start the next thread"
state whose CTA adds another source.

### Data sources

- Step 0: `useNotebooks()` (already `updated desc`).
- Step 1: `useSources(activeNotebookId)` → array length.
- Step 2: notes for the active notebook via the existing notes hook/api
  (`notesApi.list({ notebook_id })`).
- Step 3: `usePodcastEpisodes()` (wraps `podcastsApi.listEpisodes()` →
  `/podcasts/episodes`). This is a **global** episode list — there is no
  notebook-scoped episode filter today, so this step is intentionally global
  (documented imprecision, not a bug). The list also includes
  `queued`/`running`/`failed` episodes; "done" therefore requires at least one
  episode in a **completed** state, not merely any episode.

### Query-state coercion (idle vs error vs empty)

`useSources`/`useNotes` use `enabled: !!activeNotebookId`, so when no notebook is
selected their queries stay **idle** with `data === undefined` (not `[]`). The
signal builder MUST coerce every count from a possibly-`undefined` query result to
`0` — covering idle, loading, and error alike — before calling `deriveLoopSteps`.
`deriveLoopSteps` itself only ever receives concrete numbers.

## Architecture

```
app/(dashboard)/today/page.tsx        → renders <TodayScreen/>
app/(dashboard)/page.tsx              → redirect '/notebooks' → '/today'  (edit)
components/layout/AppSidebar.tsx      → add "Today" nav entry              (edit)
lib/locales/*/…                       → add today.* + navigation.today keys (edit,
                                        all 15 locales — parity is test-enforced)

components/today/
  TodayScreen.tsx     client orchestrator: reads hooks, picks active notebook,
                      calls deriveLoopSteps(), renders the pieces
  loop-steps.ts       pure deriveLoopSteps(signals) -> LoopStep[] + NextAction
                      (no React, no fetching — unit-testable)
  loop-steps.test.ts  vitest unit tests for the state machine
  NextActionCard.tsx  hero (image 1)
  LoopStepRail.tsx    horizontal numbered chips (image 2)
  LoopProgress.tsx    optional vertical "where you are" list
```

### Component boundaries

- **`loop-steps.ts`** is the brain. Input: a plain `LoopSignals` object
  (`{ notebookCount, sourceCount, noteCount, podcastCount }`). Output: an ordered
  `LoopStep[]` (each `{ id, labelKey, done, current, later, href }`) plus the
  derived `NextAction`. Pure and fully testable without a DOM or network.
- **`TodayScreen.tsx`** is the only piece that touches hooks and browser state
  (active-notebook selection + `localStorage`). It assembles signals and passes
  plain props down. It renders a loading skeleton while notebooks load and an
  empty/first-run state when `notebookCount === 0`.
- **`NextActionCard` / `LoopStepRail` / `LoopProgress`** are pure presentational
  components taking already-computed props. No fetching inside them.

## Data flow

1. `TodayScreen` calls `useNotebooks()`; picks `activeNotebookId` (persisted
   selection if still valid, else `notebooks[0]`).
2. Calls `useSources(activeNotebookId)`, `useNotes(activeNotebookId)`, and
   `usePodcastEpisodes()`.
3. Builds `LoopSignals`, calls `deriveLoopSteps(signals)`.
4. Passes `steps` + `nextAction` to the presentational components.
5. The notebook picker updates `activeNotebookId` and persists it.

## Error / edge handling

- **No notebooks yet:** first-run hero ("Create your first notebook") + all steps
  `later`; picker hidden.
- **Notebook loading:** skeleton in the hero and rail.
- **Sources/notes/episodes query error:** treat that step's count as `0`
  (step stays incomplete) and surface a non-blocking inline note; never crash the
  page. Matches Open Notebook's existing "could not load" panel pattern.
- **Persisted notebook id no longer exists** (deleted/archived): fall back to
  `notebooks[0]` and rewrite `localStorage`.
- **Empty podcast episodes list** is a normal state, not an error.

## Testing

- **Unit (highest value):** `loop-steps.test.ts` covers each transition of
  `deriveLoopSteps`:
  - 0 notebooks → step 0 current, next action = create notebook.
  - notebook but 0 sources → step 1 current.
  - sources but 0 notes → step 2 current.
  - notes but 0 podcasts → step 3 current.
  - all satisfied → loop-complete next action.
  - done/current/later flags are mutually consistent (exactly one `current`
    unless complete).
  - `undefined` counts (idle/loading/errored queries) are coerced to `0` and
    never throw.
  - podcast step is done only when an episode is in a completed state (a lone
    failed/queued episode does NOT complete the step).
- **Component smoke (optional):** `TodayScreen` renders first-run state with an
  empty notebooks list without throwing.
- **i18n parity:** `frontend/src/lib/locales/index.test.ts` must stay green — new
  keys present in all locales, no unused keys. Run `npm run test` before done.
- Run under the existing `vitest` config; follow patterns in
  `frontend/src/app/(dashboard)/notebooks/components/ChatColumn.test.tsx` and
  `AppSidebar.test.tsx`.

## i18n

Add new copy keys under a `today.*` namespace (and one `navigation.today`),
consumed via `t()`. No hard-coded user-facing English in components.

**Locale parity is enforced by tests** — `frontend/src/lib/locales/index.test.ts`
runs two checks that this work must satisfy:

1. **Locale Parity:** every non-`en-US` locale must have the *exact* same key set
   as `en-US` (no missing, no extra). Therefore the new keys MUST be added to
   **every** locale file under `frontend/src/lib/locales/` — currently **15**
   locales (`bn-IN, ca-ES, de-DE, en-US, es-ES, fr-FR, it-IT, ja-JP, pl-PL,
   pt-BR, ru-RU, tr-TR, zh-CN, zh-TW`, plus `en-US`). English placeholder values
   are acceptable for non-English locales this iteration, but the keys must exist
   everywhere. Do not rely on runtime fallback — the parity test checks the files.
2. **Unused Key Detection:** every `en-US` leaf key must be referenced somewhere in
   source. Therefore only add keys that are actually consumed by a shipped
   component. If the optional `LoopProgress` component (or any step label) is not
   built, its keys must not be added.

`en-US` is the reference locale.

## Rollout / reversibility

- Purely additive plus two one-line edits; revert = delete `components/today/`,
  the `today/` route, and undo the sidebar + redirect edits.
- No data migration, no backend change, no config change.
```
