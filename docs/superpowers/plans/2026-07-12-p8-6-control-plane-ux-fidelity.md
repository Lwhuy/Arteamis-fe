# P8.6 — Control Plane UX Fidelity (close the mockup gaps) — FOLLOW-UP PLAN

> Status: **NOT STARTED** (deferred). The P8 governed loop is fully implemented & real-DB-verified;
> these are the *experience* gaps between the shipped `/control-plane` and the agreed mockup
> `docs/superpowers/mockups/2026-07-12-control-plane/index.html`. Substance (data model, API,
> Capture→Propose→Review→Accept→Belief→Decision/Rule→Handoff→Trace→Learning) works end-to-end.

## Gaps (ranked)

1. **Living chat stream + agent inline insight-cards (biggest).**
   `frontend/src/components/control-plane/ControlPlaneChat.tsx` reuses the single-shot `/search` Ask
   widget (`use-ask.ts`) — only shows the latest `finalAnswer`, no message history, no user bubbles,
   no agent-authored action cards. Mockup: a conversation stream where, after a source finishes
   processing, the agent posts an insight card with **Ask / Draft / Propose to Company** actions.
   *Fix:* give the chat a message list (user q / agent answer / agent insight-card); after a source
   the user added transitions to `completed` (track ids via `useRecentSources`/`useSourceStatus`,
   only announce session-new sources), append an agent insight card summarizing its
   `source_insight`s with `<ProposeButton sourceSpans=[{source_id}]>` inline.

2. **Propose surfaced automatically, not hidden.** `ProposeButton` currently only lives inside
   `ArtifactReader → SourceArtifact` (must open a source to find it). Should appear in the chat
   insight card (gap 1) right after processing.

3. **Stateful loop widget.** `ContextSidebar.tsx` passes a hardcoded `currentIndex` (0 personal / 3
   company) to `LoopWidget` — decorative, never advances. *Fix:* derive `currentIndex` from real
   governance state (pending proposal → 2/3; accepted belief → 5/6; work_package open/running → 6/7;
   trace/learning → 7/8) via a small `useLoopProgress` hook over the governance queries.

4. **Citation highlight + scroll.** `SourceArtifact` renders full `full_text` via `MarkdownRenderer`
   with only a "page N" caption — no highlight/scroll to the cited span. Mockup highlights the
   passage (`mark`) and scrolls into view. *Fix:* when `?artifact=source&loc=…`, locate the span in
   the rendered content and apply a highlight + `scrollIntoView` (locator → offset/anchor mapping).

## Explicitly out of scope (PRD-deferred, not a gap)

- **Contradiction detection (D4).** `get_belief_lineage` returns `contradictions: []` with a code
  comment "reserved for later phases"; the lineage panel's contradiction block is a placeholder by
  design (PRD §4.4 / §1.7 stage the graph/contradiction layer for later). Needs embedding+LLM work.
- **Handoff/review as inline one-click chat cards** vs the current forms/dialogs — a deliberate
  "production console" choice, not a defect. Revisit only if the guided-demo feel is wanted.

## Suggested execution

Frontend-only, bite-sized TDD, in this order (1+2 together as the foundation, then 3, then 4). All
touch `frontend/src/components/control-plane/*` + existing governance/ask/source hooks; i18n across
14 locales. No backend/migration changes required (contradiction detection would be its own plan).
