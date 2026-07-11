'use client'

import { ConnectionPublic } from '@/lib/api/connectors'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

interface Props {
  connection: ConnectionPublic
  onManage: (connection: ConnectionPublic) => void
  onDisconnect: (connectionId: string) => void
}

export function ConnectedSourceCard({ connection, onManage, onDisconnect }: Props) {
  const { t } = useTranslation()
  return (
    <div className="rounded-lg border p-4 flex items-center justify-between">
      <div>
        <div className="font-medium capitalize">{connection.provider}</div>
        <p className="text-sm text-muted-foreground">{connection.account_label}</p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={() => onManage(connection)}>
          {t('connections.import')}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDisconnect(connection.id)}>
          {t('connections.disconnect')}
        </Button>
      </div>
    </div>
  )
}
