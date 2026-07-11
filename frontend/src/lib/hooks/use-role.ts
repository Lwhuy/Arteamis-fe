// frontend/src/lib/hooks/use-role.ts
'use client'

import { useAuthStore } from '@/lib/stores/auth-store'

export type WorkspaceRole = 'owner' | 'admin' | 'member'
export type WorkspaceKind = 'personal' | 'company'

export function useRole() {
  const role = useAuthStore((s) => s.role) as WorkspaceRole | null
  const workspaceId = useAuthStore((s) => s.activeWorkspaceId) // P2's field, not a new one
  const workspaceName = useAuthStore((s) => s.workspaceName)
  const workspaceKind = useAuthStore((s) => s.workspaceKind)

  const can = (...roles: WorkspaceRole[]) => !!role && roles.includes(role)

  return {
    role,
    workspaceId,
    workspaceName,
    workspaceKind,
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin', // owner ⊇ admin
    isMember: role === 'member',
    isPersonalWorkspace: workspaceKind === 'personal',
    isCompanyWorkspace: workspaceKind === 'company',
    can, // can('owner', 'admin')
  }
}
