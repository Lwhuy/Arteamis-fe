import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/lib/api/client', () => ({
  apiClient: { post: vi.fn(), get: vi.fn() },
}))
vi.mock('@/lib/config', () => ({
  getApiUrl: vi.fn(async () => 'http://api.test'),
}))

import { apiClient } from '@/lib/api/client'
import { useAuthStore } from './auth-store'

const session = {
  access_token: 'jwt-token-123',
  token_type: 'bearer',
  needs_onboarding: true,
  active_workspace_id: null,
  user: { id: 'user:1', email: 'a@b.com', display_name: 'A' },
  memberships: [],
}

describe('auth-store', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    useAuthStore.setState({ token: null, user: null, isAuthenticated: false, error: null, isLoading: false })
  })

  it('login stores token + user on success', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: session })
    const ok = await useAuthStore.getState().login('a@b.com', 'password123')
    expect(ok).toBe(true)
    const s = useAuthStore.getState()
    expect(s.token).toBe('jwt-token-123')
    expect(s.user?.email).toBe('a@b.com')
    expect(s.isAuthenticated).toBe(true)
    expect(apiClient.post).toHaveBeenCalledWith('/auth/login', { email: 'a@b.com', password: 'password123' })
  })

  it('register posts to /auth/register and stores session', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: session })
    const ok = await useAuthStore.getState().register('a@b.com', 'password123', 'A')
    expect(ok).toBe(true)
    expect(apiClient.post).toHaveBeenCalledWith('/auth/register', {
      email: 'a@b.com',
      password: 'password123',
      display_name: 'A',
    })
    expect(useAuthStore.getState().token).toBe('jwt-token-123')
  })

  it('login surfaces error message on 401', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { status: 401, data: { detail: 'Invalid email or password' } },
    })
    const ok = await useAuthStore.getState().login('a@b.com', 'wrong')
    expect(ok).toBe(false)
    expect(useAuthStore.getState().error).toBe('Invalid email or password')
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('refresh stores new session with credentials', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: session })
    const ok = await useAuthStore.getState().refresh()
    expect(ok).toBe(true)
    expect(apiClient.post).toHaveBeenCalledWith('/auth/refresh', {}, { withCredentials: true })
    expect(useAuthStore.getState().token).toBe('jwt-token-123')
  })

  it('logout clears store and auth-storage', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ data: {} })
    useAuthStore.setState({ token: 't', user: session.user, isAuthenticated: true })
    localStorage.setItem('auth-storage', JSON.stringify({ state: { token: 't' }, version: 0 }))
    await useAuthStore.getState().logout()
    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
    expect(localStorage.getItem('auth-storage')).toBeNull()
  })

  it('loginWithGoogle navigates to the google start URL', async () => {
    const assignMock = vi.fn()
    Object.defineProperty(window, 'location', { value: { href: '', assign: assignMock }, writable: true })
    await useAuthStore.getState().loginWithGoogle()
    expect(window.location.href).toBe('http://api.test/api/auth/google/start')
  })
})
