import { describe, it, expect } from 'vitest'
import { toForceGraphData, nodeColor, nodeVal, edgeColor, edgeDashed } from './graph-transform'
import type { BrainGraph } from '@/lib/types/brain'

describe('toForceGraphData', () => {
  it('maps BrainGraph nodes/edges into force-graph nodes/links', () => {
    const graph: BrainGraph = {
      nodes: [
        { id: 'd1', kind: 'domain', label: 'Engineering', salience: 4 },
        { id: 's1', kind: 'source', label: 'Doc', salience: 1 },
      ],
      edges: [{ source: 's1', target: 'd1', type: 'mentions' }],
    }
    const result = toForceGraphData(graph)
    expect(result.nodes).toEqual([
      { id: 'd1', kind: 'domain', label: 'Engineering', val: nodeVal(4) },
      { id: 's1', kind: 'source', label: 'Doc', val: nodeVal(1) },
    ])
    expect(result.links).toEqual([{ source: 's1', target: 'd1', type: 'mentions' }])
  })

  it('handles an empty graph', () => {
    expect(toForceGraphData({ nodes: [], edges: [] })).toEqual({ nodes: [], links: [] })
  })
})

describe('nodeColor', () => {
  it('maps each kind to its spec color', () => {
    expect(nodeColor('domain')).toBe('#e0651f')
    expect(nodeColor('source')).toBe('#e6e6e6')
    expect(nodeColor('topic')).toBe('#8a8a8a')
    expect(nodeColor('person')).toBe('#2f7bf0')
    expect(nodeColor('decision')).toBe('#2f7bf0')
  })
})

describe('nodeVal', () => {
  it('scales radius by salience and is monotonic', () => {
    expect(nodeVal(4)).toBeGreaterThan(nodeVal(1))
  })
  it('never returns below the floor for zero/negative salience', () => {
    expect(nodeVal(0)).toBeGreaterThan(0)
    expect(nodeVal(-5)).toBe(nodeVal(0))
  })
})

describe('edge styling', () => {
  it('maps edge type to color', () => {
    expect(edgeColor('disagrees')).toBe('#e23b3b')
    expect(edgeColor('complements')).toBe('#2f7bf0')
    expect(edgeColor('supersedes')).toBe('#9a9a9a')
    expect(edgeColor('agrees')).toBe('#9a9a9a')
    expect(edgeColor('part_of')).toBe('#d4d4d4')
    expect(edgeColor('mentions')).toBe('#d4d4d4')
  })
  it('only supersedes is dashed', () => {
    expect(edgeDashed('supersedes')).toBe(true)
    expect(edgeDashed('agrees')).toBe(false)
    expect(edgeDashed('disagrees')).toBe(false)
  })
})
