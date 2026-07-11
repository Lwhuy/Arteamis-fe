import apiClient from './client'
import { CreateWorkspaceRequest, TokenResponse, WorkspaceResponse } from '@/lib/types/api'

export const workspacesApi = {
  list: () => apiClient.get<WorkspaceResponse[]>('/workspaces').then((r) => r.data),
  create: (data: CreateWorkspaceRequest) =>
    apiClient.post<TokenResponse>('/workspaces', data).then((r) => r.data),
  switch: (workspaceId: string) =>
    apiClient.post<TokenResponse>(`/auth/switch-workspace/${workspaceId}`).then((r) => r.data),
}
