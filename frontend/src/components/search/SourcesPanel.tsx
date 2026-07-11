'use client'

import { useQueries } from '@tanstack/react-query'
import { FileText, FileEdit, Lightbulb } from 'lucide-react'
import { sourcesApi } from '@/lib/api/sources'
import { notesApi } from '@/lib/api/notes'
import { insightsApi } from '@/lib/api/insights'
import { useModalManager, type ModalType } from '@/lib/hooks/use-modal-manager'
import { useTranslation } from '@/lib/hooks/use-translation'
import { truncateSnippet, type ReferenceIndexEntry } from '@/lib/utils/source-references'

interface SourcesPanelProps {
  references: ReferenceIndexEntry[]
}

const SNIPPET_MAX = 150

function fullId(type: string, id: string) {
  return id.includes(':') ? id : `${type}:${id}`
}

export function SourcesPanel({ references }: SourcesPanelProps) {
  const { t } = useTranslation()
  const { openModal } = useModalManager()

  const results = useQueries({
    queries: references.map((ref) => {
      const fid = fullId(ref.type, ref.id)
      if (ref.type === 'note') {
        return { queryKey: ['notes', fid], queryFn: () => notesApi.get(fid) }
      }
      if (ref.type === 'source_insight') {
        return { queryKey: ['insights', fid], queryFn: () => insightsApi.get(fid) }
      }
      return { queryKey: ['sources', fid], queryFn: () => sourcesApi.get(fid) }
    }),
  })

  if (references.length === 0) return null

  return (
    <aside className="w-full lg:w-64 shrink-0 space-y-3" aria-label={t('searchPage.sources')}>
      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t('searchPage.sources')} ({references.length})
      </p>
      {references.map((ref, i) => {
        const q = results[i]
        const data = q?.data as
          | { title?: string | null; full_text?: string; content?: string | null; insight_type?: string }
          | undefined

        const Icon = ref.type === 'source' ? FileText : ref.type === 'note' ? FileEdit : Lightbulb
        const modalType: ModalType = ref.type === 'source_insight' ? 'insight' : (ref.type as ModalType)

        const title =
          data?.title ?? data?.insight_type ?? `${ref.type}:${ref.id}`
        const rawSnippet = data?.full_text ?? data?.content ?? ''
        const unavailable = q?.isError || (!q?.isLoading && !data)

        return (
          <button
            key={`${ref.type}:${ref.id}`}
            onClick={() => openModal(modalType, ref.id)}
            className="w-full text-left rounded-md border p-3 hover:bg-muted transition-colors"
          >
            <div className="flex items-center gap-2 text-sm font-medium">
              <span className="text-xs text-muted-foreground">{ref.number}</span>
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{title}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {unavailable
                ? t('searchPage.referenceUnavailable')
                : truncateSnippet(rawSnippet, SNIPPET_MAX)}
            </p>
          </button>
        )
      })}
    </aside>
  )
}
