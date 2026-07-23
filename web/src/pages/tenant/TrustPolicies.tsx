import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';

import { Input, Button, Form, Pagination, Select } from 'antd';
import { Plus, RefreshCw, Search as SearchIcon } from 'lucide-react';

import { confirmAction } from '@/utils/confirmAction';
import { formatDateTime } from '@/utils/date';

import { SkeletonLoader } from '@/components/common/SkeletonLoader';
import {
  useLazyMessage,
  LazyEmpty,
  LazyDrawer,
  LazyModal,
  LazyAlert,
  LazyPopconfirm,
} from '@/components/ui/lazyAntd';

import { useTenantStore } from '../../stores/tenant';
import {
  useTrustPolicies,
  useTrustLoading,
  useTrustError,
  useTrustActions,
} from '../../stores/trust';

import type { TrustPolicy, TrustPolicyCreate } from '../../services/trustService';

const { Search } = Input;
const { Option } = Select;

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

export const TrustPolicies: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string }>();
  const storeTenantId = useTenantStore((s) => s.currentTenant?.id ?? null);
  const tenantId = routeTenantId ?? storeTenantId;

  const policies = useTrustPolicies();
  const isLoading = useTrustLoading();
  const error = useTrustError();
  const { fetchPolicies, createPolicy, revokePolicy, clearError } = useTrustActions();

  const [searchParams, setSearchParams] = useSearchParams();
  const [workspaceFilter, setWorkspaceFilter] = useState(() => searchParams.get('workspace') ?? '');
  const [agentFilter, setAgentFilter] = useState(() => searchParams.get('agent') ?? '');
  const [appliedFilters, setAppliedFilters] = useState(() => ({
    workspace: searchParams.get('workspace') ?? '',
    agent: searchParams.get('agent') ?? '',
  }));
  const [page, setPage] = useState(() => {
    const p = Number(searchParams.get('page'));
    return Number.isInteger(p) && p > 0 ? p : 1;
  });
  const [loadError, setLoadError] = useState<string | null>(null);

  // Reflect applied filters/pagination in the URL so views survive reload and sharing
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (appliedFilters.workspace) {
      next.set('workspace', appliedFilters.workspace);
    } else {
      next.delete('workspace');
    }
    if (appliedFilters.agent) {
      next.set('agent', appliedFilters.agent);
    } else {
      next.delete('agent');
    }
    if (page > 1) {
      next.set('page', String(page));
    } else {
      next.delete('page');
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [appliedFilters, page, searchParams, setSearchParams]);

  const [selectedPolicy, setSelectedPolicy] = useState<TrustPolicy | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createForm] = Form.useForm<TrustPolicyCreate>();
  const [isCreating, setIsCreating] = useState(false);

  const buildParams = useCallback(() => {
    const params: { workspace_id: string; agent_instance_id?: string } = {
      workspace_id: appliedFilters.workspace || 'default', // Requires a workspace_id; backend treats empty as the default workspace
    };
    if (appliedFilters.agent) params.agent_instance_id = appliedFilters.agent;
    return params;
  }, [appliedFilters]);

  const loadPolicies = useCallback(async () => {
    if (!tenantId) return;
    try {
      await fetchPolicies(tenantId, buildParams());
      setLoadError(null);
    } catch (error) {
      setLoadError(getErrorMessage(error));
      clearError();
    }
  }, [tenantId, fetchPolicies, buildParams, clearError]);

  useEffect(() => {
    void loadPolicies();
  }, [loadPolicies]);

  useEffect(() => {
    if (error) {
      if (error !== loadError) {
        message?.error(error);
      }
      clearError();
    }
  }, [error, loadError, message, clearError]);

  const handleRefresh = useCallback(() => {
    void loadPolicies();
  }, [loadPolicies]);

  const handleSearch = useCallback(() => {
    setPage(1);
    setAppliedFilters({ workspace: workspaceFilter.trim(), agent: agentFilter.trim() });
  }, [workspaceFilter, agentFilter]);

  const handleCreateSubmit = async (values: TrustPolicyCreate) => {
    if (!tenantId) return;
    if (values.grant_type === 'always') {
      const confirmed = await confirmAction({
        title: t('tenant.trustPolicies.create.alwaysConfirmTitle', 'Grant persistent access?'),
        content: t('tenant.trustPolicies.create.alwaysConfirmContent', {
          defaultValue:
            'An "always" grant lets this agent run "{{actionType}}" without asking again until you revoke the policy.',
          actionType: values.action_type,
        }),
        okText: t('tenant.trustPolicies.actions.createPolicy'),
      });
      if (!confirmed) return;
    }
    setIsCreating(true);
    try {
      await createPolicy(tenantId, values);
      message?.success(t('tenant.trustPolicies.messages.created'));
      setIsCreateModalOpen(false);
      createForm.resetFields();
    } catch {
      // handled by store
    } finally {
      setIsCreating(false);
    }
  };

  const handleRevoke = async (policy: TrustPolicy) => {
    if (!tenantId) return;
    setRevokingId(policy.id);
    try {
      await revokePolicy(tenantId, policy.id, policy.workspace_id);
      message?.success(t('tenant.trustPolicies.messages.revoked', 'Trust policy revoked'));
      setSelectedPolicy((current) =>
        current?.id === policy.id ? { ...current, deleted_at: new Date().toISOString() } : current
      );
    } catch {
      message?.error(
        t('tenant.trustPolicies.messages.revokeFailed', 'Failed to revoke trust policy')
      );
    } finally {
      setRevokingId(null);
    }
  };

  const formatTimestamp = (ts: string) => formatDateTime(ts) || ts;

  const getGrantTypeLabel = (grantType: string) =>
    t(`tenant.trustPolicies.grantTypes.${grantType}`, grantType);

  const POLICIES_PAGE_SIZE = 20;
  const totalPolicyPages = Math.max(1, Math.ceil(policies.length / POLICIES_PAGE_SIZE));
  const safePolicyPage = Math.min(page, totalPolicyPages);
  const pagedPolicies = policies.slice(
    (safePolicyPage - 1) * POLICIES_PAGE_SIZE,
    safePolicyPage * POLICIES_PAGE_SIZE
  );

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
            {t('tenant.trustPolicies.title')}
          </h1>
          <p className="text-sm text-slate-500 mt-1">{t('tenant.trustPolicies.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading}
            aria-label={t('tenant.trustPolicies.refresh')}
            title={t('tenant.trustPolicies.refresh')}
            className="inline-flex items-center justify-center gap-2 px-3 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={16} />
          </button>
          <button
            type="button"
            onClick={() => {
              setIsCreateModalOpen(true);
            }}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <Plus size={16} />
            {t('tenant.trustPolicies.actions.createPolicy')}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1 max-w-xs">
            <Search
              placeholder={t('tenant.trustPolicies.filters.workspaceId')}
              aria-label={t('tenant.trustPolicies.filters.workspaceId')}
              value={workspaceFilter}
              onChange={(e) => {
                setWorkspaceFilter(e.target.value);
              }}
              onSearch={handleSearch}
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
              placeholder={t('tenant.trustPolicies.filters.agentInstanceId')}
              aria-label={t('tenant.trustPolicies.filters.agentInstanceId')}
              value={agentFilter}
              onChange={(e) => {
                setAgentFilter(e.target.value);
              }}
              onSearch={handleSearch}
              allowClear
              enterButton={
                <>
                  <span className="sr-only">{t('common.search', 'Search')}</span>
                  <SearchIcon size={16} aria-hidden="true" />
                </>
              }
            />
          </div>
        </div>
        {!appliedFilters.workspace ? (
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.trustPolicies.filters.defaultWorkspaceHint')}
          </p>
        ) : null}
      </div>

      {loadError && (
        <LazyAlert
          type="error"
          showIcon
          title={t('tenant.trustPolicies.loadError')}
          description={loadError}
          action={
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isLoading}
              className="inline-flex items-center justify-center rounded-md border border-red-300 px-3 py-1 text-sm font-medium text-red-700 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/30"
            >
              {t('common.retry')}
            </button>
          }
        />
      )}

      {/* Table */}
      {isLoading ? (
        <SkeletonLoader type="table" rows={8} />
      ) : loadError && policies.length === 0 ? null : policies.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <LazyEmpty description={t('tenant.trustPolicies.empty')} />
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.trustPolicies.columns.actionType')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.trustPolicies.columns.agentInstance')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.trustPolicies.columns.grantType')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.trustPolicies.columns.grantedBy')}
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('tenant.trustPolicies.columns.createdAt')}
                  </th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    {t('common.actions.label')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                {pagedPolicies.map((policy) => (
                  <tr
                    key={policy.id}
                    className="hover:bg-slate-50 dark:hover:bg-slate-900/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-slate-700 dark:text-slate-300 font-medium">
                      {policy.action_type}
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400 font-mono text-xs">
                      {policy.agent_instance_id}
                    </td>
                    <td className="px-4 py-3">
                      {policy.deleted_at ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">
                          {t('tenant.trustPolicies.statusRevoked', 'Revoked')}
                        </span>
                      ) : (
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                            policy.grant_type === 'always'
                              ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300'
                              : 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300'
                          }`}
                        >
                          {getGrantTypeLabel(policy.grant_type)}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      {policy.granted_by}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap text-xs">
                      {formatTimestamp(policy.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex items-center gap-3">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedPolicy(policy);
                          }}
                          className="rounded-sm text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                        >
                          {t('tenant.trustPolicies.actions.viewDetails')}
                        </button>
                        {!policy.deleted_at && (
                          <LazyPopconfirm
                            title={t('tenant.trustPolicies.revokeConfirm', {
                              defaultValue:
                                'Revoke the "{{actionType}}" grant for {{agent}}? The agent will need approval again.',
                              actionType: policy.action_type,
                              agent: policy.agent_instance_id,
                            })}
                            okText={t('tenant.trustPolicies.actions.revoke', 'Revoke')}
                            cancelText={t('common.cancel')}
                            okButtonProps={{ danger: true, loading: revokingId === policy.id }}
                            onConfirm={() => handleRevoke(policy)}
                          >
                            <button
                              type="button"
                              disabled={revokingId === policy.id}
                              className="rounded-sm text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 disabled:opacity-50"
                            >
                              {t('tenant.trustPolicies.actions.revoke', 'Revoke')}
                            </button>
                          </LazyPopconfirm>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {policies.length > POLICIES_PAGE_SIZE ? (
            <div className="flex justify-end border-t border-slate-200 px-4 py-3 dark:border-slate-700">
              <Pagination
                current={safePolicyPage}
                pageSize={POLICIES_PAGE_SIZE}
                total={policies.length}
                showSizeChanger={false}
                onChange={(nextPage) => {
                  setPage(nextPage);
                }}
              />
            </div>
          ) : null}
        </div>
      )}

      {/* Detail Drawer */}
      <LazyDrawer
        title={t('tenant.trustPolicies.details.title')}
        open={selectedPolicy !== null}
        onClose={() => {
          setSelectedPolicy(null);
        }}
        size={500}
      >
        {selectedPolicy && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.trustPolicies.details.policyId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedPolicy.id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.trustPolicies.details.createdAt')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {formatTimestamp(selectedPolicy.created_at)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.trustPolicies.details.actionType')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-medium">
                  {selectedPolicy.action_type}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.trustPolicies.details.grantType')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {getGrantTypeLabel(selectedPolicy.grant_type)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.trustPolicies.details.workspaceId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedPolicy.workspace_id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.trustPolicies.details.agentInstanceId')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedPolicy.agent_instance_id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  {t('tenant.trustPolicies.details.grantedBy')}
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedPolicy.granted_by}
                </p>
              </div>
              {selectedPolicy.deleted_at && (
                <div>
                  <p className="text-xs font-medium text-red-500 dark:text-red-400 uppercase tracking-wide mb-1">
                    {t('tenant.trustPolicies.details.deletedAt')}
                  </p>
                  <p className="text-sm text-red-600 dark:text-red-400">
                    {formatTimestamp(selectedPolicy.deleted_at)}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </LazyDrawer>

      {/* Create Modal */}
      <LazyModal
        title={t('tenant.trustPolicies.create.title')}
        open={isCreateModalOpen}
        onCancel={() => {
          setIsCreateModalOpen(false);
          createForm.resetFields();
        }}
        footer={null}
        destroyOnHidden
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={(values: TrustPolicyCreate) => {
            void handleCreateSubmit(values);
          }}
          className="mt-4"
        >
          <Form.Item
            name="workspace_id"
            label={t('tenant.trustPolicies.create.workspaceId')}
            rules={[
              {
                required: true,
                message: t('tenant.trustPolicies.create.workspaceIdRequired'),
              },
            ]}
          >
            <Input
              placeholder={t('tenant.trustPolicies.create.workspaceIdPlaceholder')}
              spellCheck={false}
              autoComplete="off"
            />
          </Form.Item>

          <Form.Item
            name="agent_instance_id"
            label={t('tenant.trustPolicies.create.agentInstanceId')}
            rules={[
              {
                required: true,
                message: t('tenant.trustPolicies.create.agentInstanceIdRequired'),
              },
            ]}
          >
            <Input
              placeholder={t('tenant.trustPolicies.create.agentInstanceIdPlaceholder')}
              spellCheck={false}
              autoComplete="off"
            />
          </Form.Item>

          <Form.Item
            name="action_type"
            label={t('tenant.trustPolicies.create.actionType')}
            rules={[
              {
                required: true,
                message: t('tenant.trustPolicies.create.actionTypeRequired'),
              },
            ]}
            tooltip={t('tenant.trustPolicies.create.actionTypeTooltip')}
          >
            <Input
              placeholder={t('tenant.trustPolicies.create.actionTypePlaceholder')}
              spellCheck={false}
              autoComplete="off"
            />
          </Form.Item>

          <Form.Item
            name="grant_type"
            label={t('tenant.trustPolicies.create.grantType')}
            rules={[
              {
                required: true,
                message: t('tenant.trustPolicies.create.grantTypeRequired'),
              },
            ]}
            initialValue="once"
          >
            <Select>
              <Option value="once">{t('tenant.trustPolicies.grantTypes.once')}</Option>
              <Option value="always">{t('tenant.trustPolicies.grantTypes.always')}</Option>
            </Select>
          </Form.Item>

          <div className="flex justify-end gap-2 mt-8">
            <Button
              onClick={() => {
                setIsCreateModalOpen(false);
              }}
            >
              {t('common.cancel')}
            </Button>
            <Button type="primary" htmlType="submit" loading={isCreating}>
              {t('tenant.trustPolicies.actions.createPolicy')}
            </Button>
          </div>
        </Form>
      </LazyModal>
    </div>
  );
};
