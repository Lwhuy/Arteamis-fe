import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { useScopeStore } from '@/lib/stores/scope-store';

vi.mock('./SourcesSection', () => ({ SourcesSection: () => <div>sources-section</div> }));
vi.mock('./ReviewInbox', () => ({ ReviewInbox: () => <div>review-inbox</div> }));
vi.mock('./CompanyBrainSection', () => ({ CompanyBrainSection: () => <div>brain-section</div> }));
vi.mock('./WorkPackagesSection', () => ({ WorkPackagesSection: () => <div>work-packages-section</div> }));

const useLoopProgressMock = vi.fn();
vi.mock('@/lib/hooks/use-loop-progress', () => ({
  useLoopProgress: () => useLoopProgressMock(),
}));

import { ContextSidebar } from './ContextSidebar';

describe('ContextSidebar', () => {
  beforeEach(() => {
    useScopeStore.setState({ scope: 'personal' });
    useLoopProgressMock.mockReset();
  });

  it('renders without throwing in personal scope', () => {
    useLoopProgressMock.mockReturnValue(0);
    render(<ContextSidebar />);
    expect(screen.getByText('sources-section')).toBeInTheDocument();
  });

  it('renders without throwing in company scope', () => {
    useScopeStore.setState({ scope: 'company' });
    useLoopProgressMock.mockReturnValue(0);
    render(<ContextSidebar />);
    expect(screen.getByText('review-inbox')).toBeInTheDocument();
    expect(screen.getByText('brain-section')).toBeInTheDocument();
    expect(screen.getByText('work-packages-section')).toBeInTheDocument();
  });

  it('reflects the real derived loop index in personal scope (no hardcoded 0)', () => {
    useLoopProgressMock.mockReturnValue(3); // Review
    render(<ContextSidebar />);
    expect(screen.getByText('controlPlane.loop.review').className).toContain('font-semibold');
  });

  it('reflects the real derived loop index in company scope (no hardcoded 3)', () => {
    useScopeStore.setState({ scope: 'company' });
    useLoopProgressMock.mockReturnValue(6); // Handoff
    render(<ContextSidebar />);
    expect(screen.getByText('controlPlane.loop.handoff').className).toContain('font-semibold');
  });
});
