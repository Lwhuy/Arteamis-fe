import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import axios from 'axios'
import { apiClient } from '@/lib/api/client'
import { getApiUrl } from '@/lib/config'
import type { AuthUser, SessionPayload } from '@/lib/types/auth'

interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: AuthUser | null
  isLoading: boolean
  error: string | null
  lastAuthCheck: number | null
  isCheckingAuth: boolean
  hasHydrated: boolean
  authRequired: boolean | null
  setHasHydrated: (state: boolean) => void
  checkAuthRequired: () => Promise<boolean>
  register: (email: string, password: string, displayName?: string) => Promise<boolean>
  login: (email: string, password: string) => Promise<boolean>
  loginWithGoogle: () => Promise<void>
  refresh: () => Promise<boolean>
  fetchMe: () => Promise<boolean>
  logout: () => Promise<void>
  checkAuth: () => Promise<boolean>
}

function errorMessage(err: unknown, fallback: string): string {
  // Prefer reading response.data.detail directly rather than gating on
  // axios.isAxiosError(): that check requires the internal `isAxiosError`
  // marker axios stamps on errors it constructs itself, which plain
  // `{ response: {...} }` rejections (e.g. from mocked apiClient calls in
  // tests) don't carry even though they have the same shape.
  if (err && typeof err === 'object' && 'response' in err) {
    const response = (err as { response?: { data?: { detail?: unknown } } }).response
    const detail = response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  if (axios.isAxiosError(err) && err.message.includes('Network Error')) {
    return 'Unable to connect to server. Please check if the API is running.'
  }
  return fallback
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => {
      const applySession = (payload: SessionPayload) => {
        set({
          token: payload.access_token,
          user: payload.user,
          isAuthenticated: true,
          isLoading: false,
          error: null,
          lastAuthCheck: Date.now(),
        })
      }

      return {
        isAuthenticated: false,
        token: null,
        user: null,
        isLoading: false,
        error: null,
        lastAuthCheck: null,
        isCheckingAuth: false,
        hasHydrated: false,
        authRequired: null,

        setHasHydrated: (state: boolean) => set({ hasHydrated: state }),

        checkAuthRequired: async () => {
          try {
            const apiUrl = await getApiUrl()
            const response = await fetch(`${apiUrl}/api/auth/status`, { cache: 'no-store' })
            if (!response.ok) {
              throw new Error(`Auth status check failed: ${response.status}`)
            }
            const data = await response.json()
            const required = data.auth_enabled || false
            set({ authRequired: required })
            if (!required) {
              set({ isAuthenticated: true, token: 'not-required' })
            }
            return required
          } catch (error) {
            if (error instanceof TypeError && error.message.includes('Failed to fetch')) {
              set({
                error: 'Unable to connect to server. Please check if the API is running.',
                authRequired: null,
              })
            } else {
              set({ authRequired: true })
            }
            throw error
          }
        },

        register: async (email, password, displayName) => {
          set({ isLoading: true, error: null })
          try {
            const { data } = await apiClient.post<SessionPayload>('/auth/register', {
              email,
              password,
              display_name: displayName,
            })
            applySession(data)
            return true
          } catch (error) {
            set({ error: errorMessage(error, 'Registration failed'), isLoading: false, isAuthenticated: false })
            return false
          }
        },

        login: async (email, password) => {
          set({ isLoading: true, error: null })
          try {
            const { data } = await apiClient.post<SessionPayload>('/auth/login', { email, password })
            applySession(data)
            return true
          } catch (error) {
            set({ error: errorMessage(error, 'Authentication failed'), isLoading: false, isAuthenticated: false })
            return false
          }
        },

        loginWithGoogle: async () => {
          const apiUrl = await getApiUrl()
          window.location.href = `${apiUrl}/api/auth/google/start`
        },

        refresh: async () => {
          try {
            const { data } = await apiClient.post<SessionPayload>('/auth/refresh', {}, { withCredentials: true })
            applySession(data)
            return true
          } catch {
            return false
          }
        },

        fetchMe: async () => {
          try {
            const { data } = await apiClient.get<{ user: AuthUser }>('/auth/me')
            set({ user: data.user, isAuthenticated: true })
            return true
          } catch {
            return false
          }
        },

        logout: async () => {
          try {
            await apiClient.post('/auth/logout', {}, { withCredentials: true })
          } catch {
            // Best-effort: clear locally even if the network call fails.
          }
          set({ isAuthenticated: false, token: null, user: null, error: null })
          if (typeof window !== 'undefined') {
            localStorage.removeItem('auth-storage')
          }
        },

        checkAuth: async () => {
          const { token } = get()
          if (!token || token === 'not-required') {
            return token === 'not-required'
          }
          return await get().fetchMe()
        },
      }
    },
    {
      name: 'auth-storage',
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)
