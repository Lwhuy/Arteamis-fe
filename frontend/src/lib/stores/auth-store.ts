import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import axios from 'axios'
import { apiClient } from '@/lib/api/client'
import { getApiUrl } from '@/lib/config'
import type { AuthUser, SessionPayload } from '@/lib/types/auth'
import { Membership, TokenResponse } from '@/lib/types/api'

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
  memberships: Membership[]
  activeWorkspaceId: string | null
  role: 'owner' | 'admin' | 'member' | null
  workspaceName: string | null
  workspaceKind: 'personal' | 'company' | null
  setHasHydrated: (state: boolean) => void
  checkAuthRequired: () => Promise<boolean>
  register: (email: string, password: string, displayName?: string) => Promise<boolean>
  login: (email: string, password: string) => Promise<boolean>
  loginWithGoogle: () => Promise<void>
  refresh: () => Promise<boolean>
  fetchMe: () => Promise<boolean>
  logout: () => Promise<void>
  checkAuth: () => Promise<boolean>
  applyToken: (res: TokenResponse) => void
  setSession: (payload: { memberships: Membership[]; activeWorkspaceId: string | null }) => void
  setActiveWorkspace: (workspaceId: string, role: string) => void
  setWorkspaceContext: (args: {
    workspaceName: string | null
    workspaceKind: 'personal' | 'company' | null
    role: 'owner' | 'admin' | 'member' | null
  }) => void
  hasCompany: () => boolean
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
        memberships: [],
        activeWorkspaceId: null,
        role: null,
        workspaceName: null,
        workspaceKind: null,

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

        applyToken: (res: TokenResponse) => {
          // The single mutation shared by workspace create + switch: swap the
          // stored Bearer to the workspace-scoped access token (apiClient reads
          // state.token). Also derive workspaceName/workspaceKind for the new
          // active workspace from the already-loaded memberships list — the
          // response itself only carries the id, not the display name/kind.
          const active = get().memberships.find((m) => m.workspace_id === res.active_workspace_id)
          set({
            token: res.access_token,
            activeWorkspaceId: res.active_workspace_id,
            role: res.role as 'owner' | 'admin' | 'member',
            workspaceName: active ? active.name : null,
            workspaceKind: active ? active.kind : null,
          })
        },

        setSession: ({ memberships, activeWorkspaceId }) => {
          // The backend's session payload always names the active workspace
          // (the caller's personal workspace on every fresh login — see the P2
          // spec's stated default) — trust it rather than re-deriving here.
          const active = memberships.find((m) => m.workspace_id === activeWorkspaceId)
          set({
            memberships,
            activeWorkspaceId,
            role: active ? (active.role as 'owner' | 'admin' | 'member') : null,
            workspaceName: active ? active.name : null,
            workspaceKind: active ? active.kind : null,
          })
        },

        setActiveWorkspace: (workspaceId: string, role: string) => {
          const active = get().memberships.find((m) => m.workspace_id === workspaceId)
          set({
            activeWorkspaceId: workspaceId,
            role: role as 'owner' | 'admin' | 'member',
            workspaceName: active ? active.name : null,
            workspaceKind: active ? active.kind : null,
          })
        },

        setWorkspaceContext: ({ workspaceName, workspaceKind, role }) => {
          set({ workspaceName, workspaceKind, role })
        },

        hasCompany: () => get().memberships.some((m) => m.kind === 'company'),
      }
    },
    {
      name: 'auth-storage',
      partialize: (state) => ({
        token: state.token,
        user: state.user,
        isAuthenticated: state.isAuthenticated,
        memberships: state.memberships,
        activeWorkspaceId: state.activeWorkspaceId,
        role: state.role,
        workspaceName: state.workspaceName,
        workspaceKind: state.workspaceKind,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)
