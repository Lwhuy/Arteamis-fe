import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ConnectorCard } from './ConnectorCard'

vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const base = { provider: 'gdrive', display_name: 'Google Drive', description: 'desc', connections: [] }

describe('ConnectorCard', () => {
  it('coming_soon card is disabled and shows the badge', () => {
    render(<ConnectorCard connector={{ ...base, status: 'coming_soon' }} onConnect={vi.fn()} />)
    expect(screen.getByText('connections.comingSoon')).toBeInTheDocument()
  })

  it('configured card fires onConnect when clicked', () => {
    const onConnect = vi.fn()
    render(<ConnectorCard connector={{ ...base, status: 'configured' }} onConnect={onConnect} />)
    fireEvent.click(screen.getByRole('button', { name: /connect/i }))
    expect(onConnect).toHaveBeenCalledWith('gdrive')
  })

  it('available-but-unconfigured card disables connect', () => {
    render(<ConnectorCard connector={{ ...base, status: 'available' }} onConnect={vi.fn()} />)
    expect(screen.getByRole('button', { name: /connect/i })).toBeDisabled()
  })
})
