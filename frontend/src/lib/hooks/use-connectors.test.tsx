import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useConnectors } from './use-connectors'

vi.mock('@/lib/api/connectors', () => ({
  connectorsApi: {
    list: vi.fn().mockResolvedValue([
      { provider: 'gdrive', display_name: 'Google Drive', description: '', status: 'available', connections: [] },
    ]),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useConnectors', () => {
  it('returns connectors from the api', async () => {
    const { result } = renderHook(() => useConnectors(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.[0].provider).toBe('gdrive')
  })
})
