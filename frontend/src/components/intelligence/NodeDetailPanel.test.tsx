import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NodeDetailPanel } from './NodeDetailPanel'
import { useBrainStore } from '@/lib/stores/brain-store'
import type { BrainGraph } from '@/lib/types/brain'

const graph: BrainGraph = {
  nodes: [
    { id: 'domain:eng', kind: 'domain', label: 'Engineering', salience: 3 },
    { id: 'source:abc', kind: 'source', label: 'Design Doc', salience: 1 },
  ],
  edges: [],
}

describe('NodeDetailPanel', () => {
  beforeEach(() => {
    useBrainStore.setState({ selectedNodeId: null, highlightedNodeIds: [], panelOpen: false })
  })

  it('shows an empty prompt when no node is selected', () => {
    render(<NodeDetailPanel graph={graph} />)
    expect(screen.getByText('intelligence.detail.empty')).toBeInTheDocument()
  })

  it('shows the selected node label and kind', () => {
    useBrainStore.setState({ selectedNodeId: 'domain:eng' })
    render(<NodeDetailPanel graph={graph} />)
    expect(screen.getByText('Engineering')).toBeInTheDocument()
    expect(screen.getByText('intelligence.detail.kind.domain')).toBeInTheDocument()
  })

  it('renders a source deep link for a source node', () => {
    useBrainStore.setState({ selectedNodeId: 'source:abc' })
    render(<NodeDetailPanel graph={graph} />)
    const link = screen.getByRole('link', { name: 'intelligence.detail.viewSource' })
    expect(link).toHaveAttribute('href', '/sources/abc')
  })
})
