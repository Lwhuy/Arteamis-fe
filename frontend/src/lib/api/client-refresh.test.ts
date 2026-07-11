import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'

vi.mock('@/lib/config', () => ({ getApiUrl: vi.fn(async () => 'http://api.test') }))

import apiClient, { refreshAccessToken } from './client'

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

  it('does not erase the persisted user when the refresh response omits user', async () => {
    localStorage.setItem(
      'auth-storage',
      JSON.stringify({
        state: { token: 'old', user: { id: 'user:1', email: 'a@b.com', display_name: null }, isAuthenticated: true },
        version: 0,
      })
    )
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: 'new-jwt' }), // no `user` field
    }) as unknown as typeof fetch

    const token = await refreshAccessToken()
    expect(token).toBe('new-jwt')

    const stored = JSON.parse(localStorage.getItem('auth-storage') as string)
    expect(stored.state.token).toBe('new-jwt')
    // The previously persisted user must survive an omission in the refresh response.
    expect(stored.state.user).toEqual({ id: 'user:1', email: 'a@b.com', display_name: null })
  })
})

// ---------------------------------------------------------------------------
// Response interceptor: 401 -> refresh -> retry, one-shot guard, dedup, redirect
// ---------------------------------------------------------------------------
//
// There is no mock-adapter library in this project (no axios-mock-adapter/msw),
// so these tests drive the *real* apiClient instance (with its real request +
// response interceptors attached) but swap out the low-level axios transport by
// overriding `apiClient.defaults.adapter` with a fake one. This exercises the
// actual interceptor code (dedup guard, `_retried` flag, redirect) rather than
// re-implementing/mocking that logic, while only mocking the network boundary
// (the adapter) and the refresh endpoint's `fetch` call.
describe('apiClient response interceptor (401 refresh/retry/redirect)', () => {
  const originalFetch = global.fetch
  const originalAdapter = apiClient.defaults.adapter
  const originalLocation = window.location

  function unauthorized(config: InternalAxiosRequestConfig) {
    const error = new Error('Request failed with status code 401') as Error & {
      config: InternalAxiosRequestConfig
      response: unknown
      isAxiosError: boolean
    }
    error.config = config
    error.isAxiosError = true
    error.response = { status: 401, data: {}, statusText: 'Unauthorized', headers: {}, config }
    return Promise.reject(error)
  }

  function ok(config: InternalAxiosRequestConfig, data: unknown = { ok: true }) {
    return Promise.resolve({ data, status: 200, statusText: 'OK', headers: {}, config })
  }

  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('auth-storage', JSON.stringify({ state: { token: 'old-token' }, version: 0 }))
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: { href: '' },
    })
  })

  afterEach(() => {
    global.fetch = originalFetch
    apiClient.defaults.adapter = originalAdapter
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: originalLocation,
    })
  })

  it('refreshes once and retries the request; a second 401 on the retry does not trigger a second refresh', async () => {
    let refreshCalls = 0
    global.fetch = vi.fn(async () => {
      refreshCalls++
      return { ok: true, json: async () => ({ access_token: 'new-token' }) }
    }) as unknown as typeof fetch

    // Every request 401s, including the retried one, to exercise the one-shot guard.
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => unauthorized(config))
    apiClient.defaults.adapter = adapter as unknown as AxiosAdapter

    await expect(apiClient.get('/notebooks')).rejects.toMatchObject({
      response: { status: 401 },
    })

    // original request + exactly one retry = 2 adapter calls
    expect(adapter).toHaveBeenCalledTimes(2)
    // refreshAccessToken's underlying fetch call happened exactly once
    expect(refreshCalls).toBe(1)
    // the retried request carried the refreshed token
    expect(adapter.mock.calls[1][0].headers.Authorization).toBe('Bearer new-token')
  })

  it('dedupes concurrent 401s into a single refresh call', async () => {
    let refreshCalls = 0
    global.fetch = vi.fn(async () => {
      refreshCalls++
      return { ok: true, json: async () => ({ access_token: 'new-token' }) }
    }) as unknown as typeof fetch

    const adapter = vi.fn((config: InternalAxiosRequestConfig & { _retried?: boolean }) => {
      if (!config._retried) return unauthorized(config)
      return ok(config)
    })
    apiClient.defaults.adapter = adapter as unknown as AxiosAdapter

    const [r1, r2] = await Promise.allSettled([apiClient.get('/a'), apiClient.get('/b')])

    expect(r1.status).toBe('fulfilled')
    expect(r2.status).toBe('fulfilled')
    // Both requests 401'd concurrently, but only one refresh should have fired.
    expect(refreshCalls).toBe(1)
  })

  it('clears auth-storage and redirects to /login when refresh fails', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 }) as unknown as typeof fetch

    const adapter = vi.fn((config: InternalAxiosRequestConfig) => unauthorized(config))
    apiClient.defaults.adapter = adapter as unknown as AxiosAdapter

    await expect(apiClient.get('/notebooks')).rejects.toMatchObject({
      response: { status: 401 },
    })

    expect(localStorage.getItem('auth-storage')).toBeNull()
    expect(window.location.href).toBe('/login')
  })
})
