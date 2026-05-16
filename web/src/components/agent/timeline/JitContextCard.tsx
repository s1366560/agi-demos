/**
 * JIT Context Card — rich rendering of memories recalled by the agent.
 *
 * Replaces the previous compact `MemoryRecalledStep` with:
 *  - Source-aware filter chips (with counts)
 *  - Per-hit score / source / category badges
 *  - Per-hit pin (persisted in localStorage by conversationId)
 *  - Per-hit expand-to-full + copy
 *  - Pinned-first ordering, then score-desc
 *
 * Inspired by Routa's `JitContextPanel` pattern: surface retrieval results
 * inline at the moment of use, with affordances to inspect and promote.
 */

import { useMemo, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import { ChevronDown, ChevronRight, Copy, Database, Pin, PinOff } from 'lucide-react';

import { useJitContextPins } from './useJitContextPins';

import type { MemoryRecalledTimelineEvent } from '../../../types/agent';

interface JitContextCardProps {
  event: MemoryRecalledTimelineEvent;
  conversationId: string | null | undefined;
}

const SNIPPET_LIMIT = 220;

function formatScore(score: number): string {
  if (Number.isNaN(score)) return '—';
  return score.toFixed(2);
}

function hitKey(eventId: string | null | undefined, idx: number): string {
  return `${eventId ?? 'no-id'}:${String(idx)}`;
}

export const JitContextCard: FC<JitContextCardProps> = ({ event, conversationId }) => {
  const { t } = useTranslation();
  const [expandedRoot, setExpandedRoot] = useState(false);
  const [expandedHits, setExpandedHits] = useState<ReadonlySet<number>>(() => new Set<number>());
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const pins = useJitContextPins(conversationId);

  const hits = useMemo(() => event.memories, [event.memories]);
  const eventId = event.id;

  const sourceBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const m of hits) {
      counts.set(m.source, (counts.get(m.source) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [hits]);

  const orderedHits = useMemo(() => {
    const indexed = hits.map((m, idx) => ({ m, idx, key: hitKey(eventId, idx) }));
    indexed.sort((a, b) => {
      const aPinned = pins.isPinned(a.key);
      const bPinned = pins.isPinned(b.key);
      if (aPinned !== bPinned) return aPinned ? -1 : 1;
      return b.m.score - a.m.score;
    });
    if (activeSource) return indexed.filter(({ m }) => m.source === activeSource);
    return indexed;
  }, [hits, pins, activeSource, eventId]);

  if (hits.length === 0) return null;

  const pinnedCount = orderedHits.filter(({ key }) => pins.isPinned(key)).length;

  const toggleHit = (idx: number) => {
    setExpandedHits((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      void message.success(
        t('components.jitContext.copySuccess', { defaultValue: 'Copied to clipboard' })
      );
    } catch {
      void message.warning(
        t('components.jitContext.copyFailed', { defaultValue: 'Failed to copy to clipboard' })
      );
    }
  };

  return (
    <div className="rounded-md border border-blue-200 bg-blue-50/60 dark:border-blue-900/60 dark:bg-blue-950/30">
      <button
        type="button"
        onClick={() => {
          setExpandedRoot((v) => !v);
        }}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-blue-700 transition-colors hover:bg-blue-100/60 dark:text-blue-300 dark:hover:bg-blue-900/40"
        data-testid="jit-context-toggle"
        aria-expanded={expandedRoot}
      >
        {expandedRoot ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Database size={12} />
        <span className="font-medium">
          {t('components.jitContext.recalled', {
            defaultValue: 'Recalled {{count}} memories',
            count: event.count,
          })}
        </span>
        <span className="text-blue-500/80 dark:text-blue-400/80">({String(event.searchMs)}ms)</span>
        {pinnedCount > 0 ? (
          <span className="ml-1 inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
            <Pin size={10} />
            {t('components.jitContext.pinned', {
              defaultValue: '{{count}} pinned',
              count: pinnedCount,
            })}
          </span>
        ) : null}
      </button>

      {expandedRoot ? (
        <div className="border-t border-blue-200/70 px-3 py-2 dark:border-blue-900/60">
          {sourceBreakdown.length > 1 ? (
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <SourceChip
                label={t('components.jitContext.allSources', { defaultValue: 'all' })}
                count={hits.length}
                active={activeSource === null}
                onClick={() => {
                  setActiveSource(null);
                }}
              />
              {sourceBreakdown.map(([src, count]) => (
                <SourceChip
                  key={src}
                  label={src}
                  count={count}
                  active={activeSource === src}
                  onClick={() => {
                    setActiveSource((cur) => (cur === src ? null : src));
                  }}
                />
              ))}
            </div>
          ) : null}

          <ul className="space-y-1.5">
            {orderedHits.map(({ m, idx, key }) => {
              const isExpanded = expandedHits.has(idx);
              const pinned = pins.isPinned(key);
              const showFull = isExpanded || m.content.length <= SNIPPET_LIMIT;
              const display = showFull ? m.content : `${m.content.slice(0, SNIPPET_LIMIT)}…`;
              return (
                <li
                  key={key}
                  className={`group rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                    pinned
                      ? 'border-amber-200 bg-amber-50/60 dark:border-amber-900/60 dark:bg-amber-950/20'
                      : 'border-blue-100/80 bg-white/60 dark:border-blue-900/50 dark:bg-slate-900/40'
                  }`}
                >
                  <div className="mb-1 flex flex-wrap items-center gap-1.5">
                    <span
                      className="inline-flex items-center rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-mono font-medium text-blue-700 dark:bg-blue-900/60 dark:text-blue-300"
                      title={t('components.jitContext.scoreTitle', {
                        defaultValue: 'Score: {{score}}',
                        score: String(m.score),
                      })}
                    >
                      {formatScore(m.score)}
                    </span>
                    <span className="inline-flex items-center rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {m.category}
                    </span>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500">
                      {t('components.jitContext.viaSource', {
                        defaultValue: 'via {{source}}',
                        source: m.source,
                      })}
                    </span>
                    <div className="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <IconButton
                        label={
                          pinned
                            ? t('components.jitContext.unpin', { defaultValue: 'Unpin' })
                            : t('components.jitContext.pin', { defaultValue: 'Pin' })
                        }
                        onClick={() => {
                          pins.toggle(key);
                        }}
                      >
                        {pinned ? <PinOff size={12} /> : <Pin size={12} />}
                      </IconButton>
                      <IconButton
                        label={t('common.copy', { defaultValue: 'Copy' })}
                        onClick={() => {
                          void copyText(m.content);
                        }}
                      >
                        <Copy size={12} />
                      </IconButton>
                    </div>
                  </div>
                  <div className="break-words text-slate-700 dark:text-slate-200">{display}</div>
                  {m.content.length > SNIPPET_LIMIT ? (
                    <button
                      type="button"
                      onClick={() => {
                        toggleHit(idx);
                      }}
                      className="mt-1 inline-flex items-center text-[10px] font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-200"
                    >
                      {isExpanded
                        ? t('components.jitContext.showLess', { defaultValue: 'Show less' })
                        : t('components.jitContext.showFull', { defaultValue: 'Show full' })}
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
};

interface SourceChipProps {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}

const SourceChip: FC<SourceChipProps> = ({ label, count, active, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors ${
      active
        ? 'border-blue-500 bg-blue-500 text-white'
        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'
    }`}
  >
    <span>{label}</span>
    <span className={active ? 'text-blue-100' : 'text-slate-400'}>{String(count)}</span>
  </button>
);

interface IconButtonProps {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}

const IconButton: FC<IconButtonProps> = ({ label, onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    aria-label={label}
    title={label}
    className="inline-flex h-5 w-5 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
  >
    {children}
  </button>
);
