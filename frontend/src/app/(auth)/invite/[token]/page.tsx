'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { useInvitationPreview, useAcceptInvitation } from '@/lib/hooks/use-invitations'
import { useSwitchWorkspace } from '@/lib/hooks/use-workspaces'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useAuthStore } from '@/lib/stores/auth-store'

function statusOf(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}

export default function InvitePage() {
  const { t } = useTranslation()
  const router = useRouter()
  const params = useParams<{ token: string }>()
  const token = params?.token ?? ''

  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const [emailMismatch, setEmailMismatch] = useState(false)

  const { data, isLoading, isError, error } = useInvitationPreview(token)
  const accept = useAcceptInvitation()
  const switchWorkspace = useSwitchWorkspace()

  const nextUrl = `/invite/${token}`

  if (isLoading) {
    return <div className="p-8 text-center">{t('common.loading')}</div>
  }

  if (isError || !data) {
    // 410 (expired/revoked/used) or 404 -> the invitation cannot be accepted.
    const expired = statusOf(error) === 410 || statusOf(error) === 404
    return (
      <div className="mx-auto max-w-md p-8 text-center">
        <h1 className="mb-2 text-xl font-semibold">
          {expired ? t('invitations.expiredTitle') : t('common.error')}
        </h1>
        <p className="mb-4 text-muted-foreground">{t('invitations.expiredBody')}</p>
        <Button onClick={() => router.push('/login')}>{t('invitations.signInCta')}</Button>
      </div>
    )
  }

  const handleAccept = async () => {
    try {
      const res = await accept.mutateAsync(token)
      // Enter the workspace with a workspace-scoped token (P2's switch-workspace),
      // which internally applies the new token/role to the auth store.
      await switchWorkspace.mutateAsync(res.workspace_id)
      router.push('/projects')
    } catch (err) {
      // 403: the authenticated account's email doesn't match inv.email. The
      // generic toast (useAcceptInvitation's onError) already fires; surface a
      // clearer inline message specific to this case too.
      if (statusOf(err) === 403) {
        setEmailMismatch(true)
      }
    }
  }

  return (
    <div className="mx-auto max-w-md p-8 text-center">
      <h1 className="mb-2 text-xl font-semibold">{t('invitations.acceptTitle')}</h1>
      <p className="mb-1">{data.workspace_name}</p>
      {data.project_name && <p className="mb-1 text-muted-foreground">{data.project_name}</p>}
      <p className="mb-4 text-muted-foreground">{data.role}</p>

      {isAuthenticated ? (
        <div className="flex flex-col items-center gap-2">
          {emailMismatch && (
            <p className="text-sm text-destructive">{t('invitations.emailMismatch')}</p>
          )}
          <Button onClick={handleAccept} disabled={accept.isPending}>
            {t('invitations.acceptButton')}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <Button
            onClick={() =>
              router.push(
                `/signup?next=${encodeURIComponent(nextUrl)}&email=${encodeURIComponent(data.email)}`,
              )
            }
          >
            {t('invitations.createAccountCta')}
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              router.push(
                `/login?next=${encodeURIComponent(nextUrl)}&email=${encodeURIComponent(data.email)}`,
              )
            }
          >
            {t('invitations.signInCta')}
          </Button>
        </div>
      )}
    </div>
  )
}
