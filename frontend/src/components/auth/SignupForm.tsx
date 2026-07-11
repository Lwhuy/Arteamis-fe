'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useAuth } from '@/lib/hooks/use-auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertCircle } from 'lucide-react'
import { useTranslation } from '@/lib/hooks/use-translation'

export function SignupForm() {
  const { t } = useTranslation()
  const { register, loginWithGoogle, isLoading, error } = useAuth()
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLocalError(null)
    if (password.length < 8) {
      setLocalError(t('auth.passwordTooShort'))
      return
    }
    if (password !== confirm) {
      setLocalError(t('auth.passwordsDontMatch'))
      return
    }
    try {
      await register(email.trim(), password, displayName.trim() || undefined)
    } catch (err) {
      console.error('Unhandled error during signup:', err)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle>{t('auth.signupTitle')}</CardTitle>
          <CardDescription>{t('auth.signupDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              type="text"
              placeholder={t('auth.displayNamePlaceholder')}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={isLoading}
            />
            <Input
              type="email"
              placeholder={t('auth.emailPlaceholder')}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
            />
            <Input
              type="password"
              placeholder={t('auth.passwordPlaceholder')}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={isLoading}
            />
            <Input
              type="password"
              placeholder={t('auth.confirmPasswordPlaceholder')}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              disabled={isLoading}
            />

            {(localError || error) && (
              <div className="flex items-center gap-2 text-red-600 text-sm">
                <AlertCircle className="h-4 w-4" />
                {localError || error || t('auth.emailInUse')}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={isLoading || !email.trim() || !password}>
              {isLoading ? t('auth.creatingAccount') : t('auth.createAccount')}
            </Button>
          </form>

          <div className="flex items-center gap-3 my-4">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">{t('auth.orWithEmail')}</span>
            <div className="h-px flex-1 bg-border" />
          </div>

          <Button type="button" variant="outline" className="w-full" onClick={() => loginWithGoogle()} disabled={isLoading}>
            {t('auth.continueWithGoogle')}
          </Button>

          <div className="text-sm text-center text-muted-foreground pt-4">
            {t('auth.haveAccount')}{' '}
            <Link href="/login" className="underline">
              {t('auth.signInLink')}
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
