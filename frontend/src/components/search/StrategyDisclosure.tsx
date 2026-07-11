'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Sparkles, ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from '@/lib/hooks/use-translation'

interface StrategyData {
  reasoning: string
  searches: Array<{ term: string; instructions: string }>
}

interface StrategyDisclosureProps {
  strategy: StrategyData | null
  answers: string[]
}

export function StrategyDisclosure({ strategy, answers }: StrategyDisclosureProps) {
  const [open, setOpen] = useState(false)
  const { t } = useTranslation()

  if (!strategy && answers.length === 0) {
    return null
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card>
        <CardHeader>
          <CollapsibleTrigger className="flex items-center justify-between w-full hover:opacity-80">
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              {t('searchPage.strategyAndReasoning')}
            </CardTitle>
            <ChevronDown className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} />
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          <CardContent className="space-y-3 pt-0">
            {strategy && (
              <>
                <div>
                  <p className="text-sm text-muted-foreground mb-2">{t('common.reasoning')}:</p>
                  <p className="text-sm">{strategy.reasoning}</p>
                </div>
                {strategy.searches.length > 0 && (
                  <div>
                    <p className="text-sm text-muted-foreground mb-2">{t('common.searchTerms')}:</p>
                    <div className="space-y-2">
                      {strategy.searches.map((search, i) => (
                        <div key={i} className="flex items-start gap-2">
                          <Badge variant="outline" className="mt-0.5">{i + 1}</Badge>
                          <div className="flex-1">
                            <p className="text-sm font-medium">{search.term}</p>
                            <p className="text-xs text-muted-foreground">{search.instructions}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
            {answers.length > 0 && (
              <div>
                <p className="text-sm text-muted-foreground mb-2">
                  {t('common.individualAnswers').replace('{count}', answers.length.toString())}
                </p>
                <div className="space-y-2">
                  {answers.map((answer, i) => (
                    <div key={i} className="p-3 rounded-md bg-muted">
                      <p className="text-sm">{answer}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
