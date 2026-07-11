import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-artifact', () => ({
  useArtifact: () => ({ artifact: { type: 'source', id: 'abc', loc: '4' }, openArtifact: vi.fn(), closeArtifact: vi.fn() }),
}));
vi.mock('@/lib/hooks/use-sources', () => ({
  useSource: () => ({ data: { id: 'abc', title: 'Q3 Research', full_text: 'SMB skews higher.', visibility: 'private' }, isLoading: false }),
}));

import { ArtifactReader } from './ArtifactReader';

describe('ArtifactReader', () => {
  it('shows the source title and content when an artifact is open', () => {
    render(<ArtifactReader />);
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/SMB skews higher/)).toBeInTheDocument();
  });
});
