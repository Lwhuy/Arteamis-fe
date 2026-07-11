import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-governance', () => ({
  useBelief: () => ({ data: {
    belief: { id: 'belief:1', title: 'SMB focus' },
    sources: [{ id: 'source:9', title: 'Q3 Research', locator: 'p.4' }],
    provenance: [{ action: 'proposal.accepted', actor: 'user:1' }],
    derived_work: [], contradictions: [],
  }, isLoading: false }),
}));

import { LineagePanel } from './LineagePanel';

describe('LineagePanel', () => {
  it('shows belief title, its source, and provenance', () => {
    render(<LineagePanel id="belief:1" />);
    expect(screen.getByText('SMB focus')).toBeInTheDocument();
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/proposal\.accepted|accepted/i)).toBeInTheDocument();
  });
});
