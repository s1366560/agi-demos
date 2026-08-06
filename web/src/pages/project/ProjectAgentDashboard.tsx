import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { Activity, AlertCircle, ListTree, RefreshCw, Workflow } from 'lucide-react';

import { ApiError } from '@/services/client/ApiError';
import { ProjectAgentContractError, projectAgentService } from '@/services/projectAgentService';

import type { SubAgentRunDTO } from '@/types/multiAgent';

type LoadState = 'loading' | 'ready' | 'forbidden' | 'unavailable';

export type ProjectAgentTraceReasonCode =
  | 'project_agent_trace_forbidden'
  | 'project_agent_trace_unavailable'
  | 'project_agent_trace_scope_conflict'
  | 'project_agent_trace_contract_invalid';

export function projectAgentTraceReasonCode(error: unknown): ProjectAgentTraceReasonCode {
  if (error instanceof ApiError && error.statusCode === 403) {
    return 'project_agent_trace_forbidden';
  }
  if (error instanceof ProjectAgentContractError) {
    if (error.reasonCode === 'project_agent_trace_scope_conflict') {
      return 'project_agent_trace_scope_conflict';
    }
    if (error.reasonCode === 'project_agent_trace_contract_invalid') {
      return 'project_agent_trace_contract_invalid';
    }
  }
  return 'project_agent_trace_unavailable';
}

export function ProjectAgentDashboard() {
  const { tenantId, projectId } = useParams<{ tenantId: string; projectId: string }>();
  const { t } = useTranslation();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [runs, setRuns] = useState<SubAgentRunDTO[]>([]);
  const [activeCount, setActiveCount] = useState(0);
  const [failureReason, setFailureReason] = useState<ProjectAgentTraceReasonCode>(
    'project_agent_trace_unavailable'
  );
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [resolvedRequestKey, setResolvedRequestKey] = useState<string | null>(null);
  const requestKey = projectId ? `${projectId}:${refreshRevision}` : null;
  const visibleLoadState: LoadState = !projectId
    ? 'unavailable'
    : resolvedRequestKey === requestKey
      ? loadState
      : 'loading';

  useEffect(() => {
    if (!projectId) return;
    const activeRequestKey = `${projectId}:${refreshRevision}`;
    let active = true;
    void Promise.all([
      projectAgentService.listRuns(projectId, { limit: 8 }),
      projectAgentService.getActiveRunCount(projectId),
    ])
      .then(([runPage, count]) => {
        if (!active) return;
        setRuns(runPage.runs);
        setActiveCount(count.active_count);
        setLoadState('ready');
        setResolvedRequestKey(activeRequestKey);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setRuns([]);
        setActiveCount(0);
        const reasonCode = projectAgentTraceReasonCode(error);
        setFailureReason(reasonCode);
        setLoadState(reasonCode === 'project_agent_trace_forbidden' ? 'forbidden' : 'unavailable');
        setResolvedRequestKey(activeRequestKey);
      });
    return () => {
      active = false;
    };
  }, [projectId, refreshRevision]);

  const basePath =
    tenantId && projectId ? `/tenant/${tenantId}/project/${projectId}/agent` : '/tenant';

  if (visibleLoadState === 'forbidden' || visibleLoadState === 'unavailable') {
    return (
      <ProjectAgentError
        reasonCode={failureReason}
        onRetry={() => setRefreshRevision((value) => value + 1)}
      />
    );
  }

  return (
    <section className="space-y-6" data-testid="project-agent-dashboard">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
            {t('projectAgent.eyebrow')}
          </p>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-slate-950 dark:text-white">
            {t('projectAgent.dashboard.title')}
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            {t('projectAgent.dashboard.description')}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setRefreshRevision((value) => value + 1)}
          disabled={visibleLoadState === 'loading'}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <RefreshCw size={16} aria-hidden="true" />
          {t('common.refresh')}
        </button>
      </header>

      <div className="grid gap-4 md:grid-cols-3">
        <MetricCard
          icon={Activity}
          label={t('projectAgent.dashboard.activeRuns')}
          value={visibleLoadState === 'loading' ? '—' : String(activeCount)}
        />
        <MetricCard
          icon={ListTree}
          label={t('projectAgent.dashboard.recentRuns')}
          value={visibleLoadState === 'loading' ? '—' : String(runs.length)}
        />
        <Link
          to={`${basePath}/patterns`}
          className="rounded-xl border border-slate-200 bg-white p-5 transition-colors hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:bg-slate-900"
        >
          <Workflow size={18} className="text-slate-500" aria-hidden="true" />
          <div className="mt-3 text-sm font-semibold text-slate-900 dark:text-white">
            {t('projectAgent.patterns.title')}
          </div>
          <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
            {t('projectAgent.patterns.degradedBadge')}
          </div>
        </Link>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <h2 className="font-semibold text-slate-950 dark:text-white">
            {t('projectAgent.dashboard.recentRuns')}
          </h2>
          <Link
            className="text-sm font-medium text-blue-600 hover:underline"
            to={`${basePath}/logs`}
          >
            {t('projectAgent.dashboard.viewAll')}
          </Link>
        </div>
        <RunList runs={runs} loading={visibleLoadState === 'loading'} />
      </div>
    </section>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950">
      <Icon size={18} className="text-slate-500" aria-hidden="true" />
      <div className="mt-3 text-3xl font-black text-slate-950 dark:text-white">{value}</div>
      <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{label}</div>
    </div>
  );
}

export function RunList({ runs, loading }: { runs: SubAgentRunDTO[]; loading: boolean }) {
  const { t } = useTranslation();
  if (loading) {
    return <div className="p-8 text-sm text-slate-500">{t('common.loading')}</div>;
  }
  if (runs.length === 0) {
    return <div className="p-8 text-sm text-slate-500">{t('projectAgent.logs.empty')}</div>;
  }
  return (
    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
      {runs.map((run) => (
        <li key={run.run_id} className="grid gap-2 px-5 py-4 md:grid-cols-[1fr_auto]">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">
              {run.subagent_name}
            </p>
            <p className="mt-1 truncate text-sm text-slate-500 dark:text-slate-400">{run.task}</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <span className="rounded-full bg-slate-100 px-2 py-1 dark:bg-slate-800">
              {run.status}
            </span>
            <time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString()}</time>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ProjectAgentError({
  reasonCode,
  onRetry,
}: {
  reasonCode: ProjectAgentTraceReasonCode;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  return (
    <section
      role="alert"
      data-reason-code={reasonCode}
      className="rounded-xl border border-red-200 bg-red-50 p-8 text-center dark:border-red-900/50 dark:bg-red-950/20"
    >
      <AlertCircle className="mx-auto text-red-600" aria-hidden="true" />
      <h1 className="mt-3 text-lg font-semibold text-red-950 dark:text-red-100">
        {t(`projectAgent.errors.${reasonCode}.title`)}
      </h1>
      <p className="mt-2 text-sm text-red-800 dark:text-red-200">
        {t(`projectAgent.errors.${reasonCode}.description`)}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-5 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800"
      >
        {t('common.retry')}
      </button>
    </section>
  );
}

export default ProjectAgentDashboard;
