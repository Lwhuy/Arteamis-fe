'use client';
import { useProposals, useBeliefs, useWorkPackages } from '@/lib/hooks/use-governance';
import { useRecentSources } from '@/lib/hooks/use-sources';

/** Real governance signals the 8-step loop widget's position is derived from. */
export type LoopSignals = {
  /** At least one source has been captured (workspace-wide). */
  hasSource?: boolean;
  /** At least one proposal is awaiting review. */
  hasPendingProposal?: boolean;
  /** At least one proposal has been accepted into a belief. */
  hasAcceptedBelief?: boolean;
  /** At least one work package has been created (handed off). */
  hasWorkPackage?: boolean;
  /** A trace has been recorded and/or turned into a learning proposal. */
  hasTraceOrLearning?: boolean;
};

/**
 * Pure "furthest progress wins" mapping from governance signals to a loop
 * step index (see LOOP_STEPS in components/control-plane/loop-steps.ts).
 * Checked highest-progress-first so a single downstream signal (e.g. a work
 * package existing) advances the widget even if upstream signals (e.g. no
 * more pending proposals) are no longer true.
 */
export function deriveLoopIndex(signals: LoopSignals = {}): number {
  const {
    hasSource = false,
    hasPendingProposal = false,
    hasAcceptedBelief = false,
    hasWorkPackage = false,
    hasTraceOrLearning = false,
  } = signals;

  if (hasTraceOrLearning) return 7; // Trace + Learning
  if (hasWorkPackage) return 6; // Handoff
  if (hasAcceptedBelief) return 5; // Rule / Belief
  if (hasPendingProposal) return 3; // Review
  if (hasSource) return 1; // Draft
  return 0; // Capture
}

/**
 * Gathers real governance state (proposals, beliefs, work packages, sources)
 * from the existing TanStack Query hooks and derives the control-plane loop
 * widget's current step. This is a workspace-global approximation (not
 * per-item progress) — see loop-progress gap write-up.
 */
export function useLoopProgress(): number {
  const proposalsQuery = useProposals();
  const beliefsQuery = useBeliefs();
  const workPackagesQuery = useWorkPackages();
  const sourcesQuery = useRecentSources();

  const proposals = proposalsQuery.data ?? [];
  const beliefs = beliefsQuery.data ?? [];
  const workPackages = workPackagesQuery.data ?? [];
  const sources = sourcesQuery.data ?? [];

  // There's no aggregate "all traces" endpoint (traces are fetched per work
  // package via useTracesForWorkPackage), so a learning-kind proposal - which
  // can only exist once a trace has been recorded and turned into a learning
  // proposal - stands in for "traces recorded" at the workspace level.
  const hasTraceOrLearning = proposals.some((p) => p.kind === 'learning');

  return deriveLoopIndex({
    hasSource: sources.length > 0,
    hasPendingProposal: proposals.some((p) => p.status === 'pending'),
    hasAcceptedBelief: beliefs.length > 0,
    hasWorkPackage: workPackages.length > 0,
    hasTraceOrLearning,
  });
}
