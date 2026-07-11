'use client'

import { useMemo, type ComponentType } from 'react'
import dynamic from 'next/dynamic'
import { useBrainStore } from '@/lib/stores/brain-store'
import { toForceGraphData, nodeColor, edgeColor, edgeDashed } from './graph-transform'
import type { BrainGraph, ForceGraphNode, ForceGraphLink } from '@/lib/types/brain'
import type { ForceGraphProps } from 'react-force-graph-2d'

// Canvas/DOM-only lib — must never render on the server.
// `react-force-graph-2d`'s default export is a generic function component;
// next/dynamic's inference collapses generics to their `{}` defaults, so we
// pin the instantiation explicitly via a cast rather than losing prop types.
const ForceGraph2D = dynamic(
  () =>
    import('react-force-graph-2d').then((mod) => ({
      default: mod.default as unknown as ComponentType<ForceGraphProps<ForceGraphNode, ForceGraphLink>>,
    })),
  { ssr: false },
)

interface GraphCanvasProps {
  graph: BrainGraph
}

export function GraphCanvas({ graph }: GraphCanvasProps) {
  const selectNode = useBrainStore((s) => s.selectNode)
  const highlightedNodeIds = useBrainStore((s) => s.highlightedNodeIds)

  const data = useMemo(() => toForceGraphData(graph), [graph])
  const highlighted = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds])

  return (
    <ForceGraph2D
      graphData={data}
      nodeId="id"
      nodeVal={(n: ForceGraphNode) => n.val}
      nodeLabel={(n: ForceGraphNode) => n.label}
      nodeColor={(n: ForceGraphNode) => nodeColor(n.kind)}
      linkColor={(l: ForceGraphLink) => edgeColor(l.type)}
      linkLineDash={(l: ForceGraphLink) => (edgeDashed(l.type) ? [4, 4] : [])}
      onNodeClick={(n: ForceGraphNode) => selectNode(n.id)}
      nodeCanvasObjectMode={(n: ForceGraphNode) =>
        highlighted.has(n.id) ? 'before' : undefined
      }
      nodeCanvasObject={(
        n: ForceGraphNode & { x?: number; y?: number },
        ctx: CanvasRenderingContext2D,
      ) => {
        // Draw a highlight ring for cited nodes (P7.4 populates highlightedNodeIds).
        if (n.x == null || n.y == null) return
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.val + 4, 0, 2 * Math.PI)
        ctx.strokeStyle = '#2f7bf0'
        ctx.lineWidth = 2
        ctx.stroke()
      }}
    />
  )
}
