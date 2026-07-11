'use client';
import { Sparkles, Gavel, ListChecks } from 'lucide-react';
import { useBeliefs, useDecisions, useRules } from '@/lib/hooks/use-governance';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';

export function CompanyBrainSection() {
  const { t } = useTranslation();
  const { data: beliefData } = useBeliefs();
  const { data: decisionData } = useDecisions();
  const { data: ruleData } = useRules();
  const { openArtifact } = useArtifact();

  const beliefs = (beliefData ?? []) as { id: string; title: string }[];
  const decisions = (decisionData ?? []) as { id: string; title: string; status: string }[];
  const rules = (ruleData ?? []) as { id: string; title: string; status: string }[];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        {beliefs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{t('controlPlane.sidebar.brainEmpty')}</div>
        ) : (
          beliefs.map((b) => (
            <button key={b.id} type="button" onClick={() => openArtifact('belief', b.id)}
              className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5 text-left hover:border-primary">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="flex-1 truncate text-xs font-semibold text-foreground">{b.title}</span>
              <span className="text-[10px] text-muted-foreground">{t('controlPlane.brain.view')}</span>
            </button>
          ))
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.brain.decisionsTitle')}</div>
        {decisions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-2.5 text-center text-xs text-muted-foreground">{t('controlPlane.brain.decisionsEmpty')}</div>
        ) : (
          decisions.map((d) => (
            <div key={d.id} className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5">
              <Gavel className="h-4 w-4 text-primary" />
              <span className="flex-1 truncate text-xs font-semibold text-foreground">{d.title}</span>
              <span className="text-[10px] text-muted-foreground">{d.status}</span>
            </div>
          ))
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.brain.rulesTitle')}</div>
        {rules.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-2.5 text-center text-xs text-muted-foreground">{t('controlPlane.brain.rulesEmpty')}</div>
        ) : (
          rules.map((r) => (
            <div key={r.id} className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5">
              <ListChecks className="h-4 w-4 text-primary" />
              <span className="flex-1 truncate text-xs font-semibold text-foreground">{r.title}</span>
              <span className="text-[10px] text-muted-foreground">{r.status}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
