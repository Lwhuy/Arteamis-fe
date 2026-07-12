import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

let mockArtifact: { type: 'source' | 'belief'; id: string; loc?: string; q?: string } = { type: 'source', id: 'abc', loc: '4' };
vi.mock('@/lib/hooks/use-artifact', () => ({
  useArtifact: () => ({ artifact: mockArtifact, openArtifact: vi.fn(), closeArtifact: vi.fn() }),
}));

let mockFullText = 'SMB skews higher.';
vi.mock('@/lib/hooks/use-sources', () => ({
  useSource: () => ({ data: { id: 'abc', title: 'Q3 Research', full_text: mockFullText, visibility: 'private' }, isLoading: false }),
}));
// ProposeButton uses useCreateProposal, which wraps @tanstack/react-query's useMutation —
// mock it so this unit test doesn't require a QueryClientProvider.
vi.mock('@/lib/hooks/use-governance', () => ({
  useCreateProposal: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ArtifactReader, findHighlightRange } from './ArtifactReader';

describe('findHighlightRange', () => {
  it('returns null when q is absent', () => {
    expect(findHighlightRange('SMB skews higher.', undefined)).toBeNull();
  });

  it('returns null when q is blank', () => {
    expect(findHighlightRange('SMB skews higher.', '   ')).toBeNull();
  });

  it('returns null when q does not appear in the text', () => {
    expect(findHighlightRange('SMB skews higher.', 'enterprise pricing')).toBeNull();
  });

  it('finds a case-insensitive exact match and returns its offsets', () => {
    const range = findHighlightRange('The market SMB SKEWS HIGHER this quarter.', 'smb skews higher');
    expect(range).toEqual({ start: 11, end: 27 });
  });

  it('is whitespace-tolerant across newlines and repeated spaces', () => {
    const text = 'Intro.\nSMB   skews\nhigher than enterprise.';
    const range = findHighlightRange(text, 'SMB skews higher');
    expect(range).not.toBeNull();
    expect(text.slice(range!.start, range!.end).replace(/\s+/g, ' ')).toBe('SMB skews higher');
  });

  it('returns the first occurrence when the phrase repeats', () => {
    const text = 'skip skew. SMB skews higher. Later, SMB skews higher again.';
    const range = findHighlightRange(text, 'SMB skews higher');
    expect(range!.start).toBe(11);
  });
});

describe('ArtifactReader', () => {
  beforeEach(() => {
    mockArtifact = { type: 'source', id: 'abc', loc: '4' };
    mockFullText = 'SMB skews higher.';
    // jsdom does not implement scrollIntoView; stub it so the highlight effect
    // can call it without throwing, and so tests can assert it fired.
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it('shows the source title and content when an artifact is open', () => {
    render(<ArtifactReader />);
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/SMB skews higher/)).toBeInTheDocument();
  });

  it('renders plain text with no highlight when q is absent', () => {
    render(<ArtifactReader />);
    expect(document.querySelector('mark[data-cp-highlight]')).toBeNull();
  });

  it('highlights the cited passage and scrolls it into view when q matches', () => {
    mockArtifact = { type: 'source', id: 'abc', loc: '4', q: 'SMB skews higher' };
    mockFullText = 'The Q3 survey found that SMB skews higher than enterprise this cycle.';
    render(<ArtifactReader />);
    const mark = document.querySelector('mark[data-cp-highlight]');
    expect(mark).not.toBeNull();
    expect(mark?.textContent?.toLowerCase()).toBe('smb skews higher');
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it('renders normally without crashing when q does not match the text', () => {
    mockArtifact = { type: 'source', id: 'abc', loc: '4', q: 'not in this document anywhere' };
    mockFullText = 'SMB skews higher.';
    render(<ArtifactReader />);
    expect(document.querySelector('mark[data-cp-highlight]')).toBeNull();
    expect(screen.getByText(/SMB skews higher/)).toBeInTheDocument();
  });
});
