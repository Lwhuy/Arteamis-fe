'use client'

import { useTranslation } from '@/lib/hooks/use-translation'
import { nodeColor, edgeColor } from './graph-transform'

type LegendNodeKind = 'domain' | 'topic' | 'person' | 'source'
type LegendEdgeType = 'supersedes' | 'disagrees' | 'complements' | 'agrees'

const NODE_KINDS: LegendNodeKind[] = ['domain', 'topic', 'person', 'source']
const EDGE_TYPES: LegendEdgeType[] = ['supersedes', 'disagrees', 'complements', 'agrees']

export function GraphLegend() {
  const { t } = useTranslation()

  // Literal t() calls (rather than a templated key) so the i18n
  // "unused key" static-analysis check can find each key by substring.
  const nodeLabels: Record<LegendNodeKind, string> = {
    domain: t('intelligence.legend.domain'),
    topic: t('intelligence.legend.topic'),
    person: t('intelligence.legend.person'),
    source: t('intelligence.legend.source'),
  }
  const edgeLabels: Record<LegendEdgeType, string> = {
    supersedes: t('intelligence.legend.supersedes'),
    disagrees: t('intelligence.legend.disagrees'),
    complements: t('intelligence.legend.complements'),
    agrees: t('intelligence.legend.agrees'),
  }

  return (
    <div className="rounded-lg border bg-card p-3 text-xs space-y-3">
      <h3 className="font-semibold uppercase tracking-wide text-muted-foreground">
        {t('intelligence.legend.title')}
      </h3>
      <div className="space-y-1.5">
        <p className="text-muted-foreground">{t('intelligence.legend.nodes')}</p>
        {NODE_KINDS.map((kind) => (
          <div key={kind} className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 rounded-full"
              style={{ backgroundColor: nodeColor(kind) }}
              aria-hidden
            />
            <span>{nodeLabels[kind]}</span>
          </div>
        ))}
      </div>
      <div className="space-y-1.5">
        <p className="text-muted-foreground">{t('intelligence.legend.relationships')}</p>
        {EDGE_TYPES.map((type) => (
          <div key={type} className="flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-5"
              style={{
                backgroundColor: edgeColor(type),
                borderTop: type === 'supersedes' ? `2px dashed ${edgeColor(type)}` : undefined,
                height: type === 'supersedes' ? 0 : undefined,
              }}
              aria-hidden
            />
            <span>{edgeLabels[type]}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
