import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { WelcomeStep } from './WelcomeStep'

describe('WelcomeStep', () => {
  it('renders the personal-workspace welcome copy and both actions', () => {
    render(<WelcomeStep onCreateCompany={vi.fn()} onSkip={vi.fn()} />)
    expect(screen.getByText('onboarding.welcomePersonalTitle')).toBeDefined()
    expect(screen.getByText('onboarding.createCompanyCta')).toBeDefined()
    expect(screen.getByText('onboarding.skipCta')).toBeDefined()
  })

  it('skip is a first-class action, not hidden behind the company flow', () => {
    const onSkip = vi.fn()
    render(<WelcomeStep onCreateCompany={vi.fn()} onSkip={onSkip} />)
    fireEvent.click(screen.getByText('onboarding.skipCta'))
    expect(onSkip).toHaveBeenCalled()
  })

  it('create-company advances without creating anything itself', () => {
    const onCreateCompany = vi.fn()
    render(<WelcomeStep onCreateCompany={onCreateCompany} onSkip={vi.fn()} />)
    fireEvent.click(screen.getByText('onboarding.createCompanyCta'))
    expect(onCreateCompany).toHaveBeenCalled()
  })
})
