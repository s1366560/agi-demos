import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { message } from 'antd';
import { X, Folder, AlertCircle, Settings, Brain, Users, Cloud, Monitor } from 'lucide-react';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

interface ProjectCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (() => void) | undefined;
}

type ProjectStatus = 'active' | 'paused' | 'archived';
type ActiveTab = 'basic' | 'memory' | 'graph' | 'sandbox';
type SandboxType = 'cloud' | 'local';

interface ProjectFormData {
  name: string;
  description: string;
  status: ProjectStatus;
  memory_rules: {
    max_episodes: number;
    retention_days: number;
    auto_refresh: boolean;
    refresh_interval: number;
  };
  graph_config: {
    max_nodes: number;
    max_edges: number;
    similarity_threshold: number;
    community_detection: boolean;
  };
  sandbox_config: {
    sandbox_type: SandboxType;
    local_config: {
      workspace_path: string;
      tunnel_url: string;
      host: string;
      port: number;
    };
  };
}

export const ProjectCreateModal: React.FC<ProjectCreateModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const { t } = useTranslation();
  const { createProject, isLoading, error } = useProjectStore();
  const { currentTenant } = useTenantStore();

  const [formData, setFormData] = useState<ProjectFormData>({
    name: '',
    description: '',
    status: 'active',
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
    sandbox_config: {
      sandbox_type: 'cloud',
      local_config: {
        workspace_path: '/workspace',
        tunnel_url: '',
        host: 'localhost',
        port: 8765,
      },
    },
  });

  const [activeTab, setActiveTab] = useState<ActiveTab>('basic');

  const resetFormData = () => {
    setFormData({
      name: '',
      description: '',
      status: 'active',
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
      sandbox_config: {
        sandbox_type: 'cloud',
        local_config: {
          workspace_path: '/workspace',
          tunnel_url: '',
          host: 'localhost',
          port: 8765,
        },
      },
    });
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>): Promise<void> => {
    e.preventDefault();
    if (!currentTenant) return;

    try {
      // Only include local_config if sandbox_type is local
      const submitData = {
        ...formData,
        tenant_id: currentTenant.id,
        sandbox_config: {
          sandbox_type: formData.sandbox_config.sandbox_type,
          ...(formData.sandbox_config.sandbox_type === 'local' && {
            local_config: formData.sandbox_config.local_config,
          }),
        },
      };
      await createProject(currentTenant.id, submitData);
      onSuccess?.();
      onClose();
      resetFormData();
    } catch (_error) {
      void message.error(_error instanceof Error ? _error.message : 'Failed to create project');
      console.error('ProjectCreateModal: create failed', _error);
    }
  };

  const handleClose = () => {
    onClose();
    resetFormData();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-4xl mx-4 max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Folder className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {t('project.create.title')}
            </h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            aria-label={t('project.create.closeAria')}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-b border-gray-200 dark:border-slate-800">
          <nav className="flex space-x-8 px-6">
            <button
              onClick={() => {
                setActiveTab('basic');
              }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
                activeTab === 'basic'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Settings className="h-4 w-4" />
                <span>{t('project.create.tabBasic')}</span>
              </div>
            </button>
            <button
              onClick={() => {
                setActiveTab('memory');
              }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
                activeTab === 'memory'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Brain className="h-4 w-4" />
                <span>{t('project.create.tabMemory')}</span>
              </div>
            </button>
            <button
              onClick={() => {
                setActiveTab('graph');
              }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
                activeTab === 'graph'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Users className="h-4 w-4" />
                <span>{t('project.create.tabGraph')}</span>
              </div>
            </button>
            <button
              onClick={() => {
                setActiveTab('sandbox');
              }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 ${
                activeTab === 'sandbox'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Monitor className="h-4 w-4" />
                <span>{t('project.create.tabSandbox')}</span>
              </div>
            </button>
          </nav>
        </div>

        <form
          onSubmit={(event) => {
            void handleSubmit(event);
          }}
          className="flex-1 overflow-y-auto"
          id="project-form"
        >
          <div className="p-6 space-y-4">
            {error && (
              <div
                className="flex items-center space-x-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 rounded-md"
                role="alert"
                aria-live="assertive"
              >
                <AlertCircle
                  className="h-4 w-4 text-red-600 dark:text-red-400"
                  aria-hidden="true"
                />
                <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
              </div>
            )}

            {activeTab === 'basic' && (
              <>
                <div>
                  <label
                    htmlFor="project-create-name"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('project.create.nameLabel')}
                  </label>
                  <input
                    type="text"
                    id="project-create-name"
                    value={formData.name}
                    onChange={(e) => {
                      setFormData({ ...formData, name: e.target.value });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder={t('project.create.namePlaceholder')}
                    required
                    disabled={isLoading}
                    aria-required="true"
                  />
                </div>

                <div>
                  <label
                    htmlFor="project-create-description"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('project.create.descriptionLabel')}
                  </label>
                  <textarea
                    id="project-create-description"
                    value={formData.description}
                    onChange={(e) => {
                      setFormData({ ...formData, description: e.target.value });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder={t('project.create.descriptionPlaceholder')}
                    rows={3}
                    disabled={isLoading}
                    aria-describedby="project-create-description-help"
                  />
                  <span
                    id="project-create-description-help"
                    className="text-xs text-gray-500 dark:text-slate-400"
                  >
                    {t('project.create.descriptionHelp')}
                  </span>
                </div>

                <div>
                  <label
                    htmlFor="project-create-status"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('project.create.statusLabel')}
                  </label>
                  <select
                    id="project-create-status"
                    value={formData.status}
                    onChange={(e) => {
                      setFormData({ ...formData, status: e.target.value as ProjectStatus });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                    disabled={isLoading}
                  >
                    <option value="active">{t('project.create.statusActive')}</option>
                    <option value="paused">{t('project.create.statusPaused')}</option>
                    <option value="archived">{t('project.create.statusArchived')}</option>
                  </select>
                </div>
              </>
            )}

            {activeTab === 'memory' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="project-create-max-episodes"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      {t('project.create.maxEpisodesLabel')}
                    </label>
                    <input
                      type="number"
                      id="project-create-max-episodes"
                      value={formData.memory_rules.max_episodes}
                      onChange={(e) => {
                        setFormData({
                          ...formData,
                          memory_rules: {
                            ...formData.memory_rules,
                            max_episodes: parseInt(e.target.value) || 1000,
                          },
                        });
                      }}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="100"
                      max="10000"
                      disabled={isLoading}
                      aria-describedby="project-create-max-episodes-help"
                    />
                    <span
                      id="project-create-max-episodes-help"
                      className="text-xs text-gray-500 dark:text-slate-400"
                    >
                      {t('project.create.rangeEpisodes')}
                    </span>
                  </div>

                  <div>
                    <label
                      htmlFor="project-create-retention-days"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      {t('project.create.retentionDaysLabel')}
                    </label>
                    <input
                      type="number"
                      id="project-create-retention-days"
                      value={formData.memory_rules.retention_days}
                      onChange={(e) => {
                        setFormData({
                          ...formData,
                          memory_rules: {
                            ...formData.memory_rules,
                            retention_days: parseInt(e.target.value) || 30,
                          },
                        });
                      }}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="1"
                      max="365"
                      disabled={isLoading}
                      aria-describedby="project-create-retention-days-help"
                    />
                    <span
                      id="project-create-retention-days-help"
                      className="text-xs text-gray-500 dark:text-slate-400"
                    >
                      {t('project.create.rangeRetentionDays')}
                    </span>
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="project-create-refresh-interval"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('project.create.refreshIntervalLabel')}
                  </label>
                  <input
                    type="number"
                    id="project-create-refresh-interval"
                    value={formData.memory_rules.refresh_interval}
                    onChange={(e) => {
                      setFormData({
                        ...formData,
                        memory_rules: {
                          ...formData.memory_rules,
                          refresh_interval: parseInt(e.target.value) || 24,
                        },
                      });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    min="1"
                    max="168"
                    disabled={isLoading}
                    aria-describedby="project-create-refresh-interval-help"
                  />
                  <span
                    id="project-create-refresh-interval-help"
                    className="text-xs text-gray-500 dark:text-slate-400"
                  >
                    {t('project.create.rangeRefreshHours')}
                  </span>
                </div>

                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="project-create-auto-refresh"
                    checked={formData.memory_rules.auto_refresh}
                    onChange={(e) => {
                      setFormData({
                        ...formData,
                        memory_rules: {
                          ...formData.memory_rules,
                          auto_refresh: e.target.checked,
                        },
                      });
                    }}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800"
                    disabled={isLoading}
                  />
                  <label
                    htmlFor="project-create-auto-refresh"
                    className="text-sm font-medium text-gray-700 dark:text-slate-300"
                  >
                    {t('project.create.autoRefreshLabel')}
                  </label>
                </div>
              </>
            )}

            {activeTab === 'graph' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="project-create-max-nodes"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      {t('project.create.maxNodesLabel')}
                    </label>
                    <input
                      type="number"
                      id="project-create-max-nodes"
                      value={formData.graph_config.max_nodes}
                      onChange={(e) => {
                        setFormData({
                          ...formData,
                          graph_config: {
                            ...formData.graph_config,
                            max_nodes: parseInt(e.target.value) || 5000,
                          },
                        });
                      }}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="100"
                      max="50000"
                      disabled={isLoading}
                      aria-describedby="project-create-max-nodes-help"
                    />
                    <span
                      id="project-create-max-nodes-help"
                      className="text-xs text-gray-500 dark:text-slate-400"
                    >
                      {t('project.create.rangeNodes')}
                    </span>
                  </div>

                  <div>
                    <label
                      htmlFor="project-create-max-edges"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      {t('project.create.maxEdgesLabel')}
                    </label>
                    <input
                      type="number"
                      id="project-create-max-edges"
                      value={formData.graph_config.max_edges}
                      onChange={(e) => {
                        setFormData({
                          ...formData,
                          graph_config: {
                            ...formData.graph_config,
                            max_edges: parseInt(e.target.value) || 10000,
                          },
                        });
                      }}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="100"
                      max="100000"
                      disabled={isLoading}
                      aria-describedby="project-create-max-edges-help"
                    />
                    <span
                      id="project-create-max-edges-help"
                      className="text-xs text-gray-500 dark:text-slate-400"
                    >
                      {t('project.create.rangeEdges')}
                    </span>
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="project-create-similarity"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    {t('project.create.similarityLabel')}
                  </label>
                  <input
                    type="range"
                    id="project-create-similarity"
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
                    className="w-full"
                    disabled={isLoading}
                    aria-describedby="project-create-similarity-value"
                  />
                  <div
                    className="flex justify-between text-xs text-gray-500 dark:text-slate-400 mt-1"
                    id="project-create-similarity-value"
                  >
                    <span>0.1</span>
                    <span aria-live="polite">{formData.graph_config.similarity_threshold}</span>
                    <span>1.0</span>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="project-create-community-detection"
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
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded bg-white dark:bg-slate-800"
                    disabled={isLoading}
                  />
                  <label
                    htmlFor="project-create-community-detection"
                    className="text-sm font-medium text-gray-700 dark:text-slate-300"
                  >
                    {t('project.create.communityDetectionLabel')}
                  </label>
                </div>
              </>
            )}

            {activeTab === 'sandbox' && (
              <>
                <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md">
                  <p className="text-sm text-blue-700 dark:text-blue-300">
                    <strong>{t('project.create.sandboxIntroPrefix')}</strong>
                    {t('project.create.sandboxIntroBody')}
                  </p>
                </div>

                <div className="space-y-4">
                  <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                    {t('project.create.sandboxTypeLabel')}
                  </label>

                  <div className="space-y-3">
                    <label className="flex items-start p-3 border border-gray-200 dark:border-slate-700 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors">
                      <input
                        type="radio"
                        name="sandbox_type"
                        value="cloud"
                        checked={formData.sandbox_config.sandbox_type === 'cloud'}
                        onChange={() => {
                          setFormData({
                            ...formData,
                            sandbox_config: {
                              ...formData.sandbox_config,
                              sandbox_type: 'cloud',
                            },
                          });
                        }}
                        className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                        disabled={isLoading}
                      />
                      <div className="ml-3 flex-1">
                        <div className="flex items-center space-x-2">
                          <Cloud className="w-4 h-4 text-blue-500" />
                          <span className="font-medium text-gray-900 dark:text-white">
                            {t('project.create.cloudSandbox')}
                          </span>
                          <span className="px-2 py-0.5 text-xs bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">
                            {t('project.create.recommended')}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
                          {t('project.create.cloudSandboxDescription')}
                        </p>
                      </div>
                    </label>

                    <label className="flex items-start p-3 border border-gray-200 dark:border-slate-700 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors">
                      <input
                        type="radio"
                        name="sandbox_type"
                        value="local"
                        checked={formData.sandbox_config.sandbox_type === 'local'}
                        onChange={() => {
                          setFormData({
                            ...formData,
                            sandbox_config: {
                              ...formData.sandbox_config,
                              sandbox_type: 'local',
                            },
                          });
                        }}
                        className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                        disabled={isLoading}
                      />
                      <div className="ml-3 flex-1">
                        <div className="flex items-center space-x-2">
                          <Monitor className="w-4 h-4 text-purple-500" />
                          <span className="font-medium text-gray-900 dark:text-white">
                            {t('project.create.localSandbox')}
                          </span>
                          <span className="px-2 py-0.5 text-xs bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300 rounded">
                            {t('project.create.advanced')}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
                          {t('project.create.localSandboxDescription')}
                        </p>
                      </div>
                    </label>
                  </div>
                </div>

                {formData.sandbox_config.sandbox_type === 'local' && (
                  <div className="mt-6 p-4 border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20 rounded-lg space-y-4">
                    <h4 className="font-medium text-purple-900 dark:text-purple-200 flex items-center space-x-2">
                      <Monitor className="w-4 h-4" />
                      <span>{t('project.create.localConfigHeading')}</span>
                    </h4>

                    <div>
                      <label
                        htmlFor="project-create-tunnel-url"
                        className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                      >
                        {t('project.create.tunnelUrlLabel')}{' '}
                        <span className="text-gray-400">{t('project.create.optional')}</span>
                      </label>
                      <input
                        type="url"
                        id="project-create-tunnel-url"
                        value={formData.sandbox_config.local_config.tunnel_url}
                        onChange={(e) => {
                          setFormData({
                            ...formData,
                            sandbox_config: {
                              ...formData.sandbox_config,
                              local_config: {
                                ...formData.sandbox_config.local_config,
                                tunnel_url: e.target.value,
                              },
                            },
                          });
                        }}
                        placeholder="wss://your-tunnel.ngrok.io"
                        className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                        disabled={isLoading}
                      />
                      <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">
                        {t('project.create.tunnelUrlHelp')}
                      </p>
                    </div>

                    <div>
                      <label
                        htmlFor="project-create-workspace-path"
                        className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                      >
                        {t('project.create.workspacePathLabel')}{' '}
                        <span className="text-gray-400">{t('project.create.optional')}</span>
                      </label>
                      <input
                        type="text"
                        id="project-create-workspace-path"
                        value={formData.sandbox_config.local_config.workspace_path}
                        onChange={(e) => {
                          setFormData({
                            ...formData,
                            sandbox_config: {
                              ...formData.sandbox_config,
                              local_config: {
                                ...formData.sandbox_config.local_config,
                                workspace_path: e.target.value,
                              },
                            },
                          });
                        }}
                        placeholder="/home/user/workspace"
                        className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                        disabled={isLoading}
                      />
                      <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">
                        {t('project.create.workspacePathHelp')}
                      </p>
                    </div>

                    <div className="pt-3 border-t border-purple-200 dark:border-purple-700">
                      <p className="text-sm text-purple-800 dark:text-purple-300">
                        <strong>{t('project.create.tipPrefix')}</strong>
                        {t('project.create.tipIntro')}
                      </p>
                      <ol className="mt-2 text-sm text-purple-700 dark:text-purple-400 list-decimal list-inside space-y-1">
                        <li>{t('project.create.tipStep1')}</li>
                        <li>{t('project.create.tipStep2')}</li>
                        <li>{t('project.create.tipStep3')}</li>
                      </ol>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </form>

        <div className="flex space-x-3 p-6 border-t border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-900">
          <button
            type="button"
            onClick={handleClose}
            className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
            disabled={isLoading}
          >
            {t('project.create.cancel')}
          </button>
          <button
            type="submit"
            form="project-form"
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isLoading || !formData.name.trim()}
          >
            {isLoading ? (
              <div className="flex items-center justify-center space-x-2">
                <div className="animate-spin motion-reduce:animate-none rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>{t('project.create.creating')}</span>
              </div>
            ) : (
              t('project.create.submit')
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
