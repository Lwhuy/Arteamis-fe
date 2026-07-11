import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useBrainAsk } from './use-brain-ask'
import { brainApi } from '@/lib/api/brain'

const setHighlighted = vi.fn()
vi.mock('@/lib/stores/brain-store', () => ({
  useBrainStore: { getState: () => ({ setHighlighted }) },
}))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('sonner', () => ({ toast: { error: vi.fn() } }))
vi.mock('@/lib/api/brain', () => ({ brainApi: { askBrain: vi.fn() } }))

const models = { strategy: 's', answer: 'a', finalAnswer: 'f' }

beforeEach(() => vi.clearAllMocks())

describe('useBrainAsk', () => {
  it('parses events, exposes citedNodeIds, and calls setHighlighted', async () => {
    vi.mocked(brainApi.askBrain).mockImplementation(async (_params, onEvent) => {
      onEvent({ type: 'answer', content: 'A', cited_node_ids: ['source:a', 'source:z'] })
      onEvent({ type: 'final_answer', content: 'Final', cited_node_ids: ['source:a', 'source:z'] })
      onEvent({ type: 'complete', final_answer: 'Final', cited_node_ids: ['source:a', 'source:z'] })
    })

    const { result } = renderHook(() => useBrainAsk())
    await act(async () => {
      await result.current.sendAsk('q?', models)
    })

    await waitFor(() => expect(result.current.finalAnswer).toBe('Final'))
    expect(result.current.answers).toEqual(['A'])
    expect(result.current.citedNodeIds).toEqual(['source:a', 'source:z'])
    expect(setHighlighted).toHaveBeenCalledWith(['source:a', 'source:z'])
    expect(result.current.isStreaming).toBe(false)
  })

  it('sets error state when the stream client throws', async () => {
    vi.mocked(brainApi.askBrain).mockRejectedValue(new Error('Stream failed: 402'))
    const { result } = renderHook(() => useBrainAsk())
    await act(async () => {
      await result.current.sendAsk('q?', models)
    })
    await waitFor(() => expect(result.current.error).toBe('Stream failed: 402'))
    expect(result.current.isStreaming).toBe(false)
  })
})
