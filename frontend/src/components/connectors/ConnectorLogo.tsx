'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'

// Providers with a bundled brand logo under /public/connectors/<provider>.svg.
const LOGO_PROVIDERS = new Set([
  'gdrive', 'slack', 'notion', 'sharepoint', 'box',
  'dropbox', 'confluence', 'msteams', 'gmail', 's3',
])

interface Props {
  provider: string
  /** Used for the alt text and the letter fallback. */
  label: string
  className?: string
}

/**
 * Renders a connector's bundled brand logo, falling back to a neutral
 * lettered tile if the provider has no asset or the image fails to load.
 */
export function ConnectorLogo({ provider, label, className }: Props) {
  const [failed, setFailed] = useState(false)

  if (failed || !LOGO_PROVIDERS.has(provider)) {
    return (
      <div
        className={cn(
          'flex items-center justify-center rounded-md bg-muted text-sm font-semibold uppercase text-muted-foreground',
          className,
        )}
        aria-hidden="true"
      >
        {label.charAt(0)}
      </div>
    )
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- static bundled SVG, no optimization needed
    <img
      src={`/connectors/${provider}.svg`}
      alt={`${label} logo`}
      className={cn('object-contain', className)}
      onError={() => setFailed(true)}
    />
  )
}
