import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useState, useEffect } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { useBrainStore } from '@/lib/stores/brain-store'
import type { BrainGraph } from '@/lib/types/brain'

// Mock next/dynamic so the { ssr:false } import resolves to the mocked lib.
// Note: unlike the brief's sketch, this project's vitest/vite setup does not
// let a CJS `require()` inside a vi.mock factory see other vi.mock'd modules
// (only ESM `import()` goes through vitest's module registry here) — verified
// via a throwaway test. So we resolve the loader's promise (which IS mocked,
// since it's a real dynamic `import()`) asynchronously instead.
vi.mock('next/dynamic', () => ({
  default: (loader: () => Promise<{ default: React.ComponentType<Record<string, unknown>> }>) => {
    return function DynamicStub(props: Record<string, unknown>) {
      const [Comp, setComp] = useState<React.ComponentType<Record<string, unknown>> | null>(null)
      useEffect(() => {
        let mounted = true
        loader().then((mod) => {
          if (mounted) setComp(() => mod.default)
        })
        return () => {
          mounted = false
        }
      }, [])
      if (!Comp) return null
      return <Comp {...props} />
    }
  },
}))

// Stub the canvas-only lib: render node count, expose a button that triggers onNodeClick.
vi.mock('react-force-graph-2d', () => ({
  default: ({
    graphData,
    onNodeClick,
  }: {
    graphData: { nodes: { id: string }[] }
    onNodeClick: (n: { id: string }) => void
  }) => (
    <div data-testid="force-graph">
      <span data-testid="node-count">{graphData.nodes.length}</span>
      <button
        data-testid="fire-click"
        onClick={() => onNodeClick({ id: graphData.nodes[0].id })}
      >
        click-node
      </button>
    </div>
  ),
}))

import { GraphCanvas } from './GraphCanvas'

const graph: BrainGraph = {
  nodes: [
    { id: 'domain:eng', kind: 'domain', label: 'Engineering', salience: 3 },
    { id: 'source:abc', kind: 'source', label: 'Doc', salience: 1 },
  ],
  edges: [{ source: 'source:abc', target: 'domain:eng', type: 'mentions' }],
}

describe('GraphCanvas', () => {
  beforeEach(() => {
    useBrainStore.setState({ selectedNodeId: null, highlightedNodeIds: [], panelOpen: false })
  })

  it('passes transformed node data into the force graph', async () => {
    render(<GraphCanvas graph={graph} />)
    expect(await screen.findByTestId('node-count')).toHaveTextContent('2')
  })

  it('clicking a node selects it in the store', async () => {
    render(<GraphCanvas graph={graph} />)
    fireEvent.click(await screen.findByTestId('fire-click'))
    expect(useBrainStore.getState().selectedNodeId).toBe('domain:eng')
  })
})
