'use client';
import { useState } from 'react';
import { Dialog, DialogContent, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { useCreateWorkPackage } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';
import type { AgentBrief } from '@/lib/api/governance';

export interface CreateWorkPackageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sourceId: string;
  sourceTitle: string;
}

export function CreateWorkPackageDialog({ open, onOpenChange, sourceId, sourceTitle }: CreateWorkPackageDialogProps) {
  const { t } = useTranslation();
  const create = useCreateWorkPackage();

  const [title, setTitle] = useState(sourceTitle);
  const [assigneeKind, setAssigneeKind] = useState<'human' | 'agent'>('human');
  const [assignee, setAssignee] = useState('');
  const [objective, setObjective] = useState('');
  const [allowedContext, setAllowedContext] = useState('');
  const [budget, setBudget] = useState('');
  const [approvalGate, setApprovalGate] = useState(true);

  const reset = () => {
    setTitle(sourceTitle);
    setAssigneeKind('human');
    setAssignee('');
    setObjective('');
    setAllowedContext('');
    setBudget('');
    setApprovalGate(true);
  };

  const handleClose = () => {
    reset();
    onOpenChange(false);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const agentBrief: AgentBrief | undefined =
      assigneeKind === 'agent'
        ? {
            objective,
            allowed_context: allowedContext
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean),
            budget: budget || undefined,
            approval_gate: approvalGate,
          }
        : undefined;
    create.mutate(
      {
        title,
        assignee_kind: assigneeKind,
        assignee: assignee || undefined,
        agent_brief: agentBrief,
        executes_ids: [sourceId],
      },
      { onSuccess: handleClose },
    );
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogTitle>{t('controlPlane.workPackage.createTitle')}</DialogTitle>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div>
            <label htmlFor="wp-title" className="mb-1 block text-xs font-semibold text-foreground">
              {t('controlPlane.workPackage.titleLabel')}
            </label>
            <Input id="wp-title" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>

          <div>
            <label htmlFor="wp-assignee-kind" className="mb-1 block text-xs font-semibold text-foreground">
              {t('controlPlane.workPackage.assigneeKindLabel')}
            </label>
            <select
              id="wp-assignee-kind"
              value={assigneeKind}
              onChange={(e) => setAssigneeKind(e.target.value as 'human' | 'agent')}
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
            >
              <option value="human">{t('controlPlane.workPackage.assigneeKindHuman')}</option>
              <option value="agent">{t('controlPlane.workPackage.assigneeKindAgent')}</option>
            </select>
          </div>

          <div>
            <label htmlFor="wp-assignee" className="mb-1 block text-xs font-semibold text-foreground">
              {t('controlPlane.workPackage.assigneeLabel')}
            </label>
            <Input id="wp-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)} />
          </div>

          {assigneeKind === 'agent' && (
            <div className="flex flex-col gap-3 rounded-lg border border-dashed border-border p-3">
              <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
                {t('controlPlane.workPackage.agentBrief.heading')}
              </div>
              <div>
                <label htmlFor="wp-objective" className="mb-1 block text-xs font-semibold text-foreground">
                  {t('controlPlane.workPackage.agentBrief.objective')}
                </label>
                <Textarea id="wp-objective" value={objective} onChange={(e) => setObjective(e.target.value)} required />
              </div>
              <div>
                <label htmlFor="wp-allowed-context" className="mb-1 block text-xs font-semibold text-foreground">
                  {t('controlPlane.workPackage.agentBrief.allowedContext')}
                </label>
                <Input
                  id="wp-allowed-context"
                  value={allowedContext}
                  onChange={(e) => setAllowedContext(e.target.value)}
                  placeholder={t('controlPlane.workPackage.agentBrief.allowedContextHint')}
                />
              </div>
              <div>
                <label htmlFor="wp-budget" className="mb-1 block text-xs font-semibold text-foreground">
                  {t('controlPlane.workPackage.agentBrief.budget')}
                </label>
                <Input id="wp-budget" value={budget} onChange={(e) => setBudget(e.target.value)} />
              </div>
              <label className="flex items-center gap-2 text-xs text-foreground">
                <Checkbox checked={approvalGate} onCheckedChange={(v) => setApprovalGate(v === true)} />
                {t('controlPlane.workPackage.agentBrief.approvalGate')}
              </label>
            </div>
          )}

          <DialogFooter>
            <button
              type="button"
              onClick={handleClose}
              className="rounded-md px-3 py-2 text-xs font-semibold text-muted-foreground hover:text-foreground"
            >
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground"
            >
              {t('controlPlane.workPackage.submit')}
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
