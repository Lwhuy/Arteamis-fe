import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import apiClient from './client'
import { projectsApi } from './projects'

describe('projectsApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('list hits /projects', async () => {
    await projectsApi.list({ order_by: 'updated desc' })
    expect(apiClient.get).toHaveBeenCalledWith('/projects', { params: { order_by: 'updated desc' } })
  })

  it('create hits /projects', async () => {
    await projectsApi.create({ name: 'Acme' })
    expect(apiClient.post).toHaveBeenCalledWith('/projects', { name: 'Acme' })
  })

  it('get hits /projects/:id', async () => {
    await projectsApi.get('notebook:1')
    expect(apiClient.get).toHaveBeenCalledWith('/projects/notebook:1')
  })
})
