'use client'

import { useTranslation } from '@/lib/hooks/use-translation'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { GraphCanvas } from '@/components/intelligence/GraphCanvas'
import { GraphLegend } from '@/components/intelligence/GraphLegend'
import { NodeDetailPanel } from '@/components/intelligence/NodeDetailPanel'
import { AskTheBrainPanel } from '@/components/intelligence/AskTheBrainPanel'
import { useBrainStatus, useBrainGraph, useRebuildBrain } from '@/lib/hooks/use-brain-graph'

export default function IntelligencePage() {
  const { t } = useTranslation()
  const { data: status, isLoading: statusLoading } = useBrainStatus()
  const { graph, isLoading: graphLoading } = useBrainGraph()
  const rebuild = useRebuildBrain()

  // TODO(role): swap for a real membership/role hook once P2/P6 role infra is
  // surfaced on the frontend. Personal workspace role is always `owner`, so the
  // gate defaults open; the backend still enforces owner/admin on /brain/rebuild.
  const canRebuild = true

  const isRunning = !!status?.running
  const built = status?.built_sources ?? 0
  const total = status?.total_sources ?? 0
  const isBuilding = isRunning || (total > 0 && built < total && built > 0)
  const isEmpty = !statusLoading && built === 0 && !isRunning

  const rebuildButton = canRebuild ? (
    <Button
      onClick={() => rebuild.mutate('incremental')}
      disabled={rebuild.isPending || isRunning}
    >
      {t('intelligence.rebuild')}
    </Button>
  ) : null

  return (
    <AppShell>
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Center: canvas / state */}
        <div className="flex-1 min-w-0 flex flex-col p-4 md:p-6">
          <div className="mb-4 flex items-center justify-between gap-2">
            <h1 className="text-xl md:text-2xl font-bold">{t('intelligence.title')}</h1>
            {!isEmpty && rebuildButton}
          </div>

          {statusLoading || graphLoading ? (
            <div className="flex flex-1 items-center justify-center">
              <LoadingSpinner />
            </div>
          ) : isEmpty ? (
            <div className="flex flex-1 flex-col items-center justify-center text-center gap-3">
              <h2 className="text-lg font-semibold">{t('intelligence.empty.title')}</h2>
              <p className="max-w-md text-sm text-muted-foreground">
                {t('intelligence.empty.description')}
              </p>
              {rebuildButton}
            </div>
          ) : isBuilding ? (
            <div className="flex flex-1 flex-col items-center justify-center text-center gap-3">
              <LoadingSpinner />
              <h2 className="text-lg font-semibold">{t('intelligence.building.title')}</h2>
              <p className="text-sm text-muted-foreground">
                {t('intelligence.building.progress')
                  .replace('{built}', String(built))
                  .replace('{total}', String(total))}
              </p>
            </div>
          ) : (
            <div className="relative flex-1 min-h-0 rounded-lg border overflow-hidden">
              {graph && <GraphCanvas graph={graph} />}
              <div className="absolute bottom-3 left-3 z-10">
                <GraphLegend />
              </div>
            </div>
          )}
        </div>

        {/* Right panel slot: NodeDetailPanel + AskTheBrainPanel (graph-aware Q&A). */}
        <aside
          data-testid="brain-right-panel"
          className="hidden lg:flex w-80 flex-col gap-4 border-l p-4 overflow-y-auto"
        >
          <NodeDetailPanel graph={graph} />
          <AskTheBrainPanel />
        </aside>
      </div>
    </AppShell>
  )
}
