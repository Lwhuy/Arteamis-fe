import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SourcesPanel } from './SourcesPanel'

vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('@/lib/hooks/use-modal-manager', () => ({ useModalManager: () => ({ openModal: vi.fn() }) }))

let queryResults: Array<{ data?: unknown; isLoading: boolean; isError: boolean }> = []
vi.mock('@tanstack/react-query', () => ({
  useQueries: () => queryResults,
}))

describe('SourcesPanel', () => {
  it('renders nothing when there are no references', () => {
    queryResults = []
    const { container } = render(<SourcesPanel references={[]} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders a numbered row with title and truncated snippet', () => {
    queryResults = [{ isLoading: false, isError: false, data: { title: 'My Source', full_text: 'hello world content' } }]
    render(<SourcesPanel references={[{ number: 1, type: 'source', id: 'a' }]} />)
    expect(screen.getByText('My Source')).toBeInTheDocument()
    expect(screen.getByText(/hello world content/)).toBeInTheDocument()
  })

  it('shows referenceUnavailable when a query errors', () => {
    queryResults = [{ isLoading: false, isError: true }]
    render(<SourcesPanel references={[{ number: 1, type: 'note', id: 'x' }]} />)
    expect(screen.getByText('searchPage.referenceUnavailable')).toBeInTheDocument()
  })
})
