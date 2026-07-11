// frontend/src/components/common/RequireRole.tsx
'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import type { ReactNode } from 'react'
import { useRole, type WorkspaceRole } from '@/lib/hooks/use-role'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

export function RequireRole({
  allow,
  children,
}: {
  allow: WorkspaceRole[]
  children: ReactNode
}) {
  const { role, isOwner } = useRole()
  const router = useRouter()
  const { toast } = useToast()
  const { t } = useTranslation()
  // owner ⊇ admin: an owner satisfies an admin-only gate even when the allow
  // list only spells out 'admin' explicitly (mirrors RoleGate's rule).
  const allowed = !!role && (allow.includes(role) || (isOwner && allow.includes('admin')))

  useEffect(() => {
    if (role && !allowed) {
      toast({ title: t('roles.accessDenied'), variant: 'destructive' })
      router.push('/notebooks')
    }
  }, [allowed, role, router, toast, t])

  if (!allowed) return null
  return <>{children}</>
}
