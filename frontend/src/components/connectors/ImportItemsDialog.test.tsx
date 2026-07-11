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
vi.mock('@/lib/hooks/use-projects', () => ({
  useProjects: () => ({
    data: [{ id: 'notebook:1', name: 'Notebook One' }, { id: 'notebook:2', name: 'Notebook Two' }],
    isLoading: false,
  }),
}))

describe('ImportItemsDialog', () => {
  it('disables Import until an item and a notebook are both selected', () => {
    render(<ImportItemsDialog open provider="gdrive" connectionId="connection:1" onOpenChange={vi.fn()} />)
    const importButton = screen.getByRole('button', { name: /import/i })
    expect(importButton).toBeDisabled()

    fireEvent.click(screen.getByLabelText('Doc One'))
    expect(importButton).toBeDisabled()

    fireEvent.click(screen.getByLabelText('Notebook One'))
    expect(importButton).not.toBeDisabled()
  })

  it('imports the selected item ids and notebook ids', () => {
    render(<ImportItemsDialog open provider="gdrive" connectionId="connection:1" onOpenChange={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Doc One'))
    fireEvent.click(screen.getByLabelText('Notebook One'))
    fireEvent.click(screen.getByRole('button', { name: /import/i }))
    expect(importMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        connection_id: 'connection:1',
        item_ids: ['f1'],
        notebooks: ['notebook:1'],
      }),
      expect.anything(),
    )
  })
})
