import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { RefreshCw } from 'lucide-react';

import { projectAgentService } from '@/services/projectAgentService';

import {
  ProjectAgentError,
  projectAgentTraceReasonCode,
  RunList,
  type ProjectAgentTraceReasonCode,
} from './ProjectAgentDashboard';

import type { SubAgentRunDTO } from '@/types/multiAgent';

type LoadState = 'loading' | 'ready' | 'forbidden' | 'unavailable';

export function ProjectAgentLogs() {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState('');
  const [runs, setRuns] = useState<SubAgentRunDTO[]>([]);
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [failureReason, setFailureReason] = useState<ProjectAgentTraceReasonCode>(
    'project_agent_trace_unavailable'
  );
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [resolvedRequestKey, setResolvedRequestKey] = useState<string | null>(null);
  const requestKey = projectId ? `${projectId}:${statusFilter}:${refreshRevision}` : null;
  const visibleLoadState: LoadState = !projectId
    ? 'unavailable'
    : resolvedRequestKey === requestKey
      ? loadState
      : 'loading';

  useEffect(() => {
    if (!projectId) return;
    const activeRequestKey = `${projectId}:${statusFilter}:${refreshRevision}`;
    let active = true;
    const options = statusFilter ? { status: statusFilter, limit: 100 } : { limit: 100 };
    void projectAgentService
      .listRuns(projectId, options)
      .then((page) => {
        if (!active) return;
        setRuns(page.runs);
        setLoadState('ready');
        setResolvedRequestKey(activeRequestKey);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setRuns([]);
        const reasonCode = projectAgentTraceReasonCode(error);
        setFailureReason(reasonCode);
        setLoadState(reasonCode === 'project_agent_trace_forbidden' ? 'forbidden' : 'unavailable');
        setResolvedRequestKey(activeRequestKey);
      });
    return () => {
      active = false;
    };
  }, [projectId, refreshRevision, statusFilter]);

  if (visibleLoadState === 'forbidden' || visibleLoadState === 'unavailable') {
    return (
      <ProjectAgentError
        reasonCode={failureReason}
        onRetry={() => setRefreshRevision((value) => value + 1)}
      />
    );
  }

  return (
    <section className="space-y-6" data-testid="project-agent-logs">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
            {t('projectAgent.eyebrow')}
          </p>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-slate-950 dark:text-white">
            {t('projectAgent.logs.title')}
          </h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
            {t('projectAgent.logs.description')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-600 dark:text-slate-300" htmlFor="run-status-filter">
            {t('projectAgent.logs.statusFilter')}
          </label>
          <select
            id="run-status-filter"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="">{t('projectAgent.logs.allStatuses')}</option>
            {['pending', 'running', 'completed', 'failed', 'cancelled', 'timed_out'].map(
              (status) => (
                <option key={status} value={status}>
                  {t(`projectAgent.status.${status}`)}
                </option>
              )
            )}
          </select>
          <button
            type="button"
            onClick={() => setRefreshRevision((value) => value + 1)}
            disabled={visibleLoadState === 'loading'}
            aria-label={t('common.refresh')}
            className="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <RefreshCw size={18} aria-hidden="true" />
          </button>
        </div>
      </header>
      <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <RunList runs={runs} loading={visibleLoadState === 'loading'} />
      </div>
    </section>
  );
}

export default ProjectAgentLogs;
