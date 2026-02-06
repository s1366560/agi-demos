import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

export const NewProject: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { createProject, isLoading, error } = useProjectStore();
  const { currentTenant } = useTenantStore();

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    status: 'active' as const,
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
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentTenant) return;

    try {
      // Remove status as it's not part of the API payload
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { status, ...projectData } = formData;
      await createProject(currentTenant.id, {
        ...projectData,
        tenant_id: currentTenant.id,
      });
      navigate(`/tenant/${currentTenant.id}/projects`);
    } catch (err) {
      console.error('Failed to create project:', err);
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
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg flex items-center gap-2">
          <span className="material-symbols-outlined text-lg">error</span>
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex flex-col gap-8">
        {/* Basic Information */}
        <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 rounded-lg">
              <span className="material-symbols-outlined">settings</span>
            </div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">
              {t('tenant.newProject.basicInfo')}
            </h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="col-span-1">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                {t('common.forms.name')} <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                required
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
                placeholder="e.g. Finance Knowledge Base"
              />
            </div>
            <div className="col-span-1">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                {t('common.forms.status')}
              </label>
              <select
                value={formData.status}
                onChange={(e) => setFormData({ ...formData, status: e.target.value as any })}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
              >
                <option value="active">{t('common.status.active')}</option>
                <option value="paused">{t('common.status.paused')}</option>
                <option value="archived">{t('common.status.archived')}</option>
              </select>
            </div>
            <div className="col-span-1 md:col-span-2">
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                {t('common.forms.description')}
              </label>
              <textarea
                rows={3}
                value={formData.description}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all resize-none"
                placeholder="Briefly describe the purpose of this project..."
              />
            </div>
          </div>
        </div>

        {/* Configuration Split */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Memory Rules */}
          <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm h-full">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 rounded-lg">
                <span className="material-symbols-outlined">psychology</span>
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                {t('tenant.newProject.memoryRules')}
              </h2>
            </div>

            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    {t('tenant.newProject.maxEpisodes')}
                  </label>
                  <input
                    type="number"
                    min="100"
                    max="10000"
                    value={formData.memory_rules.max_episodes}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        memory_rules: {
                          ...formData.memory_rules,
                          max_episodes: parseInt(e.target.value) || 1000,
                        },
                      })
                    }
                    className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    {t('tenant.newProject.retentionDays')}
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="365"
                    value={formData.memory_rules.retention_days}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        memory_rules: {
                          ...formData.memory_rules,
                          retention_days: parseInt(e.target.value) || 30,
                        },
                      })
                    }
                    className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                  {t('tenant.newProject.refreshInterval')}
                </label>
                <input
                  type="number"
                  min="1"
                  max="168"
                  value={formData.memory_rules.refresh_interval}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      memory_rules: {
                        ...formData.memory_rules,
                        refresh_interval: parseInt(e.target.value) || 24,
                      },
                    })
                  }
                  className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none"
                />
              </div>

              <div className="flex items-center gap-3 pt-2">
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formData.memory_rules.auto_refresh}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        memory_rules: { ...formData.memory_rules, auto_refresh: e.target.checked },
                      })
                    }
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-primary/20 dark:peer-focus:ring-primary/40 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-primary"></div>
                </label>
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  {t('tenant.newProject.enableAutoRefresh')}
                </span>
              </div>
            </div>
          </div>

          {/* Graph Configuration */}
          <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm h-full">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 rounded-lg">
                <span className="material-symbols-outlined">hub</span>
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                {t('tenant.newProject.graphConfig')}
              </h2>
            </div>

            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    {t('tenant.newProject.maxNodes')}
                  </label>
                  <input
                    type="number"
                    min="100"
                    value={formData.graph_config.max_nodes}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        graph_config: {
                          ...formData.graph_config,
                          max_nodes: parseInt(e.target.value) || 5000,
                        },
                      })
                    }
                    className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
                    {t('tenant.newProject.maxEdges')}
                  </label>
                  <input
                    type="number"
                    min="100"
                    value={formData.graph_config.max_edges}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        graph_config: {
                          ...formData.graph_config,
                          max_edges: parseInt(e.target.value) || 10000,
                        },
                      })
                    }
                    className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none"
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between items-center mb-2">
                  <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
                    {t('tenant.newProject.similarityThreshold')}
                  </label>
                  <span className="text-xs font-mono bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-600 dark:text-slate-300">
                    {formData.graph_config.similarity_threshold}
                  </span>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="1.0"
                  step="0.1"
                  value={formData.graph_config.similarity_threshold}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      graph_config: {
                        ...formData.graph_config,
                        similarity_threshold: parseFloat(e.target.value),
                      },
                    })
                  }
                  className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-primary"
                />
                <div className="flex justify-between text-xs text-slate-400 mt-1">
                  <span>Loose (0.1)</span>
                  <span>Strict (1.0)</span>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formData.graph_config.community_detection}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        graph_config: {
                          ...formData.graph_config,
                          community_detection: e.target.checked,
                        },
                      })
                    }
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-primary/20 dark:peer-focus:ring-primary/40 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-primary"></div>
                </label>
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  {t('tenant.newProject.enableCommunityDetection')}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-end gap-4 pt-6 border-t border-slate-200 dark:border-slate-800">
          <Link to={`/tenant/${currentTenant?.id}/projects`}>
            <button
              type="button"
              className="px-6 py-2.5 rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 font-medium hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              {t('common.cancel')}
            </button>
          </Link>
          <button
            type="submit"
            disabled={isLoading || !formData.name.trim()}
            className="px-6 py-2.5 rounded-lg bg-primary text-white font-medium hover:bg-primary/90 transition-colors shadow-lg shadow-primary/20 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isLoading && (
              <span className="material-symbols-outlined animate-spin text-sm">
                progress_activity
              </span>
            )}
            {t('tenant.newProject.submit')}
          </button>
        </div>
      </form>
    </div>
  );
};
