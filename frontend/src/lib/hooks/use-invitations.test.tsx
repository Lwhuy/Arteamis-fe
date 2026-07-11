import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('@/lib/api/invitations', () => ({
  invitationsApi: {
    create: vi.fn(),
    list: vi.fn(),
    revoke: vi.fn(),
    members: vi.fn(),
    preview: vi.fn(),
    accept: vi.fn(),
  },
}))
vi.mock('@/lib/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { invitationsApi } from '@/lib/api/invitations'
import { useCreateInvitation } from './use-invitations'

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useCreateInvitation', () => {
  beforeEach(() => vi.clearAllMocks())

  it('returns share_url from the mutation result', async () => {
    ;(invitationsApi.create as ReturnType<typeof vi.fn>).mockResolvedValue({
      email_sent: false,
      share_url: 'http://x/invite/t',
      invitation: { id: 'invitation:1' },
    })
    const { result } = renderHook(() => useCreateInvitation('workspace:acme'), { wrapper })
    const res = await result.current.mutateAsync({ email: 'a@x.com', role: 'member' })
    expect(res.share_url).toBe('http://x/invite/t')
    expect(invitationsApi.create).toHaveBeenCalledWith('workspace:acme', {
      email: 'a@x.com',
      role: 'member',
    })
  })
})
