import React, { useState } from 'react';
import { X, Folder, AlertCircle, Settings, Brain, Users } from 'lucide-react';
import { useProjectStore } from '../stores/project';
import { useTenantStore } from '../stores/tenant';

interface ProjectCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export const ProjectCreateModal: React.FC<ProjectCreateModalProps> = ({
  isOpen,
  onClose,
  onSuccess
}) => {
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
      refresh_interval: 24
    },
    graph_config: {
      max_nodes: 5000,
      max_edges: 10000,
      similarity_threshold: 0.7,
      community_detection: true
    }
  });

  const [activeTab, setActiveTab] = useState<'basic' | 'memory' | 'graph'>('basic');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentTenant) return;
    
    try {
      await createProject(currentTenant.id, {
        ...formData,
        tenant_id: currentTenant.id
      });
      onSuccess?.();
      onClose();
      setFormData({
        name: '',
        description: '',
        status: 'active',
        memory_rules: {
          max_episodes: 1000,
          retention_days: 30,
          auto_refresh: true,
          refresh_interval: 24
        },
        graph_config: {
          max_nodes: 5000,
          max_edges: 10000,
          similarity_threshold: 0.7,
          community_detection: true
        }
      });
    } catch (_error) {
      // Error is handled in store
    }
  };

  const handleClose = () => {
    onClose();
    setFormData({
      name: '',
      description: '',
      status: 'active',
      memory_rules: {
        max_episodes: 1000,
        retention_days: 30,
        auto_refresh: true,
        refresh_interval: 24
      },
      graph_config: {
        max_nodes: 5000,
        max_edges: 10000,
        similarity_threshold: 0.7,
        community_detection: true
      }
    });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-4xl mx-4 max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Folder className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">创建项目</h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-b border-gray-200 dark:border-slate-800">
          <nav className="flex space-x-8 px-6">
            <button
              onClick={() => setActiveTab('basic')}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'basic'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Settings className="h-4 w-4" />
                <span>基础设置</span>
              </div>
            </button>
            <button
              onClick={() => setActiveTab('memory')}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'memory'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Brain className="h-4 w-4" />
                <span>记忆规则</span>
              </div>
            </button>
            <button
              onClick={() => setActiveTab('graph')}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'graph'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Users className="h-4 w-4" />
                <span>图谱配置</span>
              </div>
            </button>
          </nav>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto" id="project-form">
          <div className="p-6 space-y-4">
            {error && (
              <div className="flex items-center space-x-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 rounded-md">
                <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
                <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
              </div>
            )}

            {activeTab === 'basic' && (
              <>
                <div>
                  <label htmlFor="name" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    项目名称 *
                  </label>
                  <input
                    type="text"
                    id="name"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder="输入项目名称"
                    required
                    disabled={isLoading}
                  />
                </div>

                <div>
                  <label htmlFor="description" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    项目描述
                  </label>
                  <textarea
                    id="description"
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder="描述这个项目的目标和用途"
                    rows={3}
                    disabled={isLoading}
                  />
                </div>

                <div>
                  <label htmlFor="status" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    项目状态
                  </label>
                  <select
                    id="status"
                    value={formData.status}
                    onChange={(e) => setFormData({ ...formData, status: e.target.value as any })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                    disabled={isLoading}
                  >
                    <option value="active">活跃</option>
                    <option value="paused">暂停</option>
                    <option value="archived">归档</option>
                  </select>
                </div>
              </>
            )}

            {activeTab === 'memory' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="max_episodes" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      最大记忆片段数
                    </label>
                    <input
                      type="number"
                      id="max_episodes"
                      value={formData.memory_rules.max_episodes}
                      onChange={(e) => setFormData({
                        ...formData,
                        memory_rules: {
                          ...formData.memory_rules,
                          max_episodes: parseInt(e.target.value) || 1000
                        }
                      })}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="100"
                      max="10000"
                      disabled={isLoading}
                    />
                  </div>

                  <div>
                    <label htmlFor="retention_days" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      保留天数
                    </label>
                    <input
                      type="number"
                      id="retention_days"
                      value={formData.memory_rules.retention_days}
                      onChange={(e) => setFormData({
                        ...formData,
                        memory_rules: {
                          ...formData.memory_rules,
                          retention_days: parseInt(e.target.value) || 30
                        }
                      })}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="1"
                      max="365"
                      disabled={isLoading}
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="refresh_interval" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    自动刷新间隔（小时）
                  </label>
                  <input
                    type="number"
                    id="refresh_interval"
                    value={formData.memory_rules.refresh_interval}
                    onChange={(e) => setFormData({
                      ...formData,
                      memory_rules: {
                        ...formData.memory_rules,
                        refresh_interval: parseInt(e.target.value) || 24
                      }
                    })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    min="1"
                    max="168"
                    disabled={isLoading}
                  />
                </div>

                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="auto_refresh"
                    checked={formData.memory_rules.auto_refresh}
                    onChange={(e) => setFormData({
                      ...formData,
                      memory_rules: {
                        ...formData.memory_rules,
                        auto_refresh: e.target.checked
                      }
                    })}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800"
                    disabled={isLoading}
                  />
                  <label htmlFor="auto_refresh" className="text-sm font-medium text-gray-700 dark:text-slate-300">
                    启用自动刷新
                  </label>
                </div>
              </>
            )}

            {activeTab === 'graph' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="max_nodes" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      最大节点数
                    </label>
                    <input
                      type="number"
                      id="max_nodes"
                      value={formData.graph_config.max_nodes}
                      onChange={(e) => setFormData({
                        ...formData,
                        graph_config: {
                          ...formData.graph_config,
                          max_nodes: parseInt(e.target.value) || 5000
                        }
                      })}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="100"
                      max="50000"
                      disabled={isLoading}
                    />
                  </div>

                  <div>
                    <label htmlFor="max_edges" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      最大边数
                    </label>
                    <input
                      type="number"
                      id="max_edges"
                      value={formData.graph_config.max_edges}
                      onChange={(e) => setFormData({
                        ...formData,
                        graph_config: {
                          ...formData.graph_config,
                          max_edges: parseInt(e.target.value) || 10000
                        }
                      })}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      min="100"
                      max="100000"
                      disabled={isLoading}
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="similarity_threshold" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    相似度阈值
                  </label>
                  <input
                    type="range"
                    id="similarity_threshold"
                    min="0.1"
                    max="1.0"
                    step="0.1"
                    value={formData.graph_config.similarity_threshold}
                    onChange={(e) => setFormData({
                      ...formData,
                      graph_config: {
                        ...formData.graph_config,
                        similarity_threshold: parseFloat(e.target.value)
                      }
                    })}
                    className="w-full"
                    disabled={isLoading}
                  />
                  <div className="flex justify-between text-xs text-gray-500 dark:text-slate-400 mt-1">
                    <span>0.1</span>
                    <span>{formData.graph_config.similarity_threshold}</span>
                    <span>1.0</span>
                  </div>
                </div>

                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="community_detection"
                    checked={formData.graph_config.community_detection}
                    onChange={(e) => setFormData({
                      ...formData,
                      graph_config: {
                        ...formData.graph_config,
                        community_detection: e.target.checked
                      }
                    })}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded bg-white dark:bg-slate-800"
                    disabled={isLoading}
                  />
                  <label htmlFor="community_detection" className="text-sm font-medium text-gray-700 dark:text-slate-300">
                    启用社区检测
                  </label>
                </div>
              </>
            )}
          </div>
        </form>

        <div className="flex space-x-3 p-6 border-t border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-900">
          <button
            type="button"
            onClick={handleClose}
            className="flex-1 px-4 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            disabled={isLoading}
          >
            取消
          </button>
          <button
            type="submit"
            form="project-form"
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isLoading || !formData.name.trim()}
            onClick={handleSubmit}
          >
            {isLoading ? (
              <div className="flex items-center justify-center space-x-2">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>创建中...</span>
              </div>
            ) : (
              '创建项目'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
