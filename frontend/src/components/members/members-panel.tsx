'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { InviteDialog } from './invite-dialog'
import { useInvitations, useMembers, useRevokeInvitation } from '@/lib/hooks/use-invitations'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useAuthStore } from '@/lib/stores/auth-store'

interface MembersPanelProps {
  workspaceId: string
}

export function MembersPanel({ workspaceId }: MembersPanelProps) {
  const { t } = useTranslation()
  const role = useAuthStore((s) => s.role)
  const canManage = role === 'owner' || role === 'admin'

  const { data: members } = useMembers(workspaceId)
  const { data: invitations } = useInvitations(workspaceId, 'pending')
  const revoke = useRevokeInvitation(workspaceId)
  const [inviteOpen, setInviteOpen] = useState(false)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('invitations.members')}</h2>
        {canManage && (
          <Button onClick={() => setInviteOpen(true)}>{t('invitations.inviteButton')}</Button>
        )}
      </div>

      <ul className="space-y-2">
        {(members ?? []).map((m) => (
          <li key={m.user_id} className="flex items-center justify-between rounded border p-3">
            <span>{m.display_name || m.email}</span>
            <Badge>{m.role}</Badge>
          </li>
        ))}
      </ul>

      {canManage && (invitations ?? []).length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-muted-foreground">{t('invitations.pending')}</h3>
          <ul className="space-y-2">
            {(invitations ?? []).map((inv) => (
              <li key={inv.id} className="flex items-center justify-between rounded border p-3">
                <span className="flex items-center gap-2">
                  {inv.email}
                  <Badge>{inv.role}</Badge>
                  {inv.project_name && <Badge>{inv.project_name}</Badge>}
                </span>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="destructive" size="sm">
                      {t('invitations.revoke')}
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>{t('invitations.revoke')}</AlertDialogTitle>
                      <AlertDialogDescription>{t('invitations.revokeConfirm')}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
                      <AlertDialogAction onClick={() => revoke.mutate(inv.id)}>
                        {t('invitations.revoke')}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </li>
            ))}
          </ul>
        </div>
      )}

      <InviteDialog workspaceId={workspaceId} open={inviteOpen} onOpenChange={setInviteOpen} />
    </div>
  )
}
