'use client';
import { useState } from 'react';
import { Plus, Send } from 'lucide-react';
import { useAsk } from '@/lib/hooks/use-ask';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useCreateDialogs } from '@/lib/hooks/use-create-dialogs';
import { useModelDefaults } from '@/lib/hooks/use-models';
import { useScopeStore } from '@/lib/stores/scope-store';
import { useTranslation } from '@/lib/hooks/use-translation';
import { AnswerBody } from '@/components/search/AnswerBody';

export function ControlPlaneChat() {
  const { t } = useTranslation();
  const scope = useScopeStore((s) => s.scope);
  const { finalAnswer, isStreaming, sendAsk } = useAsk();
  const { openArtifact } = useArtifact();
  const { openSourceDialog } = useCreateDialogs();
  const { data: modelDefaults } = useModelDefaults();
  const [q, setQ] = useState('');

  const submit = () => {
    if (!q.trim() || !modelDefaults?.default_chat_model) return;
    const models = {
      strategy: modelDefaults.default_chat_model,
      answer: modelDefaults.default_chat_model,
      finalAnswer: modelDefaults.default_chat_model,
    };
    sendAsk(q, models);
    setQ('');
  };

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="border-b border-border px-6 py-3">
        <h1 className="font-serif text-xl font-semibold text-foreground">{t('controlPlane.title')}</h1>
        <p className="text-xs text-muted-foreground">{t(scope === 'personal' ? 'controlPlane.personalSubtitle' : 'controlPlane.companySubtitle')}</p>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-2xl">
          <AnswerBody
            finalAnswer={finalAnswer}
            isStreaming={isStreaming}
            onReferenceClick={(type, id) => openArtifact('source', id)}
          />
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
