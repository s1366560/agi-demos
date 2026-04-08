import React, { memo, useCallback, useEffect, useRef, useState } from 'react';

import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import {
  Activity,
  ArrowUpRight,
  Brain,
  Cable,
  Link2,
  Loader2,
  Puzzle,
  Wrench,
  X,
} from 'lucide-react';

import { TraceChainView } from '../../components/agent/multiAgent/TraceChainView';
import { TraceTimeline } from '../../components/agent/multiAgent/TraceTimeline';
import { TenantAgentConfigEditor } from '../../components/agent/TenantAgentConfigEditor';
import { TenantAgentConfigView } from '../../components/agent/TenantAgentConfigView';
import { agentConfigService } from '../../services/agentConfigService';
import { traceAPI } from '../../services/traceService';
import { useTenantStore } from '../../stores/tenant';

import type { SubAgentRunDTO } from '../../types/multiAgent';
import type { TraceChainDTO } from '../../types/multiAgent';
import type { UntracedRunDetailsDTO } from '../../types/multiAgent';
import type { LucideIcon } from 'lucide-react';

type AgentDashboardProps = Record<string, never>;

interface RelatedSurfaceLink {
  title: string;
  description: string;
  path: string;
  icon: LucideIcon;
}

function createSingleRunDetails(run: SubAgentRunDTO): UntracedRunDetailsDTO {
  return {
    trace_id: null,
    conversation_id: run.conversation_id,
    runs: [run],
    total: 1,
  };
}

function buildRelatedSurfaces(basePath: string, t: TFunction): RelatedSurfaceLink[] {
  return [
    {
      title: t('nav.agentWorkspace'),
      description: t('tenant.agentDashboard.related.agentWorkspaceDescription'),
      path: `${basePath}/agent-workspace`,
      icon: Activity,
    },
    {
      title: t('nav.skills'),
      description: t('tenant.agentDashboard.related.skillsDescription'),
      path: `${basePath}/skills`,
      icon: Puzzle,
    },
    {
      title: t('nav.agentDefinitions'),
      description: t('tenant.agentDashboard.related.agentDefinitionsDescription'),
      path: `${basePath}/agent-definitions`,
      icon: Brain,
    },
    {
      title: t('nav.agentBindings'),
      description: t('tenant.agentDashboard.related.agentBindingsDescription'),
      path: `${basePath}/agent-bindings`,
      icon: Link2,
    },
    {
      title: t('nav.plugins'),
      description: t('tenant.agentDashboard.related.pluginsDescription'),
      path: `${basePath}/plugins`,
      icon: Wrench,
    },
    {
      title: t('nav.mcpServers'),
      description: t('tenant.agentDashboard.related.mcpServersDescription'),
      path: `${basePath}/mcp-servers`,
      icon: Cable,
    },
  ];
}

function RelatedSurfaceCard({ title, description, path, icon: Icon }: RelatedSurfaceLink) {
  return (
    <Link
      to={path}
      className="group flex items-start gap-3 rounded-2xl border border-slate-200/80 bg-white px-4 py-4 transition-colors duration-150 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700 dark:hover:bg-slate-900"
    >
      <div className="mt-0.5 rounded-xl border border-slate-200 bg-slate-50 p-2 text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200">
        <Icon size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-slate-900 dark:text-white">{title}</span>
          <ArrowUpRight
            size={14}
            className="text-slate-400 transition-transform duration-150 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-slate-600 dark:group-hover:text-slate-300"
          />
        </div>
        <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
      </div>
    </Link>
  );
}

export const AgentDashboard: React.FC<AgentDashboardProps> = memo(() => {
  const { t } = useTranslation();
  const { tenantId: routeTenantId } = useParams<{ tenantId: string }>();
  const currentTenantId = useTenantStore((state) => state.currentTenant?.id ?? null);
  const tenantId = routeTenantId ?? currentTenantId ?? null;
  const basePath = tenantId ? `/tenant/${tenantId}` : '/tenant';
  const relatedSurfaces = buildRelatedSurfaces(basePath, t);

  const [canEditConfig, setCanEditConfig] = useState(false);
  const [configEditorOpen, setConfigEditorOpen] = useState(false);
  const [configRefreshKey, setConfigRefreshKey] = useState(0);

  const [selectedRun, setSelectedRun] = useState<SubAgentRunDTO | null>(null);
  const [runs, setRuns] = useState<SubAgentRunDTO[]>([]);
  const [activeRunCount, setActiveRunCount] = useState(0);
  const [isTraceLoading, setIsTraceLoading] = useState(false);
  const [traceChain, setTraceChain] = useState<TraceChainDTO | UntracedRunDetailsDTO | null>(null);
  const [isChainLoading, setIsChainLoading] = useState(false);
  const [chainLoadError, setChainLoadError] = useState(false);
  const [hasLoadedTraces, setHasLoadedTraces] = useState(false);
  const [traceLoadError, setTraceLoadError] = useState(false);
  const [traceRefreshKey, setTraceRefreshKey] = useState(0);
  const traceRequestRef = useRef(0);

  useEffect(() => {
    if (!tenantId) {
      return;
    }

    let cancelled = false;
    void agentConfigService
      .canModifyConfig(tenantId)
      .then((allowed) => {
        if (!cancelled) {
          setCanEditConfig(allowed);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCanEditConfig(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  useEffect(() => {
    traceRequestRef.current += 1;
    let cancelled = false;

    queueMicrotask(() => {
      if (cancelled) {
        return;
      }
      setSelectedRun(null);
      setTraceChain(null);
      setIsChainLoading(false);
      setChainLoadError(false);
      setRuns([]);
      setActiveRunCount(0);
      setTraceLoadError(false);
      setHasLoadedTraces(false);
      setIsTraceLoading(Boolean(tenantId));
    });

    if (!tenantId) {
      return () => {
        cancelled = true;
      };
    }

    void Promise.allSettled([
      traceAPI.listTenantRuns(tenantId, { limit: 20 }),
      traceAPI.getTenantActiveRunCount(tenantId),
    ])
      .then(([runsResult, activeRunResult]) => {
        if (cancelled) {
          return;
        }

        if (runsResult.status === 'fulfilled') {
          setRuns(runsResult.value.runs);
          setTraceLoadError(false);
        } else {
          setRuns([]);
          setTraceLoadError(true);
        }

        if (activeRunResult.status === 'fulfilled') {
          setActiveRunCount(activeRunResult.value.active_count);
        } else {
          setActiveRunCount(0);
        }

        setHasLoadedTraces(true);
      })
      .finally(() => {
        if (!cancelled) {
          setIsTraceLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [tenantId, traceRefreshKey]);

  const handleSelectRun = useCallback((run: SubAgentRunDTO) => {
    setSelectedRun(run);

    traceRequestRef.current += 1;
    const requestId = traceRequestRef.current;
    setTraceChain(null);
    setChainLoadError(false);

    if (!run.trace_id) {
      setTraceChain(createSingleRunDetails(run));
      setIsChainLoading(false);
      return;
    }

    setIsChainLoading(true);
    void traceAPI
      .getTraceChain(run.conversation_id, run.trace_id)
      .then((chain) => {
        if (traceRequestRef.current === requestId) {
          setTraceChain(chain);
        }
      })
      .catch(() => {
        if (traceRequestRef.current === requestId) {
          setTraceChain(null);
          setChainLoadError(true);
        }
      })
      .finally(() => {
        if (traceRequestRef.current === requestId) {
          setIsChainLoading(false);
        }
      });
  }, []);

  return (
    <div className="mx-auto flex max-w-[1440px] flex-col gap-10 pb-24">
      <header className="grid gap-8 border-b border-slate-200/80 pb-10 dark:border-slate-800 xl:grid-cols-[minmax(0,1fr)_20rem] xl:items-end">
        <div className="max-w-4xl space-y-4">
          <div className="inline-flex flex-wrap items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            <span>{t('tenant.agentDashboard.eyebrow')}</span>
            {activeRunCount > 0 ? (
              <>
                <span className="h-1 w-1 rounded-full bg-slate-300 dark:bg-slate-700" />
                <span className="inline-flex items-center gap-1 text-slate-900 dark:text-slate-100">
                  <Activity size={12} className="animate-pulse motion-reduce:animate-none" />
                  {t('tenant.agentDashboard.activeRuns', { count: activeRunCount })}
                </span>
              </>
            ) : null}
          </div>
          <div className="space-y-3">
            <h1 className="text-4xl font-semibold tracking-[-0.04em] text-slate-950 dark:text-white sm:text-5xl">
              {t('tenant.agentDashboard.title')}
            </h1>
            <p className="max-w-3xl text-sm leading-7 text-slate-600 dark:text-slate-400 sm:text-base">
              {t('tenant.agentDashboard.description')}
            </p>
          </div>
        </div>

        <div className="rounded-[28px] border border-slate-200/80 bg-white p-6 shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
            {t('tenant.agentDashboard.scopeTitle')}
          </p>
          <p className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-400">
            {t('tenant.agentDashboard.scopeDescription')}
          </p>
        </div>
      </header>

      {!tenantId ? (
        <section className="rounded-[28px] border border-dashed border-slate-300 bg-slate-50/80 px-6 py-10 text-center dark:border-slate-700 dark:bg-slate-900/60">
          <h2 className="text-xl font-semibold tracking-[-0.03em] text-slate-900 dark:text-white">
            {t('tenant.agentDashboard.noTenantTitle')}
          </h2>
          <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">
            {t('tenant.agentDashboard.noTenantDescription')}
          </p>
        </section>
      ) : (
        <div className="grid gap-10 xl:grid-cols-[minmax(0,1fr)_20rem] xl:items-start">
          <div className="min-w-0 space-y-10">
            <section className="min-w-0">
              <TenantAgentConfigView
                key={`${tenantId}:${String(configRefreshKey)}`}
                tenantId={tenantId}
                canEdit={canEditConfig}
                onEdit={() => {
                  setConfigEditorOpen(true);
                }}
              />
              <TenantAgentConfigEditor
                open={configEditorOpen}
                tenantId={tenantId}
                onClose={() => {
                  setConfigEditorOpen(false);
                }}
                onSave={() => {
                  setConfigRefreshKey((current) => current + 1);
                }}
              />
            </section>

            <section className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    {t('tenant.agentDashboard.feedbackEyebrow')}
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-slate-950 dark:text-white">
                    {t('tenant.agentDashboard.feedbackTitle')}
                  </h2>
                </div>
                {isTraceLoading ? (
                  <Loader2
                    size={16}
                    className="text-slate-400 animate-spin motion-reduce:animate-none"
                  />
                ) : null}
              </div>

              {traceLoadError ? (
                <div className="rounded-[28px] border border-rose-200 bg-rose-50/80 px-6 py-8 dark:border-rose-900 dark:bg-rose-950/40">
                  <h3 className="text-lg font-semibold tracking-[-0.02em] text-rose-900 dark:text-rose-100">
                    {t('tenant.agentDashboard.traceLoadErrorTitle')}
                  </h3>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-rose-700 dark:text-rose-300">
                    {t('tenant.agentDashboard.traceLoadErrorDescription')}
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setTraceRefreshKey((current) => current + 1);
                    }}
                    className="mt-5 inline-flex min-h-11 items-center justify-center rounded-full border border-rose-300 px-5 text-sm font-medium text-rose-800 transition-colors duration-150 hover:bg-rose-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300 focus-visible:ring-offset-2 dark:border-rose-800 dark:text-rose-100 dark:hover:bg-rose-900/60"
                  >
                    {t('tenant.agentDashboard.retryTraceLoad')}
                  </button>
                </div>
              ) : !hasLoadedTraces ? (
                <div className="rounded-[28px] border border-slate-200/80 bg-white px-6 py-8 shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950">
                  <p className="text-lg font-semibold tracking-[-0.02em] text-slate-900 dark:text-white">
                    {t('tenant.agentDashboard.loadingTracesTitle')}
                  </p>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">
                    {t('tenant.agentDashboard.loadingTracesDescription')}
                  </p>
                </div>
              ) : runs.length === 0 ? (
                <div className="rounded-[28px] border border-dashed border-slate-300 bg-slate-50/80 px-6 py-8 dark:border-slate-700 dark:bg-slate-900/60">
                  <h3 className="text-lg font-semibold tracking-[-0.02em] text-slate-900 dark:text-white">
                    {t('tenant.agentDashboard.noTracesTitle')}
                  </h3>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">
                    {t('tenant.agentDashboard.noTracesDescription')}
                  </p>
                  <Link
                    to={`${basePath}/agent-workspace`}
                    className="mt-5 inline-flex min-h-11 items-center justify-center rounded-full bg-slate-950 px-5 text-sm font-medium text-white transition-colors duration-150 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200"
                  >
                    {t('tenant.agentDashboard.openWorkspace')}
                  </Link>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="rounded-[28px] border border-slate-200/80 bg-white p-4 shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950">
                    <TraceTimeline
                      runs={runs}
                      selectedRunId={selectedRun?.run_id ?? null}
                      onSelectRun={handleSelectRun}
                    />
                  </div>

                  {selectedRun ? (
                    <div className="rounded-[28px] border border-slate-200/80 bg-white p-4 shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950">
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                            {t('tenant.agentDashboard.selectedTrace')}
                          </p>
                          <h3 className="mt-2 text-lg font-semibold tracking-[-0.02em] text-slate-900 dark:text-white">
                            {selectedRun.run_id}
                          </h3>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            traceRequestRef.current += 1;
                            setSelectedRun(null);
                            setTraceChain(null);
                            setIsChainLoading(false);
                            setChainLoadError(false);
                          }}
                          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-full border border-slate-200 text-slate-500 transition-colors duration-150 hover:border-slate-300 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 dark:border-slate-800 dark:text-slate-400 dark:hover:border-slate-700 dark:hover:text-slate-200"
                          aria-label={t('tenant.agentDashboard.clearSelectedTrace')}
                        >
                            <X size={16} />
                          </button>
                        </div>
                        {chainLoadError ? (
                          <div className="rounded-2xl border border-rose-200 bg-rose-50/80 px-4 py-5 dark:border-rose-900 dark:bg-rose-950/40">
                            <h4 className="text-sm font-semibold text-rose-900 dark:text-rose-100">
                              {t(
                                'tenant.agentDashboard.traceChainLoadErrorTitle',
                                'Failed to load trace details'
                              )}
                            </h4>
                            <p className="mt-2 text-sm leading-6 text-rose-700 dark:text-rose-300">
                              {t(
                                'tenant.agentDashboard.traceChainLoadErrorDescription',
                                'The selected trace exists, but its detail chain could not be loaded right now.'
                              )}
                            </p>
                            <button
                              type="button"
                              onClick={() => {
                                handleSelectRun(selectedRun);
                              }}
                              className="mt-4 inline-flex min-h-11 items-center justify-center rounded-full border border-rose-300 px-5 text-sm font-medium text-rose-800 transition-colors duration-150 hover:bg-rose-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300 focus-visible:ring-offset-2 dark:border-rose-800 dark:text-rose-100 dark:hover:bg-rose-900/60"
                            >
                              {t(
                                'tenant.agentDashboard.retryTraceChainLoad',
                                'Retry loading trace'
                              )}
                            </button>
                          </div>
                        ) : (
                          <TraceChainView
                            data={traceChain}
                            isLoading={isChainLoading}
                            onSelectRun={handleSelectRun}
                          />
                        )}
                      </div>
                    ) : null}
                  </div>
                )}
            </section>
          </div>

          <aside className="space-y-4 xl:sticky xl:top-6">
            <section className="rounded-[28px] border border-slate-200/80 bg-white p-5 shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                {t('tenant.agentDashboard.relatedSurfaces')}
              </p>
              <div className="mt-4 space-y-3">
                {relatedSurfaces.map((surface) => (
                  <RelatedSurfaceCard key={surface.title} {...surface} />
                ))}
              </div>
            </section>

            <section className="rounded-[28px] border border-slate-200/80 bg-white p-5 shadow-[0_1px_0_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                {t('tenant.agentDashboard.editingModelTitle')}
              </p>
              <ul className="mt-4 space-y-3 text-sm leading-6 text-slate-600 dark:text-slate-400">
                <li>{t('tenant.agentDashboard.editingModelApplies')}</li>
                <li>{t('tenant.agentDashboard.editingModelHooks')}</li>
                <li>{t('tenant.agentDashboard.editingModelTraces')}</li>
              </ul>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
});

AgentDashboard.displayName = 'AgentDashboard';

export default AgentDashboard;
