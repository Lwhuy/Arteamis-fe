import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { GraphLegend } from './GraphLegend'

describe('GraphLegend', () => {
  it('renders a KEY heading and all node kinds', () => {
    render(<GraphLegend />)
    expect(screen.getByText('intelligence.legend.title')).toBeInTheDocument()
    expect(screen.getByText('intelligence.legend.domain')).toBeInTheDocument()
    expect(screen.getByText('intelligence.legend.topic')).toBeInTheDocument()
    expect(screen.getByText('intelligence.legend.person')).toBeInTheDocument()
    expect(screen.getByText('intelligence.legend.source')).toBeInTheDocument()
  })

  it('renders all four semantic edge types', () => {
    render(<GraphLegend />)
    expect(screen.getByText('intelligence.legend.supersedes')).toBeInTheDocument()
    expect(screen.getByText('intelligence.legend.disagrees')).toBeInTheDocument()
    expect(screen.getByText('intelligence.legend.complements')).toBeInTheDocument()
    expect(screen.getByText('intelligence.legend.agrees')).toBeInTheDocument()
  })
})
