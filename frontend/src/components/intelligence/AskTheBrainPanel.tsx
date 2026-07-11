'use client'

import { useState } from 'react'
import { Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { AnswerBody } from '@/components/search/AnswerBody'
import { StrategyDisclosure } from '@/components/search/StrategyDisclosure'
import { SourcesPanel } from '@/components/search/SourcesPanel'
import { AnswerFeedback } from '@/components/search/AnswerFeedback'
import { useBrainAsk } from '@/lib/hooks/use-brain-ask'
import { useModelDefaults } from '@/lib/hooks/use-models'
import { useTranslation } from '@/lib/hooks/use-translation'
import { buildReferenceIndex } from '@/lib/utils/source-references'

/**
 * Graph-aware Q&A panel mounted in the Intelligence page's right-hand slot.
 * Reuses the existing search Ask components; wired to `useBrainAsk` (which
 * streams `/brain/ask` and highlights cited nodes on the graph as they arrive).
 */
export function AskTheBrainPanel() {
  const { t } = useTranslation()
  const [question, setQuestion] = useState('')
  const { data: modelDefaults } = useModelDefaults()
  const { isStreaming, strategy, answers, finalAnswer, error, sendAsk } = useBrainAsk()

  const chatModel = modelDefaults?.default_chat_model

  const handleSend = () => {
    if (!question.trim() || !chatModel) return
    sendAsk(question, { strategy: chatModel, answer: chatModel, finalAnswer: chatModel })
  }

  const references = finalAnswer ? buildReferenceIndex(finalAnswer).references : []

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">{t('intelligence.askTitle')}</h2>

      <div className="space-y-3">
        <StrategyDisclosure strategy={strategy} answers={answers} />
        <AnswerBody isStreaming={isStreaming} finalAnswer={finalAnswer} />
        {finalAnswer && <AnswerFeedback answer={finalAnswer} />}
        {references.length > 0 && <SourcesPanel references={references} />}
        {error && (
          <div
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive"
          >
            {error}
          </div>
        )}
      </div>

      <div className="flex items-end gap-2">
        <Textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('intelligence.askPlaceholder')}
          rows={2}
          disabled={isStreaming}
          aria-label={t('intelligence.askTitle')}
        />
        <Button
          onClick={handleSend}
          disabled={isStreaming || !question.trim() || !chatModel}
          size="icon"
          aria-label={t('intelligence.askSend')}
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
