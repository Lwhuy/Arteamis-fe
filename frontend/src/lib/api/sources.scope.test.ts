import { describe, expect, it, vi, beforeEach } from 'vitest'
import { sourcesApi } from './sources'
import { apiClient } from './client'

vi.mock('./client', () => {
  const mockClient = { post: vi.fn().mockResolvedValue({ data: {} }), put: vi.fn().mockResolvedValue({ data: {} }) }
  return { apiClient: mockClient, default: mockClient }
})

describe('sourcesApi scope', () => {
  beforeEach(() => vi.clearAllMocks())

  it('appends scope to create FormData', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi', scope: 'personal' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('scope')).toBe('personal')
  })

  it('defaults create scope to project when omitted', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('scope')).toBe('project')
  })

  it('supports the company scope value', async () => {
    await sourcesApi.create({ type: 'text', content: 'hi', scope: 'company' })
    const fd = (apiClient.post as unknown as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(fd.get('scope')).toBe('company')
  })

  it('includes scope in update body', async () => {
    await sourcesApi.update('source:1', { scope: 'company' })
    expect(apiClient.put).toHaveBeenCalledWith('/sources/source:1', { scope: 'company' })
  })
})
