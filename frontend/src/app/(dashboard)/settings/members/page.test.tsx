import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div data-testid="app-shell">{children}</div>,
}))

const roleState = { workspaceId: null as string | null }
vi.mock('@/lib/hooks/use-role', () => ({ useRole: () => roleState }))

vi.mock('@/components/members/members-panel', () => ({
  MembersPanel: ({ workspaceId }: { workspaceId: string }) => (
    <div data-testid="members-panel">panel:{workspaceId}</div>
  ),
}))

import MembersPage from './page'

describe('MembersPage', () => {
  it('renders the Members panel scoped to the active workspace', () => {
    roleState.workspaceId = 'workspace:acme'
    render(<MembersPage />)
    expect(screen.getByTestId('members-panel').textContent).toBe('panel:workspace:acme')
  })

  it('does not render the Members panel while there is no active workspace yet', () => {
    roleState.workspaceId = null
    render(<MembersPage />)
    expect(screen.queryByTestId('members-panel')).toBeNull()
  })
})
