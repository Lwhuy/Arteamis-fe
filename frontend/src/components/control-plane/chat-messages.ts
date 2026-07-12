/**
 * Pure state transitions for the control-plane conversation stream. No DOM,
 * no hooks — the component owns the `ChatMessage[]` state and generates ids
 * (so these functions stay deterministic and unit-testable in isolation).
 */

export interface UserMessage {
  id: string;
  kind: 'user';
  text: string;
}

export interface AgentAnswerMessage {
  id: string;
  kind: 'agent-answer';
  text: string;
}

export interface AgentInsightMessage {
  id: string;
  kind: 'agent-insight';
  sourceId: string;
  sourceTitle: string;
  insights: string[];
}

export type ChatMessage = UserMessage | AgentAnswerMessage | AgentInsightMessage;

export function appendUser(messages: ChatMessage[], id: string, text: string): ChatMessage[] {
  return [...messages, { id, kind: 'user', text }];
}

export function appendAgentAnswer(messages: ChatMessage[], id: string, text: string): ChatMessage[] {
  return [...messages, { id, kind: 'agent-answer', text }];
}

export interface InsightPayload {
  id: string;
  sourceId: string;
  sourceTitle: string;
  insights: string[];
}

/**
 * Appends an agent-insight card for a source, unless one for that sourceId
 * already exists in the stream — a source only ever gets ONE insight card
 * (the first time its processing completes), so this is a same-reference
 * no-op on a duplicate rather than a fresh array with identical content.
 */
export function appendInsight(messages: ChatMessage[], insight: InsightPayload): ChatMessage[] {
  const exists = messages.some((m) => m.kind === 'agent-insight' && m.sourceId === insight.sourceId);
  if (exists) return messages;
  return [...messages, { id: insight.id, kind: 'agent-insight', sourceId: insight.sourceId, sourceTitle: insight.sourceTitle, insights: insight.insights }];
}
