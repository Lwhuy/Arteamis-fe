'use client';
import { useTranslation } from '@/lib/hooks/use-translation';
import { LoopWidget } from './LoopWidget';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-bold text-foreground">{title}</h3>
      {children}
    </section>
  );
}
function Empty({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">{text}</div>;
}

export function ContextSidebar() {
  const { t } = useTranslation();
  return (
    <aside className="flex w-[372px] flex-shrink-0 flex-col gap-5 overflow-y-auto border-l border-border bg-background p-4">
      <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.sidebar.context')}</div>
      <Section title={t('controlPlane.sidebar.sources')}><Empty text={t('controlPlane.sidebar.sourcesEmpty')} /></Section>
      <Section title={t('controlPlane.sidebar.loop')}><LoopWidget currentIndex={0} /></Section>
      <Section title={t('controlPlane.sidebar.review')}><Empty text={t('controlPlane.sidebar.reviewEmpty')} /></Section>
      <Section title={t('controlPlane.sidebar.brain')}><Empty text={t('controlPlane.sidebar.brainEmpty')} /></Section>
    </aside>
  );
}
