import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';

import { AlertCircle, Brain, Loader2, Network, Settings } from 'lucide-react';

import { BackendStoreSelectors } from '@/components/project/BackendStoreSelectors';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';
import { confirmAction } from '../../utils/confirmAction';

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

const numberInputClass =
  'w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none';

/**
 * Number input that keeps a local string while editing so clearing the field
 * does not snap back to the default; commits parsed values and restores the
 * last valid value on blur.
 */
const NumberInput: React.FC<{
  id: string;
  name: string;
  min?: number | undefined;
  max?: number | undefined;
  value: number;
  onCommit: (value: number) => void;
}> = ({ id, name, min, max, value, onCommit }) => {
  const [raw, setRaw] = useState(String(value));

  useEffect(() => {
    setRaw(String(value));
  }, [value]);

  return (
    <input
      id={id}
      name={name}
      type="number"
      min={min}
      max={max}
      value={raw}
      onChange={(e) => {
        setRaw(e.target.value);
        const parsed = parseInt(e.target.value, 10);
        if (!Number.isNaN(parsed)) {
          onCommit(parsed);
        }
      }}
      onBlur={() => {
        setRaw(String(value));
      }}
      className={numberInputClass}
    />
  );
};

export const EditProject: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId, projectId } = useParams();
  const { updateProject, getProject, isLoading, error } = useProjectStore();
  const { currentTenant } = useTenantStore();
  const [isFetching, setIsFetching] = useState(true);

  const [formData, setFormData] = useState<ProjectEditFormData>(defaultFormData);
  const [initialData, setInitialData] = useState<ProjectEditFormData | null>(null);

  useEffect(() => {
    const fetchProject = async () => {
      if (!tenantId || !projectId) {
        setIsFetching(false);
        return;
      }

      try {
        const project = await getProject(tenantId, projectId);
        const next = toProjectFormData(project);
        setFormData(next);
        setInitialData(next);
      } catch (err) {
        console.error('Failed to fetch project:', err);
      } finally {
        setIsFetching(false);
      }
    };
    void fetchProject();
  }, [tenantId, projectId, getProject]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tenantId || !projectId) return;

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
      console.error('Failed to update project:', err);
    }
  };

  const projectListPath = `/tenant/${tenantId ?? currentTenant?.id ?? ''}/projects`;

  const isDirty = initialData !== null && JSON.stringify(formData) !== JSON.stringify(initialData);

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
    return <div className="p-8 text-center text-slate-500">{t('tenant.projects.loading')}</div>;
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

        {/* Configuration Split */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Memory Rules */}
          <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm h-full">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 rounded-lg">
                <Brain size={16} />
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                {t('project.edit.memory_rules.title')}
              </h2>
            </div>

            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="memory-max-episodes"
                    className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
                  >
                    {t('project.edit.memory_rules.max_episodes')}
                  </label>
                  <NumberInput
                    id="memory-max-episodes"
                    name="max_episodes"
                    min={100}
                    max={10000}
                    value={formData.memory_rules.max_episodes}
                    onCommit={(value) => {
                      setFormData({
                        ...formData,
                        memory_rules: { ...formData.memory_rules, max_episodes: value },
                      });
                    }}
                  />
                </div>
                <div>
                  <label
                    htmlFor="memory-retention-days"
                    className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
                  >
                    {t('project.edit.memory_rules.retention')}
                  </label>
                  <NumberInput
                    id="memory-retention-days"
                    name="retention_days"
                    min={1}
                    max={365}
                    value={formData.memory_rules.retention_days}
                    onCommit={(value) => {
                      setFormData({
                        ...formData,
                        memory_rules: { ...formData.memory_rules, retention_days: value },
                      });
                    }}
                  />
                </div>
              </div>

              <div>
                <label
                  htmlFor="memory-refresh-interval"
                  className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
                >
                  {t('project.edit.memory_rules.refresh_interval')}
                </label>
                <NumberInput
                  id="memory-refresh-interval"
                  name="refresh_interval"
                  min={1}
                  max={168}
                  value={formData.memory_rules.refresh_interval}
                  onCommit={(value) => {
                    setFormData({
                      ...formData,
                      memory_rules: { ...formData.memory_rules, refresh_interval: value },
                    });
                  }}
                />
              </div>

              <div className="flex items-center gap-3 pt-2">
                <label
                  htmlFor="memory-auto-refresh"
                  className="relative inline-flex items-center cursor-pointer"
                >
                  <input
                    id="memory-auto-refresh"
                    name="auto_refresh"
                    type="checkbox"
                    checked={formData.memory_rules.auto_refresh}
                    onChange={(e) => {
                      setFormData({
                        ...formData,
                        memory_rules: { ...formData.memory_rules, auto_refresh: e.target.checked },
                      });
                    }}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-primary/20 dark:peer-focus:ring-primary/40 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-transform dark:border-gray-600 peer-checked:bg-primary"></div>
                  <span className="ml-3 text-sm font-medium text-slate-700 dark:text-slate-300">
                    {t('project.edit.memory_rules.auto_refresh')}
                  </span>
                </label>
              </div>
            </div>
          </div>

          {/* Graph Configuration */}
          <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm h-full">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 rounded-lg">
                <Network size={16} />
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                {t('project.edit.graph_config.title')}
              </h2>
            </div>

            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label
                    htmlFor="graph-max-nodes"
                    className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
                  >
                    {t('project.edit.graph_config.max_nodes')}
                  </label>
                  <NumberInput
                    id="graph-max-nodes"
                    name="max_nodes"
                    min={100}
                    value={formData.graph_config.max_nodes}
                    onCommit={(value) => {
                      setFormData({
                        ...formData,
                        graph_config: { ...formData.graph_config, max_nodes: value },
                      });
                    }}
                  />
                </div>
                <div>
                  <label
                    htmlFor="graph-max-edges"
                    className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
                  >
                    {t('project.edit.graph_config.max_edges')}
                  </label>
                  <NumberInput
                    id="graph-max-edges"
                    name="max_edges"
                    min={100}
                    value={formData.graph_config.max_edges}
                    onCommit={(value) => {
                      setFormData({
                        ...formData,
                        graph_config: { ...formData.graph_config, max_edges: value },
                      });
                    }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center mb-2">
                  <label
                    htmlFor="graph-similarity"
                    className="block text-sm font-medium text-slate-700 dark:text-slate-300"
                  >
                    {t('project.edit.graph_config.similarity')}
                  </label>
                  <span className="text-xs font-mono bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-600 dark:text-slate-300">
                    {formData.graph_config.similarity_threshold}
                  </span>
                </div>
                <input
                  id="graph-similarity"
                  name="similarity_threshold"
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.1"
                  value={formData.graph_config.similarity_threshold}
                  onChange={(e) => {
                    setFormData({
                      ...formData,
                      graph_config: {
                        ...formData.graph_config,
                        similarity_threshold: parseFloat(e.target.value),
                      },
                    });
                  }}
                  className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-primary"
                />
                <div className="flex justify-between text-xs text-slate-400 mt-1">
                  <span>{t('project.edit.graph_config.loose')}</span>
                  <span>{t('project.edit.graph_config.strict')}</span>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <label
                  htmlFor="graph-community-detection"
                  className="relative inline-flex items-center cursor-pointer"
                >
                  <input
                    id="graph-community-detection"
                    name="community_detection"
                    type="checkbox"
                    checked={formData.graph_config.community_detection}
                    onChange={(e) => {
                      setFormData({
                        ...formData,
                        graph_config: {
                          ...formData.graph_config,
                          community_detection: e.target.checked,
                        },
                      });
                    }}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-primary/20 dark:peer-focus:ring-primary/40 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-transform dark:border-gray-600 peer-checked:bg-primary"></div>
                  <span className="ml-3 text-sm font-medium text-slate-700 dark:text-slate-300">
                    {t('project.edit.graph_config.community_detection')}
                  </span>
                </label>
              </div>
            </div>
          </div>
        </div>

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
