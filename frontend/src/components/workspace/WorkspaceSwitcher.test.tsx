import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useRole } from '@/lib/hooks/use-role'

const mutate = vi.fn()
const push = vi.fn()
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useSwitchWorkspace: () => ({ mutate, isPending: false }),
}))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/lib/hooks/use-role', () => ({ useRole: vi.fn() }))

function mockRole(role: 'owner' | 'admin' | 'member', kind: 'personal' | 'company') {
  vi.mocked(useRole).mockReturnValue({
    role,
    isAdmin: role === 'owner' || role === 'admin',
    isOwner: role === 'owner',
    isCompanyWorkspace: kind === 'company',
    isPersonalWorkspace: kind === 'personal',
    can: (...roles: Array<'owner' | 'admin' | 'member'>) => roles.includes(role),
  } as unknown as ReturnType<typeof useRole>)
}

describe('WorkspaceSwitcher', () => {
  beforeEach(() => {
    mutate.mockClear()
    push.mockClear()
    // Default role for the pre-existing (P2) switching-behavior tests below,
    // which don't care about the company-only "Manage members" gating.
    mockRole('admin', 'company')
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

describe('WorkspaceSwitcher company-only gating', () => {
  it('shows "Manage members" for a company-workspace admin', () => {
    mockRole('admin', 'company')
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'admin' },
      ],
      activeWorkspaceId: 'workspace:acme',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.getByText('workspace.manageMembers')).toBeDefined()
  })

  it('hides "Manage members" for a personal-workspace owner', () => {
    mockRole('owner', 'personal')
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.queryByText('workspace.manageMembers')).toBeNull()
  })

  it('hides "Manage members" for a company-workspace member', () => {
    mockRole('member', 'company')
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'member' },
      ],
      activeWorkspaceId: 'workspace:acme',
    })
    render(<WorkspaceSwitcher />)
    expect(screen.queryByText('workspace.manageMembers')).toBeNull()
  })
})
