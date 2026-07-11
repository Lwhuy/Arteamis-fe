'use client';
import { FileText } from 'lucide-react';
import { useBelief } from '@/lib/hooks/use-governance';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';

interface LineageSource {
  id: string;
  title: string;
  locator?: string;
}

interface LineageProvenanceRow {
  action: string;
  actor: string;
}

interface BeliefLineage {
  belief: { id: string; title: string };
  sources: LineageSource[];
  provenance: LineageProvenanceRow[];
  derived_work: unknown[];
  contradictions: unknown[];
}

export function LineagePanel({ id }: { id: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useBelief(id) as unknown as { data: BeliefLineage | undefined; isLoading: boolean };
  const { openArtifact } = useArtifact();
  if (isLoading || !data) return <div className="p-4 text-sm text-muted-foreground">{t('common.loading')}</div>;
  const { belief, sources, provenance } = data;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
      <div className="text-[11px] font-bold uppercase tracking-wide text-primary">{t('controlPlane.lineage.belief')}</div>
      <h2 className="mb-3 font-serif text-lg text-foreground">{belief.title}</h2>

      <div className="mb-4">
        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.lineage.sources')}</div>
        {sources.map((s) => (
          <button key={s.id} type="button" onClick={() => openArtifact('source', s.id, s.locator)}
            className="flex w-full items-center gap-2 border-b border-border py-2 text-left text-sm text-foreground hover:text-primary">
            <FileText className="h-4 w-4 text-muted-foreground" /> <span className="flex-1">{s.title}</span>
            {s.locator ? <span className="text-xs text-muted-foreground">{s.locator}</span> : null}
          </button>
        ))}
      </div>

      <div className="mb-4">
        <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.lineage.provenance')}</div>
        {provenance.map((p, i) => (
          <div key={i} className="border-b border-border py-2 text-sm text-foreground">{p.action} · {p.actor}</div>
        ))}
      </div>

      <div className="rounded-lg bg-muted/60 p-3">
        <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.lineage.contradiction')}</div>
        <div className="text-sm text-muted-foreground">{t('controlPlane.lineage.contradictionNone')}</div>
      </div>
    </div>
  );
}
