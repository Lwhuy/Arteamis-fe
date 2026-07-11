'use client'

import { useTranslation } from '@/lib/hooks/use-translation'
import { Button } from '@/components/ui/button'

export function WelcomeStep({
  onCreateCompany,
  onSkip,
}: {
  onCreateCompany: () => void
  onSkip: () => void
}) {
  const { t } = useTranslation()

  return (
    <div className="space-y-5 text-center">
      <div>
        <h2 className="text-lg font-medium">{t('onboarding.welcomePersonalTitle')}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t('onboarding.welcomePersonalBody')}</p>
      </div>
      <div className="flex flex-col gap-2">
        <Button type="button" className="w-full" onClick={onCreateCompany}>
          {t('onboarding.createCompanyCta')}
        </Button>
        <Button type="button" variant="ghost" className="w-full" onClick={onSkip}>
          {t('onboarding.skipCta')}
        </Button>
      </div>
    </div>
  )
}
