'use client';
import { useScopeStore, type Scope } from '@/lib/stores/scope-store';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

export function ScopeSwitch() {
  const { t } = useTranslation();
  const scope = useScopeStore((s) => s.scope);
  const setScope = useScopeStore((s) => s.setScope);
  const opts: Scope[] = ['personal', 'company'];
  return (
    <div className="inline-flex rounded-lg border border-border bg-muted p-0.5" role="group">
      {opts.map((o) => (
        <button
          key={o}
          type="button"
          aria-pressed={scope === o}
          onClick={() => setScope(o)}
          className={cn(
            'rounded-md px-4 py-1.5 text-sm font-semibold text-muted-foreground transition-colors',
            scope === o && 'bg-background text-foreground shadow-sm',
          )}
        >
          {o === 'personal' ? t('controlPlane.personal') : t('controlPlane.company')}
        </button>
      ))}
    </div>
  );
}
