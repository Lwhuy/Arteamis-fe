import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('./client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

import apiClient from './client'
import { invitationsApi } from './invitations'

const mocked = apiClient as unknown as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn> }

describe('invitationsApi', () => {
  beforeEach(() => {
    mocked.get.mockReset()
    mocked.post.mockReset()
  })

  it('create posts to the workspace invitations endpoint', async () => {
    mocked.post.mockResolvedValue({ data: { email_sent: false, share_url: 'http://x/invite/t', invitation: {} } })
    const res = await invitationsApi.create('workspace:acme', { email: 'a@x.com', role: 'member' })
    expect(mocked.post).toHaveBeenCalledWith('/workspaces/workspace:acme/invitations', {
      email: 'a@x.com',
      role: 'member',
    })
    expect(res.share_url).toBe('http://x/invite/t')
  })

  it('list requests with a status param', async () => {
    mocked.get.mockResolvedValue({ data: [] })
    await invitationsApi.list('workspace:acme', 'pending')
    expect(mocked.get).toHaveBeenCalledWith('/workspaces/workspace:acme/invitations', {
      params: { status: 'pending' },
    })
  })

  it('preview hits the public token endpoint', async () => {
    mocked.get.mockResolvedValue({ data: { workspace_name: 'Acme' } })
    await invitationsApi.preview('RAW')
    expect(mocked.get).toHaveBeenCalledWith('/invitations/RAW')
  })

  it('accept posts to the token accept endpoint', async () => {
    mocked.post.mockResolvedValue({ data: { workspace_id: 'workspace:acme' } })
    await invitationsApi.accept('RAW')
    expect(mocked.post).toHaveBeenCalledWith('/invitations/RAW/accept')
  })

  it('members lists workspace members', async () => {
    mocked.get.mockResolvedValue({ data: [] })
    await invitationsApi.members('workspace:acme')
    expect(mocked.get).toHaveBeenCalledWith('/workspaces/workspace:acme/members')
  })
})
