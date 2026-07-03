import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { Activity, Bot, ClipboardList, FolderOpen, Gauge, ShieldQuestion } from 'lucide-react';

import { PermissionHitlCenter } from './PermissionHitlCenter';

import type { AgentRunViewModel } from './agentRunViewModel';

export interface AgentRunOverviewProps {
  run: AgentRunViewModel;
}

const MetricCard = memo<{
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string | undefined;
}>(({ icon, label, value, hint }) => (
  <div className="rounded-lg border border-slate-200/70 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/35">
    <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
      <span className="flex h-6 w-6 items-center justify-center rounded-md bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
        {icon}
      </span>
      {label}
    </div>
    <div className="mt-2 text-lg font-semibold text-slate-900 dark:text-slate-100">{value}</div>
    {hint ? (
      <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{hint}</p>
    ) : null}
  </div>
));

MetricCard.displayName = 'MetricCard';

export const AgentRunOverview = memo<AgentRunOverviewProps>(({ run }) => {
  const { t } = useTranslation();
  const modeLabel =
    run.mode === 'plan'
      ? t('agent.run.mode.plan', { defaultValue: 'Plan' })
      : run.mode === 'auto'
        ? t('agent.run.mode.auto', { defaultValue: 'Auto' })
        : run.mode === 'readOnly'
          ? t('agent.run.mode.readOnly', { defaultValue: 'Read-only' })
          : t('agent.run.mode.build', { defaultValue: 'Build' });
  const statusLabel =
    run.status === 'running'
      ? t('agent.run.status.running', { defaultValue: 'Running' })
      : run.status === 'waiting'
        ? t('agent.run.status.waiting', { defaultValue: 'Needs input' })
        : run.status === 'blocked'
          ? t('agent.run.status.blocked', { defaultValue: 'Blocked' })
          : t('agent.run.status.idle', { defaultValue: 'Idle' });
  const verification =
    run.verificationState === 'test_evidence'
      ? t('agent.run.verification.tests', { defaultValue: 'Tests evidence ready' })
      : run.verificationState === 'diff_ready'
        ? t('agent.run.verification.diff', { defaultValue: 'Diff evidence ready' })
        : run.verificationState === 'artifacts_ready'
          ? t('agent.run.verification.artifacts', { defaultValue: 'Artifacts ready' })
          : t('agent.run.verification.none', { defaultValue: 'No verification evidence' });

  return (
    <div className="space-y-4 p-3" data-testid="agent-run-overview">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <MetricCard
          icon={<Activity size={14} />}
          label={t('agent.run.overview.status', { defaultValue: 'Status' })}
          value={statusLabel}
          hint={
            run.currentToolName
              ? t('agent.run.overview.currentTool', {
                  defaultValue: 'Current tool: {{tool}}',
                  tool: run.currentToolName,
                })
              : verification
          }
        />
        <MetricCard
          icon={<Gauge size={14} />}
          label={t('agent.run.overview.mode', { defaultValue: 'Mode' })}
          value={modeLabel}
          hint={t('agent.run.overview.policyHint', {
            defaultValue: 'Execution still respects HITL approvals and project policy.',
          })}
        />
        <MetricCard
          icon={<ClipboardList size={14} />}
          label={t('agent.run.overview.plan', { defaultValue: 'Plan' })}
          value={
            run.taskSummary.total > 0
              ? t('agent.run.overview.taskProgress', {
                  defaultValue: '{{done}}/{{total}} done',
                  done: run.taskSummary.completed,
                  total: run.taskSummary.total,
                })
              : t('agent.run.overview.noTasks', { defaultValue: 'No tasks' })
          }
          hint={run.taskSummary.currentTask?.content}
        />
        <MetricCard
          icon={<Bot size={14} />}
          label={t('agent.run.overview.agents', { defaultValue: 'Agents' })}
          value={t('agent.run.overview.agentCount', {
            defaultValue: '{{running}} running / {{total}} total',
            running: run.agentSummary.running,
            total: run.agentSummary.total,
          })}
          hint={run.agentSummary.active?.name ?? undefined}
        />
        <MetricCard
          icon={<ShieldQuestion size={14} />}
          label={t('agent.run.overview.userInput', { defaultValue: 'User input' })}
          value={t('agent.run.overview.hitlCount', {
            defaultValue: '{{count}} pending',
            count: run.pendingRequests.length,
          })}
          hint={t('agent.run.overview.hitlBreakdown', {
            defaultValue:
              '{{permissions}} permissions, {{decisions}} decisions, {{configs}} configs',
            permissions: run.pendingRequestCounts.permission,
            decisions: run.pendingRequestCounts.decision,
            configs: run.pendingRequestCounts.env_var,
          })}
        />
        <MetricCard
          icon={<FolderOpen size={14} />}
          label={t('agent.run.overview.evidence', { defaultValue: 'Evidence' })}
          value={t('agent.run.overview.evidenceCount', {
            defaultValue: '{{count}} items',
            count: run.evidence.total,
          })}
          hint={t('agent.run.overview.evidenceBreakdown', {
            defaultValue:
              '{{tests}} tests, {{diffs}} diffs, {{screenshots}} screenshots, {{logs}} logs',
            tests: run.evidence.testRuns,
            diffs: run.evidence.diffs,
            screenshots: run.evidence.screenshots,
            logs: run.evidence.logs,
          })}
        />
      </div>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {t('agent.run.hitl.title', { defaultValue: 'Permission & HITL center' })}
          </h3>
        </div>
        <PermissionHitlCenter requests={run.pendingRequests} />
      </section>

      {run.latestNarrative ? (
        <section className="rounded-lg border border-slate-200/70 bg-white p-3 dark:border-slate-700 dark:bg-slate-900/35">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {t('agent.run.overview.latestTrace', { defaultValue: 'Latest trace' })}
          </h3>
          <p className="mt-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {run.latestNarrative.stage}
          </p>
          <p className="mt-1 text-sm leading-6 text-slate-700 dark:text-slate-200">
            {run.latestNarrative.summary}
          </p>
        </section>
      ) : null}
    </div>
  );
});

AgentRunOverview.displayName = 'AgentRunOverview';
