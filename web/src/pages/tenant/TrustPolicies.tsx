import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Button, Form, Select } from 'antd';
import { Plus, RefreshCw } from 'lucide-react';

import {
  useLazyMessage,
  LazyEmpty,
  LazySpin,
  LazyDrawer,
  LazyModal,
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

export const TrustPolicies: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const tenantId = useTenantStore((s) => s.currentTenant?.id ?? null);

  const policies = useTrustPolicies();
  const isLoading = useTrustLoading();
  const error = useTrustError();
  const { fetchPolicies, createPolicy, clearError } = useTrustActions();

  const [workspaceFilter, setWorkspaceFilter] = useState('');
  const [agentFilter, setAgentFilter] = useState('');

  const [selectedPolicy, setSelectedPolicy] = useState<TrustPolicy | null>(null);

  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createForm] = Form.useForm<TrustPolicyCreate>();
  const [isCreating, setIsCreating] = useState(false);

  const buildParams = useCallback(() => {
    const params: { workspace_id: string; agent_instance_id?: string } = {
      workspace_id: workspaceFilter || 'default', // Requires a workspace_id usually, fallback to 'default' if empty for now
    };
    if (agentFilter) params.agent_instance_id = agentFilter;
    return params;
  }, [workspaceFilter, agentFilter]);

  useEffect(() => {
    if (!tenantId) return;
    fetchPolicies(tenantId, buildParams()).catch(() => {
      // handled by store
    });
  }, [tenantId, fetchPolicies, buildParams]);

  useEffect(() => {
    if (error) {
      message?.error(error);
      clearError();
    }
  }, [error, message, clearError]);

  const handleRefresh = useCallback(() => {
    if (!tenantId) return;
    fetchPolicies(tenantId, buildParams()).catch(() => {
      // handled by store
    });
  }, [tenantId, fetchPolicies, buildParams]);

  const handleCreateSubmit = async (values: TrustPolicyCreate) => {
    if (!tenantId) return;
    setIsCreating(true);
    try {
      await createPolicy(tenantId, values);
      message?.success('Trust policy created successfully');
      setIsCreateModalOpen(false);
      createForm.resetFields();
    } catch {
      // handled by store
    } finally {
      setIsCreating(false);
    }
  };

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
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Trust Policies</h1>
          <p className="text-sm text-slate-500 mt-1">
            Manage automated execution permissions for agents in your workspaces.
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
            onClick={() => {
              setIsCreateModalOpen(true);
            }}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <Plus size={16} />
            Create Policy
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1 max-w-xs">
            <Search
              placeholder="Filter by Workspace ID"
              value={workspaceFilter}
              onChange={(e) => {
                setWorkspaceFilter(e.target.value);
              }}
              allowClear
            />
          </div>
          <div className="flex-1 max-w-xs">
            <Search
              placeholder="Filter by Agent Instance ID"
              value={agentFilter}
              onChange={(e) => {
                setAgentFilter(e.target.value);
              }}
              allowClear
            />
          </div>
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <LazySpin size="large" />
        </div>
      ) : policies.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <LazyEmpty description="No trust policies found" />
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    Action Type
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    Agent Instance
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    Grant Type
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    Granted By
                  </th>
                  <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    Created At
                  </th>
                  <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-700">
                {policies.map((policy) => (
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
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          policy.grant_type === 'always'
                            ? 'bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300'
                            : 'bg-blue-100 dark:bg-blue-900/30 text-blue-800 dark:text-blue-300'
                        }`}
                      >
                        {policy.grant_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                      {policy.granted_by}
                    </td>
                    <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap text-xs">
                      {formatTimestamp(policy.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedPolicy(policy);
                        }}
                        className="text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 text-sm font-medium"
                      >
                        View Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Detail Drawer */}
      <LazyDrawer
        title="Trust Policy Details"
        open={selectedPolicy !== null}
        onClose={() => {
          setSelectedPolicy(null);
        }}
        width={500}
      >
        {selectedPolicy && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  Policy ID
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedPolicy.id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  Created At
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {formatTimestamp(selectedPolicy.created_at)}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  Action Type
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-medium">
                  {selectedPolicy.action_type}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  Grant Type
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedPolicy.grant_type}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  Workspace ID
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedPolicy.workspace_id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  Agent Instance ID
                </p>
                <p className="text-sm text-slate-900 dark:text-white font-mono break-all">
                  {selectedPolicy.agent_instance_id}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                  Granted By
                </p>
                <p className="text-sm text-slate-900 dark:text-white">
                  {selectedPolicy.granted_by}
                </p>
              </div>
              {selectedPolicy.deleted_at && (
                <div>
                  <p className="text-xs font-medium text-red-500 dark:text-red-400 uppercase tracking-wide mb-1">
                    Deleted At
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
        title="Create Trust Policy"
        open={isCreateModalOpen}
        onCancel={() => {
          setIsCreateModalOpen(false);
          createForm.resetFields();
        }}
        footer={null}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreateSubmit} className="mt-4">
          <Form.Item
            name="workspace_id"
            label="Workspace ID"
            rules={[{ required: true, message: 'Please enter a workspace ID' }]}
          >
            <Input placeholder="Enter workspace ID" />
          </Form.Item>

          <Form.Item
            name="agent_instance_id"
            label="Agent Instance ID"
            rules={[{ required: true, message: 'Please enter an agent instance ID' }]}
          >
            <Input placeholder="Enter agent instance ID" />
          </Form.Item>

          <Form.Item
            name="action_type"
            label="Action Type"
            rules={[{ required: true, message: 'Please enter the action type' }]}
            tooltip="E.g., shell_execution, file_write, or * for all"
          >
            <Input placeholder="Enter action type" />
          </Form.Item>

          <Form.Item
            name="grant_type"
            label="Grant Type"
            rules={[{ required: true, message: 'Please select a grant type' }]}
            initialValue="once"
          >
            <Select>
              <Option value="once">Allow Once</Option>
              <Option value="always">Allow Always</Option>
            </Select>
          </Form.Item>

          <div className="flex justify-end gap-2 mt-8">
            <Button
              onClick={() => {
                setIsCreateModalOpen(false);
              }}
            >
              Cancel
            </Button>
            <Button type="primary" htmlType="submit" loading={isCreating}>
              Create Policy
            </Button>
          </div>
        </Form>
      </LazyModal>
    </div>
  );
};
