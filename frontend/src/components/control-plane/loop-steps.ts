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
