import { describe, it, expect, beforeEach } from 'vitest'
import { useBrainStore } from './brain-store'

describe('useBrainStore', () => {
  beforeEach(() => {
    useBrainStore.setState({ selectedNodeId: null, highlightedNodeIds: [], panelOpen: false })
  })

  it('has correct initial state', () => {
    const s = useBrainStore.getState()
    expect(s.selectedNodeId).toBeNull()
    expect(s.highlightedNodeIds).toEqual([])
    expect(s.panelOpen).toBe(false)
  })

  it('selectNode sets the selected id', () => {
    useBrainStore.getState().selectNode('entity:1')
    expect(useBrainStore.getState().selectedNodeId).toBe('entity:1')
  })

  it('selectNode(null) clears selection', () => {
    useBrainStore.getState().selectNode('entity:1')
    useBrainStore.getState().selectNode(null)
    expect(useBrainStore.getState().selectedNodeId).toBeNull()
  })

  it('setHighlighted replaces the highlighted set', () => {
    useBrainStore.getState().setHighlighted(['a', 'b'])
    expect(useBrainStore.getState().highlightedNodeIds).toEqual(['a', 'b'])
  })

  it('togglePanel flips panelOpen', () => {
    useBrainStore.getState().togglePanel()
    expect(useBrainStore.getState().panelOpen).toBe(true)
    useBrainStore.getState().togglePanel()
    expect(useBrainStore.getState().panelOpen).toBe(false)
  })
})
