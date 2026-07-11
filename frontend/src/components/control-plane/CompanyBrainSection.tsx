'use client';
import { Sparkles } from 'lucide-react';
import { useBeliefs } from '@/lib/hooks/use-governance';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';

export function CompanyBrainSection() {
  const { t } = useTranslation();
  const { data } = useBeliefs();
  const { openArtifact } = useArtifact();
  const beliefs = (data ?? []) as { id: string; title: string }[];
  if (beliefs.length === 0)
    return <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{t('controlPlane.sidebar.brainEmpty')}</div>;
  return (
    <div className="flex flex-col gap-1.5">
      {beliefs.map((b) => (
        <button key={b.id} type="button" onClick={() => openArtifact('belief', b.id)}
          className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5 text-left hover:border-primary">
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="flex-1 truncate text-xs font-semibold text-foreground">{b.title}</span>
          <span className="text-[10px] text-muted-foreground">{t('controlPlane.brain.view')}</span>
        </button>
      ))}
    </div>
  );
}
