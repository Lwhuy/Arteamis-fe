'use client'

import { useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useConnectionItems, useImportItems } from '@/lib/hooks/use-connectors'
import { useProjects } from '@/lib/hooks/use-projects'
import { useTranslation } from '@/lib/hooks/use-translation'

interface Props {
  open: boolean
  provider: string
  connectionId: string
  onOpenChange: (open: boolean) => void
}

export function ImportItemsDialog({ open, provider, connectionId, onOpenChange }: Props) {
  const { t } = useTranslation()
  const { data: items, isLoading } = useConnectionItems(provider, connectionId, open)
  const { data: notebooks = [], isLoading: notebooksLoading } = useProjects()
  const importItems = useImportItems(provider)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')
  const [selectedNotebooks, setSelectedNotebooks] = useState<Set<string>>(new Set())

  const filtered = useMemo(
    () => (items ?? []).filter((i) => i.title.toLowerCase().includes(query.toLowerCase())),
    [items, query],
  )

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const toggleNotebook = (id: string) => {
    setSelectedNotebooks((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  // Every import must be bound to at least one notebook in the caller's
  // workspace (P5 visibility: an unbound source is invisible to everyone,
  // including the importer). The backend enforces this too -- this is UX,
  // not the security boundary.
  const canImport =
    selected.size > 0 && selectedNotebooks.size > 0 && notebooks.length > 0

  const onImport = () => {
    importItems.mutate(
      {
        connection_id: connectionId,
        item_ids: Array.from(selected),
        notebooks: Array.from(selectedNotebooks),
      },
      {
        onSuccess: () => {
          setSelected(new Set())
          setSelectedNotebooks(new Set())
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>{t('connections.pickItems')}</DialogTitle></DialogHeader>
        <Input placeholder={t('connections.searchItems')} value={query}
               onChange={(e) => setQuery(e.target.value)} />
        <div className="max-h-80 overflow-y-auto space-y-1 mt-2">
          {isLoading && <LoadingSpinner />}
          {!isLoading && filtered.length === 0 && (
            <p className="text-sm text-muted-foreground">{t('connections.noItems')}</p>
          )}
          {filtered.map((item) => (
            <label key={item.id} className="flex items-center gap-2 py-1 cursor-pointer">
              <Checkbox
                aria-label={item.title}
                checked={selected.has(item.id)}
                onCheckedChange={() => toggle(item.id)}
              />
              <span className="text-sm truncate">{item.title}</span>
            </label>
          ))}
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">{t('connections.selectNotebook')}</label>
          <div className="max-h-40 overflow-y-auto space-y-1 border border-border rounded-md p-2">
            {notebooksLoading && <LoadingSpinner />}
            {!notebooksLoading && notebooks.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('sources.noNotebooksFound')}</p>
            )}
            {notebooks.map((notebook) => (
              <label key={notebook.id} className="flex items-center gap-2 py-1 cursor-pointer">
                <Checkbox
                  aria-label={notebook.name}
                  checked={selectedNotebooks.has(notebook.id)}
                  onCheckedChange={() => toggleNotebook(notebook.id)}
                />
                <span className="text-sm truncate">{notebook.name}</span>
              </label>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
          <Button disabled={!canImport || importItems.isPending} onClick={onImport}>
            {t('connections.import')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
