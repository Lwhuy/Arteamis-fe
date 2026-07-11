import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useCreateWorkspace, useSwitchWorkspace } from './use-workspaces'
import { workspacesApi } from '@/lib/api/workspaces'
import { useAuthStore } from '@/lib/stores/auth-store'

vi.mock('@/lib/api/workspaces', () => ({
  workspacesApi: { list: vi.fn(), create: vi.fn(), switch: vi.fn() },
}))
vi.mock('@/lib/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))

const wrapper = (client: QueryClient) =>
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }

describe('use-workspaces', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({ token: null, activeWorkspaceId: null, role: null })
  })

  it('useCreateWorkspace success applies the token to the store', async () => {
    vi.mocked(workspacesApi.create).mockResolvedValue({
      access_token: 'scoped', token_type: 'bearer', active_workspace_id: 'workspace:1', role: 'owner',
    })
    const client = new QueryClient()
    const { result } = renderHook(() => useCreateWorkspace(), { wrapper: wrapper(client) })
    result.current.mutate({ name: 'Acme' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(useAuthStore.getState().token).toBe('scoped')
    expect(useAuthStore.getState().activeWorkspaceId).toBe('workspace:1')
  })

  it('useSwitchWorkspace success applies the token and clears the cache', async () => {
    vi.mocked(workspacesApi.switch).mockResolvedValue({
      access_token: 'scoped2', token_type: 'bearer', active_workspace_id: 'workspace:2', role: 'member',
    })
    const client = new QueryClient()
    const clearSpy = vi.spyOn(client, 'clear')
    const { result } = renderHook(() => useSwitchWorkspace(), { wrapper: wrapper(client) })
    result.current.mutate('workspace:2')
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(useAuthStore.getState().token).toBe('scoped2')
    expect(clearSpy).toHaveBeenCalled()
  })
})
