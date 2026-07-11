'use client';
import { useWorkPackages, useUpdateWorkPackageStatus } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';
import type { WorkPackage } from '@/lib/api/governance';
import { TraceSection } from './TraceSection';

const NEXT_STATUS: Record<WorkPackage['status'], WorkPackage['status'] | null> = {
  open: 'running',
  running: 'done',
  done: null,
};

const STATUS_LABEL_KEY: Record<WorkPackage['status'], string> = {
  open: 'controlPlane.workPackage.status.open',
  running: 'controlPlane.workPackage.status.running',
  done: 'controlPlane.workPackage.status.done',
};

export function WorkPackagesSection() {
  const { t } = useTranslation();
  const { data, isLoading } = useWorkPackages();
  const updateStatus = useUpdateWorkPackageStatus();
  const items = data ?? [];

  if (isLoading) return <div className="text-xs text-muted-foreground">{t('common.loading')}</div>;
  if (items.length === 0)
    return (
      <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
        {t('controlPlane.sidebar.workPackagesEmpty')}
      </div>
    );

  return (
    <div className="flex flex-col gap-2">
      {items.map((wp) => {
        const next = NEXT_STATUS[wp.status];
        return (
          <div key={wp.id} className="rounded-xl border border-border bg-card p-3">
            <div className="text-xs font-bold text-foreground">{wp.title}</div>
            <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
              <span
                className={cn(
                  'rounded-full px-2 py-0.5 font-bold',
                  wp.assignee_kind === 'agent' ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground',
                )}
              >
                {t(
                  wp.assignee_kind === 'agent'
                    ? 'controlPlane.workPackage.assigneeKindAgent'
                    : 'controlPlane.workPackage.assigneeKindHuman',
                )}
              </span>
              <span>{t(STATUS_LABEL_KEY[wp.status])}</span>
            </div>
            {next && (
              <button
                type="button"
                onClick={() => updateStatus.mutate({ id: wp.id, status: next })}
                disabled={updateStatus.isPending}
                className="mt-2 rounded-md px-2.5 py-1 text-xs font-semibold text-primary hover:underline"
              >
                {t(
                  next === 'running'
                    ? 'controlPlane.workPackage.startAction'
                    : 'controlPlane.workPackage.completeAction',
                )}
              </button>
            )}
            <div className="mt-3 border-t border-border pt-3">
              {/*
                NOTE: `WorkPackage` (frontend/src/lib/api/governance.ts) does not
                currently expose which belief a work package traces back to.
                `executes_ids` is accepted on POST /work-packages and persisted
                as a `work_package->executes->belief` graph edge (see
                api/governance_service.py::create_work_package), but no read
                endpoint (GET /work-packages, GET /work-packages/{id}) returns
                it back out, so it cannot be resolved here even one hop away.
                `beliefId` is left empty until that read-side gap is closed on
                the backend — see p85-task-8-report.md for details. TraceSection
                itself is otherwise fully wired to this work package.
              */}
              <TraceSection workPackageId={wp.id} beliefId="" />
            </div>
          </div>
        );
      })}
    </div>
  );
}
