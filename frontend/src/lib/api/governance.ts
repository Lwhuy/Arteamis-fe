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

export interface Decision {
  id: string
  title: string
  rationale: string
  status: string
}

export interface Rule {
  id: string
  title: string
  statement: string
  status: string
}

export interface CreateDecisionPayload {
  title: string
  rationale?: string
  belief_ids: string[]
}

export interface CreateRulePayload {
  title: string
  statement: string
  belief_ids: string[]
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

  createDecision: (payload: CreateDecisionPayload) =>
    apiClient.post<Decision>('/decisions', payload).then((r) => r.data),

  listDecisions: (status?: string) =>
    apiClient.get<Decision[]>('/decisions', { params: { status } }).then((r) => r.data),

  createRule: (payload: CreateRulePayload) =>
    apiClient.post<Rule>('/rules', payload).then((r) => r.data),

  listRules: (status?: string) =>
    apiClient.get<Rule[]>('/rules', { params: { status } }).then((r) => r.data),
}
