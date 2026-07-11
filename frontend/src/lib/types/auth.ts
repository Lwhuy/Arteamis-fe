export interface AuthUser {
  id: string
  email: string
  display_name: string | null
}

export interface SessionPayload {
  access_token: string
  token_type: string
  needs_onboarding: boolean
  active_workspace_id: string | null
  user: AuthUser
  memberships: unknown[]
}

export interface AuthState {
  isAuthenticated: boolean
  token: string | null
  user: AuthUser | null
  isLoading: boolean
  error: string | null
}

export interface LoginCredentials {
  email: string
  password: string
}

export interface RegisterCredentials {
  email: string
  password: string
  displayName?: string
}
