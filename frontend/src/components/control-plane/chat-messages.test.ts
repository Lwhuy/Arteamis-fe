import { describe, it, expect } from 'vitest';
import { appendUser, appendAgentAnswer, appendInsight, ChatMessage } from './chat-messages';

describe('chat-messages reducer', () => {
  it('appendUser adds a user message to an empty list', () => {
    const result = appendUser([], 'm1', 'What changed in Q3?');
    expect(result).toEqual<ChatMessage[]>([{ id: 'm1', kind: 'user', text: 'What changed in Q3?' }]);
  });

  it('appendUser appends after existing messages without mutating the input', () => {
    const initial: ChatMessage[] = [{ id: 'm1', kind: 'user', text: 'first' }];
    const result = appendUser(initial, 'm2', 'second');
    expect(initial).toHaveLength(1); // not mutated
    expect(result).toEqual([
      { id: 'm1', kind: 'user', text: 'first' },
      { id: 'm2', kind: 'user', text: 'second' },
    ]);
  });

  it('appendAgentAnswer adds an agent-answer message', () => {
    const result = appendAgentAnswer([], 'a1', 'The answer is 42.');
    expect(result).toEqual<ChatMessage[]>([{ id: 'a1', kind: 'agent-answer', text: 'The answer is 42.' }]);
  });

  it('appendInsight adds an agent-insight message for a new source', () => {
    const result = appendInsight([], {
      id: 'i1',
      sourceId: 'src-1',
      sourceTitle: 'Q3 Research',
      insights: ['SMB skews higher', 'Competitor pricing dropped 15%'],
    });
    expect(result).toEqual<ChatMessage[]>([
      {
        id: 'i1',
        kind: 'agent-insight',
        sourceId: 'src-1',
        sourceTitle: 'Q3 Research',
        insights: ['SMB skews higher', 'Competitor pricing dropped 15%'],
      },
    ]);
  });

  it('appendInsight dedupes by sourceId — a second insight for the same source is a no-op', () => {
    const first = appendInsight([], { id: 'i1', sourceId: 'src-1', sourceTitle: 'Q3 Research', insights: ['a'] });
    const second = appendInsight(first, { id: 'i2', sourceId: 'src-1', sourceTitle: 'Q3 Research (renamed)', insights: ['b'] });
    expect(second).toBe(first); // same reference — no-op, not just equal content
    expect(second).toHaveLength(1);
    expect(second[0]).toMatchObject({ id: 'i1', sourceId: 'src-1' });
  });

  it('appendInsight allows different sourceIds to coexist', () => {
    const first = appendInsight([], { id: 'i1', sourceId: 'src-1', sourceTitle: 'A', insights: [] });
    const second = appendInsight(first, { id: 'i2', sourceId: 'src-2', sourceTitle: 'B', insights: [] });
    expect(second).toHaveLength(2);
  });

  it('interleaves user, agent-answer and agent-insight messages in call order', () => {
    let messages: ChatMessage[] = [];
    messages = appendUser(messages, 'u1', 'question 1');
    messages = appendAgentAnswer(messages, 'a1', 'answer 1');
    messages = appendInsight(messages, { id: 'i1', sourceId: 's1', sourceTitle: 'Source 1', insights: [] });
    expect(messages.map((m) => m.kind)).toEqual(['user', 'agent-answer', 'agent-insight']);
  });
});
