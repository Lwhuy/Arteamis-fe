import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api/governance', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/governance')>(
    '@/lib/api/governance',
  )
  return {
    ...actual,
    governanceApi: {
      ...actual.governanceApi,
      listProposals: vi.fn().mockResolvedValue([{ id: 'proposal:1', title: 'SMB', status: 'pending' }]),
      listDecisions: vi.fn().mockResolvedValue([{ id: 'decision:1', title: 'Ship SMB pricing', status: 'active' }]),
    },
  }
})

import { useProposals, useDecisions } from './use-governance'

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useProposals', () => {
  it('fetches pending proposals', async () => {
    const { result } = renderHook(() => useProposals('pending'), { wrapper })
    await waitFor(() => expect(result.current.data?.[0].title).toBe('SMB'))
  })
})

describe('useDecisions', () => {
  it('fetches active decisions', async () => {
    const { result } = renderHook(() => useDecisions('active'), { wrapper })
    await waitFor(() => expect(result.current.data?.[0].title).toBe('Ship SMB pricing'))
  })
})
