'use client'

import Link from 'next/link'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useBrainStore } from '@/lib/stores/brain-store'
import type { BrainGraph, BrainNodeKind } from '@/lib/types/brain'

interface NodeDetailPanelProps {
  graph?: BrainGraph
}

export function NodeDetailPanel({ graph }: NodeDetailPanelProps) {
  const { t } = useTranslation()
  const selectedNodeId = useBrainStore((s) => s.selectedNodeId)
  const node = graph?.nodes.find((n) => n.id === selectedNodeId)

  // Literal t() calls (rather than a templated key) so the i18n
  // "unused key" static-analysis check can find each key by substring.
  const kindLabels: Record<BrainNodeKind, string> = {
    domain: t('intelligence.detail.kind.domain'),
    topic: t('intelligence.detail.kind.topic'),
    person: t('intelligence.detail.kind.person'),
    decision: t('intelligence.detail.kind.decision'),
    source: t('intelligence.detail.kind.source'),
  }

  if (!node) {
    return (
      <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
        {t('intelligence.detail.empty')}
      </div>
    )
  }

  const sourceId = node.kind === 'source' ? node.id.replace(/^source:/, '') : null

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <div>
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {kindLabels[node.kind]}
        </p>
        <h3 className="text-lg font-semibold">{node.label}</h3>
      </div>
      <p className="text-sm text-muted-foreground">
        {t('intelligence.detail.salience')}: {node.salience.toFixed(2)}
      </p>
      {sourceId && (
        <Link
          href={`/sources/${sourceId}`}
          className="inline-block text-sm text-primary hover:underline"
        >
          {t('intelligence.detail.viewSource')}
        </Link>
      )}
    </div>
  )
}
