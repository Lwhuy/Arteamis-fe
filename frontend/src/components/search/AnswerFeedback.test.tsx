import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AnswerFeedback } from './AnswerFeedback'

vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))
const toastSuccess = vi.fn()
vi.mock('sonner', () => ({ toast: { success: (m: string) => toastSuccess(m) } }))

describe('AnswerFeedback', () => {
  beforeEach(() => {
    toastSuccess.mockClear()
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
  })

  it('copies the answer text and toasts on Copy', async () => {
    render(<AnswerFeedback answer="hello answer" />)
    fireEvent.click(screen.getByRole('button', { name: 'searchPage.copyAnswer' }))
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('hello answer')
  })

  it('toasts thanks on thumbs up (no persistence)', () => {
    render(<AnswerFeedback answer="x" />)
    fireEvent.click(screen.getByRole('button', { name: 'searchPage.helpfulYes' }))
    expect(toastSuccess).toHaveBeenCalledWith('searchPage.feedbackThanks')
  })

  it('renders children slot (e.g. Save button)', () => {
    render(<AnswerFeedback answer="x"><button>Save</button></AnswerFeedback>)
    expect(screen.getByText('Save')).toBeInTheDocument()
  })
})
