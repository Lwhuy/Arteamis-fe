import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AskTheBrainPanel } from './AskTheBrainPanel'

const useBrainAskMock = vi.fn()
vi.mock('@/lib/hooks/use-brain-ask', () => ({ useBrainAsk: () => useBrainAskMock() }))
vi.mock('@/lib/hooks/use-models', () => ({
  useModelDefaults: () => ({ data: { default_chat_model: 'model-x' }, isLoading: false }),
}))
vi.mock('@/lib/hooks/use-translation', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
// Stub the reused search components to keep this a unit test of the panel wiring
vi.mock('@/components/search/AnswerBody', () => ({
  AnswerBody: ({ finalAnswer }: { finalAnswer: string | null }) => <div>answer:{finalAnswer}</div>,
}))
vi.mock('@/components/search/StrategyDisclosure', () => ({ StrategyDisclosure: () => <div /> }))
vi.mock('@/components/search/SourcesPanel', () => ({ SourcesPanel: () => <div /> }))
vi.mock('@/components/search/AnswerFeedback', () => ({
  AnswerFeedback: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}))

beforeEach(() => vi.clearAllMocks())

const base = {
  isStreaming: false,
  strategy: null,
  answers: [],
  finalAnswer: null,
  error: null,
  citedNodeIds: [],
  sendAsk: vi.fn(),
  reset: vi.fn(),
}

describe('AskTheBrainPanel', () => {
  it('renders the streamed final answer', () => {
    useBrainAskMock.mockReturnValue({ ...base, finalAnswer: 'The answer' })
    render(<AskTheBrainPanel />)
    expect(screen.getByText('answer:The answer')).toBeInTheDocument()
  })

  it('renders an inline error state without crashing', () => {
    useBrainAskMock.mockReturnValue({ ...base, error: 'Stream failed: 402' })
    render(<AskTheBrainPanel />)
    expect(screen.getByRole('alert')).toHaveTextContent('Stream failed: 402')
  })

  it('triggers sendAsk with the typed question and resolved models when RUN is clicked', () => {
    const sendAsk = vi.fn()
    useBrainAskMock.mockReturnValue({ ...base, sendAsk })
    render(<AskTheBrainPanel />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'What changed recently?' } })
    fireEvent.click(screen.getByRole('button', { name: 'intelligence.askSend' }))

    expect(sendAsk).toHaveBeenCalledWith('What changed recently?', {
      strategy: 'model-x',
      answer: 'model-x',
      finalAnswer: 'model-x',
    })
  })

  it('disables the send button while streaming', () => {
    useBrainAskMock.mockReturnValue({ ...base, isStreaming: true })
    render(<AskTheBrainPanel />)
    expect(screen.getByRole('button', { name: 'intelligence.askSend' })).toBeDisabled()
  })
})
