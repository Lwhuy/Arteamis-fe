import { describe, it, expect, vi, beforeEach } from 'vitest'
import { workspacesApi } from './workspaces'
import apiClient from './client'

vi.mock('./client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

describe('workspacesApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('list GETs /workspaces', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: [{ id: 'workspace:1', kind: 'personal' }] })
    const res = await workspacesApi.list()
    expect(apiClient.get).toHaveBeenCalledWith('/workspaces')
    expect(res).toEqual([{ id: 'workspace:1', kind: 'personal' }])
  })

  it('create POSTs /workspaces with the body', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { access_token: 't', token_type: 'bearer', active_workspace_id: 'workspace:1', role: 'owner' },
    })
    const res = await workspacesApi.create({ name: 'Acme' })
    expect(apiClient.post).toHaveBeenCalledWith('/workspaces', { name: 'Acme' })
    expect(res.active_workspace_id).toBe('workspace:1')
  })

  it('switch POSTs the switch-workspace path', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { access_token: 't', token_type: 'bearer', active_workspace_id: 'workspace:1', role: 'member' },
    })
    await workspacesApi.switch('workspace:1')
    expect(apiClient.post).toHaveBeenCalledWith('/auth/switch-workspace/workspace:1')
  })
})
