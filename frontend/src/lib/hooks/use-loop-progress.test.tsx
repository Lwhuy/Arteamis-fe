import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

const proposalsMock = vi.fn()
const beliefsMock = vi.fn()
const workPackagesMock = vi.fn()
const sourcesMock = vi.fn()

vi.mock('@/lib/api/governance', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/governance')>(
    '@/lib/api/governance',
  )
  return {
    ...actual,
    governanceApi: {
      ...actual.governanceApi,
      listProposals: (...args: unknown[]) => proposalsMock(...args),
      listBeliefs: (...args: unknown[]) => beliefsMock(...args),
      listWorkPackages: (...args: unknown[]) => workPackagesMock(...args),
    },
  }
})

vi.mock('@/lib/api/sources', () => ({
  sourcesApi: {
    list: (...args: unknown[]) => sourcesMock(...args),
  },
}))

import { deriveLoopIndex, useLoopProgress } from './use-loop-progress'

describe('deriveLoopIndex', () => {
  it('defaults to Capture (0) when there are no signals at all', () => {
    expect(deriveLoopIndex({})).toBe(0)
  })

  it('defaults to Capture (0) when called with no argument', () => {
    expect(deriveLoopIndex()).toBe(0)
  })

  it('advances to Draft (1) once a source exists but no proposal yet', () => {
    expect(deriveLoopIndex({ hasSource: true })).toBe(1)
  })

  it('advances to Review (3) once a pending proposal exists', () => {
    expect(deriveLoopIndex({ hasSource: true, hasPendingProposal: true })).toBe(3)
  })

  it('advances to Rule/Belief (5) once an accepted belief exists', () => {
    expect(
      deriveLoopIndex({ hasSource: true, hasPendingProposal: true, hasAcceptedBelief: true }),
    ).toBe(5)
  })

  it('advances to Handoff (6) once a work package exists', () => {
    expect(
      deriveLoopIndex({
        hasSource: true,
        hasPendingProposal: true,
        hasAcceptedBelief: true,
        hasWorkPackage: true,
      }),
    ).toBe(6)
  })

  it('advances to Trace+Learning (7) once traces/a learning proposal exist', () => {
    expect(
      deriveLoopIndex({
        hasSource: true,
        hasPendingProposal: true,
        hasAcceptedBelief: true,
        hasWorkPackage: true,
        hasTraceOrLearning: true,
      }),
    ).toBe(7)
  })

  it('is monotonic: the furthest-progress signal wins even if earlier signals are false', () => {
    // e.g. a belief was accepted and its proposal cleared out of the pending
    // list, but a work package still exists downstream of it.
    expect(deriveLoopIndex({ hasWorkPackage: true })).toBe(6)
    expect(deriveLoopIndex({ hasTraceOrLearning: true })).toBe(7)
    expect(deriveLoopIndex({ hasAcceptedBelief: true })).toBe(5)
  })
})

describe('useLoopProgress', () => {
  const wrapper = ({ children }: { children: ReactNode }) => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }

  it('never throws while queries are still loading, and reports Capture (0)', async () => {
    proposalsMock.mockReturnValue(new Promise(() => {}))
    beliefsMock.mockReturnValue(new Promise(() => {}))
    workPackagesMock.mockReturnValue(new Promise(() => {}))
    sourcesMock.mockReturnValue(new Promise(() => {}))

    const { result } = renderHook(() => useLoopProgress(), { wrapper })
    expect(result.current).toBe(0)
  })

  it('reflects real governance state once queries resolve', async () => {
    proposalsMock.mockResolvedValue([{ id: 'proposal:1', status: 'pending', kind: 'belief' }])
    beliefsMock.mockResolvedValue([])
    workPackagesMock.mockResolvedValue([])
    sourcesMock.mockResolvedValue([{ id: 'source:1' }])

    const { result } = renderHook(() => useLoopProgress(), { wrapper })
    await waitFor(() => expect(result.current).toBe(3))
  })

  it('advances to Handoff (6) once a work package exists', async () => {
    proposalsMock.mockResolvedValue([])
    beliefsMock.mockResolvedValue([{ id: 'belief:1' }])
    workPackagesMock.mockResolvedValue([{ id: 'work_package:1' }])
    sourcesMock.mockResolvedValue([])

    const { result } = renderHook(() => useLoopProgress(), { wrapper })
    await waitFor(() => expect(result.current).toBe(6))
  })

  it('advances to Trace+Learning (7) once a learning-kind proposal exists', async () => {
    proposalsMock.mockResolvedValue([{ id: 'proposal:2', status: 'accepted', kind: 'learning' }])
    beliefsMock.mockResolvedValue([{ id: 'belief:1' }])
    workPackagesMock.mockResolvedValue([{ id: 'work_package:1' }])
    sourcesMock.mockResolvedValue([])

    const { result } = renderHook(() => useLoopProgress(), { wrapper })
    await waitFor(() => expect(result.current).toBe(7))
  })
})
