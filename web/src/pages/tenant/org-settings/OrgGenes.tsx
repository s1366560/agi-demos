import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Dna, Loader2, Pencil, Plus, Trash2 } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { genePolicyService } from '@/services/genePolicyService';
import type { GenePolicyResponse, GenePolicyRequest } from '@/services/genePolicyService';

import { useLazyMessage, LazySpin } from '@/components/ui/lazyAntd';

interface EditingPolicy {
  policy_key: string;
  policy_value: string;
  description: string;
  isNew: boolean;
}

export const OrgGenes: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const currentTenant = useTenantStore((s) => s.currentTenant);

  const [policies, setPolicies] = useState<GenePolicyResponse[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [editing, setEditing] = useState<EditingPolicy | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);

  const fetchPolicies = useCallback(async () => {
    if (!currentTenant) return;
    setIsLoading(true);
    try {
      const data = await genePolicyService.list(currentTenant.id);
      setPolicies(data);
    } catch (_err) {
      message?.error(t('tenant.orgSettings.genes.fetchError', 'Failed to load gene policies'));
    } finally {
      setIsLoading(false);
    }
  }, [currentTenant, message, t]);

  useEffect(() => {
    void fetchPolicies();
  }, [fetchPolicies]);

  const handleAdd = useCallback(() => {
    setEditing({
      policy_key: '',
      policy_value: '{}',
      description: '',
      isNew: true,
    });
  }, []);

  const handleEdit = useCallback((policy: GenePolicyResponse) => {
    setEditing({
      policy_key: policy.policy_key,
      policy_value: JSON.stringify(policy.policy_value, null, 2),
      description: policy.description ?? '',
      isNew: false,
    });
  }, []);

  const handleCancelEdit = useCallback(() => {
    setEditing(null);
  }, []);

  const handleSave = useCallback(async () => {
    if (!currentTenant || !editing) return;

    if (!editing.policy_key.trim()) {
      message?.error(t('tenant.orgSettings.genes.keyRequired', 'Policy key is required'));
      return;
    }

    let parsedValue: Record<string, unknown>;
    try {
      parsedValue = JSON.parse(editing.policy_value) as Record<string, unknown>;
    } catch (_err) {
      message?.error(t('tenant.orgSettings.genes.invalidJson', 'Policy value must be valid JSON'));
      return;
    }

    setIsSubmitting(true);
    try {
      const data: GenePolicyRequest = {
        policy_key: editing.policy_key,
        policy_value: parsedValue,
        description: editing.description || null,
      };
      await genePolicyService.upsert(currentTenant.id, editing.policy_key, data);
      await fetchPolicies();
      setEditing(null);
      message?.success(t('tenant.orgSettings.genes.saveSuccess', 'Gene policy saved successfully'));
    } catch (_err) {
      message?.error(t('tenant.orgSettings.genes.saveError', 'Failed to save gene policy'));
    } finally {
      setIsSubmitting(false);
    }
  }, [currentTenant, editing, fetchPolicies, message, t]);

  const handleDelete = useCallback(
    async (policyKey: string) => {
      if (!currentTenant) return;

      setDeletingKey(policyKey);
      try {
        await genePolicyService.remove(currentTenant.id, policyKey);
        await fetchPolicies();
        message?.success(t('tenant.orgSettings.genes.deleteSuccess', 'Gene policy deleted'));
      } catch (_err) {
        message?.error(t('tenant.orgSettings.genes.deleteError', 'Failed to delete gene policy'));
      } finally {
        setDeletingKey(null);
      }
    },
    [currentTenant, fetchPolicies, message, t]
  );

  if (!currentTenant) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-slate-500">{t('common.noTenant', 'No tenant selected')}</p>
      </div>
    );
  }

  if (isLoading && policies.length === 0) {
    return (
      <div className="flex items-center justify-center py-20">
        <LazySpin size="large" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            {t('tenant.orgSettings.genes.title', 'Gene Policies')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t(
              'tenant.orgSettings.genes.description',
              'Manage organizational gene policies for agent behavior configuration'
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={handleAdd}
          disabled={editing !== null}
          className="inline-flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-dark text-white rounded-lg font-medium transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus size={16} />
          {t('tenant.orgSettings.genes.addPolicy', 'Add Policy')}
        </button>
      </div>

      {/* Edit/Add Form */}
      {editing && (
        <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-6">
          <h3 className="text-md font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
            <Dna size={16} className="text-primary" />
            {editing.isNew
              ? t('tenant.orgSettings.genes.addTitle', 'Add Gene Policy')
              : t('tenant.orgSettings.genes.editTitle', 'Edit Gene Policy')}
          </h3>

          <div className="space-y-4 max-w-4xl">
            <div>
              <label
                htmlFor="gene-key"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('tenant.orgSettings.genes.policyKey', 'Policy Key')} *
              </label>
              <input
                id="gene-key"
                type="text"
                value={editing.policy_key}
                onChange={(e) => {
                  setEditing({ ...editing, policy_key: e.target.value });
                }}
                disabled={!editing.isNew}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none disabled:opacity-60 disabled:cursor-not-allowed"
                placeholder="e.g. agent_behavior, memory_retention"
              />
            </div>

            <div>
              <label
                htmlFor="gene-description"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('tenant.orgSettings.genes.policyDescription', 'Description')}
              </label>
              <input
                id="gene-description"
                type="text"
                value={editing.description}
                onChange={(e) => {
                  setEditing({ ...editing, description: e.target.value });
                }}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none"
                placeholder={t(
                  'tenant.orgSettings.genes.descriptionPlaceholder',
                  'Brief description of this policy'
                )}
              />
            </div>

            <div>
              <label
                htmlFor="gene-value"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('tenant.orgSettings.genes.policyValue', 'Policy Value (JSON)')} *
              </label>
              <textarea
                id="gene-value"
                value={editing.policy_value}
                onChange={(e) => {
                  setEditing({ ...editing, policy_value: e.target.value });
                }}
                rows={6}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none font-mono text-sm"
                placeholder='{ "key": "value" }'
              />
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  void handleSave();
                }}
                disabled={isSubmitting}
                className="bg-primary hover:bg-primary-dark text-white px-6 py-2.5 rounded-lg font-medium transition-colors disabled:opacity-70 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isSubmitting && (
                  <Loader2 size={20} className="animate-spin motion-reduce:animate-none" />
                )}
                {t('common.save', 'Save')}
              </button>
              <button
                type="button"
                onClick={handleCancelEdit}
                className="px-6 py-2.5 rounded-lg font-medium border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
              >
                {t('common.cancel', 'Cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Policy List */}
      {policies.length === 0 && !editing ? (
        <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-12 text-center">
          <Dna size={16} className="text-slate-300 dark:text-slate-600 mb-4 block" />
          <p className="text-slate-500 dark:text-slate-400 mb-2">
            {t('tenant.orgSettings.genes.empty', 'No gene policies configured')}
          </p>
          <p className="text-sm text-slate-400 dark:text-slate-500">
            {t(
              'tenant.orgSettings.genes.emptyHint',
              'Add a policy to configure agent behavior for your organization.'
            )}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {policies.map((policy) => (
            <div
              key={policy.id}
              className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Dna size={16} className="text-primary" />
                    <h4 className="font-medium text-slate-900 dark:text-white truncate">
                      {policy.policy_key}
                    </h4>
                  </div>
                  {policy.description && (
                    <p className="text-sm text-slate-500 dark:text-slate-400 mb-2">
                      {policy.description}
                    </p>
                  )}
                  <pre className="text-xs bg-slate-50 dark:bg-slate-900 rounded-lg p-3 text-slate-700 dark:text-slate-300 overflow-x-auto max-h-32">
                    {JSON.stringify(policy.policy_value, null, 2)}
                  </pre>
                  <p className="text-xs text-slate-400 dark:text-slate-500 mt-2">
                    {t('tenant.orgSettings.genes.updatedAt', 'Updated')}:{' '}
                    {new Date(policy.updated_at ?? policy.created_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => {
                      handleEdit(policy);
                    }}
                    disabled={editing !== null}
                    className="p-2 rounded-lg text-slate-400 hover:text-primary hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title={t('common.edit', 'Edit')}
                  >
                    <Pencil size={20} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleDelete(policy.policy_key);
                    }}
                    disabled={deletingKey === policy.policy_key}
                    className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    title={t('common.delete', 'Delete')}
                  >
                    {deletingKey === policy.policy_key ? (
                      <Loader2 size={20} className="animate-spin motion-reduce:animate-none" />
                    ) : (
                      <Trash2 size={20} />
                    )}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default OrgGenes;
