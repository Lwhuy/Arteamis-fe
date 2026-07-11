import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SourceCard } from './SourceCard'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const base = {
  id: 'source:1', title: 'T', topics: [], asset: null, embedded: true,
  embedded_chunks: 1, insights_count: 0, created: 'c', updated: 'u',
  status: 'completed',
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient()
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

describe('SourceCard scope badge', () => {
  it('renders the personal badge', () => {
    renderWithClient(<SourceCard source={{ ...base, scope: 'personal' }} />)
    expect(screen.getByText('sources.visibilityPersonal')).toBeInTheDocument()
  })
  it('renders the project badge', () => {
    renderWithClient(<SourceCard source={{ ...base, scope: 'project' }} />)
    expect(screen.getByText('sources.visibilityProject')).toBeInTheDocument()
  })
  it('renders the company badge', () => {
    renderWithClient(<SourceCard source={{ ...base, scope: 'company' }} />)
    expect(screen.getByText('sources.visibilityCompany')).toBeInTheDocument()
  })
})
