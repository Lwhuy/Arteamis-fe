'use client'

import { useTranslation } from '@/lib/hooks/use-translation'
import { AppShell } from '@/components/layout/AppShell'

export default function IntelligencePage() {
  const { t } = useTranslation()

  return (
    <AppShell>
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <div className="flex-1 min-w-0 flex flex-col p-4 md:p-6">
          <div className="mb-4 flex items-center justify-between gap-2">
            <h1 className="text-xl md:text-2xl font-bold">{t('intelligence.title')}</h1>
          </div>

          <div className="flex flex-1 flex-col items-center justify-center text-center gap-4">
            <span className="rounded-full border border-primary/30 bg-primary/10 px-4 py-1.5 text-sm font-medium uppercase tracking-wide text-primary">
              {t('intelligence.comingSoon.title')}
            </span>
            <p className="max-w-md text-sm text-muted-foreground">
              {t('intelligence.comingSoon.description')}
            </p>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
