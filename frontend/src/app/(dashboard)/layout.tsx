'use client'

import { useAuth } from '@/lib/hooks/use-auth'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useVersionCheck } from '@/lib/hooks/use-version-check'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { ModalProvider } from '@/components/providers/ModalProvider'
import { CreateDialogsProvider } from '@/lib/hooks/use-create-dialogs'
import { CommandPalette } from '@/components/common/CommandPalette'
import { useRole } from '@/lib/hooks/use-role'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const { isAuthenticated, isLoading } = useAuth()
  const memberships = useAuthStore((s) => s.memberships)
  const activeWorkspaceId = useAuthStore((s) => s.activeWorkspaceId)
  const setActiveWorkspace = useAuthStore((s) => s.setActiveWorkspace)
  const { workspaceId } = useRole()
  const { toast } = useToast()
  const { t } = useTranslation()
  const router = useRouter()
  const [hasCheckedAuth, setHasCheckedAuth] = useState(false)

  // Check for version updates once per session
  useVersionCheck()

  useEffect(() => {
    // Mark that we've completed the initial auth check
    if (!isLoading) {
      setHasCheckedAuth(true)

      // Redirect to login if not authenticated
      if (!isAuthenticated) {
        // Store the current path to redirect back after login
        const currentPath = window.location.pathname + window.location.search
        sessionStorage.setItem('redirectAfterLogin', currentPath)
        router.push('/login')
        return
      }

      // Defensive only: a normal session always has activeWorkspaceId set by
      // setSession (the backend always names an active — Personal —
      // workspace). This guards a corrupted/partial persisted session, NOT a
      // first-run gate — there is intentionally no memberships.length === 0
      // redirect to /onboarding, because an authenticated user's memberships
      // list is never empty and onboarding must never be a forced gate.
      if (!activeWorkspaceId && memberships.length > 0) {
        setActiveWorkspace(memberships[0].workspace_id, memberships[0].role)
      } else if (workspaceId == null) {
        // Defense-in-depth backstop: because signup auto-provisions a personal
        // workspace, an authenticated user without an active workspace should
        // be unreachable in normal operation (the branch above already
        // recovers a persisted-but-unset active workspace whenever
        // memberships are available). There is intentionally no "has a
        // company" gate here - every workspace, personal or company,
        // satisfies this check. This keeps a user without an active
        // workspace out of scoped screens before a scoped API call can 403.
        toast({ title: t('roles.noWorkspace') })
        router.push('/onboarding')
      }
    }
  }, [isAuthenticated, isLoading, memberships, activeWorkspaceId, setActiveWorkspace, workspaceId, toast, t, router])

  // Show loading spinner during initial auth check or while loading
  if (isLoading || !hasCheckedAuth) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  // Don't render anything if not authenticated (during redirect)
  if (!isAuthenticated) {
    return null
  }

  return (
    <ErrorBoundary>
      <CreateDialogsProvider>
        {children}
        <ModalProvider />
        <CommandPalette />
      </CreateDialogsProvider>
    </ErrorBoundary>
  )
}
