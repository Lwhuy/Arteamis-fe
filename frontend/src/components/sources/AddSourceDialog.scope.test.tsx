import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { AddSourceDialog } from './AddSourceDialog'

const mutateAsync = vi.fn().mockResolvedValue({ id: 'source:1' })
vi.mock('@/lib/hooks/use-sources', () => ({
  useCreateSource: () => ({ mutateAsync, isPending: false }),
  useFileUpload: () => ({ mutateAsync: vi.fn(), isPending: false }),
}))
vi.mock('@/lib/hooks/use-settings', () => ({ useSettings: () => ({ data: { default_embedding_option: 'ask' } }) }))
vi.mock('@/lib/hooks/use-transformations', () => ({ useTransformations: () => ({ data: [] }) }))
vi.mock('@/lib/hooks/use-projects', () => ({ useProjects: () => ({ data: [], isLoading: false }) }))

// jsdom has no ResizeObserver; the Radix Checkbox rendered in the Settings
// section (embed toggle) needs one to mount. Stub it so the wizard can be
// driven all the way to step 3 (ProcessingStep) in this environment.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
;(globalThis as any).ResizeObserver = ResizeObserverStub

// Drives the real 3-step wizard: pick "text" type + fill required fields (step 1),
// advance past the notebooks step (step 2), then interact with the scope control
// on the processing step (step 3) before submitting. useTranslation is globally
// mocked (src/test/setup.ts) to return the raw i18n key, so all queries below
// target literal keys like 'sources.enterText' rather than English copy.
async function goToProcessingStep() {
  // Radix Tabs switches the active tab on mousedown (not click), so a plain
  // fireEvent.click never fires TabsPrimitive's onValueChange in jsdom.
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'sources.enterText' }), { button: 0 })
  fireEvent.change(screen.getByPlaceholderText('sources.textPlaceholder'), {
    target: { value: 'hello world' },
  })
  fireEvent.change(screen.getByPlaceholderText('sources.titlePlaceholder'), {
    target: { value: 'My Title' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'common.next' }))
  fireEvent.click(await screen.findByRole('button', { name: 'common.next' }))
}

describe('AddSourceDialog scope', () => {
  beforeEach(() => vi.clearAllMocks())

  it('submits a text source with the selected scope', async () => {
    render(<AddSourceDialog open onOpenChange={() => {}} defaultNotebookId="notebook:p1" />)
    await goToProcessingStep()

    fireEvent.click(await screen.findByRole('radio', { name: /personal/i }))
    fireEvent.click(screen.getByRole('button', { name: 'common.done' }))

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ scope: 'personal' })
  })

  it('defaults to project scope when left untouched', async () => {
    render(<AddSourceDialog open onOpenChange={() => {}} defaultNotebookId="notebook:p1" />)
    await goToProcessingStep()

    expect(await screen.findByRole('radio', { name: /project/i })).toHaveAttribute('aria-checked', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'common.done' }))
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled())
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({ scope: 'project' })
  })

  it('offers all three scope options', async () => {
    render(<AddSourceDialog open onOpenChange={() => {}} defaultNotebookId="notebook:p1" />)
    await goToProcessingStep()

    expect(await screen.findByRole('radio', { name: /personal/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /project/i })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /company/i })).toBeInTheDocument()
  })
})
