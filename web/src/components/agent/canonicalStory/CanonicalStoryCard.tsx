/**
 * CanonicalStoryCard — rich rendering of a parsed canonical story.
 *
 * Distilled from Routa's `canonical-story-renderer.tsx`. Two modes:
 *   - compact: title + INVEST badges + acceptance count (default in chat stream)
 *   - full:    every section, accessible via the disclosure toggle
 *
 * Falls back to the raw YAML view (with collected issues) when the story
 * fails to parse, so authors get useful feedback inline.
 */

import { useMemo, useState } from 'react';
import type { FC, ReactNode } from 'react';

import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, XCircle } from 'lucide-react';

import {
  CANONICAL_STORY_INVEST_KEYS,
  type CanonicalStoryDocument,
  type CanonicalStoryInvestCheck,
  type CanonicalStoryInvestKey,
  type CanonicalStoryParseResult,
  type CanonicalStoryStatus,
} from './canonicalStory';

interface CanonicalStoryCardProps {
  result: CanonicalStoryParseResult;
  defaultOpen?: boolean | undefined;
}

const STATUS_STYLES: Record<
  CanonicalStoryStatus,
  { wrap: string; icon: ReactNode; label: string }
> = {
  pass: {
    wrap: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300',
    icon: <CheckCircle2 size={11} />,
    label: 'pass',
  },
  warning: {
    wrap: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300',
    icon: <AlertTriangle size={11} />,
    label: 'warn',
  },
  fail: {
    wrap: 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/30 dark:text-rose-300',
    icon: <XCircle size={11} />,
    label: 'fail',
  },
};

const INVEST_LABEL: Record<CanonicalStoryInvestKey, string> = {
  independent: 'I',
  negotiable: 'N',
  valuable: 'V',
  estimable: 'E',
  small: 'S',
  testable: 'T',
};

function InvestBadge({ k, check }: { k: CanonicalStoryInvestKey; check: CanonicalStoryInvestCheck }) {
  const styles = STATUS_STYLES[check.status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-mono font-medium ${styles.wrap}`}
      title={`${k}: ${check.reason || styles.label}`}
    >
      <span>{INVEST_LABEL[k]}</span>
      {styles.icon}
    </span>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-slate-200/70 py-2 dark:border-slate-700/50">
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-xs leading-5 text-slate-700 dark:text-slate-200">{children}</div>
    </div>
  );
}

function StringList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) {
    return <span className="text-slate-400 dark:text-slate-500">{empty}</span>;
  }
  return (
    <ul className="space-y-0.5">
      {items.map((item) => (
        <li key={item} className="break-words">
          - {item}
        </li>
      ))}
    </ul>
  );
}

const ParsedStoryView: FC<{
  story: CanonicalStoryDocument['story'];
  defaultOpen?: boolean | undefined;
}> = ({ story, defaultOpen = false }) => {
  const [open, setOpen] = useState(defaultOpen);
  const investEntries = useMemo(
    () =>
      CANONICAL_STORY_INVEST_KEYS.map((k) => ({ k, check: story.invest[k] })) as Array<{
        k: CanonicalStoryInvestKey;
        check: CanonicalStoryInvestCheck;
      }>,
    [story.invest]
  );

  const failingChecks = investEntries.filter(({ check }) => check.status !== 'pass').length;
  const acCount = story.acceptance_criteria.length;
  const dependencyOk = story.dependencies_and_sequencing.independent_story_check === 'pass';

  return (
    <div
      className="rounded-md border border-slate-200/80 bg-white text-slate-800 shadow-[0_0_0_1px_rgba(0,0,0,0.02)] dark:border-slate-700/60 dark:bg-slate-900/40 dark:text-slate-100"
      data-testid="canonical-story-card"
    >
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        className="flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-900/70"
        aria-expanded={open}
      >
        <span className="mt-0.5 shrink-0 text-slate-400 dark:text-slate-500">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-slate-500">
              Story · v{String(story.version)}
            </span>
            {!dependencyOk ? (
              <span className="inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300">
                <AlertTriangle size={10} />
                depends on others
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 truncate text-sm font-medium text-slate-900 dark:text-slate-50">
            {story.title || '(untitled story)'}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            {investEntries.map(({ k, check }) => (
              <InvestBadge key={k} k={k} check={check} />
            ))}
            <span className="ml-1 text-[11px] text-slate-500 dark:text-slate-400">
              {String(acCount)} AC{acCount === 1 ? '' : 's'}
              {failingChecks > 0 ? ` · ${String(failingChecks)} INVEST issue${failingChecks === 1 ? '' : 's'}` : ''}
            </span>
          </div>
        </span>
      </button>

      {open ? (
        <div className="px-3 pb-2">
          <Section label="Problem">
            <span className="whitespace-pre-wrap break-words">
              {story.problem_statement || '—'}
            </span>
          </Section>
          <Section label="User value">
            <span className="whitespace-pre-wrap break-words">{story.user_value || '—'}</span>
          </Section>
          <Section label="Acceptance criteria">
            {story.acceptance_criteria.length === 0 ? (
              <span className="text-slate-400 dark:text-slate-500">none</span>
            ) : (
              <ul className="space-y-1">
                {story.acceptance_criteria.map((ac) => (
                  <li
                    key={ac.id}
                    className="flex items-start gap-2 border-b border-slate-100 pb-1 last:border-b-0 dark:border-slate-800"
                  >
                    <span className="mt-0.5 shrink-0 rounded bg-slate-100 px-1 font-mono text-[10px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {ac.id}
                    </span>
                    <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">
                      {ac.text}
                    </span>
                    <span
                      className={`shrink-0 text-[9px] font-semibold uppercase tracking-[0.1em] ${
                        ac.testable
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-rose-500 dark:text-rose-400'
                      }`}
                    >
                      {ac.testable ? 'testable' : 'untestable'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
          <Section label="Constraints / affected areas">
            <StringList items={story.constraints_and_affected_areas} empty="none" />
          </Section>
          <Section label="Dependencies">
            <div className="space-y-1">
              <div>
                <span className="text-slate-500 dark:text-slate-400">Independent story check: </span>
                <span
                  className={
                    dependencyOk
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-rose-500 dark:text-rose-400'
                  }
                >
                  {story.dependencies_and_sequencing.independent_story_check}
                </span>
              </div>
              {story.dependencies_and_sequencing.depends_on.length > 0 ? (
                <div>
                  <span className="text-slate-500 dark:text-slate-400">Depends on: </span>
                  <span>{story.dependencies_and_sequencing.depends_on.join(', ')}</span>
                </div>
              ) : null}
              {story.dependencies_and_sequencing.unblock_condition ? (
                <div>
                  <span className="text-slate-500 dark:text-slate-400">Unblock when: </span>
                  <span className="break-words">
                    {story.dependencies_and_sequencing.unblock_condition}
                  </span>
                </div>
              ) : null}
            </div>
          </Section>
          {story.out_of_scope.length > 0 ? (
            <Section label="Out of scope">
              <StringList items={story.out_of_scope} empty="none" />
            </Section>
          ) : null}
          <Section label="INVEST">
            <ul className="space-y-1">
              {investEntries.map(({ k, check }) => (
                <li key={k} className="flex items-start gap-2">
                  <InvestBadge k={k} check={check} />
                  <span className="text-slate-500 dark:text-slate-400 capitalize">{k}</span>
                  <span className="min-w-0 flex-1 break-words text-slate-700 dark:text-slate-200">
                    {check.reason || '—'}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      ) : null}
    </div>
  );
};

const InvalidStoryView: FC<{ result: CanonicalStoryParseResult }> = ({ result }) => {
  const [open, setOpen] = useState(false);
  return (
    <div
      className="rounded-md border border-amber-200 bg-amber-50/70 dark:border-amber-900/60 dark:bg-amber-950/20"
      data-testid="canonical-story-invalid"
    >
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs text-amber-800 dark:text-amber-300"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <AlertTriangle size={12} />
        <span className="font-medium">Canonical story has {String(result.issues.length)} issue{result.issues.length === 1 ? '' : 's'}</span>
      </button>
      {open ? (
        <div className="border-t border-amber-200/70 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-900/60 dark:text-amber-300">
          <ul className="mb-2 list-disc space-y-0.5 pl-4">
            {result.issues.map((issue) => (
              <li key={issue} className="break-words">
                {issue}
              </li>
            ))}
          </ul>
          <pre className="overflow-x-auto rounded bg-amber-100/60 p-2 font-mono text-[10px] leading-4 text-amber-900 dark:bg-amber-900/30 dark:text-amber-200">
            {result.rawYaml}
          </pre>
        </div>
      ) : null}
    </div>
  );
};

export const CanonicalStoryCard: FC<CanonicalStoryCardProps> = ({ result, defaultOpen }) => {
  if (result.story) {
    return <ParsedStoryView story={result.story.story} defaultOpen={defaultOpen} />;
  }
  return <InvalidStoryView result={result} />;
};
