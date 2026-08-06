import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { AlertTriangle, RefreshCw, Share2 } from 'lucide-react';

import { PatternInspector } from '@/components/agent/patterns/PatternInspector';
import {
  PatternList,
  type WorkflowPattern as UIPattern,
} from '@/components/agent/patterns/PatternList';
import { ApiError } from '@/services/client/ApiError';
import { ProjectAgentContractError, projectAgentService } from '@/services/projectAgentService';

import type { WorkflowPattern } from '@/types/agent';

type LoadState = 'loading' | 'ready' | 'forbidden' | 'unavailable';

export function ProjectAgentPatterns() {
  const { projectId } = useParams<{ tenantId: string; projectId: string }>();
  const { t } = useTranslation();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [patterns, setPatterns] = useState<UIPattern[]>([]);
  const [selectedPattern, setSelectedPattern] = useState<UIPattern | null>(null);
  const [sharedTenantId, setSharedTenantId] = useState<string | null>(null);
  const [reasonCode, setReasonCode] = useState('project_agent_patterns_authority_unavailable');
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [resolvedRequestKey, setResolvedRequestKey] = useState<string | null>(null);
  const requestKey = projectId ? `${projectId}:${refreshRevision}` : null;
  const visibleLoadState: LoadState = !projectId
    ? 'unavailable'
    : resolvedRequestKey === requestKey
      ? loadState
      : 'loading';
  const visibleReasonCode = projectId
    ? reasonCode
    : 'project_agent_patterns_scope_unavailable';

  useEffect(() => {
    if (!projectId) return;
    const activeRequestKey = `${projectId}:${refreshRevision}`;
    let active = true;
    void projectAgentService
      .listSharedPatterns(projectId)
      .then((response) => {
        if (!active) return;
        setPatterns(response.patterns.map(toUIPattern));
        setSharedTenantId(response.tenant_id);
        setReasonCode('project_agent_patterns_tenant_shared');
        setLoadState('ready');
        setResolvedRequestKey(activeRequestKey);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setPatterns([]);
        setSharedTenantId(null);
        if (error instanceof ApiError && error.statusCode === 403) {
          setReasonCode('project_agent_patterns_forbidden');
          setLoadState('forbidden');
          setResolvedRequestKey(activeRequestKey);
          return;
        }
        setReasonCode(
          error instanceof ProjectAgentContractError
            ? error.reasonCode
            : 'project_agent_patterns_authority_unavailable'
        );
        setLoadState('unavailable');
        setResolvedRequestKey(activeRequestKey);
      });
    return () => {
      active = false;
    };
  }, [projectId, refreshRevision]);

  if (visibleLoadState === 'forbidden' || visibleLoadState === 'unavailable') {
    return (
      <section
        role="alert"
        data-testid="project-agent-patterns"
        data-availability="unavailable"
        data-reason-code={visibleReasonCode}
        className="rounded-xl border border-amber-200 bg-amber-50 p-8 dark:border-amber-900/50 dark:bg-amber-950/20"
      >
        <AlertTriangle className="text-amber-700 dark:text-amber-300" aria-hidden="true" />
        <h1 className="mt-3 text-lg font-semibold text-amber-950 dark:text-amber-100">
          {t('projectAgent.patterns.unavailableTitle')}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-amber-900 dark:text-amber-200">
          {t('projectAgent.patterns.unavailableDescription')}
        </p>
        <button
          type="button"
          onClick={() => setRefreshRevision((value) => value + 1)}
          className="mt-5 rounded-lg border border-amber-300 px-4 py-2 text-sm font-semibold text-amber-900 hover:bg-amber-100 dark:border-amber-800 dark:text-amber-100 dark:hover:bg-amber-900/40"
        >
          {t('common.retry')}
        </button>
      </section>
    );
  }

  return (
    <section
      data-testid="project-agent-patterns"
      data-availability={visibleLoadState === 'loading' ? 'loading' : 'available'}
      data-reason-code={visibleReasonCode}
      data-scope-kind="tenant_shared"
      data-tenant-id={sharedTenantId ?? undefined}
      className="space-y-6"
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
            {t('projectAgent.eyebrow')}
          </p>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-slate-950 dark:text-white">
            {t('projectAgent.patterns.title')}
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            {t('projectAgent.patterns.sharedDescription')}
          </p>
          <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700 dark:bg-blue-950/40 dark:text-blue-200">
            <Share2 size={14} aria-hidden="true" />
            {t('projectAgent.patterns.sharedBadge')}
          </div>
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

      {visibleLoadState === 'loading' ? (
        <div className="rounded-xl border border-slate-200 p-8 text-sm text-slate-500 dark:border-slate-800">
          {t('common.loading')}
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_30rem]">
          <PatternList
            patterns={patterns}
            selectedId={selectedPattern?.id}
            onSelect={setSelectedPattern}
            viewMode="detailed"
            selectionPolicy="all"
          />
          <PatternInspector pattern={selectedPattern} onClose={() => setSelectedPattern(null)} />
        </div>
      )}
    </section>
  );
}

function toUIPattern(pattern: WorkflowPattern): UIPattern {
  const successRate = Math.round(pattern.success_rate * 10_000) / 100;
  return {
    id: pattern.id,
    name: pattern.name,
    signature: pattern.id.slice(0, 16),
    status: 'unclassified',
    usageCount: pattern.usage_count,
    successRate,
    avgRuntime: pattern.metadata?.avg_runtime as number | undefined,
    lastUsed: pattern.updated_at,
    pattern: {
      name: pattern.name,
      description: pattern.description,
      tools: pattern.steps.map((step) => step.tool_name),
      steps: pattern.steps.map((step) => ({
        tool: step.tool_name,
        params: step.tool_parameters || {},
      })),
    },
  };
}

export default ProjectAgentPatterns;
