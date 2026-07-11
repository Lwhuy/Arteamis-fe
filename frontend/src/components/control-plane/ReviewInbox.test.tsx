import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const accept = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useProposals: () => ({ data: [{ id: 'proposal:1', title: 'SMB focus', status: 'pending' }], isLoading: false }),
  useAcceptProposal: () => ({ mutate: accept, isPending: false }),
  useRequestChanges: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ReviewInbox } from './ReviewInbox';

describe('ReviewInbox', () => {
  it('lists a pending proposal and accepts it', () => {
    render(<ReviewInbox />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /controlPlane\.review\.accept|accept|duyệt/i }));
    expect(accept).toHaveBeenCalledWith('proposal:1');
  });
});
