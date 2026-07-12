'use client';
import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { useArtifact } from '@/lib/hooks/use-artifact';
import { useSource } from '@/lib/hooks/use-sources';
import { useSourceInsights } from '@/lib/hooks/use-insights';
import { MarkdownRenderer } from '@/components/ui/markdown-renderer';
import { useTranslation } from '@/lib/hooks/use-translation';
import { ProposeButton } from './ProposeButton';
import { LineagePanel } from './LineagePanel';

export type HighlightRange = { start: number; end: number };

/**
 * Locates the first case-insensitive, whitespace-tolerant occurrence of `q`
 * inside `text`. Returns the character offsets of the match in `text`, or
 * `null` when `q` is absent/blank or not found — callers should render the
 * text unhighlighted in that case, never throw.
 */
export function findHighlightRange(text: string, q?: string | null): HighlightRange | null {
  if (!q) return null;
  const words = q.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return null;
  const pattern = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
  const match = new RegExp(pattern, 'i').exec(text);
  if (!match) return null;
  return { start: match.index, end: match.index + match[0].length };
}

/** Clears any highlight `<mark>` previously inserted by `applyHighlight`, restoring plain text nodes. */
function clearHighlight(root: HTMLElement) {
  root.querySelectorAll('mark[data-cp-highlight]').forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parent.normalize();
  });
}

/** Finds `text.slice(start, end)` inside the rendered DOM under `root` and wraps it in a highlight `<mark>`. */
function locateRangeInDom(root: HTMLElement, start: number, end: number): Range | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let offset = 0;
  let startNode: Text | null = null;
  let startOffset = 0;
  let endNode: Text | null = null;
  let endOffset = 0;
  let node: Node | null = walker.nextNode();
  while (node) {
    const length = node.textContent?.length ?? 0;
    const nodeStart = offset;
    const nodeEnd = offset + length;
    if (startNode === null && start >= nodeStart && start < nodeEnd) {
      startNode = node as Text;
      startOffset = start - nodeStart;
    }
    if (endNode === null && end > nodeStart && end <= nodeEnd) {
      endNode = node as Text;
      endOffset = end - nodeStart;
    }
    if (startNode && endNode) break;
    offset = nodeEnd;
    node = walker.nextNode();
  }
  if (!startNode || !endNode) return null;
  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  return range;
}

/**
 * Highlights the first occurrence of `q` inside `root`'s rendered text and
 * scrolls it into view. Best-effort: any failure (no match, DOM structure
 * that can't be wrapped) leaves the content rendered normally — never throws.
 */
function applyHighlight(root: HTMLElement, q: string | undefined) {
  clearHighlight(root);
  if (!q) return;
  const fullText = root.textContent ?? '';
  const range = findHighlightRange(fullText, q);
  if (!range) return;
  const domRange = locateRangeInDom(root, range.start, range.end);
  if (!domRange) return;
  try {
    const mark = document.createElement('mark');
    mark.dataset.cpHighlight = 'true';
    mark.className = 'rounded-sm bg-amber-200/70 px-0.5 ring-1 ring-amber-400/60 dark:bg-amber-400/30';
    domRange.surroundContents(mark);
    const reducedMotion =
      typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    mark.scrollIntoView?.({ block: 'center', behavior: reducedMotion ? 'auto' : 'smooth' });
  } catch {
    // The matched range crosses element boundaries in a way surroundContents
    // can't wrap (e.g. splits an inline markdown element) — degrade to
    // rendering the text unhighlighted rather than crashing.
  }
}

export function ArtifactReader() {
  const { t } = useTranslation();
  const { artifact, closeArtifact } = useArtifact();
  if (!artifact) return null;

  return (
    <aside className="flex w-[384px] flex-shrink-0 flex-col border-r border-border bg-muted/40">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
          {t('controlPlane.artifact.title')}
        </span>
        <button type="button" aria-label={t('common.close')} onClick={closeArtifact} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      {artifact.type === 'source' ? (
        <SourceArtifact id={artifact.id} loc={artifact.loc} q={artifact.q} />
      ) : (
        <LineagePanel id={artifact.id} />
      )}
    </aside>
  );
}

function SourceArtifact({ id, loc, q }: { id: string; loc?: string; q?: string }) {
  const { data, isLoading } = useSource(id);
  const { data: insights } = useSourceInsights(id);
  const { t } = useTranslation();
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = bodyRef.current;
    if (!root) return;
    applyHighlight(root, q);
  }, [id, q, data?.full_text]);

  if (isLoading) return <div className="p-4 text-sm text-muted-foreground">{t('common.loading')}</div>;
  if (!data) return <div className="p-4 text-sm text-muted-foreground">{t('controlPlane.artifact.notFound')}</div>;
  // Carry the source's insight content into the proposal body so the company
  // brain belief holds real synthesized knowledge, not just the file name. Falls
  // back to a truncated excerpt of the source text when there are no insights yet.
  const insightBody = (insights ?? []).map((i) => i.content).filter(Boolean).join('\n\n');
  const proposalBody = insightBody || (data.full_text ?? '').slice(0, 2000);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-4 py-2">
        <div className="text-sm font-semibold text-foreground">{data.title}</div>
        {loc ? <div className="text-xs text-muted-foreground">{t('controlPlane.artifact.locator').replace('{loc}', loc)}</div> : null}
      </div>
      <div ref={bodyRef} className="flex-1 overflow-y-auto p-4 text-sm">
        <MarkdownRenderer>{data.full_text ?? ''}</MarkdownRenderer>
        <div className="mt-4">
          <ProposeButton title={data.title ?? ''} body={proposalBody} sourceSpans={[{ source_id: id, locator: loc }]} />
        </div>
      </div>
    </div>
  );
}
