'use client';
import { Check } from 'lucide-react';
import { deriveLoopSteps, COMPANY_BOUNDARY_INDEX } from './loop-steps';
import { useTranslation } from '@/lib/hooks/use-translation';
import { cn } from '@/lib/utils';

export function LoopWidget({ currentIndex }: { currentIndex: number }) {
  const { t } = useTranslation();
  const steps = deriveLoopSteps(currentIndex);
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      {steps.map((s, i) => (
        <div key={s.id}>
          {i === COMPANY_BOUNDARY_INDEX && (
            <div className="my-2 text-center text-[10px] font-bold uppercase tracking-wide text-muted-foreground">
              {t('controlPlane.loop.boundary')}
            </div>
          )}
          <div className="flex items-center gap-3 py-1.5">
            <span
              className={cn(
                'grid h-5 w-5 place-items-center rounded-full border-2 text-[11px] font-bold',
                s.status === 'done' && 'border-green-600 bg-green-600 text-white',
                s.status === 'current' && 'border-primary bg-primary text-primary-foreground',
                s.status === 'later' && 'border-border text-muted-foreground',
              )}
            >
              {s.status === 'done' ? <Check className="h-3 w-3" /> : i + 1}
            </span>
            <span className={cn('text-xs', s.status === 'current' ? 'font-semibold text-foreground' : 'text-muted-foreground')}>
              {t(s.labelKey)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
