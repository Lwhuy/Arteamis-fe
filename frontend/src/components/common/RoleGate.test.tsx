// frontend/src/components/common/RoleGate.test.tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RoleGate } from './RoleGate'
import { useAuthStore } from '@/lib/stores/auth-store'

function setRole(role: 'owner' | 'admin' | 'member' | null, kind: 'personal' | 'company' = 'company') {
  useAuthStore.setState({ role, activeWorkspaceId: 'workspace:A', workspaceName: 'Acme', workspaceKind: kind } as never)
}

describe('RoleGate', () => {
  beforeEach(() => setRole(null))

  it('renders children for an allowed role', () => {
    setRole('admin')
    render(<RoleGate allow={['owner', 'admin']}><button>Delete</button></RoleGate>)
    expect(screen.getByText('Delete')).toBeDefined()
  })

  it('hides children for a disallowed role (default mode)', () => {
    setRole('member')
    render(<RoleGate allow={['owner', 'admin']}><button>Delete</button></RoleGate>)
    expect(screen.queryByText('Delete')).toBeNull()
  })

  it('disable mode renders children but aria-disabled', () => {
    setRole('member')
    render(
      <RoleGate allow={['owner', 'admin']} mode="disable">
        <button>Delete</button>
      </RoleGate>,
    )
    const el = screen.getByText('Delete').parentElement as HTMLElement
    expect(el.getAttribute('aria-disabled')).toBe('true')
    expect(el.className).toContain('pointer-events-none')
  })

  it('owner passes an admin-only gate (owner ⊇ admin)', () => {
    setRole('owner')
    render(<RoleGate allow={['admin']}><span>Manage</span></RoleGate>)
    expect(screen.getByText('Manage')).toBeDefined()
  })

  it('requireCompanyWorkspace hides for a personal-workspace owner even though role passes', () => {
    setRole('owner', 'personal')
    render(
      <RoleGate allow={['owner', 'admin']} requireCompanyWorkspace>
        <button>Invite</button>
      </RoleGate>,
    )
    expect(screen.queryByText('Invite')).toBeNull()
  })

  it('requireCompanyWorkspace renders for a company-workspace admin', () => {
    setRole('admin', 'company')
    render(
      <RoleGate allow={['owner', 'admin']} requireCompanyWorkspace>
        <button>Invite</button>
      </RoleGate>,
    )
    expect(screen.getByText('Invite')).toBeDefined()
  })
})
