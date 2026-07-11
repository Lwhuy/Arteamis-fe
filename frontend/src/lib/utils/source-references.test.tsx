import { describe, it, expect } from 'vitest'
import { buildReferenceIndex, truncateSnippet } from './source-references'

describe('buildReferenceIndex', () => {
  it('numbers unique references in first-appearance order and dedups repeats', () => {
    const { numberedText, references } = buildReferenceIndex(
      'See [source:a] and [note:b]. Also [source:a] again.'
    )
    expect(references).toEqual([
      { number: 1, type: 'source', id: 'a' },
      { number: 2, type: 'note', id: 'b' },
    ])
    expect(numberedText).toContain('[1](#ref-source-a)')
    expect(numberedText).toContain('[2](#ref-note-b)')
    expect(numberedText).not.toMatch(/References:/)
  })

  it('normalizes the insight: alias to source_insight', () => {
    const { references } = buildReferenceIndex('Per [insight:z].')
    expect(references).toEqual([{ number: 1, type: 'source_insight', id: 'z' }])
  })

  it('returns empty references and unchanged text when there are none', () => {
    const { numberedText, references } = buildReferenceIndex('no refs here')
    expect(references).toEqual([])
    expect(numberedText).toBe('no refs here')
  })
})

describe('truncateSnippet', () => {
  it('collapses whitespace and trims', () => {
    expect(truncateSnippet('  a\n\n  b  ', 100)).toBe('a b')
  })
  it('truncates with an ellipsis only when longer than max', () => {
    expect(truncateSnippet('abcdef', 3)).toBe('abc…')
    expect(truncateSnippet('abc', 3)).toBe('abc')
  })
  it('handles empty/nullish input', () => {
    expect(truncateSnippet('', 10)).toBe('')
    expect(truncateSnippet(null as unknown as string, 10)).toBe('')
  })
})
