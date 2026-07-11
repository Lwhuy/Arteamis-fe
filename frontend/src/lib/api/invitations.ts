import apiClient from './client'
import {
  InvitationResponse,
  CreateInvitationRequest,
  InvitationCreateResponse,
  InvitationPreviewResponse,
  AcceptInvitationResponse,
  MemberResponse,
} from '@/lib/types/api'

export const invitationsApi = {
  list: async (workspaceId: string, status?: string) => {
    const response = await apiClient.get<InvitationResponse[]>(
      `/workspaces/${workspaceId}/invitations`,
      { params: status ? { status } : undefined },
    )
    return response.data
  },

  create: async (workspaceId: string, data: CreateInvitationRequest) => {
    const response = await apiClient.post<InvitationCreateResponse>(
      `/workspaces/${workspaceId}/invitations`,
      data,
    )
    return response.data
  },

  revoke: async (workspaceId: string, invitationId: string) => {
    const response = await apiClient.post<InvitationResponse>(
      `/workspaces/${workspaceId}/invitations/${invitationId}/revoke`,
    )
    return response.data
  },

  preview: async (token: string) => {
    const response = await apiClient.get<InvitationPreviewResponse>(`/invitations/${token}`)
    return response.data
  },

  accept: async (token: string) => {
    const response = await apiClient.post<AcceptInvitationResponse>(
      `/invitations/${token}/accept`,
    )
    return response.data
  },

  members: async (workspaceId: string) => {
    const response = await apiClient.get<MemberResponse[]>(`/workspaces/${workspaceId}/members`)
    return response.data
  },
}
