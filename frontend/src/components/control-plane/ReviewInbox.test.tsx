import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const accept = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useProposals: () => ({
    data: [
      { id: 'proposal:1', title: 'SMB focus', status: 'pending', kind: 'belief' },
      { id: 'proposal:2', title: 'Outcome: SMB outreach worked', status: 'pending', kind: 'learning' },
    ],
    isLoading: false,
  }),
  useAcceptProposal: () => ({ mutate: accept, isPending: false }),
  useRequestChanges: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ReviewInbox } from './ReviewInbox';

describe('ReviewInbox', () => {
  // NOTE: this project's global test setup (src/test/setup.ts) mocks
  // useTranslation as `t: (key) => key` for every test (see the
  // already-established convention in WorkPackagesSection.test.tsx), so
  // button/badge text below is the raw i18n key, not literal English copy.
  it('lists a pending proposal and accepts it', () => {
    render(<ReviewInbox />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'controlPlane.review.accept' })[0]);
    expect(accept).toHaveBeenCalledWith('proposal:1');
  });

  it('badges a learning-kind proposal so reviewers see it closes the loop', () => {
    render(<ReviewInbox />);
    expect(screen.getByText('Outcome: SMB outreach worked')).toBeInTheDocument();
    expect(screen.getByText('controlPlane.review.learningBadge')).toBeInTheDocument();
  });
});
