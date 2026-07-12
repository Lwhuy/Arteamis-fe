import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/components/layout/AppShell', () => ({ AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }))

import IntelligencePage from './page'

describe('IntelligencePage', () => {
  it('shows the coming soon state', () => {
    render(<IntelligencePage />)
    expect(screen.getByText('intelligence.comingSoon.title')).toBeInTheDocument()
    expect(screen.getByText('intelligence.comingSoon.description')).toBeInTheDocument()
  })

  it('does not render the graph canvas', () => {
    render(<IntelligencePage />)
    expect(screen.queryByTestId('graph-canvas')).not.toBeInTheDocument()
  })
})
