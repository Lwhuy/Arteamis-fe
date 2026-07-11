import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const recordTraceMutate = vi.fn((_vars, opts) => {
  opts?.onSuccess?.({ id: 'trace:1', work_package: 'work_package:1', summary: 'Ran playbook', outcome: 'success', sources_used: [] });
});
const createLearningMutate = vi.fn();

vi.mock('@/lib/hooks/use-governance', () => ({
  useTracesForWorkPackage: () => ({
    data: [{ id: 'trace:0', summary: 'Earlier run', outcome: 'mixed' }],
    isLoading: false,
  }),
  useRecordTrace: () => ({ mutate: recordTraceMutate, isPending: false }),
  useCreateLearningProposal: () => ({ mutate: createLearningMutate, isPending: false }),
}));

import { TraceSection } from './TraceSection';

describe('TraceSection', () => {
  it('lists prior traces, records a new outcome, then proposes a learning update', () => {
    render(<TraceSection workPackageId="work_package:1" beliefId="belief:1" />);

    expect(screen.getByText('Earlier run')).toBeInTheDocument();

    // NOTE: this project's global test setup (src/test/setup.ts) mocks
    // useTranslation as `t: (key) => key` for every test (see the
    // already-established convention in WorkPackagesSection.test.tsx, which
    // asserts against raw dotted keys for the same reason). So placeholder
    // and button text below are the i18n keys themselves, not literal
    // English copy -- the literal English strings live in the locale files.
    fireEvent.change(screen.getByPlaceholderText('controlPlane.trace.summaryPlaceholder'), {
      target: { value: 'SMB outreach playbook ran; response rate tripled.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'controlPlane.trace.recordOutcome' }));

    expect(recordTraceMutate).toHaveBeenCalledWith(
      {
        workPackageId: 'work_package:1',
        payload: { summary: 'SMB outreach playbook ran; response rate tripled.', outcome: 'success', sources_used: [] },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );

    fireEvent.change(screen.getByPlaceholderText('controlPlane.trace.learningPlaceholder'), {
      target: { value: 'SMBs respond 3x better to this outreach angle.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'controlPlane.trace.submitLearning' }));

    expect(createLearningMutate).toHaveBeenCalledWith(
      {
        traceId: 'trace:1',
        payload: {
          title: 'controlPlane.trace.learningTitle',
          body: 'SMBs respond 3x better to this outreach angle.',
          belief_id: 'belief:1',
        },
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });
});
