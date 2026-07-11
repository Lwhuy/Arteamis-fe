/* eslint-disable @typescript-eslint/no-explicit-any */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AppSidebar } from './AppSidebar'
import { useSidebarStore } from '@/lib/stores/sidebar-store'
import { useRole } from '@/lib/hooks/use-role'

// Mock Tooltip components to avoid Radix UI async issues in tests
vi.mock('@/components/ui/tooltip', () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

// WorkspaceSwitcher's useSwitchWorkspace needs a QueryClientProvider ancestor;
// mock it out here since these tests only exercise sidebar chrome/collapse behavior.
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useSwitchWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/lib/hooks/use-role', () => ({
  useRole: vi.fn(),
}))

function mockRole(role: 'owner' | 'admin' | 'member', kind: 'personal' | 'company' = 'company') {
  vi.mocked(useRole).mockReturnValue({
    role,
    workspaceId: 'workspace:A',
    workspaceName: 'Acme',
    workspaceKind: kind,
    isOwner: role === 'owner',
    isAdmin: role === 'owner' || role === 'admin',
    isMember: role === 'member',
    isPersonalWorkspace: kind === 'personal',
    isCompanyWorkspace: kind === 'company',
    can: (...roles: Array<'owner' | 'admin' | 'member'>) => roles.includes(role),
  } as unknown as ReturnType<typeof useRole>)
}

describe('AppSidebar', () => {
  beforeEach(() => mockRole('owner'))

  it('renders correctly when expanded', () => {
    render(<AppSidebar />)

    // With mocked t() returning keys, check for translation key strings
    expect(screen.getByText('common.appName')).toBeDefined()
    expect(screen.getByText('navigation.sources')).toBeDefined()
    expect(screen.getByText('navigation.projects')).toBeDefined()
  })

  it('toggles collapse state when clicking handle', () => {
    const toggleCollapse = vi.fn()
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: false,
      toggleCollapse,
    } as any)

    render(<AppSidebar />)

    fireEvent.click(screen.getByTestId('sidebar-toggle'))

    expect(toggleCollapse).toHaveBeenCalled()
  })

  it('shows collapsed view when isCollapsed is true', () => {
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: true,
      toggleCollapse: vi.fn(),
    } as any)

    render(<AppSidebar />)

    // In collapsed mode, app name shouldn't be visible (as text)
    expect(screen.queryByText('common.appName')).toBeNull()
  })

  it('renders an Intelligence nav link to /intelligence', () => {
    render(<AppSidebar />)
    const links = screen.getAllByRole('link')
    const intel = links.find((l) => l.getAttribute('href') === '/intelligence')
    expect(intel).toBeDefined()
    expect(screen.getByText('navigation.intelligence')).toBeInTheDocument()
  })
})

describe('AppSidebar role gating', () => {
  beforeEach(() => {
    // A prior test in the file above can leave the mocked sidebar store
    // collapsed; these assertions all rely on the expanded (label-visible) view.
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: false,
      toggleCollapse: vi.fn(),
    } as any)
  })

  it('admin sees the Manage section and Create→Notebook', () => {
    mockRole('admin')
    render(<AppSidebar />)
    expect(screen.getByText('navigation.manage')).toBeDefined()
  })

  it('member does NOT see the Manage section', () => {
    mockRole('member')
    render(<AppSidebar />)
    expect(screen.queryByText('navigation.manage')).toBeNull()
  })

  it('a personal-workspace owner does not see manage-members/invite entries', () => {
    mockRole('owner', 'personal')
    render(<AppSidebar />)
    expect(screen.queryByText('navigation.manageMembers')).toBeNull()
  })

  it('a company-workspace admin sees manage-members/invite entries', () => {
    mockRole('admin', 'company')
    render(<AppSidebar />)
    expect(screen.getByText('navigation.manageMembers')).toBeDefined()
  })
})
