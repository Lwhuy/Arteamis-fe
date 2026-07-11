'use client'

import { useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useConnectionItems, useImportItems } from '@/lib/hooks/use-connectors'
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
  const importItems = useImportItems(provider)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')
  const [notebooksInput, setNotebooksInput] = useState('')

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

  const onImport = () => {
    const notebooks = notebooksInput
      .split(',')
      .map((n) => n.trim())
      .filter(Boolean)
    importItems.mutate(
      {
        connection_id: connectionId,
        item_ids: Array.from(selected),
        ...(notebooks.length > 0 ? { notebooks } : {}),
      },
      { onSuccess: () => { setSelected(new Set()); setNotebooksInput(''); onOpenChange(false) } },
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
          <Input
            placeholder={t('connections.selectNotebook')}
            value={notebooksInput}
            onChange={(e) => setNotebooksInput(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
          <Button disabled={selected.size === 0 || importItems.isPending} onClick={onImport}>
            {t('connections.import')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
