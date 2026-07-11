import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { governanceApi, type CreateProposalPayload } from '@/lib/api/governance'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

const KEYS = {
  proposals: ['proposals'] as const,
  beliefs: ['beliefs'] as const,
}

export const useProposals = (status?: string) =>
  useQuery({
    queryKey: [...KEYS.proposals, status ?? 'all'],
    queryFn: () => governanceApi.listProposals(status),
  })

export const useBeliefs = () =>
  useQuery({
    queryKey: KEYS.beliefs,
    queryFn: () => governanceApi.listBeliefs(),
  })

export const useBelief = (id?: string) =>
  useQuery({
    queryKey: [...KEYS.beliefs, id],
    queryFn: () => governanceApi.getBelief(id as string),
    enabled: !!id,
  })

export function useCreateProposal() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (payload: CreateProposalPayload) => governanceApi.createProposal(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.proposals })
      toast({ title: t('governance.toastProposed') })
    },
  })
}

export function useAcceptProposal() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (id: string) => governanceApi.acceptProposal(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.proposals })
      queryClient.invalidateQueries({ queryKey: KEYS.beliefs })
      toast({ title: t('governance.toastAccepted') })
    },
  })
}

export function useRequestChanges() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) => governanceApi.requestChanges(id, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.proposals })
      toast({ title: t('governance.toastChangesRequested') })
    },
  })
}
