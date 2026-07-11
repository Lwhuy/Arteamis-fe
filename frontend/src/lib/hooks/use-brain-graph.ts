import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { brainApi } from '@/lib/api/brain'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'

export function useBrainGraph(params?: { domain?: string; limit?: number }) {
  const query = useQuery({
    queryKey: ['brain', 'graph', params ?? {}],
    queryFn: () => brainApi.getGraph(params),
    staleTime: 30 * 1000,
  })
  return { graph: query.data, isLoading: query.isLoading, isError: query.isError, refetch: query.refetch }
}

export function useBrainStatus() {
  return useQuery({
    queryKey: ['brain', 'status'],
    queryFn: () => brainApi.getStatus(),
    refetchInterval: (query) => (query.state.data?.running ? 3000 : false),
    staleTime: 0,
  })
}

export function useRebuildBrain() {
  const queryClient = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn: (mode: 'incremental' | 'full') => brainApi.rebuild(mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['brain'] })
      toast.success(t('intelligence.rebuildStarted'))
    },
    onError: (error: Error) => {
      toast.error(t(getApiErrorKey(error.message)))
    },
  })
}
