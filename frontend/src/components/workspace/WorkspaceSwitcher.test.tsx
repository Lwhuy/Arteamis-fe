import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
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

// The switcher is a dropdown: its options render only once the trigger is
// clicked. Open it before asserting on menu contents.
function openMenu() {
  fireEvent.click(screen.getByRole('button', { name: 'workspace.switchLabel' }))
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

  it('shows the active workspace on the trigger', () => {
    render(<WorkspaceSwitcher />)
    // Personal is active -> its label appears on the trigger without opening.
    expect(screen.getByText('workspace.personalLabel')).toBeDefined()
  })

  it('lists the personal workspace and companies with role badges once opened', () => {
    render(<WorkspaceSwitcher />)
    openMenu()
    const menu = within(screen.getByRole('listbox'))
    expect(menu.getByText('workspace.personalLabel')).toBeDefined()
    expect(menu.getByText('Acme')).toBeDefined()
    expect(menu.getByText('workspace.roleMember')).toBeDefined()
  })

  it('switches when a different workspace is selected', () => {
    render(<WorkspaceSwitcher />)
    openMenu()
    fireEvent.click(screen.getByTestId('workspace-option-workspace:acme'))
    expect(mutate).toHaveBeenCalledWith('workspace:acme')
  })

  it('does not switch when the active workspace is selected', () => {
    render(<WorkspaceSwitcher />)
    openMenu()
    fireEvent.click(screen.getByTestId('workspace-option-workspace:p1'))
    expect(mutate).not.toHaveBeenCalled()
  })

  it('exposes a "create a company" entry that navigates to /onboarding', () => {
    render(<WorkspaceSwitcher />)
    openMenu()
    fireEvent.click(screen.getByText('workspace.addCompanyCta'))
    expect(push).toHaveBeenCalledWith('/onboarding')
  })

  it('hides the "no company yet" hint once a company membership exists', () => {
    render(<WorkspaceSwitcher />)
    openMenu()
    expect(screen.queryByText('workspace.createCompanyBanner')).toBeNull()
  })

  it('shows the "no company yet" hint when only the personal workspace is present', () => {
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    render(<WorkspaceSwitcher />)
    openMenu()
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
    openMenu()
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
    openMenu()
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
    openMenu()
    expect(screen.queryByText('workspace.manageMembers')).toBeNull()
  })
})
