import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

vi.mock('@/lib/api/projects', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([{ id: 'notebook:1', name: 'Acme' }]),
    create: vi.fn().mockResolvedValue({ id: 'notebook:2', name: 'New' }),
  },
}))
vi.mock('@/lib/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { projectsApi } from '@/lib/api/projects'
import { useProjects } from './use-projects'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useProjects', () => {
  it('fetches from projectsApi.list', async () => {
    const { result } = renderHook(() => useProjects(), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(projectsApi.list).toHaveBeenCalled()
    expect(result.current.data?.[0].id).toBe('notebook:1')
  })
})
