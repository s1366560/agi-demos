import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { AlertCircle, Loader2, Settings } from 'lucide-react';

import { BackendStoreSelectors } from '@/components/project/BackendStoreSelectors';
import { ProjectConfigForm } from '@/components/tenant/ProjectConfigForm';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';
import { confirmAction } from '../../utils/confirmAction';
import { logger } from '../../utils/logger';

export const NewProject: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { createProject, isLoading, error } = useProjectStore();
  const { currentTenant } = useTenantStore();

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    memory_rules: {
      max_episodes: 1000,
      retention_days: 30,
      auto_refresh: true,
      refresh_interval: 24,
    },
    graph_config: {
      max_nodes: 5000,
      max_edges: 10000,
      similarity_threshold: 0.7,
      community_detection: true,
    },
    graph_store_id: null as string | null,
    retrieval_store_id: null as string | null,
  });

  const isDirty = formData.name.trim() !== '' || formData.description.trim() !== '';

  const handleCancel = async () => {
    if (
      isDirty &&
      !(await confirmAction({
        title: t('tenant.newProject.discardConfirm'),
        danger: true,
      }))
    ) {
      return;
    }
    void navigate(currentTenant ? `/tenant/${currentTenant.id}/projects` : '/tenant');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentTenant) return;

    try {
      await createProject(currentTenant.id, {
        ...formData,
        tenant_id: currentTenant.id,
      });
      void navigate(`/tenant/${currentTenant.id}/projects`);
    } catch (err) {
      logger.error('Failed to create project', err);
    }
  };

  return (
    <div className="max-w-5xl mx-auto flex flex-col gap-8 pb-10 px-6">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
          {t('tenant.newProject.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400">{t('tenant.newProject.subtitle')}</p>
      </div>

      {error && (
        <div
          role="alert"
          className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg flex items-center gap-2"
        >
          <AlertCircle size={16} aria-hidden="true" />
          {error}
        </div>
      )}

      <form
        onSubmit={(e) => {
          void handleSubmit(e);
        }}
        className="flex flex-col gap-8"
      >
        {/* Basic Information */}
        <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 rounded-lg">
              <Settings size={16} />
            </div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">
              {t('tenant.newProject.basicInfo')}
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="col-span-1 md:col-span-2">
              <label
                htmlFor="new-project-name"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('common.forms.name')} <span className="text-red-500">*</span>
              </label>
              <input
                id="new-project-name"
                type="text"
                name="name"
                autoComplete="organization"
                spellCheck={false}
                required
                value={formData.name}
                onChange={(e) => {
                  setFormData({ ...formData, name: e.target.value });
                }}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                placeholder={t('tenant.newProject.namePlaceholder')}
              />
            </div>
            <div className="col-span-1 md:col-span-2">
              <label
                htmlFor="new-project-description"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('common.forms.description')}
              </label>
              <textarea
                id="new-project-description"
                rows={3}
                value={formData.description}
                onChange={(e) => {
                  setFormData({ ...formData, description: e.target.value });
                }}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform] resize-none"
                placeholder={t('tenant.newProject.descriptionPlaceholder')}
              />
            </div>
          </div>
        </div>

        <BackendStoreSelectors
          tenantId={currentTenant?.id}
          graphStoreId={formData.graph_store_id}
          retrievalStoreId={formData.retrieval_store_id}
          disabled={isLoading}
          onChange={(patch) => {
            setFormData({
              ...formData,
              graph_store_id: patch.graph_store_id ?? formData.graph_store_id,
              retrieval_store_id: patch.retrieval_store_id ?? formData.retrieval_store_id,
            });
          }}
        />

        <ProjectConfigForm
          idPrefix="new-project"
          memoryRules={formData.memory_rules}
          graphConfig={formData.graph_config}
          onMemoryRulesChange={(memory_rules) => {
            setFormData({ ...formData, memory_rules });
          }}
          onGraphConfigChange={(graph_config) => {
            setFormData({ ...formData, graph_config });
          }}
        />

        {/* Footer Actions */}
        <div className="flex items-center justify-end gap-4 pt-6 border-t border-slate-200 dark:border-slate-800">
          <button
            type="button"
            onClick={() => {
              void handleCancel();
            }}
            className="px-6 py-2.5 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            disabled={isLoading || !formData.name.trim()}
            className="px-6 py-2.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors shadow-lg shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading && <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />}
            {t('tenant.newProject.submit')}
          </button>
        </div>
      </form>
    </div>
  );
};
