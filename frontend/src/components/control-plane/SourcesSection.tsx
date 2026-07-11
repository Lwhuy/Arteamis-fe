'use client';
import { FileText } from 'lucide-react';
import { useRecentSources } from '@/lib/hooks/use-sources';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

export function SourcesSection() {
  const { t } = useTranslation();
  const { data, isLoading } = useRecentSources();
  const { openArtifact } = useArtifact();
  // sourcesApi.list resolves to a plain SourceListResponse[] (no pagination wrapper).
  const sources = data ?? [];

  if (isLoading) {
    return <div className="text-xs text-muted-foreground">{t('common.loading')}</div>;
  }

  if (sources.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
        {t('controlPlane.sidebar.sourcesEmpty')}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {sources.map((s) => (
        <button
          key={s.id}
          type="button"
          onClick={() => openArtifact('source', s.id)}
          className="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5 text-left hover:border-primary"
        >
          <span className="grid h-6 w-6 flex-shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
            <FileText className="h-3.5 w-3.5" />
          </span>
          <span className="flex-1 truncate text-xs font-semibold text-foreground">
            {s.title ?? t('controlPlane.artifact.title')}
          </span>
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[10px] font-bold',
              s.visibility === 'company' ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground',
            )}
          >
            {t(s.visibility === 'company' ? 'controlPlane.badge.company' : 'controlPlane.badge.private')}
          </span>
        </button>
      ))}
    </div>
  );
}
