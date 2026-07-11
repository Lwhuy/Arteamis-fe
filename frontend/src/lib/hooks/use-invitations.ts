import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { invitationsApi } from '@/lib/api/invitations'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateInvitationRequest } from '@/lib/types/api'

export function useInvitations(workspaceId: string, status?: string) {
  return useQuery({
    queryKey: [...QUERY_KEYS.invitations(workspaceId), { status }],
    queryFn: () => invitationsApi.list(workspaceId, status),
    enabled: !!workspaceId,
  })
}

export function useMembers(workspaceId: string) {
  return useQuery({
    queryKey: QUERY_KEYS.members(workspaceId),
    queryFn: () => invitationsApi.members(workspaceId),
    enabled: !!workspaceId,
  })
}

export function useCreateInvitation(workspaceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: CreateInvitationRequest) => invitationsApi.create(workspaceId, data),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.invitations(workspaceId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.members(workspaceId) })
      toast({
        title: t('common.success'),
        // If the email wasn't sent, the dialog surfaces the copyable share link.
        description: res.email_sent ? t('invitations.emailedSuccess') : t('invitations.copyLinkTitle'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useRevokeInvitation(workspaceId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (invitationId: string) => invitationsApi.revoke(workspaceId, invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.invitations(workspaceId) })
      toast({ title: t('common.success'), description: t('invitations.revokeSuccess') })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useInvitationPreview(token: string) {
  return useQuery({
    queryKey: ['invitation-preview', token],
    queryFn: () => invitationsApi.preview(token),
    enabled: !!token,
    retry: false,
  })
}

export function useAcceptInvitation() {
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (token: string) => invitationsApi.accept(token),
    onSuccess: () => {
      toast({ title: t('common.success'), description: t('invitations.acceptSuccess') })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}
