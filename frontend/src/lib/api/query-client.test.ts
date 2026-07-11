import { describe, expect, it } from 'vitest'
import { QUERY_KEYS } from './query-client'

describe('QUERY_KEYS projects', () => {
  it('exposes a projects list key', () => {
    expect(QUERY_KEYS.projects).toEqual(['projects'])
  })
  it('exposes a project(id) key', () => {
    expect(QUERY_KEYS.project('notebook:1')).toEqual(['projects', 'notebook:1'])
  })
})
