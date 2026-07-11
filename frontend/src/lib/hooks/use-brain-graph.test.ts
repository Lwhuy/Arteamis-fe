import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

const { getGraph, getStatus, rebuild } = vi.hoisted(() => ({
  getGraph: vi.fn(),
  getStatus: vi.fn(),
  rebuild: vi.fn(),
}))
vi.mock('@/lib/api/brain', () => ({ brainApi: { getGraph, getStatus, rebuild } }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import { useBrainGraph, useBrainStatus, useRebuildBrain } from './use-brain-graph'

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client }, children)
  }
  return Wrapper
}

describe('brain hooks', () => {
  beforeEach(() => { getGraph.mockReset(); getStatus.mockReset(); rebuild.mockReset() })

  it('useBrainGraph fetches the graph and exposes graph + isLoading', async () => {
    getGraph.mockResolvedValue({ nodes: [{ id: 'a', kind: 'domain', label: 'Eng', salience: 1 }], edges: [] })
    const { result } = renderHook(() => useBrainGraph(), { wrapper: wrapper() })
    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.graph?.nodes).toHaveLength(1)
    expect(getGraph).toHaveBeenCalled()
  })

  it('useBrainStatus fetches status', async () => {
    getStatus.mockResolvedValue({ total_sources: 5, built_sources: 2, running: false })
    const { result } = renderHook(() => useBrainStatus(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.data?.total_sources).toBe(5))
  })

  it('useRebuildBrain calls brainApi.rebuild with the mode', async () => {
    rebuild.mockResolvedValue({ command_id: 'cmd-9' })
    const { result } = renderHook(() => useRebuildBrain(), { wrapper: wrapper() })
    await act(async () => { await result.current.mutateAsync('incremental') })
    expect(rebuild).toHaveBeenCalledWith('incremental')
  })
})
