import apiClient from './client'

export interface ConnectionPublic {
  id: string
  provider: string
  account_label: string
  status: string
  created?: string | null
}

export type ConnectorStatus = 'connected' | 'configured' | 'available' | 'coming_soon'

export interface Connector {
  provider: string
  display_name: string
  description: string
  status: ConnectorStatus
  connections: ConnectionPublic[]
}

export interface ConnectorItem {
  id: string
  kind: string
  title: string
  subtitle?: string | null
  mime?: string | null
  modified_at?: string | null
}

export interface ImportResult {
  accepted: string[]
  failed: { item_id: string; error: string }[]
}

export interface ImportBody {
  connection_id: string
  item_ids: string[]
  notebooks?: string[]
}

export const connectorsApi = {
  async list(): Promise<Connector[]> {
    const { data } = await apiClient.get('/connectors')
    return data
  },
  async authorize(provider: string): Promise<{ authorize_url: string }> {
    const { data } = await apiClient.get(`/connectors/${provider}/authorize`)
    return data
  },
  async items(provider: string, connectionId: string): Promise<ConnectorItem[]> {
    const { data } = await apiClient.get(`/connectors/${provider}/items`, {
      params: { connection_id: connectionId },
    })
    return data
  },
  async import(provider: string, body: ImportBody): Promise<ImportResult> {
    const { data } = await apiClient.post(`/connectors/${provider}/import`, body)
    return data
  },
  async disconnect(connectionId: string): Promise<void> {
    await apiClient.delete(`/connectors/connections/${connectionId}`)
  },
}
