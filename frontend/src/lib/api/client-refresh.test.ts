import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/lib/config', () => ({ getApiUrl: vi.fn(async () => 'http://api.test') }))

import { refreshAccessToken } from './client'

describe('refreshAccessToken', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('auth-storage', JSON.stringify({ state: { token: 'old' }, version: 0 }))
  })
  afterEach(() => {
    global.fetch = originalFetch
  })

  it('writes the new token into auth-storage and returns it', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        access_token: 'new-jwt',
        user: { id: 'user:1', email: 'a@b.com', display_name: null },
      }),
    }) as unknown as typeof fetch

    const token = await refreshAccessToken()
    expect(token).toBe('new-jwt')
    expect(global.fetch).toHaveBeenCalledWith(
      'http://api.test/api/auth/refresh',
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    )
    const stored = JSON.parse(localStorage.getItem('auth-storage') as string)
    expect(stored.state.token).toBe('new-jwt')
    expect(stored.state.user.id).toBe('user:1')
  })

  it('returns null when refresh fails', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({ ok: false, status: 401 }) as unknown as typeof fetch
    const token = await refreshAccessToken()
    expect(token).toBeNull()
  })
})
