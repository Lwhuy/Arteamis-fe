'use client'

import { ThumbsUp, ThumbsDown, Copy } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'

interface AnswerFeedbackProps {
  answer: string
  children?: React.ReactNode
}

export function AnswerFeedback({ answer, children }: AnswerFeedbackProps) {
  const { t } = useTranslation()

  const thanks = () => toast.success(t('searchPage.feedbackThanks'))

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(answer)
      toast.success(t('searchPage.answerCopied'))
    } catch {
      // clipboard can reject on insecure contexts; fail quietly
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="sm" onClick={thanks} aria-label={t('searchPage.helpfulYes')}>
        <ThumbsUp className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="sm" onClick={thanks} aria-label={t('searchPage.helpfulNo')}>
        <ThumbsDown className="h-4 w-4" />
      </Button>
      <Button variant="ghost" size="sm" onClick={copy} aria-label={t('searchPage.copyAnswer')}>
        <Copy className="h-4 w-4 mr-1" />
        {t('searchPage.copyAnswer')}
      </Button>
      {children ? <div className="ml-auto">{children}</div> : null}
    </div>
  )
}
