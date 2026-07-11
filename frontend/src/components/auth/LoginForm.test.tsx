import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const loginMock = vi.fn()
const googleMock = vi.fn()
vi.mock('@/lib/hooks/use-auth', () => ({
  useAuth: () => ({ login: loginMock, loginWithGoogle: googleMock, isLoading: false, error: null }),
}))
vi.mock('@/lib/stores/auth-store', () => ({
  useAuthStore: () => ({
    authRequired: true,
    checkAuthRequired: vi.fn(),
    hasHydrated: true,
    isAuthenticated: false,
  }),
}))
vi.mock('@/lib/config', () => ({
  getConfig: vi.fn(async () => ({ apiUrl: 'http://api.test', version: '1', buildTime: new Date().toISOString() })),
}))

import { LoginForm } from './LoginForm'

describe('LoginForm', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders email + password + google + signup link', async () => {
    render(<LoginForm />)
    await waitFor(() => expect(screen.getByPlaceholderText('auth.emailPlaceholder')).toBeInTheDocument())
    expect(screen.getByPlaceholderText('auth.passwordPlaceholder')).toBeInTheDocument()
    expect(screen.getByText('auth.continueWithGoogle')).toBeInTheDocument()
    expect(screen.getByText('auth.signUpLink')).toBeInTheDocument()
  })

  it('submits email + password to login', async () => {
    loginMock.mockResolvedValueOnce(true)
    render(<LoginForm />)
    await waitFor(() => screen.getByPlaceholderText('auth.emailPlaceholder'))
    fireEvent.change(screen.getByPlaceholderText('auth.emailPlaceholder'), { target: { value: 'a@b.com' } })
    fireEvent.change(screen.getByPlaceholderText('auth.passwordPlaceholder'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: 'auth.signIn' }))
    await waitFor(() => expect(loginMock).toHaveBeenCalledWith('a@b.com', 'password123'))
  })

  it('google button triggers loginWithGoogle', async () => {
    render(<LoginForm />)
    await waitFor(() => screen.getByText('auth.continueWithGoogle'))
    fireEvent.click(screen.getByText('auth.continueWithGoogle'))
    expect(googleMock).toHaveBeenCalled()
  })
})
