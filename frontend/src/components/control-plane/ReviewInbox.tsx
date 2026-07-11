'use client';
import { useProposals, useAcceptProposal, useRequestChanges } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

export function ReviewInbox() {
  const { t } = useTranslation();
  const { data, isLoading } = useProposals('pending');
  const accept = useAcceptProposal();
  const changes = useRequestChanges();
  const items = data ?? [];
  if (isLoading) return <div className="text-xs text-muted-foreground">{t('common.loading')}</div>;
  if (items.length === 0)
    return <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{t('controlPlane.sidebar.reviewEmpty')}</div>;
  return (
    <div className="flex flex-col gap-2">
      {items.map((p) => (
        <div key={p.id} className="rounded-xl border border-border bg-card p-3">
          <div className="text-xs font-bold text-foreground">{p.title}</div>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => accept.mutate(p.id)} disabled={accept.isPending}
              className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground">
              {t('controlPlane.review.accept')}
            </button>
            <button type="button" onClick={() => changes.mutate({ id: p.id, note: '' })}
              className="rounded-md px-2.5 py-1 text-xs font-semibold text-muted-foreground hover:text-foreground">
              {t('controlPlane.review.changes')}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
