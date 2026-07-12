'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { cn } from '@/lib/utils'
import { Logo } from '@/components/common/Logo'
import { Button } from '@/components/ui/button'
import { WorkspaceSwitcher } from '@/components/workspace/WorkspaceSwitcher'
import { RoleGate } from '@/components/common/RoleGate'
import { useAuth } from '@/lib/hooks/use-auth'
import { useSidebarStore } from '@/lib/stores/sidebar-store'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { ThemeToggle } from '@/components/common/ThemeToggle'
import { LanguageToggle } from '@/components/common/LanguageToggle'
import type { TFunction } from 'i18next'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Separator } from '@/components/ui/separator'
import {
  Book,
  Search,
  Bot,
  LogOut,
  ChevronLeft,
  Menu,
  FileText,
  Command,
  Plug,
  Users,
  Network,
  Sparkles,
} from 'lucide-react'

const getNavigation = (t: TFunction) => [
  {
    title: t('controlPlane.launcher'),
    items: [
      { name: t('controlPlane.launcher'), href: '/control-plane', icon: Sparkles },
    ],
  },
  {
    title: t('navigation.collect'),
    items: [
      { name: t('navigation.sources'), href: '/sources', icon: FileText },
      { name: t('navigation.connections'), href: '/connections', icon: Plug },
    ],
  },
  {
    title: t('navigation.process'),
    items: [
      { name: t('navigation.projects'), href: '/projects', icon: Book },
      { name: t('navigation.askAndSearch'), href: '/search', icon: Search },
      { name: t('navigation.intelligence'), href: '/intelligence', icon: Network },
    ],
  },
  {
    title: t('navigation.manage'),
    items: [
      { name: t('navigation.models'), href: '/settings/api-keys', icon: Bot },
      { name: t('navigation.manageMembers'), href: '/settings/members', icon: Users },
    ],
  },
] as const

export function AppSidebar() {
  const { t } = useTranslation()
  const navigation = getNavigation(t)
  const pathname = usePathname()
  const { logout } = useAuth()
  const { isCollapsed, toggleCollapse } = useSidebarStore()

  const [isMac, setIsMac] = useState(true) // Default to Mac for SSR

  // Detect platform for keyboard shortcut display
  useEffect(() => {
    setIsMac(navigator.platform.toLowerCase().includes('mac'))
  }, [])

  // The command palette listens for a global Cmd/Ctrl+K keydown; re-dispatch it
  // so the footer shortcut button opens the same palette.
  const openCommandPalette = () => {
    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'k', metaKey: true, ctrlKey: true, bubbles: true })
    )
  }

  const quickActionsButton = (
    <Button
      variant="ghost"
      size="icon"
      onClick={openCommandPalette}
      aria-label={t('common.quickActions')}
      className="h-9 w-full sidebar-menu-item text-sidebar-foreground"
    >
      <Command className="h-[1.2rem] w-[1.2rem]" />
    </Button>
  )

  const signOutButton = (
    <Button
      variant="ghost"
      size="icon"
      onClick={logout}
      aria-label={t('common.signOut')}
      className="h-9 w-full sidebar-menu-item text-sidebar-foreground"
    >
      <LogOut className="h-[1.2rem] w-[1.2rem]" />
    </Button>
  )

  return (
    <TooltipProvider delayDuration={0}>
      <div
        className={cn(
          'app-sidebar flex h-full flex-col bg-sidebar border-sidebar-border border-r transition-all duration-300',
          isCollapsed ? 'w-16' : 'w-64'
        )}
      >
        <div
          className={cn(
            'flex h-16 items-center group',
            isCollapsed ? 'justify-center px-2' : 'justify-between px-4'
          )}
        >
          {isCollapsed ? (
            <div className="relative flex items-center justify-center w-full">
              <Logo
                aria-label={t('common.appName')}
                className="h-8 w-8 text-sidebar-foreground transition-opacity group-hover:opacity-0"
              />
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="absolute text-sidebar-foreground hover:bg-sidebar-accent opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <Menu className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <Logo aria-label={t('common.appName')} className="h-8 w-8 text-sidebar-foreground" />
                <span className="text-base font-medium text-sidebar-foreground">
                  {t('common.appName')}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleCollapse}
                className="text-sidebar-foreground hover:bg-sidebar-accent"
                data-testid="sidebar-toggle"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
            </>
          )}
        </div>

        <nav
          className={cn(
            'flex-1 space-y-1 py-4',
            isCollapsed ? 'px-2' : 'px-3'
          )}
        >
          {navigation.map((section, index) => {
            const sectionNode = (
              <div key={section.title}>
                {index > 0 && (
                  <Separator className="my-3" />
                )}
                <div className="space-y-1">
                  {!isCollapsed && (
                    <h3 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-sidebar-foreground/60">
                      {section.title}
                    </h3>
                  )}

                  {section.items.map((item) => {
                    const isActive = pathname?.startsWith(item.href) || false
                    const button = (
                      <Button
                        variant={isActive ? 'secondary' : 'ghost'}
                        className={cn(
                          'w-full gap-3 text-sidebar-foreground sidebar-menu-item',
                          isActive && 'bg-sidebar-accent text-sidebar-accent-foreground',
                          isCollapsed ? 'justify-center px-2' : 'justify-start'
                        )}
                      >
                        <item.icon className="h-4 w-4" />
                        {!isCollapsed && <span>{item.name}</span>}
                      </Button>
                    )

                    const linkNode = isCollapsed ? (
                      <Tooltip key={item.name}>
                        <TooltipTrigger asChild>
                          <Link href={item.href}>
                            {button}
                          </Link>
                        </TooltipTrigger>
                        <TooltipContent side="right">{item.name}</TooltipContent>
                      </Tooltip>
                    ) : (
                      <Link key={item.name} href={item.href}>
                        {button}
                      </Link>
                    )

                    // "Manage members" has no meaning for a solo tenant - gate
                    // it (on top of the section-level role gate below) to
                    // company workspaces only.
                    if (item.name === t('navigation.manageMembers')) {
                      return (
                        <RoleGate key={item.name} allow={['owner', 'admin']} requireCompanyWorkspace>
                          {linkNode}
                        </RoleGate>
                      )
                    }

                    return linkNode
                  })}
                </div>
              </div>
            )

            // Manage is owner/admin-only (true in a personal workspace too,
            // since its sole member is always "owner" - this is a role gate,
            // not a kind gate).
            if (section.title === t('navigation.manage')) {
              return (
                <RoleGate key={section.title} allow={['owner', 'admin']}>
                  {sectionNode}
                </RoleGate>
              )
            }
            return sectionNode
          })}
        </nav>

        <div
          className={cn(
            'border-t border-sidebar-border p-3 space-y-2',
            isCollapsed && 'px-2'
          )}
        >
          {/* Workspace / company switcher */}
          <WorkspaceSwitcher collapsed={isCollapsed} />

          {/* Compact action row: quick actions, theme, language, sign out */}
          {isCollapsed ? (
            <div className="flex flex-col items-center gap-1">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="w-full">{quickActionsButton}</div>
                </TooltipTrigger>
                <TooltipContent side="right">
                  {t('common.quickActions')} {isMac ? '⌘K' : 'Ctrl+K'}
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="w-full">
                    <ThemeToggle iconOnly />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right">{t('common.theme')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="w-full">
                    <LanguageToggle iconOnly />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right">{t('common.language')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="w-full">{signOutButton}</div>
                </TooltipTrigger>
                <TooltipContent side="right">{t('common.signOut')}</TooltipContent>
              </Tooltip>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex-1">{quickActionsButton}</div>
                </TooltipTrigger>
                <TooltipContent side="top">
                  {t('common.quickActions')} {isMac ? '⌘K' : 'Ctrl+K'}
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex-1">
                    <ThemeToggle iconOnly />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top">{t('common.theme')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex-1">
                    <LanguageToggle iconOnly />
                  </div>
                </TooltipTrigger>
                <TooltipContent side="top">{t('common.language')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div className="flex-1">{signOutButton}</div>
                </TooltipTrigger>
                <TooltipContent side="top">{t('common.signOut')}</TooltipContent>
              </Tooltip>
            </div>
          )}
        </div>
      </div>
    </TooltipProvider>
  )
}
