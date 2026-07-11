import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

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
import type { BrainAskStreamEvent } from '@/lib/types/brain'

function sseStream(lines: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const l of lines) controller.enqueue(enc.encode(l))
      controller.close()
    },
  })
}

const askParams = { question: 'q?', strategy_model: 's', answer_model: 'a', final_answer_model: 'f' }

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

describe('brainApi.askBrain', () => {
  afterEach(() => vi.restoreAllMocks())

  it('parses SSE data lines and invokes onEvent per event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      body: sseStream([
        'data: {"type":"answer","content":"A","cited_node_ids":["source:a"]}\n\n',
        'data: {"type":"complete","final_answer":"A","cited_node_ids":["source:a"]}\n\n',
      ]),
    }))

    const events: BrainAskStreamEvent[] = []
    await brainApi.askBrain(askParams, (e) => events.push(e))

    expect(events.map((e) => e.type)).toEqual(['answer', 'complete'])
    expect(events[0].cited_node_ids).toEqual(['source:a'])
  })

  it('throws "Stream failed: <status>" on non-ok response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 402, body: null }))
    await expect(brainApi.askBrain(askParams, () => {})).rejects.toThrow('Stream failed: 402')
  })
})
