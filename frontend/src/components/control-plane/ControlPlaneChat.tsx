'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Plus, Send } from 'lucide-react';
import { useAsk } from '@/lib/hooks/use-ask';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useCreateDialogs } from '@/lib/hooks/use-create-dialogs';
import { useModelDefaults } from '@/lib/hooks/use-models';
import { useRecentSources, useSourceStatus } from '@/lib/hooks/use-sources';
import { useSourceInsights } from '@/lib/hooks/use-insights';
import { useScopeStore } from '@/lib/stores/scope-store';
import { useTranslation } from '@/lib/hooks/use-translation';
import { AnswerBody } from '@/components/search/AnswerBody';
import { ProposeButton } from './ProposeButton';
import { appendUser, appendAgentAnswer, appendInsight, ChatMessage } from './chat-messages';

/**
 * Watches a single session-new source until its processing completes, then
 * fetches its insights and reports them exactly once. Renders nothing — it's
 * a pure "run these hooks per tracked id" helper so ControlPlaneChat doesn't
 * have to call useSourceStatus/useSourceInsights in a loop (rules of hooks).
 */
function SourceInsightWatcher({
  sourceId,
  sourceTitle,
  onReady,
}: {
  sourceId: string;
  sourceTitle: string;
  onReady: (sourceId: string, sourceTitle: string, insights: string[]) => void;
}) {
  const { data: status } = useSourceStatus(sourceId);
  const completed = status?.status === 'completed';
  const { data: insights } = useSourceInsights(sourceId, { enabled: completed });
  const announcedRef = useRef(false);

  useEffect(() => {
    if (!completed || announcedRef.current || insights === undefined) return;
    announcedRef.current = true;
    onReady(sourceId, sourceTitle, insights.map((i) => i.content));
  }, [completed, insights, sourceId, sourceTitle, onReady]);

  return null;
}

function ChatMessageItem({
  message,
  onReferenceClick,
  onAskMore,
  onOpenSource,
}: {
  message: ChatMessage;
  onReferenceClick: (type: string, id: string) => void;
  onAskMore: (sourceTitle: string) => void;
  onOpenSource: (sourceId: string) => void;
}) {
  const { t } = useTranslation();

  if (message.kind === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {message.text}
        </div>
      </div>
    );
  }

  if (message.kind === 'agent-answer') {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-3">
          <AnswerBody finalAnswer={message.text} isStreaming={false} onReferenceClick={onReferenceClick} />
        </div>
      </div>
    );
  }

  // agent-insight
  const hasInsights = message.insights.length > 0;
  return (
    <div className="flex justify-start">
      <div className="w-full max-w-[85%] rounded-2xl border border-border bg-card p-4">
        <p className="text-sm text-foreground">
          {t('controlPlane.insight.processedPrefix')}{' '}
          <span className="font-semibold">&ldquo;{message.sourceTitle}&rdquo;</span>.{' '}
          {hasInsights ? t('controlPlane.insight.withInsightsSuffix') : t('controlPlane.insight.noInsightsSuffix')}
        </p>
        {hasInsights && (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground">
            {message.insights.map((insight, i) => (
              <li key={i}>{insight}</li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onAskMore(message.sourceTitle)}
            className="rounded-lg border border-border px-3 py-2 text-xs font-semibold text-muted-foreground hover:text-foreground"
          >
            {t('controlPlane.insight.askMore')}
          </button>
          <button
            type="button"
            onClick={() => onOpenSource(message.sourceId)}
            className="rounded-lg border border-border px-3 py-2 text-xs font-semibold text-muted-foreground hover:text-foreground"
          >
            {t('controlPlane.insight.openSource')}
          </button>
          <ProposeButton title={message.sourceTitle} body="" sourceSpans={[{ source_id: message.sourceId }]} />
        </div>
      </div>
    </div>
  );
}

export function ControlPlaneChat() {
  const { t } = useTranslation();
  const scope = useScopeStore((s) => s.scope);
  const { finalAnswer, isStreaming, sendAsk } = useAsk();
  const { openArtifact } = useArtifact();
  const { openSourceDialog } = useCreateDialogs();
  const { data: modelDefaults } = useModelDefaults();
  const { data: recentSources } = useRecentSources();
  const [q, setQ] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const idCounterRef = useRef(0);
  const nextId = useCallback((prefix: string) => {
    idCounterRef.current += 1;
    return `${prefix}-${idCounterRef.current}`;
  }, []);

  const handleReferenceClick = useCallback(
    (type: string, id: string) => openArtifact('source', id),
    [openArtifact],
  );

  // Snapshot the completed answer into the stream once it lands, without
  // dropping the live streaming indicator (isStreaming/finalAnswer from
  // useAsk keep driving the "in flight" bubble until this fires).
  const capturedAnswerRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isStreaming && finalAnswer && finalAnswer !== capturedAnswerRef.current) {
      capturedAnswerRef.current = finalAnswer;
      setMessages((prev) => appendAgentAnswer(prev, nextId('agent'), finalAnswer));
    }
  }, [isStreaming, finalAnswer, nextId]);
  const showLiveAnswer = isStreaming || (finalAnswer !== null && finalAnswer !== capturedAnswerRef.current);

  // Session-new source tracking: sources present when the chat first mounts
  // are the baseline ("already seen"); only ids that appear afterwards (e.g.
  // via "Add source" during this session) get watched for completion.
  const seenIdsRef = useRef<Set<string> | null>(null);
  const [trackedIds, setTrackedIds] = useState<string[]>([]);
  useEffect(() => {
    if (!recentSources) return;
    if (seenIdsRef.current === null) {
      seenIdsRef.current = new Set(recentSources.map((s) => s.id));
      return;
    }
    const fresh = recentSources.filter((s) => !seenIdsRef.current!.has(s.id));
    if (fresh.length === 0) return;
    fresh.forEach((s) => seenIdsRef.current!.add(s.id));
    setTrackedIds((prev) => [...prev, ...fresh.map((s) => s.id)]);
  }, [recentSources]);

  const handleInsightReady = useCallback(
    (sourceId: string, sourceTitle: string, insights: string[]) => {
      setMessages((prev) => appendInsight(prev, { id: nextId('insight'), sourceId, sourceTitle, insights }));
      setTrackedIds((prev) => prev.filter((id) => id !== sourceId));
    },
    [nextId],
  );

  const askAboutSource = useCallback(
    (sourceTitle: string) => {
      setQ(t('controlPlane.insight.askMorePrompt').replace('{title}', sourceTitle));
    },
    [t],
  );

  const submit = () => {
    const text = q.trim();
    if (!text || !modelDefaults?.default_chat_model) return;
    const models = {
      strategy: modelDefaults.default_chat_model,
      answer: modelDefaults.default_chat_model,
      finalAnswer: modelDefaults.default_chat_model,
    };
    setMessages((prev) => appendUser(prev, nextId('user'), text));
    sendAsk(text, models);
    setQ('');
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="border-b border-border px-6 py-3">
        <h1 className="font-serif text-xl font-semibold text-foreground">{t('controlPlane.title')}</h1>
        <p className="text-xs text-muted-foreground">{t(scope === 'personal' ? 'controlPlane.personalSubtitle' : 'controlPlane.companySubtitle')}</p>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {messages.map((m) => (
            <ChatMessageItem
              key={m.id}
              message={m}
              onReferenceClick={handleReferenceClick}
              onAskMore={askAboutSource}
              onOpenSource={(id) => openArtifact('source', id)}
            />
          ))}
          {showLiveAnswer && (
            <div className="flex justify-start">
              <div className="max-w-[85%] rounded-2xl bg-muted px-4 py-3">
                <AnswerBody finalAnswer={isStreaming ? null : finalAnswer} isStreaming={isStreaming} onReferenceClick={handleReferenceClick} />
              </div>
            </div>
          )}
          {trackedIds.map((id) => {
            const source = recentSources?.find((s) => s.id === id);
            if (!source) return null;
            return (
              <SourceInsightWatcher
                key={id}
                sourceId={id}
                sourceTitle={source.title ?? t('controlPlane.artifact.title')}
                onReady={handleInsightReady}
              />
            );
          })}
        </div>
      </div>
      <div className="border-t border-border p-4">
        <div className="mx-auto flex max-w-2xl items-center gap-2 rounded-2xl border border-border bg-card p-2">
          <button type="button" onClick={() => openSourceDialog()} className="flex items-center gap-1.5 rounded-xl border border-dashed border-border px-3 py-2 text-xs font-semibold text-muted-foreground hover:text-foreground">
            <Plus className="h-4 w-4" /> {t('controlPlane.addSource')}
          </button>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
            placeholder={t('controlPlane.composerPlaceholder')}
            className="flex-1 bg-transparent text-sm outline-none"
          />
          <button type="button" aria-label={t('controlPlane.send')} onClick={submit} className="grid h-9 w-9 place-items-center rounded-xl bg-primary text-primary-foreground">
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </section>
  );
}
