// frontend/src/components/common/RoleGate.tsx
'use client'

import type { ReactNode } from 'react'
import { useRole, type WorkspaceRole } from '@/lib/hooks/use-role'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RoleGate({
  allow,
  mode = 'hide',
  requireCompanyWorkspace = false,
  children,
}: {
  allow: WorkspaceRole[]
  mode?: 'hide' | 'disable'
  requireCompanyWorkspace?: boolean
  children: ReactNode
}) {
  const { role, isOwner, isCompanyWorkspace } = useRole()
  const { t } = useTranslation()

  // owner ⊇ admin: an owner satisfies an admin-only gate even when the allow
  // list only spells out 'admin' explicitly.
  const roleAllowed = !!role && (allow.includes(role) || (isOwner && allow.includes('admin')))
  const allowed = roleAllowed && (!requireCompanyWorkspace || isCompanyWorkspace)

  if (allowed) return <>{children}</>
  if (mode === 'hide') return null

  return (
    <span
      aria-disabled="true"
      className="opacity-50 pointer-events-none"
      title={t('roles.adminOnly')}
    >
      {children}
    </span>
  )
}
