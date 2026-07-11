import { create } from 'zustand'

interface BrainState {
  selectedNodeId: string | null
  highlightedNodeIds: string[]
  panelOpen: boolean
  selectNode: (id: string | null) => void
  setHighlighted: (ids: string[]) => void
  togglePanel: () => void
}

export const useBrainStore = create<BrainState>((set) => ({
  selectedNodeId: null,
  highlightedNodeIds: [],
  panelOpen: false,
  selectNode: (id) => set({ selectedNodeId: id }),
  setHighlighted: (ids) => set({ highlightedNodeIds: ids }),
  togglePanel: () => set((state) => ({ panelOpen: !state.panelOpen })),
}))
