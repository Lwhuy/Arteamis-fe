'use client'

import { Check, Plus } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useSwitchWorkspace } from '@/lib/hooks/use-workspaces'
import { useTranslation } from '@/lib/hooks/use-translation'

export function WorkspaceSwitcher() {
  const { t } = useTranslation()
  const router = useRouter()
  const memberships = useAuthStore((s) => s.memberships)
  const activeWorkspaceId = useAuthStore((s) => s.activeWorkspaceId)
  const switchWorkspace = useSwitchWorkspace()

  // Literal keys (not template strings) so the i18n usage test can find them.
  const roleLabels: Record<string, string> = {
    owner: t('workspace.roleOwner'),
    admin: t('workspace.roleAdmin'),
    member: t('workspace.roleMember'),
  }

  return (
    <div role="listbox" aria-label={t('workspace.switchLabel')} className="flex flex-col gap-1">
      {memberships.map((m) => {
        const isActive = m.workspace_id === activeWorkspaceId
        const label = m.kind === 'personal' ? t('workspace.personalLabel') : m.name
        return (
          <button
            key={m.workspace_id}
            type="button"
            role="option"
            aria-selected={isActive}
            data-testid={`workspace-option-${m.workspace_id}`}
            disabled={switchWorkspace.isPending}
            onClick={() => {
              if (!isActive) switchWorkspace.mutate(m.workspace_id)
            }}
            className="flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
          >
            <span className="truncate">{label}</span>
            <span className="flex items-center gap-2">
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase">
                {roleLabels[m.role] ?? m.role}
              </span>
              {isActive && <Check className="h-4 w-4" aria-hidden />}
            </span>
          </button>
        )
      })}
      {!memberships.some((m) => m.kind === 'company') && (
        <p className="px-3 pt-1 text-[11px] text-muted-foreground">
          {t('workspace.createCompanyBanner')}
        </p>
      )}
      <button
        type="button"
        onClick={() => router.push('/onboarding')}
        className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-accent"
      >
        <Plus className="h-4 w-4" aria-hidden />
        {t('workspace.addCompanyCta')}
      </button>
    </div>
  )
}
