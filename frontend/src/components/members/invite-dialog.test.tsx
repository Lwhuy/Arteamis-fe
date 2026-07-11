import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'

const mutateAsync = vi.fn()
vi.mock('@/lib/hooks/use-invitations', () => ({
  useCreateInvitation: () => ({ mutateAsync, isPending: false }),
}))
vi.mock('@/lib/hooks/use-projects', () => ({ useProjects: () => ({ data: [] }) }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { InviteDialog } from './invite-dialog'

describe('InviteDialog', () => {
  it('shows the copy-link fallback body when a share_url is returned', async () => {
    render(
      <InviteDialog
        workspaceId="workspace:acme"
        open={true}
        onOpenChange={() => {}}
        initialShareUrl="http://localhost:3000/invite/RAW"
      />,
    )
    // The read-only URL + copy affordance render from the share-url branch.
    expect(screen.getByDisplayValue('http://localhost:3000/invite/RAW')).toBeTruthy()
    expect(screen.getByText('invitations.copyLink')).toBeTruthy()
  })

  it('renders the invite form when no share_url yet', () => {
    render(<InviteDialog workspaceId="workspace:acme" open={true} onOpenChange={() => {}} />)
    expect(screen.getByText('invitations.sendInvite')).toBeTruthy()
  })
})
