import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams('artifact=source&aid=abc'),
}));
vi.mock('@/lib/hooks/use-ask', () => ({
  useAsk: () => ({ isStreaming: false, answers: [], finalAnswer: '', error: null, sendAsk: vi.fn(), reset: vi.fn() }),
}));
vi.mock('@/lib/hooks/use-create-dialogs', () => ({ useCreateDialogs: () => ({ openSourceDialog: vi.fn() }) }));
// ControlPlaneChat sources chat models via useModelDefaults, which wraps @tanstack/react-query's
// useQuery — mock it so the component doesn't require a QueryClientProvider in this unit test
// (consistent with ControlPlane.test.tsx).
vi.mock('@/lib/hooks/use-models', () => ({ useModelDefaults: () => ({ data: undefined, isLoading: false }) }));
vi.mock('@/lib/hooks/use-sources', () => ({
  useSource: () => ({ data: { id: 'abc', title: 'Q3 Research', full_text: 'body', visibility: 'private' }, isLoading: false }),
  useRecentSources: () => ({ data: [], isLoading: false }),
}));
// SourceArtifact (inside the artifact reader) reads a source's insights to seed
// the propose body — mock it for the same QueryClientProvider-free reason.
vi.mock('@/lib/hooks/use-insights', () => ({
  useSourceInsights: () => ({ data: [] }),
}));
// ProposeButton (rendered inside the artifact reader) uses useCreateProposal, which wraps
// @tanstack/react-query's useMutation — mock it so this unit test doesn't require a QueryClientProvider.
// ContextSidebar's useLoopProgress also pulls useProposals/useBeliefs/useWorkPackages
// (useQuery-backed) for the same QueryClientProvider-free reason.
vi.mock('@/lib/hooks/use-governance', () => ({
  useCreateProposal: () => ({ mutate: vi.fn(), isPending: false }),
  useProposals: () => ({ data: [], isLoading: false }),
  useBeliefs: () => ({ data: [], isLoading: false }),
  useWorkPackages: () => ({ data: [], isLoading: false }),
}));

import { ControlPlane } from './ControlPlane';

describe('ControlPlane with artifact param', () => {
  it('renders the artifact reader column when ?artifact is set', () => {
    render(<ControlPlane />);
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
  });
});
