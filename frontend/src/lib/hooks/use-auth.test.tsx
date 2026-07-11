import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

const pushMock = vi.fn()
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: pushMock }) }))

const store = {
  isAuthenticated: false,
  user: null,
  isLoading: false,
  error: null,
  hasHydrated: true,
  authRequired: true as boolean | null,
  token: null as string | null,
  login: vi.fn(),
  register: vi.fn(),
  loginWithGoogle: vi.fn(),
  logout: vi.fn(),
  refresh: vi.fn(),
  checkAuth: vi.fn(),
  checkAuthRequired: vi.fn(),
}
vi.mock('@/lib/stores/auth-store', () => ({
  useAuthStore: () => store,
}))

// src/test/setup.ts globally mocks this module (with a stub lacking
// login/register) so consumers of useAuth don't need to know its internals.
// This suite tests the real implementation, so un-mock it here.
vi.unmock('@/lib/hooks/use-auth')

import { useAuth } from './use-auth'

describe('useAuth', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    store.token = null
    sessionStorage.clear()
  })

  it('login success pushes to /notebooks', async () => {
    store.login.mockResolvedValueOnce(true)
    const { result } = renderHook(() => useAuth())
    await act(async () => {
      await result.current.login('a@b.com', 'password123')
    })
    expect(store.login).toHaveBeenCalledWith('a@b.com', 'password123')
    expect(pushMock).toHaveBeenCalledWith('/notebooks')
  })

  it('login success honors redirectAfterLogin', async () => {
    sessionStorage.setItem('redirectAfterLogin', '/settings')
    store.login.mockResolvedValueOnce(true)
    const { result } = renderHook(() => useAuth())
    await act(async () => {
      await result.current.login('a@b.com', 'password123')
    })
    expect(pushMock).toHaveBeenCalledWith('/settings')
  })

  it('bootstraps a refresh when no token is present', async () => {
    store.token = null
    store.refresh.mockResolvedValueOnce(false)
    renderHook(() => useAuth())
    await waitFor(() => expect(store.refresh).toHaveBeenCalled())
  })
})
