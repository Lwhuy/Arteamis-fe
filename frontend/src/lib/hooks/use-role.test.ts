// frontend/src/lib/hooks/use-role.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRole } from './use-role'
import { useAuthStore } from '@/lib/stores/auth-store'

function setRole(role: 'owner' | 'admin' | 'member' | null, kind: 'personal' | 'company' | null = 'company') {
  useAuthStore.setState({
    activeWorkspaceId: role ? 'workspace:A' : null, // P2's existing field, not a new one
    workspaceName: role ? 'Acme' : null,
    workspaceKind: role ? kind : null,
    role,
  } as Partial<ReturnType<typeof useAuthStore.getState>>)
}

describe('useRole', () => {
  beforeEach(() => setRole(null))

  it('owner is owner and admin (owner ⊇ admin)', () => {
    setRole('owner')
    const { result } = renderHook(() => useRole())
    expect(result.current.isOwner).toBe(true)
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.isMember).toBe(false)
    expect(result.current.can('owner', 'admin')).toBe(true)
  })

  it('admin is admin but not owner', () => {
    setRole('admin')
    const { result } = renderHook(() => useRole())
    expect(result.current.isOwner).toBe(false)
    expect(result.current.isAdmin).toBe(true)
    expect(result.current.can('owner', 'admin')).toBe(true)
    expect(result.current.can('owner')).toBe(false)
  })

  it('member is only member', () => {
    setRole('member')
    const { result } = renderHook(() => useRole())
    expect(result.current.isAdmin).toBe(false)
    expect(result.current.isMember).toBe(true)
    expect(result.current.can('owner', 'admin')).toBe(false)
    expect(result.current.can('member')).toBe(true)
  })

  it('no role → nothing granted, workspace null', () => {
    const { result } = renderHook(() => useRole())
    expect(result.current.role).toBeNull()
    expect(result.current.workspaceId).toBeNull()
    expect(result.current.isAdmin).toBe(false)
    expect(result.current.can('member')).toBe(false)
  })

  it('surfaces workspaceName', () => {
    setRole('owner')
    const { result } = renderHook(() => useRole())
    expect(result.current.workspaceName).toBe('Acme')
  })

  it('a personal workspace owner is isPersonalWorkspace, not isCompanyWorkspace', () => {
    setRole('owner', 'personal')
    const { result } = renderHook(() => useRole())
    expect(result.current.isPersonalWorkspace).toBe(true)
    expect(result.current.isCompanyWorkspace).toBe(false)
  })

  it('a company workspace member is isCompanyWorkspace, not isPersonalWorkspace', () => {
    setRole('member', 'company')
    const { result } = renderHook(() => useRole())
    expect(result.current.isCompanyWorkspace).toBe(true)
    expect(result.current.isPersonalWorkspace).toBe(false)
  })
})
