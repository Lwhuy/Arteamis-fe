'use client'

import { useState } from 'react'
import { useCreateWorkspace } from '@/lib/hooks/use-workspaces'
import { useTranslation } from '@/lib/hooks/use-translation'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function CompanyStep({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation()
  const createWorkspace = useCreateWorkspace()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createWorkspace.mutate(
      { name: name.trim(), slug: slug.trim() || undefined },
      { onSuccess: () => onCreated() },
    )
  }

  return (
    <form data-testid="company-step-form" onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <label className="block text-sm font-medium" htmlFor="workspace-name">
          {t('workspace.nameLabel')}
        </label>
        <Input
          id="workspace-name"
          autoFocus
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('workspace.namePlaceholder')}
        />
      </div>
      <div className="space-y-1.5">
        <label className="block text-sm font-medium" htmlFor="workspace-slug">
          {t('workspace.slugLabel')}
        </label>
        <Input
          id="workspace-slug"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t('workspace.slugHelp')}</p>
      </div>
      <Button type="submit" className="w-full" disabled={createWorkspace.isPending || !name.trim()}>
        {t('onboarding.createCompanyCta')}
      </Button>
    </form>
  )
}
