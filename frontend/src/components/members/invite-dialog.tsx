'use client'

import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCreateInvitation } from '@/lib/hooks/use-invitations'
import { useProjects } from '@/lib/hooks/use-projects'
import { useTranslation } from '@/lib/hooks/use-translation'

interface InviteDialogProps {
  workspaceId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  // Test/seed hook: render the copy-link fallback body directly.
  initialShareUrl?: string
}

export function InviteDialog({ workspaceId, open, onOpenChange, initialShareUrl }: InviteDialogProps) {
  const { t } = useTranslation()
  const { data: projects } = useProjects()
  const createInvitation = useCreateInvitation(workspaceId)

  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'admin' | 'member'>('member')
  const [scopeToProject, setScopeToProject] = useState(false)
  const [projectId, setProjectId] = useState<string>('')
  const [shareUrl, setShareUrl] = useState<string | undefined>(initialShareUrl)
  const [copied, setCopied] = useState(false)

  // Dialogs don't auto-reset; the parent clears state on close (frontend AGENTS.md).
  const reset = () => {
    setEmail('')
    setRole('member')
    setScopeToProject(false)
    setProjectId('')
    setShareUrl(undefined)
    setCopied(false)
  }

  const handleClose = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }

  const handleSubmit = async () => {
    const res = await createInvitation.mutateAsync({
      email,
      role,
      project_id: scopeToProject && projectId ? projectId : null,
    })
    if (!res.email_sent && res.share_url) {
      setShareUrl(res.share_url)
    } else {
      handleClose(false)
    }
  }

  const handleCopy = async () => {
    if (shareUrl) {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{shareUrl ? t('invitations.copyLinkTitle') : t('invitations.title')}</DialogTitle>
        </DialogHeader>

        {shareUrl ? (
          <div className="space-y-3">
            <Input readOnly value={shareUrl} aria-label={t('invitations.copyLinkTitle')} />
            <Button type="button" onClick={handleCopy}>
              {copied ? t('invitations.copied') : t('invitations.copyLink')}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="invite-email">{t('invitations.emailLabel')}</Label>
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>{t('invitations.roleLabel')}</Label>
              <Select value={role} onValueChange={(v) => setRole(v as 'admin' | 'member')}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">{t('invitations.roleAdmin')}</SelectItem>
                  <SelectItem value="member">{t('invitations.roleMember')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={scopeToProject}
                  onChange={(e) => setScopeToProject(e.target.checked)}
                />
                {t('invitations.projectScopeToggle')}
              </label>
              {scopeToProject && (
                <Select value={projectId} onValueChange={setProjectId}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('invitations.projectLabel')} />
                  </SelectTrigger>
                  <SelectContent>
                    {(projects ?? []).map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                onClick={handleSubmit}
                disabled={!email || createInvitation.isPending}
              >
                {t('invitations.sendInvite')}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
