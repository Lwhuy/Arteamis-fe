import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { useAuthStore } from '@/lib/stores/auth-store'

const mutate = vi.fn()
const push = vi.fn()
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useSwitchWorkspace: () => ({ mutate, isPending: false }),
}))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))

describe('WorkspaceSwitcher', () => {
  beforeEach(() => {
    mutate.mockClear()
    push.mockClear()
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'member' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
  })

  it('lists the personal workspace and companies with role badges', () => {
    render(<WorkspaceSwitcher />)
    expect(screen.getByText('workspace.personalLabel')).toBeDefined()
    expect(screen.getByText('Acme')).toBeDefined()
    expect(screen.getByText('workspace.roleMember')).toBeDefined()
  })

  it('switches when a different workspace is selected', () => {
    render(<WorkspaceSwitcher />)
    fireEvent.click(screen.getByTestId('workspace-option-workspace:acme'))
    expect(mutate).toHaveBeenCalledWith('workspace:acme')
  })

  it('does not switch when the active workspace is selected', () => {
    render(<WorkspaceSwitcher />)
    fireEvent.click(screen.getByTestId('workspace-option-workspace:p1'))
    expect(mutate).not.toHaveBeenCalled()
  })

  it('exposes a "create a company" entry that navigates to /onboarding', () => {
    render(<WorkspaceSwitcher />)
    fireEvent.click(screen.getByText('workspace.addCompanyCta'))
    expect(push).toHaveBeenCalledWith('/onboarding')
  })

  it('hides the "no company yet" banner once a company membership exists', () => {
    render(<WorkspaceSwitcher />)
    expect(screen.queryByText('workspace.createCompanyBanner')).toBeNull()
  })

  it('shows the "no company yet" banner when only the personal workspace is present', () => {
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.getByText('workspace.createCompanyBanner')).toBeDefined()
  })
})
