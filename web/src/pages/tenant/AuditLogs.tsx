/**
 * Audit Logs Page
 *
 * Displays tenant audit trail with filtering, pagination, export, detail drawer,
 * and a focused runtime-hook observability view.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { DatePicker, Input } from 'antd';
import {
  Activity,
  BookOpen,
  Boxes,
  Braces,
  Download,
  History,
  RefreshCw,
  Search as SearchIcon,
  Shield,
} from 'lucide-react';

import {
  LazyDrawer,
  LazyEmpty,
  useLazyMessage,
  LazySelect,
  LazySpin,
} from '@/components/ui/lazyAntd';

import {
  useAuditActions,
  useAuditError,
  useAuditLoading,
  useAuditLogs,
  useAuditTotal,
  useRuntimeHookAuditSummary,
  useRuntimeHookAuditSummaryLoading,
} from '../../stores/audit';
import { useTenantStore } from '../../stores/tenant';

import type {
  AuditEntry,
  AuditListParams,
  RuntimeHookAuditListParams,
} from '../../services/auditService';

const { Search } = Input;

const PAGE_SIZE = 20;

type AuditViewMode = 'all' | 'runtime-hooks';

const RESOURCE_TYPE_OPTIONS = [
  { value: '', label: 'All Types' },
  { value: 'instance', label: 'Instance' },
  { value: 'project', label: 'Project' },
  { value: 'user', label: 'User' },
  { value: 'tenant', label: 'Tenant' },
  { value: 'api_key', label: 'API Key' },
  { value: 'member', label: 'Member' },
  { value: 'skill', label: 'Skill' },
  { value: 'subagent', label: 'SubAgent' },
  { value: 'mcp_server', label: 'MCP Server' },
];

const RUNTIME_HOOK_ACTION_VALUES = [
  'runtime_hook.custom_execution_blocked',
  'runtime_hook.custom_execution_started',
  'runtime_hook.custom_execution_failed',
  'runtime_hook.custom_execution_succeeded',
  'runtime_hook.custom_execution_requires_sandbox',
] as const;

const RUNTIME_HOOK_ACTION_FALLBACK_LABELS: Record<string, string> = {
  custom_execution_blocked: 'Blocked',
  custom_execution_started: 'Started',
  custom_execution_failed: 'Failed',
  custom_execution_succeeded: 'Succeeded',
  custom_execution_requires_sandbox: 'Requires Sandbox',
};

const RUNTIME_HOOK_EXECUTOR_VALUES = ['builtin', 'script', 'plugin'] as const;

const RUNTIME_HOOK_FAMILY_VALUES = ['observational', 'mutating', 'policy', 'side_effect'] as const;

const RUNTIME_HOOK_ISOLATION_VALUES = ['host', 'sandbox'] as const;

function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function getTopCountEntry(
  counts: Record<string, number> | null | undefined
): [string, number] | null {
  const entries = Object.entries(counts ?? {});
  if (entries.length === 0) return null;
  return entries.sort((a, b) => b[1] - a[1])[0] ?? null;
}

function formatRuntimeHookAction(action: string): string {
  const normalizedAction = action.replace(/^runtime_hook\./u, '');
  return (
    RUNTIME_HOOK_ACTION_FALLBACK_LABELS[normalizedAction] ?? formatFallbackLabel(normalizedAction)
  );
}

function formatFallbackLabel(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
}

function getDetailLabel(entry: AuditEntry, key: string): string {
  const value = entry.details?.[key];
  return typeof value === 'string' && value.trim() ? value : '—';
}

interface SummaryBreakdownProps {
  title: string;
  counts: Record<string, number>;
  emptyLabel: string;
  formatLabel?: (label: string) => string;
}

const SummaryBreakdown: React.FC<SummaryBreakdownProps> = ({
  title,
  counts,
  emptyLabel,
  formatLabel,
}) => {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/40 p-4">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-3">{title}</p>
      {entries.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{emptyLabel}</p>
      ) : (
        <div className="space-y-2">
          {entries.map(([label, count]) => (
            <div key={label} className="flex items-center justify-between gap-4 text-sm">
              <span className="text-slate-600 dark:text-slate-300 break-all">
                {formatLabel?.(label) ?? label}
              </span>
              <span className="font-medium text-slate-900 dark:text-white">{count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

interface SummaryBarChartProps {
  title: string;
  counts: Record<string, number>;
  emptyLabel: string;
  formatLabel?: (label: string) => string;
}

const SummaryBarChart: React.FC<SummaryBarChartProps> = ({
  title,
  counts,
  emptyLabel,
  formatLabel,
}) => {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const maxCount = Math.max(...entries.map(([, count]) => count), 0);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/40 p-4">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-4">{title}</p>
      {entries.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{emptyLabel}</p>
      ) : (
        <div data-testid="runtime-hook-action-chart" className="space-y-3">
          {entries.map(([label, count]) => {
            const widthRatio = maxCount > 0 ? Math.max((count / maxCount) * 100, 8) : 0;
            const width = `${widthRatio.toFixed(1)}%`;
            return (
              <div key={label} className="space-y-1.5">
                <div className="flex items-center justify-between gap-4 text-sm">
                  <span className="text-slate-600 dark:text-slate-300 break-all">
                    {formatLabel?.(label) ?? label}
                  </span>
                  <span className="font-medium text-slate-900 dark:text-white">{count}</span>
                </div>
                <div className="h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-primary-500 via-blue-500 to-violet-500"
                    style={{ width }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

interface RuntimeHookTimelineProps {
  items: AuditEntry[];
  title: string;
  emptyLabel: string;
  executorLabel: string;
  isolationLabel: string;
  familyLabel: string;
  resourceLabel: string;
  formatActionLabel: (label: string) => string;
  formatExecutorKindLabel: (label: string) => string;
  formatIsolationModeLabel: (label: string) => string;
  formatHookFamilyLabel: (label: string) => string;
}

const RuntimeHookTimeline: React.FC<RuntimeHookTimelineProps> = ({
  items,
  title,
  emptyLabel,
  executorLabel,
  isolationLabel,
  familyLabel,
  resourceLabel,
  formatActionLabel,
  formatExecutorKindLabel,
  formatIsolationModeLabel,
  formatHookFamilyLabel,
}) => {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/40 p-4">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-4">{title}</p>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{emptyLabel}</p>
      ) : (
        <ol data-testid="runtime-hook-timeline" className="space-y-4">
          {items.map((entry, index) => (
            <li key={entry.id} className="relative pl-6">
              {index < items.length - 1 && (
                <span className="absolute left-[0.45rem] top-5 h-[calc(100%+0.5rem)] w-px bg-slate-200 dark:bg-slate-700" />
              )}
              <span className="absolute left-0 top-1.5 h-3.5 w-3.5 rounded-full border-2 border-white dark:border-slate-900 bg-primary-500 shadow-sm" />
              <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white/70 dark:bg-slate-950/40 p-3">
                <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-900 dark:text-white">
                      {formatActionLabel(entry.action)}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                      {formatTimestamp(entry.timestamp)}
                    </p>
                  </div>
                  <span className="inline-flex items-center rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs text-slate-600 dark:text-slate-300">
                    {getDetailLabel(entry, 'hook_name')}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-slate-500 dark:text-slate-400 sm:grid-cols-2">
                  <div>
                    <span className="font-medium text-slate-600 dark:text-slate-300">
                      {executorLabel}:{' '}
                    </span>
                    {formatExecutorKindLabel(getDetailLabel(entry, 'executor_kind'))}
                  </div>
                  <div>
                    <span className="font-medium text-slate-600 dark:text-slate-300">
                      {isolationLabel}:{' '}
                    </span>
                    {formatIsolationModeLabel(getDetailLabel(entry, 'isolation_mode'))}
                  </div>
                  <div>
                    <span className="font-medium text-slate-600 dark:text-slate-300">
                      {familyLabel}:{' '}
                    </span>
                    {formatHookFamilyLabel(getDetailLabel(entry, 'hook_family'))}
                  </div>
                  <div className="truncate">
                    <span className="font-medium text-slate-600 dark:text-slate-300">
                      {resourceLabel}:{' '}
                    </span>
                    {entry.resource_id ?? '—'}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
};

export const AuditLogs: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const tenantId = useTenantStore((s) => s.currentTenant?.id ?? null);

  const logs = useAuditLogs();
  const total = useAuditTotal();
  const isLoading = useAuditLoading();
  const isRuntimeHookSummaryLoading = useRuntimeHookAuditSummaryLoading();
  const runtimeHookSummary = useRuntimeHookAuditSummary();
  const error = useAuditError();
  const {
    fetchLogs,
    fetchRuntimeHookLogs,
    fetchRuntimeHookSummary,
    exportLogs,
    clearError,
    reset,
  } = useAuditActions();

  const [viewMode, setViewMode] = useState<AuditViewMode>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [actionFilter, setActionFilter] = useState('');
  const [resourceTypeFilter, setResourceTypeFilter] = useState('');
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');
  const [runtimeActionFilter, setRuntimeActionFilter] = useState('');
  const [hookNameFilter, setHookNameFilter] = useState('');
  const [executorKindFilter, setExecutorKindFilter] = useState('');
  const [hookFamilyFilter, setHookFamilyFilter] = useState('');
  const [isolationModeFilter, setIsolationModeFilter] = useState('');
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const getLocalizedLabel = useCallback(
    (key: string, fallback: string): string => {
      const translated = t(key);
      return translated === key ? fallback : translated;
    },
    [t]
  );

  const formatRuntimeHookActionLabel = useCallback(
    (action: string): string => {
      const normalizedAction = action.replace(/^runtime_hook\./u, '');
      return getLocalizedLabel(
        `tenant.auditLogs.runtimeHookSummary.actionLabels.${normalizedAction}`,
        formatRuntimeHookAction(action)
      );
    },
    [getLocalizedLabel]
  );

  const formatExecutorKindLabel = useCallback(
    (executorKind: string): string =>
      getLocalizedLabel(
        `tenant.auditLogs.runtimeHookSummary.executorLabels.${executorKind}`,
        formatFallbackLabel(executorKind)
      ),
    [getLocalizedLabel]
  );

  const formatHookFamilyLabel = useCallback(
    (hookFamily: string): string =>
      getLocalizedLabel(
        `tenant.auditLogs.runtimeHookSummary.familyLabels.${hookFamily}`,
        formatFallbackLabel(hookFamily)
      ),
    [getLocalizedLabel]
  );

  const formatIsolationModeLabel = useCallback(
    (isolationMode: string): string =>
      getLocalizedLabel(
        `tenant.auditLogs.runtimeHookSummary.isolationLabels.${isolationMode}`,
        formatFallbackLabel(isolationMode)
      ),
    [getLocalizedLabel]
  );

  const runtimeHookActionOptions = useMemo(
    () => [
      {
        value: '',
        label: getLocalizedLabel('tenant.auditLogs.runtimeHookSummary.allActions', 'All Actions'),
      },
      ...RUNTIME_HOOK_ACTION_VALUES.map((value) => ({
        value,
        label: formatRuntimeHookActionLabel(value),
      })),
    ],
    [formatRuntimeHookActionLabel, getLocalizedLabel]
  );

  const runtimeHookExecutorOptions = useMemo(
    () => [
      {
        value: '',
        label: getLocalizedLabel(
          'tenant.auditLogs.runtimeHookSummary.allExecutors',
          'All Executors'
        ),
      },
      ...RUNTIME_HOOK_EXECUTOR_VALUES.map((value) => ({
        value,
        label: formatExecutorKindLabel(value),
      })),
    ],
    [formatExecutorKindLabel, getLocalizedLabel]
  );

  const runtimeHookFamilyOptions = useMemo(
    () => [
      {
        value: '',
        label: getLocalizedLabel('tenant.auditLogs.runtimeHookSummary.allFamilies', 'All Families'),
      },
      ...RUNTIME_HOOK_FAMILY_VALUES.map((value) => ({
        value,
        label: formatHookFamilyLabel(value),
      })),
    ],
    [formatHookFamilyLabel, getLocalizedLabel]
  );

  const runtimeHookIsolationOptions = useMemo(
    () => [
      {
        value: '',
        label: getLocalizedLabel(
          'tenant.auditLogs.runtimeHookSummary.allIsolationModes',
          'All Isolation Modes'
        ),
      },
      ...RUNTIME_HOOK_ISOLATION_VALUES.map((value) => ({
        value,
        label: formatIsolationModeLabel(value),
      })),
    ],
    [formatIsolationModeLabel, getLocalizedLabel]
  );

  const buildGenericParams = useCallback((): AuditListParams => {
    const params: AuditListParams = {
      page: currentPage,
      page_size: PAGE_SIZE,
    };
    if (actionFilter) params.action = actionFilter;
    if (resourceTypeFilter) params.resource_type = resourceTypeFilter;
    if (fromDate) params.from_date = fromDate;
    if (toDate) params.to_date = toDate;
    return params;
  }, [currentPage, actionFilter, resourceTypeFilter, fromDate, toDate]);

  const buildRuntimeHookParams = useCallback((): RuntimeHookAuditListParams => {
    const params: RuntimeHookAuditListParams = {
      page: currentPage,
      page_size: PAGE_SIZE,
    };
    if (runtimeActionFilter) params.action = runtimeActionFilter;
    if (hookNameFilter) params.hook_name = hookNameFilter;
    if (executorKindFilter) params.executor_kind = executorKindFilter;
    if (hookFamilyFilter) params.hook_family = hookFamilyFilter;
    if (isolationModeFilter) params.isolation_mode = isolationModeFilter;
    return params;
  }, [
    currentPage,
    runtimeActionFilter,
    hookNameFilter,
    executorKindFilter,
    hookFamilyFilter,
    isolationModeFilter,
  ]);

  const loadCurrentView = useCallback(async () => {
    if (!tenantId) return;

    if (viewMode === 'runtime-hooks') {
      const runtimeParams = buildRuntimeHookParams();
      const runtimeSummaryParams = {
        ...(runtimeParams.action ? { action: runtimeParams.action } : {}),
        ...(runtimeParams.hook_name ? { hook_name: runtimeParams.hook_name } : {}),
        ...(runtimeParams.executor_kind ? { executor_kind: runtimeParams.executor_kind } : {}),
        ...(runtimeParams.hook_family ? { hook_family: runtimeParams.hook_family } : {}),
        ...(runtimeParams.isolation_mode ? { isolation_mode: runtimeParams.isolation_mode } : {}),
      };
      await Promise.all([
        fetchRuntimeHookLogs(tenantId, runtimeParams),
        fetchRuntimeHookSummary(tenantId, runtimeSummaryParams),
      ]);
      return;
    }

    await fetchLogs(tenantId, buildGenericParams());
  }, [
    tenantId,
    viewMode,
    buildGenericParams,
    buildRuntimeHookParams,
    fetchLogs,
    fetchRuntimeHookLogs,
    fetchRuntimeHookSummary,
  ]);

  useEffect(() => {
    if (!tenantId) return;
    loadCurrentView().catch(() => {
      /* handled by store */
    });
  }, [tenantId, loadCurrentView]);

  useEffect(() => {
    return () => {
      reset();
    };
  }, [reset]);

  useEffect(() => {
    if (error) {
      message?.error(error);
      clearError();
    }
  }, [error, message, clearError]);

  const handlePageChange = useCallback((newPage: number) => {
    setCurrentPage(newPage);
  }, []);

  const handleExport = useCallback(
    async (format: 'csv' | 'json') => {
      if (!tenantId || viewMode === 'runtime-hooks') return;
      setIsExporting(true);
      try {
        await exportLogs(tenantId, format, buildGenericParams());
        message?.success(t('tenant.auditLogs.exportSuccess'));
      } catch {
        // handled by store
      } finally {
        setIsExporting(false);
      }
    },
    [tenantId, viewMode, exportLogs, buildGenericParams, message, t]
  );

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / PAGE_SIZE)), [total]);
  const runtimeTopExecutor = useMemo(
    () => getTopCountEntry(runtimeHookSummary?.executor_counts),
    [runtimeHookSummary]
  );
  const runtimeTopIsolation = useMemo(
    () => getTopCountEntry(runtimeHookSummary?.isolation_mode_counts),
    [runtimeHookSummary]
  );
  const runtimeTimelineEntries = useMemo(
    () => (viewMode === 'runtime-hooks' ? logs.slice(0, 6) : []),
    [viewMode, logs]
  );
  const runtimeHookResourceTypeLabel = useMemo(
    () =>
      getLocalizedLabel('tenant.auditLogs.runtimeHookSummary.resourceTypeLabel', 'Runtime Hook'),
    [getLocalizedLabel]
  );
  const formattedSelectedEntryDetails = useMemo(() => {
    if (!selectedEntry?.details) {
      return null;
    }
    if (selectedEntry.resource_type !== 'runtime_hook') {
      return selectedEntry.details;
    }

    return Object.fromEntries(
      Object.entries(selectedEntry.details).map(([key, value]) => {
        if (typeof value !== 'string') {
          return [key, value];
        }
        if (key === 'executor_kind') {
          return [key, formatExecutorKindLabel(value)];
        }
        if (key === 'hook_family') {
          return [key, formatHookFamilyLabel(value)];
        }
        if (key === 'isolation_mode') {
          return [key, formatIsolationModeLabel(value)];
        }
        return [key, value];
      })
    );
  }, [selectedEntry, formatExecutorKindLabel, formatHookFamilyLabel, formatIsolationModeLabel]);

  if (!tenantId) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant')}</p>
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.auditLogs.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t('tenant.auditLogs.description')}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex items-center rounded-lg border border-slate-300 dark:border-slate-600 overflow-hidden">
            <button
              type="button"
              data-testid="audit-view-all"
              onClick={() => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setViewMode('all');
              }}
              className={`px-3 py-2 text-sm transition-colors ${
                viewMode === 'all'
                  ? 'bg-primary-600 text-white'
                  : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'
              }`}
            >
              {t('tenant.auditLogs.mode.allEvents')}
            </button>
            <button
              type="button"
              data-testid="audit-view-runtime-hooks"
              onClick={() => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setViewMode('runtime-hooks');
              }}
              className={`px-3 py-2 text-sm transition-colors ${
                viewMode === 'runtime-hooks'
                  ? 'bg-primary-600 text-white'
                  : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300'
              }`}
            >
              {t('tenant.auditLogs.mode.runtimeHooks')}
            </button>
          </div>

          <button
            type="button"
            onClick={() => {
              loadCurrentView().catch(() => {
                /* handled by store */
              });
            }}
            disabled={isLoading || isRuntimeHookSummaryLoading}
            aria-label={t('common.refresh', 'Refresh')}
            title={t('common.refresh', 'Refresh')}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={16} />
          </button>

          {viewMode === 'all' && (
            <>
              <button
                type="button"
                disabled={isExporting}
                onClick={() => {
                  void handleExport('csv');
                }}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50"
              >
                <Download size={16} />
                {t('tenant.auditLogs.exportCsv')}
              </button>
              <button
                type="button"
                disabled={isExporting}
                onClick={() => {
                  void handleExport('json');
                }}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                <Braces size={16} />
                {t('tenant.auditLogs.exportJson')}
              </button>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {viewMode === 'runtime-hooks'
                  ? t('tenant.auditLogs.runtimeHookSummary.total')
                  : t('tenant.auditLogs.stats.total')}
              </p>
              <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">
                {viewMode === 'runtime-hooks' ? (runtimeHookSummary?.total ?? total) : total}
              </p>
            </div>
            <History size={16} className="text-4xl text-primary-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {viewMode === 'runtime-hooks'
                  ? t('tenant.auditLogs.runtimeHookSummary.topExecutor')
                  : t('tenant.auditLogs.stats.thisPage')}
              </p>
              <p className="text-2xl font-bold text-blue-600 dark:text-blue-400 mt-1">
                {viewMode === 'runtime-hooks'
                  ? runtimeTopExecutor
                    ? formatExecutorKindLabel(runtimeTopExecutor[0])
                    : '—'
                  : logs.length}
              </p>
            </div>
            <Boxes size={16} className="text-4xl text-blue-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {viewMode === 'runtime-hooks'
                  ? t('tenant.auditLogs.runtimeHookSummary.latestEvent')
                  : t('tenant.auditLogs.stats.pages')}
              </p>
              <p className="text-2xl font-bold text-purple-600 dark:text-purple-400 mt-1">
                {viewMode === 'runtime-hooks'
                  ? formatTimestamp(runtimeHookSummary?.latest_timestamp)
                  : totalPages}
              </p>
            </div>
            {viewMode === 'runtime-hooks' ? (
              <Activity size={16} className="text-4xl text-purple-500" />
            ) : (
              <BookOpen size={16} className="text-4xl text-purple-500" />
            )}
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        {viewMode === 'runtime-hooks' ? (
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="flex-1">
              <Search
                id="runtime-hook-name-search"
                aria-label={t('tenant.auditLogs.runtimeHookSummary.filterHookName')}
                placeholder={t('tenant.auditLogs.runtimeHookSummary.filterHookName')}
                value={hookNameFilter}
                onChange={(e) => {
                  setCurrentPage(1);
                  setSelectedEntry(null);
                  setHookNameFilter(e.target.value);
                }}
                allowClear
                enterButton={
                  <>
                    <span className="sr-only">{t('common.search', 'Search')}</span>
                    <SearchIcon size={16} aria-hidden="true" />
                  </>
                }
              />
            </div>
            <LazySelect
              aria-label={t('tenant.auditLogs.runtimeHookSummary.filterAction')}
              value={runtimeActionFilter}
              onChange={(val: string) => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setRuntimeActionFilter(val);
              }}
              className="w-full lg:w-52"
              options={runtimeHookActionOptions}
              placeholder={t('tenant.auditLogs.runtimeHookSummary.filterAction')}
            />
            <LazySelect
              aria-label={t('tenant.auditLogs.runtimeHookSummary.filterExecutorKind')}
              value={executorKindFilter}
              onChange={(val: string) => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setExecutorKindFilter(val);
              }}
              className="w-full lg:w-40"
              options={runtimeHookExecutorOptions}
              placeholder={t('tenant.auditLogs.runtimeHookSummary.filterExecutorKind')}
            />
            <LazySelect
              aria-label={t('tenant.auditLogs.runtimeHookSummary.filterHookFamily')}
              value={hookFamilyFilter}
              onChange={(val: string) => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setHookFamilyFilter(val);
              }}
              className="w-full lg:w-44"
              options={runtimeHookFamilyOptions}
              placeholder={t('tenant.auditLogs.runtimeHookSummary.filterHookFamily')}
            />
            <LazySelect
              aria-label={t('tenant.auditLogs.runtimeHookSummary.filterIsolationMode')}
              value={isolationModeFilter}
              onChange={(val: string) => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setIsolationModeFilter(val);
              }}
              className="w-full lg:w-44"
              options={runtimeHookIsolationOptions}
              placeholder={t('tenant.auditLogs.runtimeHookSummary.filterIsolationMode')}
            />
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="flex-1">
              <Search
                id="audit-action-search"
                aria-label={t('tenant.auditLogs.filterActionPlaceholder')}
                placeholder={t('tenant.auditLogs.filterActionPlaceholder')}
                value={actionFilter}
                onChange={(e) => {
                  setCurrentPage(1);
                  setSelectedEntry(null);
                  setActionFilter(e.target.value);
                }}
                allowClear
                enterButton={
                  <>
                    <span className="sr-only">{t('common.search', 'Search')}</span>
                    <SearchIcon size={16} aria-hidden="true" />
                  </>
                }
              />
            </div>
            <LazySelect
              aria-label={t('tenant.auditLogs.filterResourceType')}
              value={resourceTypeFilter}
              onChange={(val: string) => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setResourceTypeFilter(val);
              }}
              className="w-full sm:w-44"
              options={RESOURCE_TYPE_OPTIONS}
              placeholder={t('tenant.auditLogs.filterResourceType')}
            />
            <DatePicker
              aria-label={t('tenant.auditLogs.filterFromDate')}
              placeholder={t('tenant.auditLogs.filterFromDate')}
              className="w-full sm:w-40"
              onChange={(_date, dateString) => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setFromDate(typeof dateString === 'string' ? dateString : '');
              }}
            />
            <DatePicker
              aria-label={t('tenant.auditLogs.filterToDate')}
              placeholder={t('tenant.auditLogs.filterToDate')}
              className="w-full sm:w-40"
              onChange={(_date, dateString) => {
                setCurrentPage(1);
                setSelectedEntry(null);
                setToDate(typeof dateString === 'string' ? dateString : '');
              }}
            />
          </div>
        )}
      </div>

      {viewMode === 'runtime-hooks' && (
        <div
          data-testid="runtime-hook-summary"
          className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700"
        >
          <div className="flex items-start justify-between gap-4 mb-6">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                {t('tenant.auditLogs.runtimeHookSummary.title')}
              </h2>
              <p className="text-sm text-slate-500 mt-1">
                {t('tenant.auditLogs.runtimeHookSummary.description')}
              </p>
            </div>
            <div className="inline-flex items-center gap-2 rounded-full bg-slate-100 dark:bg-slate-900 px-3 py-1 text-xs font-medium text-slate-600 dark:text-slate-300">
              <Shield size={14} />
              {runtimeTopIsolation
                ? formatIsolationModeLabel(runtimeTopIsolation[0])
                : t('tenant.auditLogs.runtimeHookSummary.noData')}
            </div>
          </div>

          {isRuntimeHookSummaryLoading && !runtimeHookSummary ? (
            <div className="flex items-center justify-center py-10">
              <LazySpin size="large" />
            </div>
          ) : (
            <div className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {t('tenant.auditLogs.runtimeHookSummary.total')}
                  </p>
                  <p
                    data-testid="runtime-hook-summary-total"
                    className="mt-2 text-2xl font-bold text-slate-900 dark:text-white"
                  >
                    {runtimeHookSummary?.total ?? 0}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {t('tenant.auditLogs.runtimeHookSummary.latestEvent')}
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900 dark:text-white">
                    {formatTimestamp(runtimeHookSummary?.latest_timestamp)}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {t('tenant.auditLogs.runtimeHookSummary.topExecutor')}
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900 dark:text-white">
                    {runtimeTopExecutor ? formatExecutorKindLabel(runtimeTopExecutor[0]) : '—'}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    {t('tenant.auditLogs.runtimeHookSummary.topIsolation')}
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-900 dark:text-white">
                    {runtimeTopIsolation ? formatIsolationModeLabel(runtimeTopIsolation[0]) : '—'}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <SummaryBreakdown
                  title={t('tenant.auditLogs.runtimeHookSummary.actions')}
                  counts={runtimeHookSummary?.action_counts ?? {}}
                  emptyLabel={t('tenant.auditLogs.runtimeHookSummary.noData')}
                  formatLabel={formatRuntimeHookActionLabel}
                />
                <SummaryBreakdown
                  title={t('tenant.auditLogs.runtimeHookSummary.executors')}
                  counts={runtimeHookSummary?.executor_counts ?? {}}
                  emptyLabel={t('tenant.auditLogs.runtimeHookSummary.noData')}
                  formatLabel={formatExecutorKindLabel}
                />
                <SummaryBreakdown
                  title={t('tenant.auditLogs.runtimeHookSummary.families')}
                  counts={runtimeHookSummary?.family_counts ?? {}}
                  emptyLabel={t('tenant.auditLogs.runtimeHookSummary.noData')}
                  formatLabel={formatHookFamilyLabel}
                />
                <SummaryBreakdown
                  title={t('tenant.auditLogs.runtimeHookSummary.isolationModes')}
                  counts={runtimeHookSummary?.isolation_mode_counts ?? {}}
                  emptyLabel={t('tenant.auditLogs.runtimeHookSummary.noData')}
                  formatLabel={formatIsolationModeLabel}
                />
              </div>

              <div className="grid grid-cols-1 xl:grid-cols-[1.1fr,0.9fr] gap-4">
                <SummaryBarChart
                  title={t('tenant.auditLogs.runtimeHookSummary.actionChart')}
                  counts={runtimeHookSummary?.action_counts ?? {}}
                  emptyLabel={t('tenant.auditLogs.runtimeHookSummary.noData')}
                  formatLabel={formatRuntimeHookActionLabel}
                />
                <RuntimeHookTimeline
                  title={t('tenant.auditLogs.runtimeHookSummary.timeline')}
                  items={runtimeTimelineEntries}
                  emptyLabel={t('tenant.auditLogs.runtimeHookSummary.timelineEmpty')}
                  executorLabel={t('tenant.auditLogs.runtimeHookSummary.executorLabel')}
                  isolationLabel={t('tenant.auditLogs.runtimeHookSummary.isolationLabel')}
                  familyLabel={t('tenant.auditLogs.runtimeHookSummary.familyLabel')}
                  resourceLabel={t('tenant.auditLogs.runtimeHookSummary.resourceLabel')}
                  formatActionLabel={formatRuntimeHookActionLabel}
                  formatExecutorKindLabel={formatExecutorKindLabel}
                  formatIsolationModeLabel={formatIsolationModeLabel}
                  formatHookFamilyLabel={formatHookFamilyLabel}
                />
              </div>
            </div>
          )}
        </div>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LazySpin size="large" />
        </div>
      ) : logs.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <LazyEmpty description={t('tenant.auditLogs.noLogs')} />
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.auditLogs.colTimestamp')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.auditLogs.colActor')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.auditLogs.colAction')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.auditLogs.colResourceType')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.auditLogs.colResourceId')}
                  </th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('common.actions.label')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                {logs.map((entry) => (
                  <tr
                    key={entry.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-900/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300 whitespace-nowrap">
                      {formatTimestamp(entry.timestamp)}
                    </td>
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300">
                      {entry.actor_name ?? entry.actor ?? '-'}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300">
                        {viewMode === 'runtime-hooks'
                          ? formatRuntimeHookActionLabel(entry.action)
                          : entry.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      {viewMode === 'runtime-hooks' && entry.resource_type === 'runtime_hook'
                        ? runtimeHookResourceTypeLabel
                        : entry.resource_type}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 font-mono text-xs truncate max-w-50">
                      {entry.resource_id ?? '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedEntry(entry);
                        }}
                        className="text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 text-sm font-medium"
                      >
                        {t('tenant.auditLogs.viewDetails')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-700">
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.auditLogs.showing', {
                  from: (currentPage - 1) * PAGE_SIZE + 1,
                  to: Math.min(currentPage * PAGE_SIZE, total),
                  total,
                })}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    handlePageChange(currentPage - 1);
                  }}
                  disabled={currentPage <= 1}
                  className="px-3 py-1.5 border border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.previous')}
                </button>
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  {currentPage} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    handlePageChange(currentPage + 1);
                  }}
                  disabled={currentPage >= totalPages}
                  className="px-3 py-1.5 border border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.next')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {selectedEntry && (
        <LazyDrawer
          title={t('tenant.auditLogs.detailTitle')}
          open
          onClose={() => {
            setSelectedEntry(null);
          }}
          size="large"
        >
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.auditLogs.colTimestamp')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {formatTimestamp(selectedEntry.timestamp)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.auditLogs.colActor')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedEntry.actor_name ?? selectedEntry.actor ?? '-'}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.auditLogs.colAction')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedEntry.resource_type === 'runtime_hook'
                    ? formatRuntimeHookActionLabel(selectedEntry.action)
                    : selectedEntry.action}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.auditLogs.colResourceType')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedEntry.resource_type === 'runtime_hook'
                    ? runtimeHookResourceTypeLabel
                    : selectedEntry.resource_type}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.auditLogs.colResourceId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono">
                  {selectedEntry.resource_id ?? '-'}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  IP
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono">
                  {selectedEntry.ip_address ?? '-'}
                </p>
              </div>
            </div>

            {selectedEntry.user_agent && (
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  User Agent
                </p>
                <p className="text-sm text-slate-600 dark:text-slate-300 break-all">
                  {selectedEntry.user_agent}
                </p>
              </div>
            )}

            {selectedEntry.details && Object.keys(selectedEntry.details).length > 0 && (
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">
                  {t('tenant.auditLogs.details')}
                </p>
                <pre className="bg-slate-50 dark:bg-slate-900 rounded-lg p-4 text-xs font-mono text-slate-700 dark:text-slate-300 overflow-x-auto max-h-80">
                  {JSON.stringify(formattedSelectedEntryDetails, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </LazyDrawer>
      )}
    </div>
  );
};
