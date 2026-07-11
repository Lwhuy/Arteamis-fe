import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SourceDetailContent } from './SourceDetailContent'

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient()
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

const mutateAsync = vi.fn().mockResolvedValue({})
let currentUserId = 'user:me'

vi.mock('@/lib/hooks/use-sources', () => ({ useUpdateSource: () => ({ mutateAsync, isPending: false }) }))
// The real auth store (src/lib/stores/auth-store.ts) exposes the current user
// as `user: { id, ... } | null`, not a flat `userId` field.
vi.mock('@/lib/stores/auth-store', () => ({
  useAuthStore: (sel: (s: { user: { id: string } | null }) => unknown) =>
    sel({ user: { id: currentUserId } }),
}))
vi.mock('@/lib/api/sources', () => ({
  sourcesApi: {
    get: vi.fn().mockResolvedValue({
      id: 'source:1', title: 'T', scope: 'project', owner: 'user:me',
      topics: [], asset: null, full_text: '', embedded: false, embedded_chunks: 0,
      insights_count: 0, created: '2024-01-01T00:00:00Z', updated: '2024-01-01T00:00:00Z',
    }),
    downloadFile: vi.fn(),
  },
}))
vi.mock('@/lib/api/insights', () => ({
  insightsApi: { listForSource: vi.fn().mockResolvedValue([]) },
}))
vi.mock('@/lib/api/transformations', () => ({
  transformationsApi: { list: vi.fn().mockResolvedValue([]) },
}))

describe('SourceDetailContent scope control', () => {
  beforeEach(() => {
    currentUserId = 'user:me'
    mutateAsync.mockClear()
  })

  it('owner can change scope to company and it calls useUpdateSource', async () => {
    renderWithClient(<SourceDetailContent sourceId="source:1" />)
    const control = await screen.findByRole('radio', { name: /company/i })
    fireEvent.click(control)
    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ id: 'source:1', data: { scope: 'company' } }),
    )
  })

  it('non-owner sees a read-only scope badge instead of the control', async () => {
    currentUserId = 'user:someone-else'
    renderWithClient(<SourceDetailContent sourceId="source:1" />)
    await screen.findByText('sources.visibilityProject')
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
  })
})
