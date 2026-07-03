import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  AlertTriangle,
  Bot,
  CircleDot,
  ClipboardList,
  FolderOpen,
  PauseCircle,
  ShieldQuestion,
  Square,
} from 'lucide-react';

import type { AgentRunViewModel } from './agentRunViewModel';

export interface RunStatusStripProps {
  run: AgentRunViewModel;
  onStop?: (() => void) | undefined;
  onOpenInspector?: (() => void) | undefined;
  onOpenEvidence?: (() => void) | undefined;
}

function statusToneClass(status: AgentRunViewModel['status']): string {
  switch (status) {
    case 'running':
      return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800/60 dark:bg-blue-950/25 dark:text-blue-300';
    case 'waiting':
      return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800/60 dark:bg-amber-950/25 dark:text-amber-300';
    case 'blocked':
      return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-800/60 dark:bg-rose-950/25 dark:text-rose-300';
    case 'idle':
    default:
      return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300';
  }
}

export const RunStatusStrip = memo<RunStatusStripProps>(
  ({ run, onStop, onOpenInspector, onOpenEvidence }) => {
    const { t } = useTranslation();
    const statusLabel =
      run.status === 'running'
        ? t('agent.run.status.running', { defaultValue: 'Running' })
        : run.status === 'waiting'
          ? t('agent.run.status.waiting', { defaultValue: 'Needs input' })
          : run.status === 'blocked'
            ? t('agent.run.status.blocked', { defaultValue: 'Blocked' })
            : t('agent.run.status.idle', { defaultValue: 'Idle' });
    const modeLabel =
      run.mode === 'plan'
        ? t('agent.run.mode.plan', { defaultValue: 'Plan' })
        : run.mode === 'auto'
          ? t('agent.run.mode.auto', { defaultValue: 'Auto' })
          : run.mode === 'readOnly'
            ? t('agent.run.mode.readOnly', { defaultValue: 'Read-only' })
            : t('agent.run.mode.build', { defaultValue: 'Build' });
    const checkpoint =
      run.taskSummary.currentTask?.content ||
      (run.taskSummary.total > 0
        ? t('agent.run.checkpoint.finished', { defaultValue: 'All checkpoints complete' })
        : t('agent.run.checkpoint.none', { defaultValue: 'No checkpoint yet' }));
    const blocker =
      run.blocker === 'doom_loop'
        ? t('agent.run.blocker.doomLoop', {
            defaultValue: 'Repeated tool loop detected',
          })
        : run.blocker === 'hitl'
          ? t('agent.run.blocker.hitl', {
              defaultValue: '{{count}} user input request pending',
              count: run.pendingRequests.length,
            })
          : run.blocker === 'task_failed'
            ? t('agent.run.blocker.taskFailed', { defaultValue: 'Task failure needs review' })
            : null;
    const verification =
      run.verificationState === 'test_evidence'
        ? t('agent.run.verification.tests', { defaultValue: 'Tests evidence ready' })
        : run.verificationState === 'diff_ready'
          ? t('agent.run.verification.diff', { defaultValue: 'Diff evidence ready' })
          : run.verificationState === 'artifacts_ready'
            ? t('agent.run.verification.artifacts', { defaultValue: 'Artifacts ready' })
            : t('agent.run.verification.none', { defaultValue: 'No verification evidence' });

    return (
      <section
        className="flex shrink-0 flex-col gap-2 border-t border-slate-200/60 bg-white/85 px-3 py-2 dark:border-slate-800/70 dark:bg-slate-950/70 sm:px-4"
        data-testid="run-status-strip"
        aria-label={t('agent.run.statusStrip.aria', { defaultValue: 'Agent run status' })}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span
            className={`inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs font-semibold ${statusToneClass(run.status)}`}
          >
            {run.status === 'waiting' ? (
              <ShieldQuestion size={13} />
            ) : run.status === 'blocked' ? (
              <AlertTriangle size={13} />
            ) : (
              <CircleDot size={13} />
            )}
            {statusLabel}
          </span>
          <span className="inline-flex h-7 items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <PauseCircle size={13} />
            {modeLabel}
          </span>
          <span className="inline-flex h-7 min-w-0 max-w-full items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 sm:max-w-[38%]">
            <ClipboardList size={13} className="shrink-0" />
            <span className="truncate">
              {run.taskSummary.total > 0
                ? t('agent.run.checkpoint.progress', {
                    defaultValue: '{{done}}/{{total}} - {{checkpoint}}',
                    done: run.taskSummary.completed,
                    total: run.taskSummary.total,
                    checkpoint,
                  })
                : checkpoint}
            </span>
          </span>
          <span className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <Bot size={13} />
            <span className="truncate">
              {t('agent.run.agents.summary', {
                defaultValue: '{{running}} running / {{total}} agents',
                running: run.agentSummary.running,
                total: run.agentSummary.total,
              })}
            </span>
          </span>
          <button
            type="button"
            onClick={onOpenEvidence}
            disabled={run.evidence.total === 0}
            className="inline-flex h-7 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 text-xs text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            title={verification}
            aria-label={verification}
          >
            <FolderOpen size={13} />
            {t('agent.run.evidence.summary', {
              defaultValue: '{{count}} evidence',
              count: run.evidence.total,
            })}
          </button>
          {blocker ? (
            <span className="inline-flex h-7 min-w-0 items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2 text-xs text-amber-700 dark:border-amber-800/60 dark:bg-amber-950/25 dark:text-amber-300">
              <AlertTriangle size={13} className="shrink-0" />
              <span className="truncate">{blocker}</span>
            </span>
          ) : null}
          <div className="ml-auto flex shrink-0 items-center gap-1">
            {run.isStreaming && onStop ? (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex h-7 items-center gap-1 rounded-md bg-rose-600 px-2 text-xs font-medium text-white transition-colors hover:bg-rose-700"
              >
                <Square size={13} className="fill-current" />
                {t('agent.inputBar.stop', { defaultValue: 'Stop' })}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onOpenInspector}
              className="inline-flex h-7 items-center rounded-md border border-slate-200 bg-white px-2 text-xs font-medium text-slate-600 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t('agent.run.openInspector', { defaultValue: 'Inspector' })}
            </button>
          </div>
        </div>
      </section>
    );
  }
);

RunStatusStrip.displayName = 'RunStatusStrip';
