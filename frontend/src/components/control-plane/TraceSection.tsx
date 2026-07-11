'use client';
import { useState } from 'react';
import { useTracesForWorkPackage, useRecordTrace, useCreateLearningProposal } from '@/lib/hooks/use-governance';
import { useTranslation } from '@/lib/hooks/use-translation';

const OUTCOMES = ['pending', 'success', 'fail', 'mixed'] as const;
type Outcome = (typeof OUTCOMES)[number];

const OUTCOME_LABEL_KEY: Record<Outcome, string> = {
  pending: 'controlPlane.trace.outcomes.pending',
  success: 'controlPlane.trace.outcomes.success',
  fail: 'controlPlane.trace.outcomes.fail',
  mixed: 'controlPlane.trace.outcomes.mixed',
};

export function TraceSection({ workPackageId }: { workPackageId: string }) {
  const { t } = useTranslation();
  const { data: traces, isLoading } = useTracesForWorkPackage(workPackageId);
  const recordTrace = useRecordTrace();
  const createLearning = useCreateLearningProposal();

  const [summary, setSummary] = useState('');
  const [outcome, setOutcome] = useState<Outcome>('success');
  const [learningNote, setLearningNote] = useState('');
  const [newTraceId, setNewTraceId] = useState<string | null>(null);

  const handleRecordOutcome = () => {
    recordTrace.mutate(
      { workPackageId, payload: { summary, outcome, sources_used: [] } },
      { onSuccess: (trace) => { setNewTraceId(trace.id); setSummary(''); } },
    );
  };

  const handleProposeLearning = () => {
    if (!newTraceId) return;
    createLearning.mutate(
      {
        traceId: newTraceId,
        // belief_id is resolved server-side from the trace (see
        // api/governance_service.py::_resolve_belief_id_from_trace) — no
        // need to look it up or thread it through props here.
        payload: { title: t('controlPlane.trace.learningTitle'), body: learningNote },
      },
      { onSuccess: () => { setNewTraceId(null); setLearningNote(''); } },
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
        {t('controlPlane.trace.title')}
      </div>

      {isLoading ? (
        <div className="text-xs text-muted-foreground">{t('common.loading')}</div>
      ) : (traces ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground">
          {t('controlPlane.trace.empty')}
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {(traces ?? []).map((tr) => (
            <div key={tr.id} className="rounded-xl border border-border bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-foreground">{tr.summary}</span>
                <span className="text-[10px] uppercase text-muted-foreground">
                  {t(OUTCOME_LABEL_KEY[tr.outcome as Outcome] ?? tr.outcome)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-xl border border-border bg-card p-3">
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder={t('controlPlane.trace.summaryPlaceholder')}
          className="w-full rounded-md border border-border bg-background p-2 text-xs"
        />
        <select
          value={outcome}
          onChange={(e) => setOutcome(e.target.value as Outcome)}
          className="mt-2 rounded-md border border-border bg-background p-1.5 text-xs"
        >
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>{t(OUTCOME_LABEL_KEY[o])}</option>
          ))}
        </select>
        <button
          type="button"
          disabled={!summary || recordTrace.isPending}
          onClick={handleRecordOutcome}
          className="mt-2 flex items-center rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-50"
        >
          {t('controlPlane.trace.recordOutcome')}
        </button>

        {newTraceId ? (
          <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
            <textarea
              value={learningNote}
              onChange={(e) => setLearningNote(e.target.value)}
              placeholder={t('controlPlane.trace.learningPlaceholder')}
              className="w-full rounded-md border border-border bg-background p-2 text-xs"
            />
            <button
              type="button"
              disabled={!learningNote || createLearning.isPending}
              onClick={handleProposeLearning}
              className="self-start rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground disabled:opacity-50"
            >
              {t('controlPlane.trace.submitLearning')}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
