import { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Drawer } from 'antd';
import { FileDiff, RefreshCw } from 'lucide-react';


import type { RunSummary } from '@/services/projectWorkService';
import type { ActiveAgentRun } from '@/services/runInputService';
import {
  runReviewService,
  type ChangeScope,
  type ChangeSnapshot,
} from '@/services/runReviewService';

import { Spinner } from '@/components/common/Spinner';

interface RunReviewDrawerProps {
  run: ActiveAgentRun | null;
  latestTurnId?: string | null;
}

export function RunReviewDrawer({ run, latestTurnId }: RunReviewDrawerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<ChangeScope>('run');
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [changes, setChanges] = useState<ChangeSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSummary(null);
    setChanges(null);
    setError(null);
  }, [run?.run_id]);

  const load = useCallback(async () => {
    if (!run) return;
    setLoading(true);
    setError(null);
    try {
      const [nextSummary, nextChanges] = await Promise.all([
        runReviewService.getSummary(run.run_id),
        runReviewService.getChanges(run.run_id, {
          scope,
          expected_revision: run.run_revision,
          ...(scope === 'turn' && latestTurnId ? { turn_id: latestTurnId } : {}),
        }),
      ]);
      setSummary(nextSummary);
      setChanges(nextChanges);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }, [latestTurnId, run, scope]);

  useEffect(() => {
    if (open) void load();
  }, [load, open]);

  if (!run) return null;

  return (
    <>
      <button
        type="button"
        aria-label={t('agent.runReview.title', { defaultValue: 'Run review' })}
        onClick={() => {
          setOpen(true);
        }}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-slate-200 px-2 text-xs text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        <FileDiff size={15} />
        <span className="hidden xl:inline">
          {t('agent.runReview.title', { defaultValue: 'Run review' })}
        </span>
      </button>
      <Drawer
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        size="large"
        title={t('agent.runReview.title', { defaultValue: 'Run summary and changes' })}
        extra={
          <button
            type="button"
            onClick={() => {
              void load();
            }}
            disabled={loading}
            aria-label={t('common.refresh', { defaultValue: 'Refresh' })}
            className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <RefreshCw size={15} />
          </button>
        }
      >
        <div className="mb-4 flex flex-wrap gap-1.5">
          {(['turn', 'run', 'session'] as const).map((candidate) => (
            <button
              key={candidate}
              type="button"
              disabled={candidate === 'turn' && !latestTurnId}
              aria-pressed={scope === candidate}
              onClick={() => {
                setScope(candidate);
              }}
              className={`rounded-full border px-2.5 py-1 text-xs ${
                scope === candidate
                  ? 'border-primary/50 bg-primary/10 text-primary'
                  : 'border-slate-200 text-slate-500 dark:border-slate-700 dark:text-slate-400'
              } disabled:cursor-not-allowed disabled:opacity-40`}
            >
              {t(`agent.runReview.scope.${candidate}`, { defaultValue: candidate })}
            </button>
          ))}
        </div>
        {loading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : error ? (
          <div role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            {t('agent.runReview.loadFailed', {
              defaultValue: 'The authoritative run review could not be loaded.',
            })}
          </div>
        ) : (
          <div className="space-y-5">
            {summary && (
              <section className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {t('agent.runReview.summary', { defaultValue: 'Completion summary' })}
                  </h3>
                  <span className="text-xs text-slate-500">{summary.status}</span>
                </div>
                {summary.completion_summary ? (
                  <p className="mt-2 whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300">
                    {summary.completion_summary}
                  </p>
                ) : (
                  <p className="mt-2 text-xs text-slate-500">
                    {t('agent.runReview.summaryUnavailable', {
                      defaultValue: 'No authoritative summary was recorded for this run.',
                    })}
                  </p>
                )}
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                  {summary.input_tokens !== null &&
                    summary.input_tokens !== undefined &&
                    summary.output_tokens !== null &&
                    summary.output_tokens !== undefined && (
                    <span>
                      {t('agent.runReview.tokens', {
                        defaultValue: '{{count}} tokens',
                        count: summary.input_tokens + summary.output_tokens,
                      })}
                    </span>
                  )}
                  {summary.files_changed !== null && summary.files_changed !== undefined && (
                    <span>
                      {t('agent.runReview.changeCount', {
                        defaultValue: '{{count}} files changed',
                        count: summary.files_changed,
                      })}
                    </span>
                  )}
                  {summary.checks_passed !== null &&
                    summary.checks_passed !== undefined &&
                    summary.checks_failed !== null &&
                    summary.checks_failed !== undefined && (
                    <span>
                      {t('agent.runReview.checkCount', {
                        defaultValue: '{{passed}} passed · {{failed}} failed',
                        passed: summary.checks_passed,
                        failed: summary.checks_failed,
                      })}
                    </span>
                  )}
                </div>
              </section>
            )}
            {changes && (
              <section>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {t('agent.runReview.changes', { defaultValue: 'Changes' })}
                  </h3>
                  <span className="text-xs text-slate-500">
                    +{changes.additions} / -{changes.deletions}
                  </span>
                </div>
                {changes.status !== 'ready' ? (
                  <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-500 dark:bg-slate-900">
                    {changes.reason ||
                      t('agent.runReview.unattributed', {
                        defaultValue: 'Changes are not attributable at this scope.',
                      })}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {changes.files.map((file) => (
                      <details
                        key={`${file.path}:${file.patch_digest}`}
                        className="rounded-lg border border-slate-200 p-2 dark:border-slate-800"
                      >
                        <summary className="cursor-pointer text-xs font-medium text-slate-800 dark:text-slate-200">
                          {file.path}{' '}
                          <span className="font-normal text-slate-400">
                            +{file.additions} / -{file.deletions}
                          </span>
                        </summary>
                        <div className="mt-2 space-y-2 overflow-x-auto">
                          {file.hunks.map((hunk, index) => (
                            <pre
                              key={hunk.id || `${hunk.header}:${String(index)}`}
                              className="min-w-max rounded bg-slate-950 p-2 text-[11px] leading-5 text-slate-200"
                            >
                              {hunk.header}
                              {'\n'}
                              {hunk.lines
                                .map((line) => {
                                  const prefix =
                                    line.kind === 'addition'
                                      ? '+'
                                      : line.kind === 'deletion'
                                        ? '-'
                                        : ' ';
                                  return `${prefix}${line.text}`;
                                })
                                .join('\n')}
                            </pre>
                          ))}
                        </div>
                      </details>
                    ))}
                  </div>
                )}
              </section>
            )}
          </div>
        )}
      </Drawer>
    </>
  );
}
