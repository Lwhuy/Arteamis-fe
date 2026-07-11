import apiClient from './client'
import type { BrainGraph, BrainStatus } from '@/lib/types/brain'

export const brainApi = {
  getGraph: async (params?: { domain?: string; limit?: number }): Promise<BrainGraph> => {
    const response = await apiClient.get<BrainGraph>('/brain/graph', { params })
    return response.data
  },

  getStatus: async (): Promise<BrainStatus> => {
    const response = await apiClient.get<BrainStatus>('/brain/status')
    return response.data
  },

  rebuild: async (mode: 'incremental' | 'full'): Promise<{ command_id: string }> => {
    const response = await apiClient.post<{ command_id: string }>('/brain/rebuild', { mode })
    return response.data
  },
}
