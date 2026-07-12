import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

// Mutable fixtures the mocked hooks read from — let tests drive re-renders
// with different data without re-mocking modules per test.
let recentSourcesData: Array<{ id: string; title: string | null; visibility?: string }> = [];
let sourceStatusData: Record<string, { status?: string }> = {};
let sourceInsightsData: Record<string, Array<{ id: string; content: string }>> = {};
let askState = { isStreaming: false, finalAnswer: null as string | null };

vi.mock('@/lib/hooks/use-ask', () => ({
  useAsk: () => ({ ...askState, sendAsk: vi.fn(), reset: vi.fn() }),
}));
vi.mock('@/lib/hooks/use-models', () => ({
  useModelDefaults: () => ({ data: { default_chat_model: 'gpt-test' }, isLoading: false }),
}));
vi.mock('@/lib/hooks/use-sources', () => ({
  useRecentSources: () => ({ data: recentSourcesData, isLoading: false }),
  useSourceStatus: (id: string) => ({ data: sourceStatusData[id] ?? { status: 'running' } }),
}));
vi.mock('@/lib/hooks/use-insights', () => ({
  useSourceInsights: (id: string, options?: { enabled?: boolean }) => ({
    data: options?.enabled === false ? undefined : (sourceInsightsData[id] ?? []),
  }),
}));
vi.mock('@/lib/hooks/use-governance', () => ({
  useCreateProposal: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ControlPlaneChat } from './ControlPlaneChat';

describe('ControlPlaneChat', () => {
  beforeEach(() => {
    recentSourcesData = [];
    sourceStatusData = {};
    sourceInsightsData = {};
    askState = { isStreaming: false, finalAnswer: null };
  });

  it('renders the conversation stream container and a pinned composer', () => {
    render(<ControlPlaneChat />);
    expect(screen.getByPlaceholderText('controlPlane.composerPlaceholder')).toBeInTheDocument();
    expect(screen.getByLabelText('controlPlane.send')).toBeInTheDocument();
  });

  it('keeps showing live streaming feedback while a question is in flight', () => {
    askState = { isStreaming: true, finalAnswer: null };
    render(<ControlPlaneChat />);
    // AnswerBody shows the "processingQuestion" copy (raw i18n key under test mocks) while streaming.
    expect(screen.getByText('searchPage.processingQuestion')).toBeInTheDocument();
  });

  it('surfaces an agent-insight card with an inline Propose action once a session-new source completes', () => {
    const { rerender } = render(<ControlPlaneChat />);

    // Source appears mid-session (not present at mount) — simulate it finishing processing.
    recentSourcesData = [{ id: 'src-1', title: 'Q3 Research', visibility: 'private' }];
    sourceStatusData = { 'src-1': { status: 'completed' } };
    sourceInsightsData = { 'src-1': [{ id: 'ins-1', content: 'SMB skews higher than enterprise' }] };
    rerender(<ControlPlaneChat />);

    expect(screen.getByText(/Q3 Research/)).toBeInTheDocument();
    expect(screen.getByText(/SMB skews higher than enterprise/)).toBeInTheDocument();
    expect(screen.getByText('controlPlane.proposeToCompany')).toBeInTheDocument();
    expect(screen.getByText('controlPlane.insight.askMore')).toBeInTheDocument();
    expect(screen.getByText('controlPlane.insight.openSource')).toBeInTheDocument();
  });

  it('does not announce a source that was already present when the chat mounted', () => {
    recentSourcesData = [{ id: 'src-existing', title: 'Old Source', visibility: 'private' }];
    sourceStatusData = { 'src-existing': { status: 'completed' } };
    sourceInsightsData = { 'src-existing': [{ id: 'ins-2', content: 'stale insight' }] };
    render(<ControlPlaneChat />);
    expect(screen.queryByText(/Old Source/)).not.toBeInTheDocument();
  });
});
