import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ImportItemsDialog } from './ImportItemsDialog'

const importMutate = vi.fn()
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('@/lib/hooks/use-connectors', () => ({
  useConnectionItems: () => ({
    data: [{ id: 'f1', kind: 'file', title: 'Doc One' }, { id: 'f2', kind: 'file', title: 'Doc Two' }],
    isLoading: false,
  }),
  useImportItems: () => ({ mutate: importMutate, isPending: false }),
}))

describe('ImportItemsDialog', () => {
  it('imports the selected item ids', () => {
    render(<ImportItemsDialog open provider="gdrive" connectionId="connection:1" onOpenChange={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Doc One'))
    fireEvent.click(screen.getByRole('button', { name: /import/i }))
    expect(importMutate).toHaveBeenCalledWith(
      expect.objectContaining({ connection_id: 'connection:1', item_ids: ['f1'] }),
      expect.anything(),
    )
  })
})
