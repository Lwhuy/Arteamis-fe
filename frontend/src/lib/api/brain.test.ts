import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockGet, mockPost } = vi.hoisted(() => {
  return {
    mockGet: vi.fn(),
    mockPost: vi.fn(),
  }
})

vi.mock('./client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
  },
}))

import { brainApi } from './brain'

describe('brainApi', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
  })

  it('getGraph calls GET /brain/graph with params and returns data', async () => {
    mockGet.mockResolvedValue({ data: { nodes: [], edges: [] } })
    const result = await brainApi.getGraph({ domain: 'engineering', limit: 50 })
    expect(mockGet).toHaveBeenCalledWith('/brain/graph', { params: { domain: 'engineering', limit: 50 } })
    expect(result).toEqual({ nodes: [], edges: [] })
  })

  it('getGraph works with no params', async () => {
    mockGet.mockResolvedValue({ data: { nodes: [], edges: [] } })
    await brainApi.getGraph()
    expect(mockGet).toHaveBeenCalledWith('/brain/graph', { params: undefined })
  })

  it('getStatus calls GET /brain/status', async () => {
    mockGet.mockResolvedValue({ data: { total_sources: 3, built_sources: 1, running: true } })
    const result = await brainApi.getStatus()
    expect(mockGet).toHaveBeenCalledWith('/brain/status')
    expect(result.running).toBe(true)
  })

  it('rebuild POSTs the mode and returns command_id', async () => {
    mockPost.mockResolvedValue({ data: { command_id: 'cmd-1' } })
    const result = await brainApi.rebuild('full')
    expect(mockPost).toHaveBeenCalledWith('/brain/rebuild', { mode: 'full' })
    expect(result.command_id).toBe('cmd-1')
  })
})
