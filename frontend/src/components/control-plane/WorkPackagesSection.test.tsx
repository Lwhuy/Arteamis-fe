import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const updateStatus = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useWorkPackages: () => ({
    data: [{ id: 'work_package:1', title: 'Draft SMB outreach plan', assignee_kind: 'agent', status: 'open' }],
    isLoading: false,
  }),
  useUpdateWorkPackageStatus: () => ({ mutate: updateStatus, isPending: false }),
}));

import { WorkPackagesSection } from './WorkPackagesSection';

describe('WorkPackagesSection', () => {
  it('lists a work package and advances its status', () => {
    render(<WorkPackagesSection />);
    expect(screen.getByText('Draft SMB outreach plan')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'controlPlane.workPackage.startAction' }));
    expect(updateStatus).toHaveBeenCalledWith({ id: 'work_package:1', status: 'running' });
  });
});
