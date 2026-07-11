'use client';
import { ArrowUp } from 'lucide-react';
import { useCreateProposal } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

export function ProposeButton({ title, body, sourceSpans }: {
  title: string; body: string; sourceSpans: { source_id: string; locator?: string }[];
}) {
  const { t } = useTranslation();
  const create = useCreateProposal();
  return (
    <button type="button" disabled={create.isPending}
      onClick={() => create.mutate({ kind: 'belief', title, body, source_spans: sourceSpans })}
      className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground">
      <ArrowUp className="h-3.5 w-3.5" /> {t('controlPlane.proposeToCompany')}
    </button>
  );
}
