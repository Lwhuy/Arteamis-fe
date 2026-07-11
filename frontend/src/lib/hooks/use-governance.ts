import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  governanceApi,
  type CreateProposalPayload,
  type CreateDecisionPayload,
  type CreateRulePayload,
  type CreateWorkPackagePayload,
  type WorkPackage,
  type RecordTracePayload,
  type CreateLearningProposalPayload,
} from '@/lib/api/governance'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'

const KEYS = {
  proposals: ['proposals'] as const,
  beliefs: ['beliefs'] as const,
  decisions: ['decisions'] as const,
  rules: ['rules'] as const,
  workPackages: ['workPackages'] as const,
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

export const useWorkPackages = (status?: string) =>
  useQuery({
    queryKey: [...KEYS.workPackages, status ?? 'all'],
    queryFn: () => governanceApi.listWorkPackages(status),
  })

export const useWorkPackage = (id?: string) =>
  useQuery({
    queryKey: [...KEYS.workPackages, id],
    queryFn: () => governanceApi.getWorkPackage(id as string),
    enabled: !!id,
  })

export function useCreateWorkPackage() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (payload: CreateWorkPackagePayload) => governanceApi.createWorkPackage(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.workPackages })
      toast({ title: t('governance.toastWorkPackageCreated') })
    },
  })
}

export function useUpdateWorkPackageStatus() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: WorkPackage['status'] }) =>
      governanceApi.updateWorkPackageStatus(id, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.workPackages })
      toast({ title: t('governance.toastWorkPackageStatusUpdated') })
    },
  })
}

export const useTracesForWorkPackage = (workPackageId?: string) =>
  useQuery({
    queryKey: ['traces', workPackageId],
    queryFn: () => governanceApi.listTraces(workPackageId as string),
    enabled: !!workPackageId,
  })

export const useTrace = (id?: string) =>
  useQuery({
    queryKey: ['traces', 'detail', id],
    queryFn: () => governanceApi.getTrace(id as string),
    enabled: !!id,
  })

export function useRecordTrace() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ workPackageId, payload }: { workPackageId: string; payload: RecordTracePayload }) =>
      governanceApi.recordTrace(workPackageId, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['traces', variables.workPackageId] })
      toast({ title: t('governance.toastTraceRecorded') })
    },
  })
}

export function useCreateLearningProposal() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ traceId, payload }: { traceId: string; payload: CreateLearningProposalPayload }) =>
      governanceApi.createLearningProposal(traceId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEYS.proposals })
      toast({ title: t('governance.toastLearningProposed') })
    },
  })
}
