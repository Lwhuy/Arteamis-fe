import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CompanyStep } from './CompanyStep'

const mutate = vi.fn()
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useCreateWorkspace: () => ({ mutate, isPending: false }),
}))

describe('CompanyStep', () => {
  it('renders the workspace name field (i18n keys via mocked t)', () => {
    render(<CompanyStep onCreated={vi.fn()} />)
    expect(screen.getByText('workspace.nameLabel')).toBeDefined()
    expect(screen.getByText('onboarding.createCompanyCta')).toBeDefined()
  })

  it('submits the trimmed name through useCreateWorkspace', () => {
    render(<CompanyStep onCreated={vi.fn()} />)
    fireEvent.change(screen.getByPlaceholderText('workspace.namePlaceholder'), {
      target: { value: '  Acme  ' },
    })
    fireEvent.submit(screen.getByTestId('company-step-form'))
    expect(mutate).toHaveBeenCalledWith(
      { name: 'Acme', slug: undefined },
      expect.anything(),
    )
  })
})
