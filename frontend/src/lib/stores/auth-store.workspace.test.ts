import { describe, it, expect, beforeEach } from 'vitest'
import { useAuthStore } from './auth-store'

describe('auth-store workspace slice', () => {
  beforeEach(() => {
    useAuthStore.setState({
      token: null,
      memberships: [],
      activeWorkspaceId: null,
      role: null,
    })
  })

  it('applyToken swaps token, activeWorkspaceId and role', () => {
    useAuthStore.getState().applyToken({
      access_token: 'scoped-token',
      token_type: 'bearer',
      active_workspace_id: 'workspace:acme',
      role: 'owner',
    })
    const s = useAuthStore.getState()
    expect(s.token).toBe('scoped-token')
    expect(s.activeWorkspaceId).toBe('workspace:acme')
    expect(s.role).toBe('owner')
  })

  it('applyToken derives workspaceName/workspaceKind for the new active workspace from memberships', () => {
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'member' },
      ],
    })
    useAuthStore.getState().applyToken({
      access_token: 'scoped-token',
      token_type: 'bearer',
      active_workspace_id: 'workspace:acme',
      role: 'member',
    })
    const s = useAuthStore.getState()
    expect(s.workspaceName).toBe('Acme')
    expect(s.workspaceKind).toBe('company')
  })

  it('setSession stores memberships and the given activeWorkspaceId (always the personal workspace on login)', () => {
    useAuthStore.getState().setSession({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'member' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    const s = useAuthStore.getState()
    expect(s.memberships).toHaveLength(2)
    expect(s.activeWorkspaceId).toBe('workspace:p1')
    expect(s.role).toBe('owner')
    expect(s.workspaceName).toBe('Personal')
    expect(s.workspaceKind).toBe('personal')
  })

  it('setActiveWorkspace derives workspaceName/workspaceKind for the newly-active workspace', () => {
    useAuthStore.setState({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'admin' },
      ],
    })
    useAuthStore.getState().setActiveWorkspace('workspace:acme', 'admin')
    const s = useAuthStore.getState()
    expect(s.activeWorkspaceId).toBe('workspace:acme')
    expect(s.role).toBe('admin')
    expect(s.workspaceName).toBe('Acme')
    expect(s.workspaceKind).toBe('company')
  })

  it('hasCompany is false when only the personal workspace is present', () => {
    useAuthStore.getState().setSession({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    expect(useAuthStore.getState().hasCompany()).toBe(false)
  })

  it('hasCompany is true once a company membership exists', () => {
    useAuthStore.getState().setSession({
      memberships: [
        { workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' },
        { workspace_id: 'workspace:acme', name: 'Acme', slug: 'acme', kind: 'company', role: 'owner' },
      ],
      activeWorkspaceId: 'workspace:p1',
    })
    expect(useAuthStore.getState().hasCompany()).toBe(true)
  })
})
