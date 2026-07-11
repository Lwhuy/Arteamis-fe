import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

const mutate = vi.fn();
vi.mock('@/lib/hooks/use-governance', () => ({
  useCreateWorkPackage: () => ({ mutate, isPending: false }),
}));

import { CreateWorkPackageDialog } from './CreateWorkPackageDialog';

describe('CreateWorkPackageDialog', () => {
  it('submits a human assignment without an agent brief', () => {
    render(
      <CreateWorkPackageDialog open onOpenChange={vi.fn()} sourceId="belief:1" sourceTitle="SMB focus" />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'controlPlane.workPackage.submit' }));
    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'SMB focus',
        assignee_kind: 'human',
        executes_ids: ['belief:1'],
        agent_brief: undefined,
      }),
      expect.anything(),
    );
  });

  it('shows the agent brief sub-form and includes it on submit when assignee kind is agent', () => {
    render(
      <CreateWorkPackageDialog open onOpenChange={vi.fn()} sourceId="belief:1" sourceTitle="SMB focus" />,
    );
    fireEvent.change(screen.getByLabelText('controlPlane.workPackage.assigneeKindLabel'), {
      target: { value: 'agent' },
    });
    fireEvent.change(screen.getByLabelText('controlPlane.workPackage.agentBrief.objective'), {
      target: { value: 'Summarize churn drivers' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'controlPlane.workPackage.submit' }));
    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        assignee_kind: 'agent',
        agent_brief: expect.objectContaining({
          objective: 'Summarize churn drivers',
          approval_gate: true,
        }),
      }),
      expect.anything(),
    );
  });
});
