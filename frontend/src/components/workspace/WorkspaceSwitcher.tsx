'use client'

import { useEffect, useRef, useState } from 'react'
import { Check, Plus, ChevronsUpDown, Building2, Users } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useSwitchWorkspace } from '@/lib/hooks/use-workspaces'
import { useTranslation } from '@/lib/hooks/use-translation'
import { RoleGate } from '@/components/common/RoleGate'
import { cn } from '@/lib/utils'

interface WorkspaceSwitcherProps {
  /** Render the trigger as an icon-only button (collapsed sidebar). */
  collapsed?: boolean
}

/**
 * Account/workspace switcher shown in the sidebar footer. The trigger shows the
 * active workspace; the menu (opening upward) lists every workspace and offers a
 * single "Create a company" action, so the create-company prompt is contextual
 * instead of permanently occupying the top of the sidebar.
 */
export function WorkspaceSwitcher({ collapsed = false }: WorkspaceSwitcherProps) {
  const { t } = useTranslation()
  const router = useRouter()
  const memberships = useAuthStore((s) => s.memberships)
  const activeWorkspaceId = useAuthStore((s) => s.activeWorkspaceId)
  const switchWorkspace = useSwitchWorkspace()

  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Literal keys (not template strings) so the i18n usage test can find them.
  const roleLabels: Record<string, string> = {
    owner: t('workspace.roleOwner'),
    admin: t('workspace.roleAdmin'),
    member: t('workspace.roleMember'),
  }

  const active = memberships.find((m) => m.workspace_id === activeWorkspaceId)
  const activeLabel = active
    ? active.kind === 'personal'
      ? t('workspace.personalLabel')
      : active.name
    : t('workspace.personalLabel')
  const hasCompany = memberships.some((m) => m.kind === 'company')

  // Close on outside click / Escape (the controlled menu has no portal).
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const handleSelect = (workspaceId: string) => {
    if (workspaceId !== activeWorkspaceId) switchWorkspace.mutate(workspaceId)
    setOpen(false)
  }

  const handleCreateCompany = () => {
    setOpen(false)
    router.push('/onboarding')
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('workspace.switchLabel')}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-2 rounded-md py-2 text-sm text-sidebar-foreground hover:bg-sidebar-accent',
          collapsed ? 'justify-center px-0' : 'px-2'
        )}
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-primary/15 text-primary">
          <Building2 className="h-4 w-4" aria-hidden />
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 truncate text-left font-medium">{activeLabel}</span>
            {active && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
                {roleLabels[active.role] ?? active.role}
              </span>
            )}
            <ChevronsUpDown className="h-4 w-4 shrink-0 text-sidebar-foreground/50" aria-hidden />
          </>
        )}
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={t('workspace.switchLabel')}
          className={cn(
            'absolute bottom-full z-50 mb-1 min-w-56 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md',
            collapsed ? 'left-0' : 'left-0 right-0'
          )}
        >
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
                onClick={() => handleSelect(m.workspace_id)}
                className="flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
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

          <RoleGate allow={['owner', 'admin']} requireCompanyWorkspace>
            <a
              href="/settings/members"
              className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent"
            >
              <Users className="h-4 w-4" aria-hidden />
              {t('workspace.manageMembers')}
            </a>
          </RoleGate>

          <div className="my-1 h-px bg-border" role="separator" />

          <button
            type="button"
            onClick={handleCreateCompany}
            className="flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent"
          >
            <Plus className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span className="flex min-w-0 flex-col">
              <span>{t('workspace.addCompanyCta')}</span>
              {!hasCompany && (
                <span className="text-[11px] text-muted-foreground">
                  {t('workspace.createCompanyBanner')}
                </span>
              )}
            </span>
          </button>
        </div>
      )}
    </div>
  )
}
