import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ControlPlane } from './ControlPlane';

vi.mock('next/navigation', () => ({ usePathname: () => '/', useRouter: () => ({ push: vi.fn() }), useSearchParams: () => new URLSearchParams() }));
vi.mock('@/lib/hooks/use-ask', () => ({
  useAsk: () => ({ isStreaming: false, strategy: null, answers: [], finalAnswer: '', error: null, sendAsk: vi.fn(), reset: vi.fn() }),
}));
vi.mock('@/lib/hooks/use-create-dialogs', () => ({ useCreateDialogs: () => ({ openSourceDialog: vi.fn() }) }));
// ControlPlaneChat sources chat models via useModelDefaults (see search/page.tsx pattern), which
// wraps @tanstack/react-query's useQuery — mock it so the component doesn't require a
// QueryClientProvider in this unit test (consistent with other query-hook component tests, e.g.
// ChatColumn.test.tsx mocking useNotebookChat/useNotes).
vi.mock('@/lib/hooks/use-models', () => ({ useModelDefaults: () => ({ data: undefined, isLoading: false }) }));
// ContextSidebar's SourcesSection sources data via useRecentSources, which also wraps
// useQuery — mock it for the same QueryClientProvider-free reason as useModelDefaults above.
vi.mock('@/lib/hooks/use-sources', () => ({ useRecentSources: () => ({ data: [], isLoading: false }) }));

describe('ControlPlane', () => {
  it('renders rail, scope switch, chat composer and sidebar together', () => {
    render(<ControlPlane />);
    expect(screen.getByRole ? screen.getByRole('group') : screen.getByText(/personal/i)).toBeTruthy(); // scope switch
    expect(screen.getByRole('link', { name: /chat/i })).toBeInTheDocument();                            // rail
    expect(screen.getByPlaceholderText(/controlPlane\.composerPlaceholder|Ask the brain/i)).toBeInTheDocument(); // composer
  });
});
