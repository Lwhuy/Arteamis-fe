import apiClient from './client'
import type { AskRequest } from '@/lib/types/search'
import type { BrainAskStreamEvent, BrainGraph, BrainStatus } from '@/lib/types/brain'

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

  // Ask-the-Brain with streaming (uses relative URL for Docker compatibility)
  askBrain: async (
    params: AskRequest,
    onEvent: (event: BrainAskStreamEvent) => void
  ): Promise<void> => {
    // Get auth token using the same logic as apiClient interceptor
    let token: string | null = null
    if (typeof window !== 'undefined') {
      const authStorage = localStorage.getItem('auth-storage')
      if (authStorage) {
        try {
          const { state } = JSON.parse(authStorage)
          if (state?.token) {
            token = state.token
          }
        } catch (error) {
          console.error('Error parsing auth storage:', error)
        }
      }
    }

    // Use relative URL to leverage Next.js rewrites
    // This works both in dev (Next.js proxy) and production (Docker network)
    const response = await fetch('/api/brain/ask', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` })
      },
      body: JSON.stringify(params)
    })

    if (!response.ok) {
      throw new Error(`Stream failed: ${response.status}`)
    }

    if (!response.body) {
      throw new Error('No response body received')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()

      if (done) {
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')

      // Keep the last incomplete line in buffer
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const jsonStr = line.slice(6).trim()
            if (!jsonStr) continue

            const data: BrainAskStreamEvent = JSON.parse(jsonStr)
            onEvent(data)
          } catch (e) {
            if (e instanceof SyntaxError) {
              console.error('Error parsing SSE data:', e, 'Line:', line)
              // Don't throw - continue processing other lines
            } else {
              throw e
            }
          }
        }
      }
    }
  },
}
