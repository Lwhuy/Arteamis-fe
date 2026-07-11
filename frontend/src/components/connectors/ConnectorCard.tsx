'use client'

import { Connector } from '@/lib/api/connectors'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/hooks/use-translation'
import { ConnectorLogo } from './ConnectorLogo'

interface Props {
  connector: Connector
  onConnect: (provider: string) => void
}

export function ConnectorCard({ connector, onConnect }: Props) {
  const { t } = useTranslation()
  const comingSoon = connector.status === 'coming_soon'
  const canConnect = connector.status === 'configured'

  return (
    <div className={cn(
      'rounded-lg border p-4 flex flex-col gap-3',
      comingSoon && 'opacity-50',
    )}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <ConnectorLogo
            provider={connector.provider}
            label={connector.display_name}
            className="h-9 w-9 shrink-0"
          />
          <div>
            <div className="font-medium">{connector.display_name}</div>
            <p className="text-sm text-muted-foreground mt-1">{connector.description}</p>
          </div>
        </div>
        {comingSoon && <Badge variant="secondary" className="shrink-0">{t('connections.comingSoon')}</Badge>}
      </div>
      {!comingSoon && (
        <div className="mt-auto">
          <Button
            size="sm"
            disabled={!canConnect}
            title={canConnect ? undefined : t('connections.connectDisabledHint')}
            onClick={() => onConnect(connector.provider)}
          >
            {t('connections.connect')}
          </Button>
        </div>
      )}
    </div>
  )
}
