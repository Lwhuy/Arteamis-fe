import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const mutate = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useCreateWorkPackage: () => ({ mutate, isPending: false }),
}));

import { CreateWorkPackageButton } from './CreateWorkPackageButton';

describe('CreateWorkPackageButton', () => {
  it('opens the create work package dialog', () => {
    render(<CreateWorkPackageButton sourceId="belief:1" sourceTitle="SMB focus" />);
    fireEvent.click(screen.getByRole('button', { name: 'controlPlane.workPackage.assignAction' }));
    expect(screen.getByText('controlPlane.workPackage.createTitle')).toBeInTheDocument();
  });
});
