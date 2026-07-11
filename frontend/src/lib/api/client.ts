import axios, { AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { getApiUrl } from '@/lib/config'

// API client with runtime-configurable base URL
// The base URL is fetched from the API config endpoint on first request
//
// Request timeout defaults to 10 minutes (600000ms) to accommodate slow LLM
// operations (transformations, insights, synchronous chat) on slower hardware
// (Ollama, LM Studio). Configure it via NEXT_PUBLIC_API_TIMEOUT_MS for models
// that can take longer than 10 minutes to respond (#880).
// Note: value is in milliseconds; an explicit 0 disables the timeout entirely.
// An empty or invalid value falls back to the default (so a present-but-empty
// env var doesn't accidentally disable timeouts).
const DEFAULT_API_TIMEOUT_MS = 600000 // 600 seconds = 10 minutes
const rawTimeout = process.env.NEXT_PUBLIC_API_TIMEOUT_MS
const parsedTimeout = rawTimeout && rawTimeout.trim() !== '' ? Number(rawTimeout) : NaN
const apiTimeout = Number.isFinite(parsedTimeout) && parsedTimeout >= 0
  ? parsedTimeout
  : DEFAULT_API_TIMEOUT_MS

export const apiClient = axios.create({
  timeout: apiTimeout,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: false,
})

// Request interceptor to add base URL and auth header
apiClient.interceptors.request.use(async (config) => {
  // Set the base URL dynamically from runtime config
  if (!config.baseURL) {
    const apiUrl = await getApiUrl()
    config.baseURL = `${apiUrl}/api`
  }

  if (typeof window !== 'undefined') {
    const authStorage = localStorage.getItem('auth-storage')
    if (authStorage) {
      try {
        const { state } = JSON.parse(authStorage)
        if (state?.token) {
          config.headers.Authorization = `Bearer ${state.token}`
        }
      } catch (error) {
        console.error('Error parsing auth storage:', error)
      }
    }
  }

  // Handle FormData vs JSON content types
  if (config.data instanceof FormData) {
    // Remove any Content-Type header to let browser set multipart boundary
    delete config.headers['Content-Type']
  } else if (config.method && ['post', 'put', 'patch'].includes(config.method.toLowerCase())) {
    config.headers['Content-Type'] = 'application/json'
  }

  return config
})

/**
 * Exchange the httpOnly refresh cookie for a fresh access token. Uses a raw
 * fetch with credentials:'include' so the cookie is sent (the base apiClient is
 * withCredentials:false). Writes the new access_token + user into the persisted
 * Zustand `auth-storage` blob so the request interceptor picks it up. Returns
 * the new token, or null on failure.
 *
 * CORS caveat: the refresh cookie only survives cross-origin when the backend
 * CORS_ORIGINS is the explicit frontend origin (not '*') so allow_credentials
 * is on. Documented in .env.example.
 */
export async function refreshAccessToken(): Promise<string | null> {
  if (typeof window === 'undefined') return null
  try {
    const apiUrl = await getApiUrl()
    const res = await fetch(`${apiUrl}/api/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
    if (!res.ok) return null
    const data = await res.json()
    const token = data?.access_token as string | undefined
    if (!token) return null

    let blob: { state?: Record<string, unknown>; version?: number } = {}
    try {
      blob = JSON.parse(localStorage.getItem('auth-storage') || '{}')
    } catch {
      blob = {}
    }
    blob.state = {
      ...(blob.state || {}),
      token,
      ...(data.user ? { user: data.user } : {}),
      isAuthenticated: true,
    }
    if (blob.version === undefined) blob.version = 0
    localStorage.setItem('auth-storage', JSON.stringify(blob))
    return token
  } catch {
    return null
  }
}

// Module-level guards: dedupe concurrent 401s and prevent infinite loops.
let refreshPromise: Promise<string | null> | null = null

function redirectToLogin() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('auth-storage')
    window.location.href = '/login'
  }
}

// Response interceptor: on 401, attempt ONE refresh + retry the original request
// once; on refresh failure, clear auth-storage and redirect to /login.
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  async (error) => {
    const status = error.response?.status
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined

    // Never try to refresh the refresh call itself, and only retry once.
    const isRefreshCall = typeof original?.url === 'string' && original.url.includes('/auth/refresh')

    if (status === 401 && original && !original._retried && !isRefreshCall) {
      original._retried = true
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null
        })
      }
      const newToken = await refreshPromise
      if (newToken) {
        original.headers = original.headers || {}
        original.headers.Authorization = `Bearer ${newToken}`
        return apiClient(original)
      }
      redirectToLogin()
    } else if (status === 401) {
      redirectToLogin()
    }
    return Promise.reject(error)
  }
)

export default apiClient
