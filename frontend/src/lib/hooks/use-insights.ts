import { useQuery } from '@tanstack/react-query'
import { insightsApi } from '@/lib/api/insights'

export function useInsight(id: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['insights', id],
    queryFn: () => insightsApi.get(id),
    enabled: options?.enabled !== false && !!id,
    staleTime: 30 * 1000, // 30 seconds
  })
}

/**
 * Insights already extracted for a single source (`source_insight`s), e.g. to
 * populate the control-plane chat's "agent insight card" once a source
 * finishes processing. Disabled by default until the caller knows the source
 * has actually completed processing (no point polling insights for a source
 * still queued/running).
 */
export function useSourceInsights(sourceId: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['sources', sourceId, 'insights'],
    queryFn: () => insightsApi.listForSource(sourceId),
    enabled: options?.enabled !== false && !!sourceId,
    staleTime: 30 * 1000,
  })
}
