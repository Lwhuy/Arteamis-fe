import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const updateStatus = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useWorkPackages: () => ({
    data: [{ id: 'work_package:1', title: 'Draft SMB outreach plan', assignee_kind: 'agent', status: 'open' }],
    isLoading: false,
  }),
  useUpdateWorkPackageStatus: () => ({ mutate: updateStatus, isPending: false }),
  // TraceSection (rendered inside each work-package card) pulls these too.
  useTracesForWorkPackage: () => ({ data: [], isLoading: false }),
  useRecordTrace: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateLearningProposal: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { WorkPackagesSection } from './WorkPackagesSection';

describe('WorkPackagesSection', () => {
  it('lists a work package and advances its status', () => {
    render(<WorkPackagesSection />);
    expect(screen.getByText('Draft SMB outreach plan')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'controlPlane.workPackage.startAction' }));
    expect(updateStatus).toHaveBeenCalledWith({ id: 'work_package:1', status: 'running' });
  });

  it('renders the Trace & Learning section for the work package (loop closes)', () => {
    render(<WorkPackagesSection />);
    expect(screen.getByText('controlPlane.trace.title')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('controlPlane.trace.summaryPlaceholder')).toBeInTheDocument();
  });
});
