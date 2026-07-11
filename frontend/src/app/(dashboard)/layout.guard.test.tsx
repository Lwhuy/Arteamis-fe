import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import DashboardLayout from './layout'
import { useAuth } from '@/lib/hooks/use-auth'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useRouter } from 'next/navigation'

vi.mock('next/navigation', () => ({ useRouter: vi.fn() }))
vi.mock('@/lib/hooks/use-auth', () => ({ useAuth: vi.fn() }))
vi.mock('@/lib/hooks/use-version-check', () => ({ useVersionCheck: vi.fn() }))
// This guard test only exercises the auth/workspace redirect effect — stub out
// the heavier chrome (dialogs/modals/command palette) the layout also renders.
vi.mock('@/lib/hooks/use-create-dialogs', () => ({
  CreateDialogsProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useCreateDialogs: () => ({ openSourceDialog: vi.fn(), openNotebookDialog: vi.fn(), openPodcastDialog: vi.fn() }),
}))
vi.mock('@/components/providers/ModalProvider', () => ({ ModalProvider: () => null }))
vi.mock('@/components/common/CommandPalette', () => ({ CommandPalette: () => null }))

describe('DashboardLayout — no forced onboarding gate', () => {
  const push = vi.fn()
  beforeEach(() => {
    push.mockClear()
    vi.mocked(useRouter).mockReturnValue({ push } as any)
  })

  it('renders the dashboard directly for a user with ONLY a personal workspace (no redirect)', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, isLoading: false } as any)
    useAuthStore.setState({
      memberships: [{ workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' }],
      activeWorkspaceId: 'workspace:p1',
    })
    const { getByText } = render(<DashboardLayout>content</DashboardLayout>)
    expect(getByText('content')).toBeDefined()
    expect(push).not.toHaveBeenCalledWith('/onboarding')
  })

  it('auto-selects the first membership when a persisted session has none active', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, isLoading: false } as any)
    useAuthStore.setState({
      memberships: [{ workspace_id: 'workspace:p1', name: 'Personal', slug: 'personal-1', kind: 'personal', role: 'owner' }],
      activeWorkspaceId: null,
    })
    render(<DashboardLayout>content</DashboardLayout>)
    expect(useAuthStore.getState().activeWorkspaceId).toBe('workspace:p1')
    expect(push).not.toHaveBeenCalledWith('/onboarding')
  })

  it('redirects to /login when unauthenticated (unchanged P1 behavior)', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: false, isLoading: false } as any)
    useAuthStore.setState({ memberships: [], activeWorkspaceId: null })
    render(<DashboardLayout>content</DashboardLayout>)
    expect(push).toHaveBeenCalledWith('/login')
  })
})
