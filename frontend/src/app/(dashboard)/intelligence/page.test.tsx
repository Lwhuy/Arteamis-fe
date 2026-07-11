import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const useBrainStatus = vi.fn()
const useBrainGraph = vi.fn()
const rebuildMutate = vi.fn()
vi.mock('@/lib/hooks/use-brain-graph', () => ({
  useBrainStatus: () => useBrainStatus(),
  useBrainGraph: () => useBrainGraph(),
  useRebuildBrain: () => ({ mutate: rebuildMutate, isPending: false }),
}))
vi.mock('@/components/intelligence/GraphCanvas', () => ({ GraphCanvas: () => <div data-testid="graph-canvas" /> }))
vi.mock('@/components/intelligence/GraphLegend', () => ({ GraphLegend: () => <div data-testid="legend" /> }))
vi.mock('@/components/intelligence/NodeDetailPanel', () => ({ NodeDetailPanel: () => <div data-testid="detail" /> }))
vi.mock('@/components/intelligence/AskTheBrainPanel', () => ({ AskTheBrainPanel: () => <div data-testid="ask-the-brain-panel" /> }))
vi.mock('@/components/layout/AppShell', () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }))

import IntelligencePage from './page'

describe('IntelligencePage', () => {
  beforeEach(() => { rebuildMutate.mockReset() })

  it('shows the empty state with a rebuild button when nothing is built', () => {
    useBrainStatus.mockReturnValue({ data: { total_sources: 3, built_sources: 0, running: false }, isLoading: false })
    useBrainGraph.mockReturnValue({ graph: { nodes: [], edges: [] }, isLoading: false })
    render(<IntelligencePage />)
    expect(screen.getByText('intelligence.empty.title')).toBeInTheDocument()
    expect(screen.queryByTestId('graph-canvas')).not.toBeInTheDocument()
  })

  it('rebuild button triggers the mutation', () => {
    useBrainStatus.mockReturnValue({ data: { total_sources: 3, built_sources: 0, running: false }, isLoading: false })
    useBrainGraph.mockReturnValue({ graph: { nodes: [], edges: [] }, isLoading: false })
    render(<IntelligencePage />)
    fireEvent.click(screen.getByRole('button', { name: 'intelligence.rebuild' }))
    expect(rebuildMutate).toHaveBeenCalledWith('incremental')
  })

  it('shows the building state while running', () => {
    useBrainStatus.mockReturnValue({ data: { total_sources: 4, built_sources: 1, running: true }, isLoading: false })
    useBrainGraph.mockReturnValue({ graph: { nodes: [], edges: [] }, isLoading: false })
    render(<IntelligencePage />)
    expect(screen.getByText('intelligence.building.title')).toBeInTheDocument()
  })

  it('shows the canvas, legend and right-panel slot when populated', () => {
    useBrainStatus.mockReturnValue({ data: { total_sources: 4, built_sources: 4, running: false }, isLoading: false })
    useBrainGraph.mockReturnValue({
      graph: { nodes: [{ id: 'd', kind: 'domain', label: 'Eng', salience: 1 }], edges: [] },
      isLoading: false,
    })
    render(<IntelligencePage />)
    expect(screen.getByTestId('graph-canvas')).toBeInTheDocument()
    expect(screen.getByTestId('legend')).toBeInTheDocument()
    expect(screen.getByTestId('brain-right-panel')).toBeInTheDocument()
    expect(screen.getByTestId('ask-the-brain-panel')).toBeInTheDocument()
  })
})
