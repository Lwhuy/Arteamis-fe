import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

const push = vi.fn()
vi.mock('next/navigation', () => ({
  useParams: () => ({ token: 'RAW' }),
  useRouter: () => ({ push }),
}))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

const previewState = { data: undefined as unknown, isLoading: false, isError: false, error: undefined as unknown }
const switchWorkspace = { mutateAsync: vi.fn() }
vi.mock('@/lib/hooks/use-invitations', () => ({
  useInvitationPreview: () => previewState,
  useAcceptInvitation: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('@/lib/hooks/use-workspaces', () => ({
  useSwitchWorkspace: () => switchWorkspace,
}))
const authState = { isAuthenticated: false }
vi.mock('@/lib/stores/auth-store', () => ({
  useAuthStore: (sel: (s: typeof authState) => unknown) => sel(authState),
}))

import InvitePage from './page'

describe('InvitePage', () => {
  it('shows the expired state on a 410 preview error', () => {
    previewState.isError = true
    previewState.error = { response: { status: 410 } }
    render(<InvitePage />)
    expect(screen.getByText('invitations.expiredTitle')).toBeTruthy()
  })

  it('offers sign-in / create-account when logged out', () => {
    previewState.isError = false
    previewState.error = undefined
    previewState.data = { workspace_name: 'Acme', role: 'member', email: 'a@x.com', project_name: null, status: 'pending', expired: false }
    authState.isAuthenticated = false
    render(<InvitePage />)
    expect(screen.getByText('invitations.createAccountCta')).toBeTruthy()
    expect(screen.getByText('invitations.signInCta')).toBeTruthy()
  })
})
