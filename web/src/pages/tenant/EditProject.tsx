import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { AlertCircle, Loader2, Settings } from 'lucide-react';

import { useUnsavedChangesWarning } from '@/hooks/useUnsavedChangesWarning';

import { BackendStoreSelectors } from '@/components/project/BackendStoreSelectors';
import { ProjectConfigForm } from '@/components/tenant/ProjectConfigForm';
import { LazySkeleton } from '@/components/ui/lazyAntd';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';
import { confirmAction } from '../../utils/confirmAction';
import { logger } from '../../utils/logger';

import type { GraphConfig, MemoryRulesConfig, Project, ProjectUpdate } from '../../types/memory';

interface ProjectEditFormData {
  name: string;
  description: string;
  memory_rules: MemoryRulesConfig;
  graph_config: GraphConfig;
  graph_store_id: string | null;
  retrieval_store_id: string | null;
}

const defaultMemoryRules: MemoryRulesConfig = {
  max_episodes: 1000,
  retention_days: 30,
  auto_refresh: true,
  refresh_interval: 24,
};

const defaultGraphConfig: GraphConfig = {
  max_nodes: 5000,
  max_edges: 10000,
  similarity_threshold: 0.7,
  community_detection: true,
};

const defaultFormData: ProjectEditFormData = {
  name: '',
  description: '',
  memory_rules: defaultMemoryRules,
  graph_config: defaultGraphConfig,
  graph_store_id: null,
  retrieval_store_id: null,
};

const toProjectFormData = (project: Partial<Project>): ProjectEditFormData => ({
  name: project.name ?? '',
  description: project.description ?? '',
  memory_rules: {
    max_episodes: project.memory_rules?.max_episodes ?? defaultMemoryRules.max_episodes,
    retention_days: project.memory_rules?.retention_days ?? defaultMemoryRules.retention_days,
    auto_refresh: project.memory_rules?.auto_refresh ?? defaultMemoryRules.auto_refresh,
    refresh_interval: project.memory_rules?.refresh_interval ?? defaultMemoryRules.refresh_interval,
  },
  graph_config: {
    max_nodes: project.graph_config?.max_nodes ?? defaultGraphConfig.max_nodes,
    max_edges: project.graph_config?.max_edges ?? defaultGraphConfig.max_edges,
    similarity_threshold:
      project.graph_config?.similarity_threshold ?? defaultGraphConfig.similarity_threshold,
    community_detection:
      project.graph_config?.community_detection ?? defaultGraphConfig.community_detection,
  },
  graph_store_id: project.graph_store_id ?? null,
  retrieval_store_id: project.retrieval_store_id ?? null,
});

export const EditProject: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId, projectId } = useParams();
  const { updateProject, getProject, isLoading, error } = useProjectStore();
  const { currentTenant } = useTenantStore();
  const [isFetching, setIsFetching] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const [formData, setFormData] = useState<ProjectEditFormData>(defaultFormData);
  const [initialData, setInitialData] = useState<ProjectEditFormData | null>(null);

  const fetchProject = useCallback(async () => {
    if (!tenantId || !projectId) {
      setIsFetching(false);
      setLoadError(true);
      return;
    }

    setIsFetching(true);
    setLoadError(false);
    try {
      const project = await getProject(tenantId, projectId);
      const next = toProjectFormData(project);
      setFormData(next);
      setInitialData(next);
    } catch (err) {
      logger.error('Failed to fetch project', err);
      setLoadError(true);
      setInitialData(null);
    } finally {
      setIsFetching(false);
    }
  }, [tenantId, projectId, getProject]);

  useEffect(() => {
    void fetchProject();
  }, [fetchProject]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tenantId || !projectId || !initialData) return;

    try {
      const projectData: ProjectUpdate = {
        name: formData.name,
        description: formData.description,
        memory_rules: formData.memory_rules,
        graph_config: formData.graph_config,
        graph_store_id: formData.graph_store_id,
        retrieval_store_id: formData.retrieval_store_id,
      };
      await updateProject(tenantId, projectId, projectData);
      void navigate(`/tenant/${tenantId}/projects`);
    } catch (err) {
      logger.error('Failed to update project', err);
    }
  };

  const projectListPath = `/tenant/${tenantId ?? currentTenant?.id ?? ''}/projects`;

  const isDirty = initialData !== null && JSON.stringify(formData) !== JSON.stringify(initialData);
  useUnsavedChangesWarning(isDirty);

  const handleCancel = () => {
    if (!isDirty) {
      void navigate(projectListPath);
      return;
    }
    void confirmAction({
      title: t('project.edit.discardConfirmTitle'),
      content: t('project.edit.discardConfirmContent'),
      okText: t('project.edit.discardConfirmOk'),
      cancelText: t('project.edit.actions.cancel'),
      danger: true,
    }).then((confirmed) => {
      if (confirmed) {
        void navigate(projectListPath);
      }
    });
  };

  if (isFetching) {
    return (
      <div className="max-w-full mx-auto w-full" aria-busy="true">
        <LazySkeleton active paragraph={{ rows: 10 }} />
      </div>
    );
  }

  // Never render an editable form with default values when the project could
  // not be loaded: saving it would overwrite the live configuration.
  if (loadError || initialData === null) {
    return (
      <div className="max-w-full mx-auto flex flex-col gap-6">
        <div
          role="alert"
          className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg flex items-center gap-2"
        >
          <AlertCircle size={16} aria-hidden="true" />
          {t('project.edit.load_error', {
            defaultValue:
              'Failed to load the project configuration. Retry to edit it safely; nothing was changed.',
          })}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              void fetchProject();
            }}
            className="px-4 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            {t('common.retry')}
          </button>
          <button
            type="button"
            onClick={() => {
              void navigate(projectListPath);
            }}
            className="px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
          >
            {t('project.edit.actions.cancel')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-full mx-auto flex flex-col gap-8 pb-10">
      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
          {t('project.edit.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400">{t('project.edit.subtitle')}</p>
      </div>

      {error && (
        <div
          role="alert"
          className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg flex items-center gap-2"
        >
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      <form
        onSubmit={(event) => {
          void handleSubmit(event);
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
              {t('project.edit.basic_info')}
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="col-span-1">
              <label
                htmlFor="project-name"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('project.edit.name')} <span className="text-red-500">*</span>
              </label>
              <input
                id="project-name"
                name="name"
                type="text"
                required
                autoComplete="off"
                spellCheck={false}
                value={formData.name}
                onChange={(e) => {
                  setFormData({ ...formData, name: e.target.value });
                }}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                placeholder={t('project.edit.namePlaceholder')}
              />
            </div>
            <div className="col-span-1 md:col-span-2">
              <label
                htmlFor="project-description"
                className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
              >
                {t('project.edit.description')}
              </label>
              <textarea
                id="project-description"
                name="description"
                rows={3}
                value={formData.description}
                onChange={(e) => {
                  setFormData({ ...formData, description: e.target.value });
                }}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform] resize-none"
                placeholder={t('project.edit.descriptionPlaceholder')}
              />
            </div>
          </div>
        </div>

        <BackendStoreSelectors
          tenantId={tenantId ?? currentTenant?.id}
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
          idPrefix="edit-project"
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
            onClick={handleCancel}
            className="px-6 py-2.5 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
          >
            {t('project.edit.actions.cancel')}
          </button>
          <button
            type="submit"
            disabled={isLoading || !formData.name.trim()}
            className="px-6 py-2.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors shadow-lg shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading && <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />}
            {t('project.edit.actions.update')}
          </button>
        </div>
      </form>
    </div>
  );
};
