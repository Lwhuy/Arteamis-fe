import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  governanceApi,
  type CreateProposalPayload,
  type CreateDecisionPayload,
  type CreateRulePayload,
} from '@/lib/api/governance'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

const KEYS = {
  proposals: ['proposals'] as const,
  beliefs: ['beliefs'] as const,
  decisions: ['decisions'] as const,
  rules: ['rules'] as const,
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

export const useDecisions = (status?: string) =>
  useQuery({
    queryKey: [...KEYS.decisions, status ?? 'all'],
    queryFn: () => governanceApi.listDecisions(status),
  })

export const useRules = (status?: string) =>
  useQuery({
    queryKey: [...KEYS.rules, status ?? 'all'],
    queryFn: () => governanceApi.listRules(status),
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

export function useCreateDecision() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (payload: CreateDecisionPayload) => governanceApi.createDecision(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.decisions })
      toast({ title: t('governance.toastDecisionCreated') })
    },
  })
}

export function useCreateRule() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (payload: CreateRulePayload) => governanceApi.createRule(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.rules })
      toast({ title: t('governance.toastRuleCreated') })
    },
  })
}
