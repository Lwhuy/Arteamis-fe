import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('@/lib/hooks/use-sources', () => ({
  useRecentSources: () => ({ data: [{ id: 's1', title: 'Q3 Research', visibility: 'private' }], isLoading: false }),
  useSourceStatus: () => ({ data: { status: 'completed' } }),
}));
vi.mock('@/lib/hooks/use-artifact', () => ({ useArtifact: () => ({ openArtifact: vi.fn() }) }));

import { SourcesSection } from './SourcesSection';

describe('SourcesSection', () => {
  it('lists a source with its title and a private badge', () => {
    render(<SourcesSection />);
    expect(screen.getByText('Q3 Research')).toBeInTheDocument();
    expect(screen.getByText(/private/i)).toBeInTheDocument();
  });
});
