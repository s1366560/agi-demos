/**
 * Audit Logs Page
 *
 * Displays tenant audit trail with filtering, pagination, export, and detail drawer.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, DatePicker } from 'antd';
import { BookOpen, Braces, Download, History, List, RefreshCw } from 'lucide-react';

import {
  useLazyMessage,
  LazySelect,
  LazyEmpty,
  LazySpin,
  LazyDrawer,
} from '@/components/ui/lazyAntd';

import {
  useAuditLogs,
  useAuditTotal,
  useAuditLoading,
  useAuditError,
  useAuditActions,
  useAuditStore,
} from '../../stores/audit';
import { useTenantStore } from '../../stores/tenant';

import type { AuditEntry } from '../../services/auditService';

const { Search } = Input;

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

const PAGE_SIZE = 20;

export const AuditLogs: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const tenantId = useTenantStore((s) => s.currentTenant?.id ?? null);

  const logs = useAuditLogs();
  const total = useAuditTotal();
  const isLoading = useAuditLoading();
  const error = useAuditError();
  const page = useAuditStore((s) => s.page);
  const { fetchLogs, exportLogs, clearError, reset } = useAuditActions();

  const [actionFilter, setActionFilter] = useState('');
  const [resourceTypeFilter, setResourceTypeFilter] = useState('');
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const buildParams = useCallback(() => {
    const params: Record<string, string | number> = {
      page,
      page_size: PAGE_SIZE,
    };
    if (actionFilter) params.action = actionFilter;
    if (resourceTypeFilter) params.resource_type = resourceTypeFilter;
    if (fromDate) params.from_date = fromDate;
    if (toDate) params.to_date = toDate;
    return params;
  }, [page, actionFilter, resourceTypeFilter, fromDate, toDate]);

  // Fetch on mount and filter changes
  useEffect(() => {
    if (!tenantId) return;
    fetchLogs(tenantId, buildParams()).catch(() => {
      /* handled by store */
    });
  }, [tenantId, fetchLogs, buildParams]);

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

  const handlePageChange = useCallback(
    (newPage: number) => {
      if (!tenantId) return;
      fetchLogs(tenantId, { ...buildParams(), page: newPage }).catch(() => {
        /* handled by store */
      });
    },
    [tenantId, fetchLogs, buildParams]
  );

  const handleExport = useCallback(
    async (format: 'csv' | 'json') => {
      if (!tenantId) return;
      setIsExporting(true);
      try {
        await exportLogs(tenantId, format, buildParams());
        message?.success(t('tenant.auditLogs.exportSuccess'));
      } catch {
        // handled by store
      } finally {
        setIsExporting(false);
      }
    },
    [tenantId, exportLogs, buildParams, message, t]
  );

  const handleRefresh = useCallback(() => {
    if (!tenantId) return;
    fetchLogs(tenantId, buildParams()).catch(() => {
      /* handled by store */
    });
  }, [tenantId, fetchLogs, buildParams]);

  const totalPages = useMemo(() => Math.ceil(total / PAGE_SIZE), [total]);

  const formatTimestamp = (ts: string) => {
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  };

  if (!tenantId) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant')}</p>
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto w-full flex flex-col gap-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('tenant.auditLogs.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t('tenant.auditLogs.description')}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={16} />
          </button>
          <div className="relative">
            <button
              type="button"
              disabled={isExporting}
              onClick={() => handleExport('csv')}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50"
            >
              <Download size={16} />
              {t('tenant.auditLogs.exportCsv')}
            </button>
          </div>
          <button
            type="button"
            disabled={isExporting}
            onClick={() => handleExport('json')}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <Braces size={16} />
            {t('tenant.auditLogs.exportJson')}
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.auditLogs.stats.total')}
              </p>
              <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{total}</p>
            </div>
            <History size={16} className="text-4xl text-primary-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.auditLogs.stats.thisPage')}
              </p>
              <p className="text-2xl font-bold text-blue-600 dark:text-blue-400 mt-1">
                {logs.length}
              </p>
            </div>
            <List size={16} className="text-4xl text-blue-500" />
          </div>
        </div>

        <div className="bg-white dark:bg-slate-800 rounded-lg p-6 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.auditLogs.stats.pages')}
              </p>
              <p className="text-2xl font-bold text-purple-600 dark:text-purple-400 mt-1">
                {totalPages}
              </p>
            </div>
            <BookOpen size={16} className="text-4xl text-purple-500" />
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <Search
              id="audit-action-search"
              placeholder={t('tenant.auditLogs.filterActionPlaceholder')}
              value={actionFilter}
              onChange={(e) => {
                setActionFilter(e.target.value);
              }}
              allowClear
            />
          </div>
          <LazySelect
            value={resourceTypeFilter}
            onChange={(val: string) => {
              setResourceTypeFilter(val);
            }}
            className="w-full sm:w-44"
            options={RESOURCE_TYPE_OPTIONS}
            placeholder={t('tenant.auditLogs.filterResourceType')}
          />
          <DatePicker
            placeholder={t('tenant.auditLogs.filterFromDate')}
            className="w-full sm:w-40"
            onChange={(_date, dateString) => {
              setFromDate(typeof dateString === 'string' ? dateString : '');
            }}
          />
          <DatePicker
            placeholder={t('tenant.auditLogs.filterToDate')}
            className="w-full sm:w-40"
            onChange={(_date, dateString) => {
              setToDate(typeof dateString === 'string' ? dateString : '');
            }}
          />
        </div>
      </div>

      {/* Table */}
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
                    {t('common.actions')}
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
                        {entry.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      {entry.resource_type}
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

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-700">
              <p className="text-sm text-slate-600 dark:text-slate-400">
                {t('tenant.auditLogs.showing', {
                  from: (page - 1) * PAGE_SIZE + 1,
                  to: Math.min(page * PAGE_SIZE, total),
                  total,
                })}
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    handlePageChange(page - 1);
                  }}
                  disabled={page <= 1}
                  className="px-3 py-1.5 border border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.previous')}
                </button>
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    handlePageChange(page + 1);
                  }}
                  disabled={page >= totalPages}
                  className="px-3 py-1.5 border border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.next')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Detail Drawer */}
      <LazyDrawer
        title={t('tenant.auditLogs.detailTitle')}
        open={selectedEntry !== null}
        onClose={() => {
          setSelectedEntry(null);
        }}
        width={560}
      >
        {selectedEntry && (
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
                <p className="text-sm text-slate-900 dark:text-white">{selectedEntry.action}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.auditLogs.colResourceType')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedEntry.resource_type}
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
                  {JSON.stringify(selectedEntry.details, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </LazyDrawer>
    </div>
  );
};
