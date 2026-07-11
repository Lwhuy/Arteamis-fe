'use client'

import { useState, useCallback } from 'react'
import { toast } from 'sonner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { brainApi } from '@/lib/api/brain'
import { useBrainStore } from '@/lib/stores/brain-store'
import type { BrainAskStreamEvent } from '@/lib/types/brain'

interface AskModels {
  strategy: string
  answer: string
  finalAnswer: string
}

interface StrategyData {
  reasoning: string
  searches: Array<{ term: string; instructions: string }>
}

interface BrainAskState {
  isStreaming: boolean
  strategy: StrategyData | null
  answers: string[]
  finalAnswer: string | null
  error: string | null
  citedNodeIds: string[]
}

const INITIAL: BrainAskState = {
  isStreaming: false,
  strategy: null,
  answers: [],
  finalAnswer: null,
  error: null,
  citedNodeIds: [],
}

export function useBrainAsk() {
  const { t } = useTranslation()
  const [state, setState] = useState<BrainAskState>(INITIAL)

  const sendAsk = useCallback(
    async (question: string, models: AskModels) => {
      if (!question.trim()) {
        toast.error(t('apiErrors.pleaseEnterQuestion'))
        return
      }
      if (!models.strategy || !models.answer || !models.finalAnswer) {
        toast.error(t('apiErrors.pleaseConfigureModels'))
        return
      }

      setState({ ...INITIAL, isStreaming: true })

      try {
        await brainApi.askBrain(
          {
            question,
            strategy_model: models.strategy,
            answer_model: models.answer,
            final_answer_model: models.finalAnswer,
          },
          (data: BrainAskStreamEvent) => {
            if (data.cited_node_ids && data.cited_node_ids.length > 0) {
              const ids = data.cited_node_ids
              setState((prev) => ({ ...prev, citedNodeIds: ids }))
              useBrainStore.getState().setHighlighted(ids)
            }
            if (data.type === 'strategy') {
              setState((prev) => ({
                ...prev,
                strategy: { reasoning: data.reasoning || '', searches: data.searches || [] },
              }))
            } else if (data.type === 'answer') {
              setState((prev) => ({ ...prev, answers: [...prev.answers, data.content || ''] }))
            } else if (data.type === 'final_answer') {
              setState((prev) => ({ ...prev, finalAnswer: data.content || '', isStreaming: false }))
            } else if (data.type === 'complete') {
              setState((prev) => ({ ...prev, isStreaming: false }))
            } else if (data.type === 'error') {
              throw new Error(data.message || 'Stream error occurred')
            }
          }
        )
        setState((prev) => ({ ...prev, isStreaming: false }))
      } catch (error) {
        const err = error as { message?: string }
        const errorMessage = err.message || 'An unexpected error occurred'
        console.error('Brain ask error:', error)
        setState((prev) => ({ ...prev, isStreaming: false, error: errorMessage }))
        toast.error(t('apiErrors.askFailed'), {
          description: getApiErrorMessage(errorMessage, (key) => t(key)),
        })
      }
    },
    [t]
  )

  const reset = useCallback(() => setState(INITIAL), [])

  return { ...state, sendAsk, reset }
}
