import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { AxiosError } from 'axios'
import { workspacesApi } from '@/lib/api/workspaces'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useAuthStore } from '@/lib/stores/auth-store'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateWorkspaceRequest } from '@/lib/types/api'

export function useWorkspaces() {
  return useQuery({
    queryKey: QUERY_KEYS.workspaces,
    queryFn: () => workspacesApi.list(),
  })
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const applyToken = useAuthStore((s) => s.applyToken)

  return useMutation({
    mutationFn: (data: CreateWorkspaceRequest) => workspacesApi.create(data),
    onSuccess: (res) => {
      applyToken(res)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaces })
      toast({ title: t('common.success'), description: t('workspace.createSuccess') })
    },
    onError: (error: unknown) => {
      const status = (error as AxiosError)?.response?.status
      const description =
        status === 409 ? t('workspace.slugTaken') : t(getApiErrorKey(error, t('common.error')))
      toast({ title: t('common.error'), description, variant: 'destructive' })
    },
  })
}

export function useSwitchWorkspace() {
  const queryClient = useQueryClient()
  const router = useRouter()
  const { toast } = useToast()
  const { t } = useTranslation()
  const applyToken = useAuthStore((s) => s.applyToken)

  return useMutation({
    mutationFn: (workspaceId: string) => workspacesApi.switch(workspaceId),
    onSuccess: (res) => {
      applyToken(res)
      // A workspace change invalidates ALL workspace-scoped caches.
      queryClient.clear()
      toast({ title: t('common.success'), description: t('workspace.switchSuccess') })
      router.push('/notebooks')
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
