import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const openArtifact = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useBeliefs: () => ({ data: [{ id: 'belief:1', title: 'SMB focus' }] }),
  useDecisions: () => ({ data: [{ id: 'decision:1', title: 'Ship SMB pricing', status: 'active' }] }),
  useRules: () => ({ data: [{ id: 'rule:1', title: 'Always cite two sources', status: 'active' }] }),
  useCreateWorkPackage: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateRule: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('@/lib/hooks/use-artifact', () => ({
  useArtifact: () => ({ openArtifact }),
}));

import { CompanyBrainSection } from './CompanyBrainSection';

describe('CompanyBrainSection', () => {
  it('shows beliefs, decisions, and rules', () => {
    render(<CompanyBrainSection />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    expect(screen.getByText('Ship SMB pricing')).toBeInTheDocument();
    expect(screen.getByText('Always cite two sources')).toBeInTheDocument();
  });

  it('opens the belief artifact and offers a work-package assign affordance', () => {
    render(<CompanyBrainSection />);
    fireEvent.click(screen.getByText('SMB focus'));
    expect(openArtifact).toHaveBeenCalledWith('belief', 'belief:1');
    expect(screen.getByRole('button', { name: 'controlPlane.workPackage.assignAction' })).toBeInTheDocument();
  });
});
