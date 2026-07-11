import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { projectsApi } from '@/lib/api/projects'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateProjectRequest, UpdateProjectRequest } from '@/lib/types/api'

export function useProjects(archived?: boolean) {
  return useQuery({
    queryKey: [...QUERY_KEYS.projects, { archived }],
    queryFn: () => projectsApi.list({ archived, order_by: 'updated desc' }),
  })
}

export function useProject(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.project(id),
    queryFn: () => projectsApi.get(id),
    enabled: !!id,
  })
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: CreateProjectRequest) => projectsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects })
      toast({ title: t('common.success'), description: t('projects.createSuccess') })
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

export function useUpdateProject() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateProjectRequest }) =>
      projectsApi.update(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.project(id) })
      toast({ title: t('common.success'), description: t('projects.updateSuccess') })
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

export function useProjectDeletePreview(id: string, enabled: boolean = false) {
  return useQuery({
    queryKey: [...QUERY_KEYS.project(id), 'delete-preview'],
    queryFn: () => projectsApi.deletePreview(id),
    enabled: !!id && enabled,
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({
      id,
      deleteExclusiveSources = false,
    }: {
      id: string
      deleteExclusiveSources?: boolean
    }) => projectsApi.delete(id, deleteExclusiveSources),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects })
      // Also invalidate sources since some may have been deleted
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      toast({ title: t('common.success'), description: t('projects.deleteSuccess') })
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
