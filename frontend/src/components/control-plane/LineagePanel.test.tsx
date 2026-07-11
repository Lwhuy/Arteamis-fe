import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-governance', () => ({
  useBelief: () => ({ data: {
    belief: { id: 'belief:2', title: 'SMB focus Q3' },
    sources: [{ id: 'source:9', title: 'Q3 Research', locator: 'p.4' }],
    provenance: [{ action: 'proposal.accepted', actor: 'user:1' }],
    derived_work: [], contradictions: [],
    updated_from: { belief: 'belief:1', trace: 'trace:1' },
  }, isLoading: false }),
  useCreateDecision: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { LineagePanel } from './LineagePanel';

describe('LineagePanel', () => {
  it('shows belief title, its source, and provenance', () => {
    render(<LineagePanel id="belief:2" />);
    expect(screen.getByText('SMB focus Q3')).toBeInTheDocument();
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/proposal\.accepted|accepted/i)).toBeInTheDocument();
  });

  // NOTE: this project's global test setup (src/test/setup.ts) mocks
  // useTranslation as `t: (key) => key` for every test (see the
  // already-established convention in WorkPackagesSection.test.tsx), so
  // the assertion below is the raw i18n key, not literal English copy.
  it('shows the belief was updated from a real outcome when updated_from is present', () => {
    render(<LineagePanel id="belief:2" />);
    expect(screen.getByText('controlPlane.lineage.updatedFromOutcome')).toBeInTheDocument();
  });
});
