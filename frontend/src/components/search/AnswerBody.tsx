'use client'

import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { MarkdownRenderer } from '@/components/ui/markdown-renderer'
import { buildReferenceIndex, createCompactReferenceLinkComponent } from '@/lib/utils/source-references'
import { useModalManager } from '@/lib/hooks/use-modal-manager'
import { useTranslation } from '@/lib/hooks/use-translation'
import { toast } from 'sonner'

interface AnswerBodyProps {
  isStreaming: boolean
  finalAnswer: string | null
}

export function AnswerBody({ isStreaming, finalAnswer }: AnswerBodyProps) {
  const { openModal } = useModalManager()
  const { t } = useTranslation()

  const handleReferenceClick = (type: string, id: string) => {
    const modalType = type === 'source_insight' ? 'insight' : type as 'source' | 'note' | 'insight'

    try {
      openModal(modalType, id)
      // Note: The modal system uses URL parameters and doesn't throw errors for missing items.
      // The modal component itself will handle displaying "not found" states.
      // This try-catch is here for future enhancements or unexpected errors.
    } catch {
      const typeLabel = type === 'source_insight' ? 'insight' : type
      toast.error(t('common.itemNotFound').replace('{type}', typeLabel))
    }
  }

  if (!finalAnswer && !isStreaming) {
    return null
  }

  const LinkComponent = createCompactReferenceLinkComponent(handleReferenceClick)

  return (
    <div
      role="region"
      aria-label={t('common.accessibility.askResponse')}
      aria-live="polite"
      aria-busy={isStreaming}
    >
      {finalAnswer && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-2">
            {t('searchPage.answerLabel')}
          </p>
          <div>
            <MarkdownRenderer components={{ a: LinkComponent }}>
              {buildReferenceIndex(finalAnswer).numberedText}
            </MarkdownRenderer>
          </div>
        </div>
      )}

      {isStreaming && !finalAnswer && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoadingSpinner size="sm" />
          <span>{t('searchPage.processingQuestion')}</span>
        </div>
      )}
    </div>
  )
}
