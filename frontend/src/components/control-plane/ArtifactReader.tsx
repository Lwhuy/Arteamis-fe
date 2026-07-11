'use client';
import { X } from 'lucide-react';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useSource } from '@/lib/hooks/use-sources';
import { MarkdownRenderer } from '@/components/ui/markdown-renderer';
import { useTranslation } from '@/lib/hooks/use-translation';
import { ProposeButton } from './ProposeButton';
import { LineagePanel } from './LineagePanel';

export function ArtifactReader() {
  const { t } = useTranslation();
  const { artifact, closeArtifact } = useArtifact();
  if (!artifact) return null;

  return (
    <aside className="flex w-[384px] flex-shrink-0 flex-col border-r border-border bg-muted/40">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          {t('controlPlane.artifact.title')}
        </span>
        <button type="button" aria-label={t('common.close')} onClick={closeArtifact} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      {artifact.type === 'source' ? <SourceArtifact id={artifact.id} loc={artifact.loc} /> : <LineagePanel id={artifact.id} />}
    </aside>
  );
}

function SourceArtifact({ id, loc }: { id: string; loc?: string }) {
  const { data, isLoading } = useSource(id);
  const { t } = useTranslation();
  if (isLoading) return <div className="p-4 text-sm text-muted-foreground">{t('common.loading')}</div>;
  if (!data) return <div className="p-4 text-sm text-muted-foreground">{t('controlPlane.artifact.notFound')}</div>;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-4 py-2">
        <div className="text-sm font-semibold text-foreground">{data.title}</div>
        {loc ? <div className="text-xs text-muted-foreground">{t('controlPlane.artifact.locator').replace('{loc}', loc)}</div> : null}
      </div>
      <div className="flex-1 overflow-y-auto p-4 text-sm">
        <MarkdownRenderer>{data.full_text ?? ''}</MarkdownRenderer>
        <div className="mt-4">
          <ProposeButton title={data.title ?? ''} body="" sourceSpans={[{ source_id: id, locator: loc }]} />
        </div>
      </div>
    </div>
  );
}
