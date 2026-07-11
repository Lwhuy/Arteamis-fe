'use client';
import { Gavel } from 'lucide-react';
import { useCreateDecision } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

export function CreateDecisionButton({ beliefId, beliefTitle }: { beliefId: string; beliefTitle: string }) {
  const { t } = useTranslation();
  const create = useCreateDecision();
  return (
    <button type="button" disabled={create.isPending}
      onClick={() => create.mutate({ title: beliefTitle, rationale: '', belief_ids: [beliefId] })}
      className="mt-2 flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground hover:border-primary">
      <Gavel className="h-3.5 w-3.5" /> {t('controlPlane.lineage.createDecision')}
    </button>
  );
}
