import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const registerMock = vi.fn()
const googleMock = vi.fn()
vi.mock('@/lib/hooks/use-auth', () => ({
  useAuth: () => ({ register: registerMock, loginWithGoogle: googleMock, isLoading: false, error: null }),
}))

import { SignupForm } from './SignupForm'

describe('SignupForm', () => {
  beforeEach(() => vi.clearAllMocks())

  const fill = (name: string, email: string, pw: string, confirm: string) => {
    fireEvent.change(screen.getByPlaceholderText('auth.displayNamePlaceholder'), { target: { value: name } })
    fireEvent.change(screen.getByPlaceholderText('auth.emailPlaceholder'), { target: { value: email } })
    fireEvent.change(screen.getByPlaceholderText('auth.passwordPlaceholder'), { target: { value: pw } })
    fireEvent.change(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder'), { target: { value: confirm } })
  }

  it('renders all inputs and the login link', () => {
    render(<SignupForm />)
    expect(screen.getByPlaceholderText('auth.displayNamePlaceholder')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('auth.confirmPasswordPlaceholder')).toBeInTheDocument()
    expect(screen.getByText('auth.signInLink')).toBeInTheDocument()
  })

  it('blocks submit and shows error when passwords differ', async () => {
    render(<SignupForm />)
    fill('A', 'a@b.com', 'password123', 'different1')
    fireEvent.click(screen.getByRole('button', { name: 'auth.createAccount' }))
    await waitFor(() => expect(screen.getByText('auth.passwordsDontMatch')).toBeInTheDocument())
    expect(registerMock).not.toHaveBeenCalled()
  })

  it('blocks submit and shows error when password too short', async () => {
    render(<SignupForm />)
    fill('A', 'a@b.com', 'short', 'short')
    fireEvent.click(screen.getByRole('button', { name: 'auth.createAccount' }))
    await waitFor(() => expect(screen.getByText('auth.passwordTooShort')).toBeInTheDocument())
    expect(registerMock).not.toHaveBeenCalled()
  })

  it('registers on valid input', async () => {
    registerMock.mockResolvedValueOnce(true)
    render(<SignupForm />)
    fill('A', 'a@b.com', 'password123', 'password123')
    fireEvent.click(screen.getByRole('button', { name: 'auth.createAccount' }))
    await waitFor(() => expect(registerMock).toHaveBeenCalledWith('a@b.com', 'password123', 'A'))
  })
})
