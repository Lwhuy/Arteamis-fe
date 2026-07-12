'use client';
import { useTranslation } from '@/lib/hooks/use-translation';
import { useScopeStore } from '@/lib/stores/scope-store';
import { useLoopProgress } from '@/lib/hooks/use-loop-progress';
import { LoopWidget } from './LoopWidget';
import { SourcesSection } from './SourcesSection';
import { ReviewInbox } from './ReviewInbox';
import { CompanyBrainSection } from './CompanyBrainSection';
import { WorkPackagesSection } from './WorkPackagesSection';

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
  const scope = useScopeStore((s) => s.scope);
  // Real governance state (proposals/beliefs/work-packages/traces), not a
  // hardcoded per-scope index. Workspace-global approximation, not per-item.
  const loopIndex = useLoopProgress();
  return (
    <aside className="flex w-[372px] flex-shrink-0 flex-col gap-5 overflow-y-auto border-l border-border bg-background p-4">
      <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{t('controlPlane.sidebar.context')}</div>
      {scope === 'personal' ? (
        <>
          <Section title={t('controlPlane.sidebar.sources')}><SourcesSection /></Section>
          <Section title={t('controlPlane.sidebar.loop')}><LoopWidget currentIndex={loopIndex} /></Section>
        </>
      ) : (
        <>
          <Section title={t('controlPlane.sidebar.review')}><ReviewInbox /></Section>
          <Section title={t('controlPlane.sidebar.loop')}><LoopWidget currentIndex={loopIndex} /></Section>
          <Section title={t('controlPlane.sidebar.brain')}><CompanyBrainSection /></Section>
          <Section title={t('controlPlane.sidebar.workPackages')}><WorkPackagesSection /></Section>
        </>
      )}
    </aside>
  );
}
