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

export interface AgentBrief {
  objective: string
  allowed_context: string[]
  budget?: string
  approval_gate: boolean
}

export interface WorkPackage {
  id: string
  title: string
  assignee_kind: 'human' | 'agent'
  assignee?: string
  status: 'open' | 'running' | 'done'
  agent_brief?: AgentBrief
}

export interface CreateWorkPackagePayload {
  title: string
  assignee_kind?: 'human' | 'agent'
  assignee?: string
  agent_brief?: AgentBrief
  executes_ids: string[]
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

  createWorkPackage: (payload: CreateWorkPackagePayload) =>
    apiClient.post<WorkPackage>('/work-packages', payload).then((r) => r.data),

  listWorkPackages: (status?: string) =>
    apiClient.get<WorkPackage[]>('/work-packages', { params: { status } }).then((r) => r.data),

  getWorkPackage: (id: string) =>
    apiClient.get<WorkPackage>(`/work-packages/${id}`).then((r) => r.data),

  updateWorkPackageStatus: (id: string, status: WorkPackage['status']) =>
    apiClient.post<WorkPackage>(`/work-packages/${id}/status`, { status }).then((r) => r.data),
}
