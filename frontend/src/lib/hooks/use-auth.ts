'use client'

import { useAuthStore } from '@/lib/stores/auth-store'
import { useRouter } from 'next/navigation'
import { useEffect, useRef } from 'react'

export function useAuth() {
  const router = useRouter()
  const {
    isAuthenticated,
    user,
    isLoading,
    error,
    hasHydrated,
    authRequired,
    token,
    login,
    register,
    loginWithGoogle,
    logout,
    refresh,
    checkAuth,
    checkAuthRequired,
  } = useAuthStore()

  const bootstrapped = useRef(false)

  // Determine whether auth is required, then either validate the current token
  // or, when there is no token, try one refresh to pick up a valid refresh
  // cookie (covers the Google callback landing on /projects and returning
  // sessions).
  useEffect(() => {
    if (!hasHydrated || bootstrapped.current) return
    bootstrapped.current = true

    const run = async () => {
      let required = authRequired
      if (required === null) {
        try {
          required = await checkAuthRequired()
        } catch {
          return
        }
      }
      if (!required) return // Auth disabled: already authenticated.
      if (token && token !== 'not-required') {
        await checkAuth()
      } else {
        await refresh()
      }
    }
    void run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasHydrated])

  const afterAuth = () => {
    const redirectPath = sessionStorage.getItem('redirectAfterLogin')
    if (redirectPath) {
      sessionStorage.removeItem('redirectAfterLogin')
      router.push(redirectPath)
    } else {
      router.push('/projects')
    }
  }

  const handleLogin = async (email: string, password: string) => {
    const success = await login(email, password)
    if (success) afterAuth()
    return success
  }

  const handleRegister = async (email: string, password: string, displayName?: string) => {
    const success = await register(email, password, displayName)
    if (success) afterAuth()
    return success
  }

  const handleLogout = async () => {
    await logout()
    router.push('/login')
  }

  return {
    isAuthenticated,
    user,
    isLoading: isLoading || !hasHydrated,
    error,
    login: handleLogin,
    register: handleRegister,
    loginWithGoogle,
    logout: handleLogout,
  }
}
