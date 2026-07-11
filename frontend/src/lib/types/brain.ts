import type { AskStreamEvent } from '@/lib/types/search'

export type BrainNodeKind = 'domain' | 'topic' | 'person' | 'decision' | 'source'

export type BrainEdgeType =
  | 'part_of'
  | 'mentions'
  | 'supersedes'
  | 'disagrees'
  | 'complements'
  | 'agrees'

export interface BrainNode {
  id: string
  kind: BrainNodeKind
  label: string
  salience: number
}

export interface BrainEdge {
  source: string
  target: string
  type: BrainEdgeType
}

export interface BrainGraph {
  nodes: BrainNode[]
  edges: BrainEdge[]
}

export interface BrainStatus {
  total_sources: number
  built_sources: number
  running: boolean
}

/** Shape consumed by react-force-graph-2d. `val` scales node radius. */
export interface ForceGraphNode {
  id: string
  kind: BrainNodeKind
  label: string
  val: number
}

export interface ForceGraphLink {
  source: string
  target: string
  type: BrainEdgeType
}

export interface ForceGraphData {
  nodes: ForceGraphNode[]
  links: ForceGraphLink[]
}

export type BrainAskStreamEvent = AskStreamEvent & {
  cited_node_ids?: string[]
}
