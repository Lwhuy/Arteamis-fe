import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { connectorsApi, ImportBody } from '@/lib/api/connectors'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'

export const CONNECTOR_QUERY_KEYS = {
  all: ['connectors'] as const,
  items: (provider: string, connectionId: string) =>
    ['connectors', provider, 'items', connectionId] as const,
}

export function useConnectors() {
  return useQuery({
    queryKey: CONNECTOR_QUERY_KEYS.all,
    queryFn: () => connectorsApi.list(),
  })
}

export function useConnectionItems(provider: string, connectionId: string, enabled: boolean) {
  return useQuery({
    queryKey: CONNECTOR_QUERY_KEYS.items(provider, connectionId),
    queryFn: () => connectorsApi.items(provider, connectionId),
    enabled: enabled && !!connectionId,
  })
}

export function useStartConnect() {
  const { t } = useTranslation()
  return useMutation({
    mutationFn: (provider: string) => connectorsApi.authorize(provider),
    onSuccess: (data) => { window.location.href = data.authorize_url },
    onError: (e) => toast.error(t(getApiErrorKey(e))),
  })
}

export function useImportItems(provider: string) {
  const { t } = useTranslation()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ImportBody) => connectorsApi.import(provider, body),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['sources'] })
      if (res.failed.length === 0) {
        toast.success(t('connections.importStarted').replace('{count}', String(res.accepted.length)))
      } else {
        toast.warning(
          t('connections.importPartial')
            .replace('{ok}', String(res.accepted.length))
            .replace('{fail}', String(res.failed.length)),
        )
      }
    },
    onError: (e) => toast.error(t(getApiErrorKey(e))),
  })
}

export function useDisconnect() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (connectionId: string) => connectorsApi.disconnect(connectionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CONNECTOR_QUERY_KEYS.all })
      toast.success(t('connections.disconnected'))
    },
    onError: (e) => toast.error(t(getApiErrorKey(e))),
  })
}
