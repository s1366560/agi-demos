/**
 * MultiSourceResultsCard - Aggregated view across multiple search/RAG tool
 * calls within one timeline group. Renders a single deduped, grouped list of
 * sources to replace the per-tool noise of N near-identical search cards.
 *
 * Pure presentation. Source detection / dedup / grouping is in
 * `normalizeSources.ts`.
 */

import { memo, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { ChevronDown, ChevronRight, ExternalLink, Globe, Database, Network } from 'lucide-react';

import {
  aggregateSources,
  groupSources,
  normalizeToolSources,
  type Source,
  type SourceGroup,
} from './normalizeSources';

import type { TimelineStep } from '../timeline/ExecutionTimeline';
import type { TFunction } from 'i18next';

interface MultiSourceResultsCardProps {
  steps: ReadonlyArray<TimelineStep>;
  /** Minimum number of search-shaped steps required to show this card. */
  minSearchSteps?: number | undefined;
}

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

const TYPE_ICON: Record<
  Source['sourceType'],
  React.ComponentType<{ size?: number; className?: string }>
> = {
  web: Globe,
  rag: Database,
  graph: Network,
  other: Database,
};

function SourceRow({ source }: { source: Source }) {
  const Icon = TYPE_ICON[source.sourceType];
  const titleNode = source.url ? (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
    >
      <span className="line-clamp-1">{source.title}</span>
      <ExternalLink size={11} className="flex-shrink-0 opacity-70" />
    </a>
  ) : (
    <span className="text-sm font-medium text-slate-800 dark:text-slate-100 line-clamp-1">
      {source.title}
    </span>
  );

  return (
    <li className="flex items-start gap-2 py-1.5">
      <Icon size={13} className="mt-0.5 flex-shrink-0 text-slate-400 dark:text-slate-500" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {titleNode}
          {typeof source.score === 'number' ? (
            <span className="text-[10px] tabular-nums text-slate-400 dark:text-slate-500">
              {source.score.toFixed(2)}
            </span>
          ) : null}
        </div>
        {source.snippet ? (
          <p className="mt-0.5 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">
            {source.snippet}
          </p>
        ) : null}
      </div>
    </li>
  );
}

const SourceRowMemo = memo(SourceRow);

function GroupBlock({ group, defaultOpen }: { group: SourceGroup; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div className="border-t border-slate-200/70 first:border-t-0 dark:border-slate-700/60">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs uppercase tracking-wide text-slate-500 transition-colors hover:bg-slate-50 dark:text-slate-400 dark:hover:bg-slate-800/40"
        aria-expanded={open}
      >
        <span className="flex items-center gap-1.5">
          <Chevron size={12} />
          <span className="font-medium normal-case text-slate-700 dark:text-slate-200">
            {group.label}
          </span>
          <span className="text-[10px] text-slate-400 dark:text-slate-500">
            {group.sources.length}
          </span>
        </span>
      </button>
      {open ? (
        <ul className="space-y-0 px-3 pb-2">
          {group.sources.map((src, i) => (
            <SourceRowMemo key={`${group.key}-${String(i)}`} source={src} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export const MultiSourceResultsCard = memo(function MultiSourceResultsCard({
  steps,
  minSearchSteps = 2,
}: MultiSourceResultsCardProps) {
  const { t } = useTranslation();
  const { groups, totalSources, searchStepCount } = useMemo(() => {
    const perStepLists: Array<ReadonlyArray<Source>> = [];
    let searchStepsFound = 0;
    for (const step of steps) {
      const sources = normalizeToolSources(
        step.toolName,
        typeof step.output === 'string' ? step.output : (step.output ?? null)
      );
      if (sources && sources.length > 0) {
        searchStepsFound += 1;
        perStepLists.push(sources);
      }
    }
    const flat = aggregateSources(perStepLists);
    return {
      groups: groupSources(flat),
      totalSources: flat.length,
      searchStepCount: searchStepsFound,
    };
  }, [steps]);

  if (searchStepCount < minSearchSteps || totalSources === 0) return null;
  const callLabel =
    searchStepCount === 1
      ? tFallback(t, 'agent.results.multiSource.call', 'call')
      : tFallback(t, 'agent.results.multiSource.calls', 'calls');
  const groupLabel =
    groups.length === 1
      ? tFallback(t, 'agent.results.multiSource.group', 'group')
      : tFallback(t, 'agent.results.multiSource.groups', 'groups');

  return (
    <div
      data-testid="multi-source-results-card"
      className="mb-2 overflow-hidden rounded-lg border border-slate-200/70 bg-white shadow-sm dark:border-slate-700/60 dark:bg-slate-800/60"
    >
      <div className="flex items-center justify-between gap-2 bg-slate-50/70 px-3 py-2 dark:bg-slate-800/40">
        <div className="flex items-center gap-2 text-xs font-medium text-slate-700 dark:text-slate-200">
          <Globe size={13} className="text-slate-500 dark:text-slate-400" />
          <span>{tFallback(t, 'agent.results.multiSource.title', 'Aggregated sources')}</span>
        </div>
        <span className="text-[10px] tabular-nums text-slate-500 dark:text-slate-400">
          {totalSources} {tFallback(t, 'agent.results.multiSource.from', 'from')} {searchStepCount}{' '}
          {callLabel} · {groups.length} {groupLabel}
        </span>
      </div>
      <div>
        {groups.map((g, idx) => (
          <GroupBlock key={g.key} group={g} defaultOpen={idx < 2} />
        ))}
      </div>
    </div>
  );
});
