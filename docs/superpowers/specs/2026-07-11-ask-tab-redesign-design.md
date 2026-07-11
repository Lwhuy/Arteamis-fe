# Ask Tab Redesign — Design Spec

## Context

Open Notebook's `/search` page (`frontend/src/app/(dashboard)/search/page.tsx`) has two tabs: **Ask** (LLM answer over the knowledge base, via `useAsk` + `StreamingResponse`) and **Search** (keyword/vector search results, via `useSearch`). The user wants the **Ask tab** restyled to match a reference product ("Quelvio Enterprise"): question-as-title, borderless answer, inline feedback icons, a right-side Sources panel with citation snippets, and a bottom-docked follow-up input.

This spec covers a **visual and structural restyle of the Ask tab only**. The Search tab, `AppShell`/left navigation, and backend APIs are unchanged.

## Decisions made during brainstorming

| Element from reference | Decision |
|---|---|
| Follow-up input implying threaded memory | **Fresh question each time** — visually a follow-up bar, but functionally identical to submitting a new Ask call. No conversation-history changes to the backend. |
| "Related Questions" chips | **Dropped.** Requires a new LLM-backed suggestion endpoint that doesn't exist; out of scope. |
| Thumbs up / down feedback icons | **UI-only, no persistence.** Clicking shows a toast; nothing is sent to the backend or stored. |
| Copy button | **Real** — copies the rendered answer text to the clipboard. |
| Right-side Sources panel with snippets | **Built for real**, using data already available (see below) — not mocked. |
| Search tab (keyword/vector) | **Untouched.** Redesign applies only when `activeTab === 'ask'`. |

## Layout changes (Ask tab only)

Current structure (top to bottom, all in one `Card`):
1. Question `Textarea` + Ask button
2. Model badges (Strategy/Answer/Final) + Advanced button
3. `StreamingResponse`: Strategy card (collapsible) → Individual Answers card (collapsible) → Final Answer card (bordered)

New structure:
1. **Before first answer**: keep today's "Ask Your Knowledge Base" card as-is (question textarea, model badges, Ask button, embedding-model warning). No change here — this is the empty state.
2. **After an answer exists**:
   - The submitted question renders as an `<h3>` page-level heading (replacing the textarea's visual prominence, though the textarea/logic still exists for the follow-up bar at the bottom).
   - **Answer area**: full-width, no `Card` border — just the existing `MarkdownRenderer` output with inline citations, same click-to-open-modal behavior as today.
   - **Feedback row** directly under the answer: 👍 👎 (UI-only, toast on click) · Copy (copies answer markdown/text) · existing "Save to Notebooks" button relocated here.
   - **Strategy & reasoning**: today's Strategy + Individual Answers content, merged into a single collapsible disclosure (collapsed by default), positioned below the feedback row instead of above the answer.
   - **Follow-up bar**: docked below the strategy disclosure (not fixed/sticky — simple layout position, no need for viewport-pinning). Contains: text input (reuses `askQuestion` state + `handleAsk`), the existing model badges/Advanced-settings button (relocated from the top), and an Ask/Run button. Submitting it just calls `handleAsk()` again — same fresh, stateless call as today.
   - **"+ New Question"** control near the top (next to the question heading) resets state back to the empty "Ask Your Knowledge Base" card.
   - **Right-side Sources panel**: new component, rendered alongside the answer in a two-column flex layout (`flex-1` answer + fixed-width sidebar, stacking vertically below the answer on narrow/mobile widths). Lists each **unique** reference cited in the final answer (parsed via the existing `parseSourceReferences` from `source-references.tsx`), numbered to match inline citation markers. Each entry shows: type icon, title, and a short snippet.

## Data requirements for the Sources panel

`parseSourceReferences(finalAnswer)` already extracts `{ type, id }` pairs from the answer text (used today to make inline citations clickable). For the panel we need, per unique `(type, id)`:
- **Title** — already fetched by the existing per-item detail endpoints used by the click-to-open modal (`source`, `note`, `source_insight` detail fetches).
- **Snippet** — a short excerpt of the item's content. Source/note detail responses include full content; truncate client-side (e.g., first ~150 chars of the relevant chunk/content, or the content field if no chunk-level match is available — implementation detail to confirm in the plan).

No new backend endpoints are required — this is client-side aggregation of data already reachable through existing detail-fetch calls, deduplicated by `type:id` and ordered by first appearance in the answer text.

## Non-goals

- No changes to the Search (keyword/vector) tab.
- No new backend endpoints, DB fields, or migrations.
- No real feedback persistence (thumbs up/down are cosmetic).
- No related-questions generation.
- No true multi-turn conversation memory in Ask.

## Constraints to carry into implementation

- **i18n**: every new UI string (feedback tooltips, "New Question", "Sources" panel labels, snippet truncation ellipsis, etc.) must go through `t('section.key')` and be added to **all 7 locales** under `frontend/src/lib/locales/` (`en-US`, `pt-BR`, `zh-CN`, `zh-TW`, `ja-JP`, `ru-RU`, `bn-IN`).
- Reuse `useModalManager` / existing detail-fetch hooks for the Sources panel rather than introducing a new data-fetching pattern.
- Keep `StreamingResponse` behavior (streaming states, loading spinner) intact — this is a re-layout of existing pieces, not a rewrite of the ask/streaming logic.
- Follow existing component conventions in `frontend/src/components/search/`.
