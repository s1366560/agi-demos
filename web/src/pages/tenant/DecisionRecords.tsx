import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Modal, Select } from 'antd';
import { RefreshCw, Search as SearchIcon } from 'lucide-react';

import { useLazyMessage, LazyEmpty, LazySpin, LazyDrawer } from '@/components/ui/lazyAntd';

import { useTenantStore } from '../../stores/tenant';
import {
  useTrustDecisions,
  useTrustLoading,
  useTrustError,
  useTrustActions,
} from '../../stores/trust';

import type { DecisionRecord } from '../../services/trustService';

const { Search } = Input;
const { Option } = Select;

export const DecisionRecords: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const tenantId = useTenantStore((s) => s.currentTenant?.id ?? null);

  const decisions = useTrustDecisions();
  const isLoading = useTrustLoading();
  const error = useTrustError();
  const { fetchDecisions, resolveApproval, clearError } = useTrustActions();

  const [workspaceFilter, setWorkspaceFilter] = useState('');
  const [agentFilter, setAgentFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  const [selectedRecord, setSelectedRecord] = useState<DecisionRecord | null>(null);

  const [isResolveModalOpen, setIsResolveModalOpen] = useState(false);
  const [resolvingRecord, setResolvingRecord] = useState<DecisionRecord | null>(null);
  const [resolveAction, setResolveAction] = useState<string>('allow_once');
  const [isResolving, setIsResolving] = useState(false);

  const buildParams = useCallback(() => {
    const params: { workspace_id: string; agent_id?: string; decision_type?: string } = {
      workspace_id: workspaceFilter || 'default',
    };
    if (agentFilter) params.agent_id = agentFilter;
    if (typeFilter) params.decision_type = typeFilter;
    return params;
  }, [workspaceFilter, agentFilter, typeFilter]);

  useEffect(() => {
    if (!tenantId) return;
    fetchDecisions(tenantId, buildParams()).catch(() => {});
  }, [tenantId, fetchDecisions, buildParams]);

  useEffect(() => {
    if (error) {
      message?.error(error);
      clearError();
    }
  }, [error, message, clearError]);

  const handleRefresh = useCallback(() => {
    if (!tenantId) return;
    fetchDecisions(tenantId, buildParams()).catch(() => {});
  }, [tenantId, fetchDecisions, buildParams]);

  const handleResolveSubmit = async () => {
    if (!tenantId || !resolvingRecord) return;
    setIsResolving(true);
    try {
      await resolveApproval(tenantId, resolvingRecord.id, { decision: resolveAction });
      message?.success(t('tenant.decisionRecords.messages.resolved'));
      setIsResolveModalOpen(false);
      setResolvingRecord(null);
      handleRefresh();
    } catch {
      // handled by store
    } finally {
      setIsResolving(false);
    }
  };

  const openResolveModal = (record: DecisionRecord) => {
    setResolvingRecord(record);
    setResolveAction('allow_once');
    setIsResolveModalOpen(true);
  };

  const formatTimestamp = (ts: string) => {
    try {
      return new Date(ts).toLocaleString();
    } catch {
      return ts;
    }
  };

  const getOutcomeBadgeClass = (outcome: string) => {
    switch (outcome) {
      case 'pending':
        return 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-300';
      case 'approved':
        return 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300';
      case 'denied':
        return 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-300';
      default:
        return 'bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-300';
    }
  };

  const getOutcomeLabel = (outcome: string) =>
    t(`tenant.decisionRecords.outcomes.${outcome}`, outcome);

  const getDecisionTypeLabel = (decisionType: string) =>
    t(`tenant.decisionRecords.types.${decisionType}`, decisionType);

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
            {t('tenant.decisionRecords.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t('tenant.decisionRecords.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading}
            aria-label={t('tenant.decisionRecords.refresh')}
            title={t('tenant.decisionRecords.refresh')}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1 max-w-xs">
            <Search
              placeholder={t('tenant.decisionRecords.filters.workspaceId')}
              value={workspaceFilter}
              onChange={(e) => {
                setWorkspaceFilter(e.target.value);
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
          <div className="flex-1 max-w-xs">
            <Search
              placeholder={t('tenant.decisionRecords.filters.agentId')}
              value={agentFilter}
              onChange={(e) => {
                setAgentFilter(e.target.value);
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
          <div className="flex-1 max-w-xs">
            <Select
              className="w-full"
              placeholder={t('tenant.decisionRecords.filters.decisionType')}
              value={typeFilter}
              onChange={(val) => {
                setTypeFilter(val);
              }}
              allowClear
            >
              <Option value="permission">{t('tenant.decisionRecords.types.permission')}</Option>
              <Option value="action">{t('tenant.decisionRecords.types.action')}</Option>
            </Select>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LazySpin size="large" />
        </div>
      ) : decisions.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <LazyEmpty description={t('tenant.decisionRecords.empty')} />
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.decisionRecords.columns.decisionType')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.decisionRecords.columns.agentInstance')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.decisionRecords.columns.outcome')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.decisionRecords.columns.context')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.decisionRecords.columns.createdAt')}
                  </th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('common.actions.label')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                {decisions.map((record) => (
                  <tr
                    key={record.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-900/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300 font-medium capitalize">
                      {getDecisionTypeLabel(record.decision_type)}
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400 font-mono text-xs">
                      {record.agent_instance_id}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize ${getOutcomeBadgeClass(
                          record.outcome
                        )}`}
                      >
                        {getOutcomeLabel(record.outcome)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400 truncate max-w-xs">
                      {record.context_summary || '-'}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap text-xs">
                      {formatTimestamp(record.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-3">
                        {record.outcome === 'pending' && (
                          <button
                            type="button"
                            onClick={() => {
                              openResolveModal(record);
                            }}
                            className="text-green-600 hover:text-green-700 dark:text-green-400 dark:hover:text-green-300 text-sm font-medium"
                          >
                            {t('tenant.decisionRecords.actions.resolve')}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedRecord(record);
                          }}
                          className="text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 text-sm font-medium"
                        >
                          {t('tenant.decisionRecords.actions.details')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <LazyDrawer
        title={t('tenant.decisionRecords.drawer.title')}
        open={selectedRecord !== null}
        onClose={() => {
          setSelectedRecord(null);
        }}
        size={500}
      >
        {selectedRecord && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.recordId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedRecord.id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.outcome')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white capitalize">
                  {getOutcomeLabel(selectedRecord.outcome)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.decisionType')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white capitalize">
                  {getDecisionTypeLabel(selectedRecord.decision_type)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.workspaceId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedRecord.workspace_id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.agentInstanceId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedRecord.agent_instance_id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.reviewerId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedRecord.reviewer_id || '-'}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.createdAt')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {formatTimestamp(selectedRecord.created_at)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.resolvedAt')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedRecord.resolved_at ? formatTimestamp(selectedRecord.resolved_at) : '-'}
                </p>
              </div>
            </div>

            {selectedRecord.context_summary && (
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.contextSummary')}
                </p>
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  {selectedRecord.context_summary}
                </p>
              </div>
            )}

            {selectedRecord.review_comment && (
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.decisionRecords.drawer.reviewComment')}
                </p>
                <p className="text-sm text-slate-600 dark:text-slate-300">
                  {selectedRecord.review_comment}
                </p>
              </div>
            )}

            {Object.keys(selectedRecord.proposal).length > 0 && (
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-2">
                  {t('tenant.decisionRecords.drawer.proposalDetails')}
                </p>
                <pre className="bg-slate-50 dark:bg-slate-900 rounded-lg p-4 text-xs font-mono text-slate-700 dark:text-slate-300 overflow-x-auto max-h-80">
                  {JSON.stringify(selectedRecord.proposal, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </LazyDrawer>

      <Modal
        title={t('tenant.decisionRecords.resolve.title')}
        open={isResolveModalOpen}
        onCancel={() => {
          setIsResolveModalOpen(false);
          setResolvingRecord(null);
        }}
        onOk={() => {
          void handleResolveSubmit();
        }}
        confirmLoading={isResolving}
        okText={t('tenant.decisionRecords.resolve.ok')}
        cancelText={t('common.cancel')}
      >
        <div className="mt-4 flex flex-col gap-4">
          <p className="text-sm text-slate-600">
            {t('tenant.decisionRecords.resolve.descriptionPrefix')}{' '}
            <strong>{resolvingRecord?.agent_instance_id}</strong>
            {t('tenant.decisionRecords.resolve.descriptionSuffix')}
          </p>
          <div>
            <label htmlFor="resolve-action" className="block text-sm font-medium mb-1">
              {t('tenant.decisionRecords.resolve.decision')}
            </label>
            <Select
              id="resolve-action"
              className="w-full"
              value={resolveAction}
              onChange={(val) => {
                setResolveAction(val);
              }}
            >
              <Option value="allow_once">
                {t('tenant.decisionRecords.resolve.actions.allow_once')}
              </Option>
              <Option value="allow_always">
                {t('tenant.decisionRecords.resolve.actions.allow_always')}
              </Option>
              <Option value="deny">{t('tenant.decisionRecords.resolve.actions.deny')}</Option>
            </Select>
          </div>
        </div>
      </Modal>
    </div>
  );
};
