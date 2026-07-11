import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('@/lib/api/governance', () => ({
  governanceApi: { listProposals: vi.fn().mockResolvedValue([{ id: 'proposal:1', title: 'SMB', status: 'pending' }]) },
}))

import { useProposals } from './use-governance'

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
