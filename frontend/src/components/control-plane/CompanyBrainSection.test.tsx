import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-governance', () => ({
  useBeliefs: () => ({ data: [{ id: 'belief:1', title: 'SMB focus' }] }),
  useDecisions: () => ({ data: [{ id: 'decision:1', title: 'Ship SMB pricing', status: 'active' }] }),
  useRules: () => ({ data: [{ id: 'rule:1', title: 'Always cite two sources', status: 'active' }] }),
}));
vi.mock('@/lib/hooks/use-artifact', () => ({
  useArtifact: () => ({ openArtifact: vi.fn() }),
}));

import { CompanyBrainSection } from './CompanyBrainSection';

describe('CompanyBrainSection', () => {
  it('shows beliefs, decisions, and rules', () => {
    render(<CompanyBrainSection />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    expect(screen.getByText('Ship SMB pricing')).toBeInTheDocument();
    expect(screen.getByText('Always cite two sources')).toBeInTheDocument();
  });
});
