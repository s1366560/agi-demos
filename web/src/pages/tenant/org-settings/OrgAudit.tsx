/**
 * Organization Audit Logs Page
 *
 * Displays organization-level audit logs with filtering and export capabilities.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, DatePicker } from 'antd';
import { BookOpen, Braces, Download, History, List, RefreshCw } from 'lucide-react';

import {
  useAuditLogs,
  useAuditTotal,
  useAuditLoading,
  useAuditError,
  useAuditActions,
  useAuditStore,
} from '@/stores/audit';
import { useTenantStore } from '@/stores/tenant';

import type { AuditEntry } from '@/services/auditService';

import {
  useLazyMessage,
  LazySelect,
  LazyEmpty,
  LazySpin,
  LazyDrawer,
} from '@/components/ui/lazyAntd';

const { Search } = Input;

const RESOURCE_TYPE_OPTIONS = [
  { value: '', label: 'All Types' },
  { value: 'instance', label: 'Instance' },
  { value: 'project', label: 'Project' },
  { value: 'user', label: 'User' },
  { value: 'tenant', label: 'Tenant' },
  { value: 'cluster', label: 'Cluster' },
  { value: 'registry', label: 'Registry' },
  { value: 'member', label: 'Member' },
];

const ACTION_OPTIONS = [
  { value: '', label: 'All Actions' },
  { value: 'create', label: 'Create' },
  { value: 'update', label: 'Update' },
  { value: 'delete', label: 'Delete' },
  { value: 'login', label: 'Login' },
  { value: 'logout', label: 'Logout' },
  { value: 'invite', label: 'Invite' },
  { value: 'export', label: 'Export' },
];

const PAGE_SIZE = 15;

const getActionColor = (action: string): string => {
  switch (action.toLowerCase()) {
    case 'create':
      return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
    case 'update':
      return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
    case 'delete':
      return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300';
    case 'login':
    case 'logout':
      return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300';
    case 'invite':
      return 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300';
    case 'export':
      return 'bg-cyan-100 text-cyan-800 dark:bg-cyan-900/30 dark:text-cyan-300';
    default:
      return 'bg-slate-100 text-slate-800 dark:bg-slate-700 dark:text-slate-300';
  }
};

export const OrgAudit: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const tenantId = useTenantStore((s) => s.currentTenant?.id ?? null);

  const logs = useAuditLogs();
  const total = useAuditTotal();
  const isLoading = useAuditLoading();
  const error = useAuditError();
  const page = useAuditStore((s) => s.page);
  const { fetchLogs, exportLogs, clearError, reset } = useAuditActions();

  const [userFilter, setUserFilter] = useState('');
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
    if (userFilter) params.actor = userFilter;
    if (actionFilter) params.action = actionFilter;
    if (resourceTypeFilter) params.resource_type = resourceTypeFilter;
    if (fromDate) params.from_date = fromDate;
    if (toDate) params.to_date = toDate;
    return params;
  }, [page, userFilter, actionFilter, resourceTypeFilter, fromDate, toDate]);

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
        message?.success(t('tenant.orgSettings.audit.exportSuccess'));
      } catch {
        message?.error(t('common.error'));
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
    <div className="space-y-6">
      {/* Header with actions */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            {t('tenant.orgSettings.audit.title')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.orgSettings.audit.description')}
          </p>
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
          <button
            type="button"
            disabled={isExporting}
            onClick={() => handleExport('csv')}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <Download size={16} />
            {t('tenant.orgSettings.audit.exportCsv')}
          </button>
          <button
            type="button"
            disabled={isExporting}
            onClick={() => handleExport('json')}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <Braces size={16} />
            {t('tenant.orgSettings.audit.exportJson')}
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary-100 dark:bg-primary-900/30 rounded-lg">
              <History size={16} className="text-primary-600 dark:text-primary-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{total}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.audit.stats.total')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
              <List size={16} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{logs.length}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.audit.stats.thisPage')}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg">
              <BookOpen size={16} className="text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-slate-900 dark:text-white">{totalPages}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t('tenant.orgSettings.audit.stats.pages')}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <Search
            id="audit-user-search"
            placeholder={t('tenant.orgSettings.audit.filterUser')}
            value={userFilter}
            onChange={(e) => {
              setUserFilter(e.target.value);
            }}
            allowClear
          />
          <LazySelect
            value={actionFilter}
            onChange={(val: string) => {
              setActionFilter(val);
            }}
            options={ACTION_OPTIONS}
            className="w-full"
            placeholder={t('tenant.orgSettings.audit.filterAction')}
          />
          <LazySelect
            value={resourceTypeFilter}
            onChange={(val: string) => {
              setResourceTypeFilter(val);
            }}
            options={RESOURCE_TYPE_OPTIONS}
            className="w-full"
            placeholder={t('tenant.orgSettings.audit.filterResourceType')}
          />
          <DatePicker
            placeholder={t('tenant.orgSettings.audit.filterFromDate')}
            className="w-full"
            onChange={(_date, dateString) => {
              setFromDate(typeof dateString === 'string' ? dateString : '');
            }}
          />
          <DatePicker
            placeholder={t('tenant.orgSettings.audit.filterToDate')}
            className="w-full"
            onChange={(_date, dateString) => {
              setToDate(typeof dateString === 'string' ? dateString : '');
            }}
          />
        </div>
      </div>

      {/* Logs table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LazySpin size="large" />
        </div>
      ) : logs.length === 0 ? (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 py-20">
          <LazyEmpty description={t('tenant.orgSettings.audit.noLogs')} />
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.orgSettings.audit.colTimestamp')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.orgSettings.audit.colActor')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.orgSettings.audit.colAction')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.orgSettings.audit.colResourceType')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.orgSettings.audit.colResourceId')}
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
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${getActionColor(entry.action)}`}
                      >
                        {entry.action}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      {entry.resource_type}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 font-mono text-xs truncate max-w-[150px]">
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
                        {t('tenant.orgSettings.audit.viewDetails')}
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
                {t('tenant.orgSettings.audit.showing', {
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
        title={t('tenant.orgSettings.audit.detailTitle')}
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
                  {t('tenant.orgSettings.audit.colTimestamp')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {formatTimestamp(selectedEntry.timestamp)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.orgSettings.audit.colActor')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedEntry.actor_name ?? selectedEntry.actor ?? '-'}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.orgSettings.audit.colAction')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">{selectedEntry.action}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.orgSettings.audit.colResourceType')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedEntry.resource_type}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.orgSettings.audit.colResourceId')}
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
                  {t('tenant.orgSettings.audit.details')}
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

export default OrgAudit;
