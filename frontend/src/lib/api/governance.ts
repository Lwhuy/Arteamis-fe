import apiClient from '@/lib/api/client'

export interface Proposal {
  id: string
  title: string
  body: string
  status: string
  kind: string
  claim_type: string
  confidence: number
}

export interface Belief {
  id: string
  title: string
  body: string
  status: string
}

export interface CreateProposalPayload {
  kind?: string
  title: string
  body?: string
  claim_type?: string
  confidence?: number
  source_spans: { source_id: string; locator?: string }[]
}

export const governanceApi = {
  createProposal: (payload: CreateProposalPayload) =>
    apiClient.post<Proposal>('/proposals', payload).then((r) => r.data),

  listProposals: (status?: string) =>
    apiClient.get<Proposal[]>('/proposals', { params: { status } }).then((r) => r.data),

  acceptProposal: (id: string) =>
    apiClient.post<Belief>(`/proposals/${id}/accept`).then((r) => r.data),

  requestChanges: (id: string, note: string) =>
    apiClient.post<Proposal>(`/proposals/${id}/request-changes`, { note }).then((r) => r.data),

  listBeliefs: () => apiClient.get<Belief[]>('/beliefs').then((r) => r.data),

  getBelief: (id: string) => apiClient.get<Belief>(`/beliefs/${id}`).then((r) => r.data),
}
