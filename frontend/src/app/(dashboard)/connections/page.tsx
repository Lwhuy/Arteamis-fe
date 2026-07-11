'use client'

import { useState } from 'react'
import { AppShell } from '@/components/layout/AppShell'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ConnectorCard, ConnectedSourceCard, ImportItemsDialog } from '@/components/connectors'
import { useConnectors, useStartConnect, useDisconnect } from '@/lib/hooks/use-connectors'
import { ConnectionPublic } from '@/lib/api/connectors'
import { useTranslation } from '@/lib/hooks/use-translation'

export default function ConnectionsPage() {
  const { t } = useTranslation()
  const { data: connectors, isLoading } = useConnectors()
  const startConnect = useStartConnect()
  const disconnect = useDisconnect()
  const [manage, setManage] = useState<{ provider: string; connection: ConnectionPublic } | null>(null)

  if (isLoading) return <AppShell><LoadingSpinner /></AppShell>

  const connected = (connectors ?? []).flatMap((c) =>
    c.connections.map((conn) => ({ provider: c.provider, conn })))

  return (
    <AppShell>
      <div className="max-w-4xl mx-auto p-6 space-y-8">
        <div>
          <h1 className="text-2xl font-semibold">{t('connections.title')}</h1>
          <p className="text-muted-foreground">{t('connections.subtitle')}</p>
        </div>

        {connected.length > 0 && (
          <section className="space-y-3">
            <h2 className="text-sm uppercase text-muted-foreground">{t('connections.connected')}</h2>
            {connected.map(({ provider, conn }) => (
              <ConnectedSourceCard
                key={conn.id}
                connection={conn}
                onManage={(c) => setManage({ provider, connection: c })}
                onDisconnect={(id) => disconnect.mutate(id)}
              />
            ))}
          </section>
        )}

        <section className="space-y-3">
          <h2 className="text-sm uppercase text-muted-foreground">{t('connections.addMore')}</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {(connectors ?? [])
              .filter((c) => c.status !== 'connected')
              .map((c) => (
                <ConnectorCard key={c.provider} connector={c}
                  onConnect={(p) => startConnect.mutate(p)} />
              ))}
          </div>
        </section>
      </div>

      {manage && (
        <ImportItemsDialog
          open={!!manage}
          provider={manage.provider}
          connectionId={manage.connection.id}
          onOpenChange={(o) => !o && setManage(null)}
        />
      )}
    </AppShell>
  )
}
