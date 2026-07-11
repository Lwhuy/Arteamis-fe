'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslation } from '@/lib/hooks/use-translation'
import { WelcomeStep } from './WelcomeStep'
import { CompanyStep } from './CompanyStep'

type Step = 'welcome' | 'company' | 'project'

export function OnboardingWizard() {
  const { t } = useTranslation()
  const router = useRouter()
  const [step, setStep] = useState<Step>('welcome')

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-lg flex-col justify-center px-4 py-12">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold">{t('onboarding.title')}</h1>
      </div>

      <div className="mb-5 flex items-center justify-center gap-2 text-xs font-medium">
        <span aria-current={step === 'welcome'}>{t('onboarding.stepWelcome')}</span>
        <span className="h-px w-8 bg-border" />
        <span aria-current={step === 'company'}>{t('onboarding.stepCompany')}</span>
        <span className="h-px w-8 bg-border" />
        <span aria-current={step === 'project'}>{t('onboarding.stepProject')}</span>
      </div>

      <div className="rounded-xl border p-6">
        {step === 'welcome' && (
          <WelcomeStep
            onCreateCompany={() => setStep('company')}
            onSkip={() => router.push('/notebooks')}
          />
        )}
        {step === 'company' && (
          <>
            <h2 className="mb-4 text-lg font-medium">{t('onboarding.companyStepTitle')}</h2>
            {/* On create, the token is already workspace-scoped to the new
                company (useCreateWorkspace applied it). Advance to the P3
                project hand-off. */}
            <CompanyStep onCreated={() => setStep('project')} />
          </>
        )}
        {step === 'project' && (
          // P3 fills in the first-project step here. Until then, hand off to
          // the dashboard now that the company + owner token exist.
          <ProjectHandoff onDone={() => router.push('/notebooks')} />
        )}
      </div>
    </div>
  )
}

function ProjectHandoff({ onDone }: { onDone: () => void }) {
  // Immediately hand off — P3 replaces this with a real project-create step.
  onDone()
  return null
}
