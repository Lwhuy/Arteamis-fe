import type {
  BrainGraph,
  BrainNodeKind,
  BrainEdgeType,
  ForceGraphData,
} from '@/lib/types/brain'

const NODE_COLORS: Record<BrainNodeKind, string> = {
  domain: '#e0651f',
  source: '#e6e6e6',
  topic: '#8a8a8a',
  person: '#2f7bf0',
  decision: '#2f7bf0',
}

const NEUTRAL = '#9a9a9a'
const FAINT = '#d4d4d4'
const EDGE_COLORS: Record<BrainEdgeType, string> = {
  supersedes: NEUTRAL,
  agrees: NEUTRAL,
  disagrees: '#e23b3b',
  complements: '#2f7bf0',
  part_of: FAINT,
  mentions: FAINT,
}

export function nodeColor(kind: BrainNodeKind): string {
  return NODE_COLORS[kind]
}

/** Radius scales with sqrt(salience) so area ~ salience; floored so tiny nodes stay clickable. */
export function nodeVal(salience: number): number {
  const s = Math.max(0, salience)
  return 1 + Math.sqrt(s)
}

export function edgeColor(type: BrainEdgeType): string {
  return EDGE_COLORS[type]
}

export function edgeDashed(type: BrainEdgeType): boolean {
  return type === 'supersedes'
}

export function toForceGraphData(graph: BrainGraph): ForceGraphData {
  return {
    nodes: graph.nodes.map((n) => ({
      id: n.id,
      kind: n.kind,
      label: n.label,
      val: nodeVal(n.salience),
    })),
    links: graph.edges.map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
    })),
  }
}
