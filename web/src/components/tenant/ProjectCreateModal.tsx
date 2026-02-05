import React, { useState } from 'react';

import { X, Folder, AlertCircle, Settings, Brain, Users, Cloud, Monitor } from 'lucide-react';

import { useProjectStore } from '../../stores/project';
import { useTenantStore } from '../../stores/tenant';

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
    },
    sandbox_config: {
      sandbox_type: 'cloud' as 'cloud' | 'local',
      local_config: {
        workspace_path: '/workspace',
        tunnel_url: '',
        host: 'localhost',
        port: 8765
      }
    }
  });

  const [activeTab, setActiveTab] = useState<'basic' | 'memory' | 'graph' | 'sandbox'>('basic');

  const resetFormData = () => {
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
      },
      sandbox_config: {
        sandbox_type: 'cloud',
        local_config: {
          workspace_path: '/workspace',
          tunnel_url: '',
          host: 'localhost',
          port: 8765
        }
      }
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
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
            local_config: formData.sandbox_config.local_config
          })
        }
      };
      await createProject(currentTenant.id, submitData);
      onSuccess?.();
      onClose();
      resetFormData();
    } catch (_error) {
      // Error is handled in store
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
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">创建项目</h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
            aria-label="关闭创建项目弹窗"
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
            <button
              onClick={() => setActiveTab('sandbox')}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'sandbox'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Monitor className="h-4 w-4" />
                <span>沙箱设置</span>
              </div>
            </button>
          </nav>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto" id="project-form">
          <div className="p-6 space-y-4">
            {error && (
              <div className="flex items-center space-x-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 rounded-md" role="alert" aria-live="assertive">
                <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" aria-hidden="true" />
                <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
              </div>
            )}

            {activeTab === 'basic' && (
              <>
                <div>
                  <label htmlFor="project-create-name" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    项目名称 *
                  </label>
                  <input
                    type="text"
                    id="project-create-name"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder="输入项目名称"
                    required
                    disabled={isLoading}
                    aria-required="true"
                  />
                </div>

                <div>
                  <label htmlFor="project-create-description" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    项目描述
                  </label>
                  <textarea
                    id="project-create-description"
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder="描述这个项目的目标和用途"
                    rows={3}
                    disabled={isLoading}
                    aria-describedby="project-create-description-help"
                  />
                  <span id="project-create-description-help" className="text-xs text-gray-500 dark:text-slate-400">
                    可选：描述项目的目标和用途
                  </span>
                </div>

                <div>
                  <label htmlFor="project-create-status" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    项目状态
                  </label>
                  <select
                    id="project-create-status"
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
                    <label htmlFor="project-create-max-episodes" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      最大记忆片段数
                    </label>
                    <input
                      type="number"
                      id="project-create-max-episodes"
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
                      aria-describedby="project-create-max-episodes-help"
                    />
                    <span id="project-create-max-episodes-help" className="text-xs text-gray-500 dark:text-slate-400">
                      范围：100 - 10000
                    </span>
                  </div>

                  <div>
                    <label htmlFor="project-create-retention-days" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      保留天数
                    </label>
                    <input
                      type="number"
                      id="project-create-retention-days"
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
                      aria-describedby="project-create-retention-days-help"
                    />
                    <span id="project-create-retention-days-help" className="text-xs text-gray-500 dark:text-slate-400">
                      范围：1 - 365 天
                    </span>
                  </div>
                </div>

                <div>
                  <label htmlFor="project-create-refresh-interval" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    自动刷新间隔（小时）
                  </label>
                  <input
                    type="number"
                    id="project-create-refresh-interval"
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
                    aria-describedby="project-create-refresh-interval-help"
                  />
                  <span id="project-create-refresh-interval-help" className="text-xs text-gray-500 dark:text-slate-400">
                    范围：1 - 168 小时
                  </span>
                </div>

                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="project-create-auto-refresh"
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
                  <label htmlFor="project-create-auto-refresh" className="text-sm font-medium text-gray-700 dark:text-slate-300">
                    启用自动刷新
                  </label>
                </div>
              </>
            )}

            {activeTab === 'graph' && (
              <>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label htmlFor="project-create-max-nodes" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      最大节点数
                    </label>
                    <input
                      type="number"
                      id="project-create-max-nodes"
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
                      aria-describedby="project-create-max-nodes-help"
                    />
                    <span id="project-create-max-nodes-help" className="text-xs text-gray-500 dark:text-slate-400">
                      范围：100 - 50000
                    </span>
                  </div>

                  <div>
                    <label htmlFor="project-create-max-edges" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                      最大边数
                    </label>
                    <input
                      type="number"
                      id="project-create-max-edges"
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
                      aria-describedby="project-create-max-edges-help"
                    />
                    <span id="project-create-max-edges-help" className="text-xs text-gray-500 dark:text-slate-400">
                      范围：100 - 100000
                    </span>
                  </div>
                </div>

                <div>
                  <label htmlFor="project-create-similarity" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                    相似度阈值
                  </label>
                  <input
                    type="range"
                    id="project-create-similarity"
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
                    aria-describedby="project-create-similarity-value"
                  />
                  <div className="flex justify-between text-xs text-gray-500 dark:text-slate-400 mt-1" id="project-create-similarity-value">
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
                  <label htmlFor="project-create-community-detection" className="text-sm font-medium text-gray-700 dark:text-slate-300">
                    启用社区检测
                  </label>
                </div>
              </>
            )}

            {activeTab === 'sandbox' && (
              <>
                <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-md">
                  <p className="text-sm text-blue-700 dark:text-blue-300">
                    <strong>沙箱</strong>是 Agent 执行代码和工具的安全隔离环境。您可以选择使用云端托管沙箱或在本地运行沙箱。
                  </p>
                </div>

                <div className="space-y-4">
                  <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                    沙箱类型
                  </label>
                  
                  <div className="space-y-3">
                    <label className="flex items-start p-3 border border-gray-200 dark:border-slate-700 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors">
                      <input
                        type="radio"
                        name="sandbox_type"
                        value="cloud"
                        checked={formData.sandbox_config.sandbox_type === 'cloud'}
                        onChange={() => setFormData({
                          ...formData,
                          sandbox_config: {
                            ...formData.sandbox_config,
                            sandbox_type: 'cloud'
                          }
                        })}
                        className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                        disabled={isLoading}
                      />
                      <div className="ml-3 flex-1">
                        <div className="flex items-center space-x-2">
                          <Cloud className="w-4 h-4 text-blue-500" />
                          <span className="font-medium text-gray-900 dark:text-white">云端沙箱</span>
                          <span className="px-2 py-0.5 text-xs bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300 rounded">推荐</span>
                        </div>
                        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
                          在云端 Docker 容器中运行，无需本地配置，开箱即用。适合大多数用户。
                        </p>
                      </div>
                    </label>

                    <label className="flex items-start p-3 border border-gray-200 dark:border-slate-700 rounded-lg cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors">
                      <input
                        type="radio"
                        name="sandbox_type"
                        value="local"
                        checked={formData.sandbox_config.sandbox_type === 'local'}
                        onChange={() => setFormData({
                          ...formData,
                          sandbox_config: {
                            ...formData.sandbox_config,
                            sandbox_type: 'local'
                          }
                        })}
                        className="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300"
                        disabled={isLoading}
                      />
                      <div className="ml-3 flex-1">
                        <div className="flex items-center space-x-2">
                          <Monitor className="w-4 h-4 text-purple-500" />
                          <span className="font-medium text-gray-900 dark:text-white">本地沙箱</span>
                          <span className="px-2 py-0.5 text-xs bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300 rounded">高级</span>
                        </div>
                        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
                          在您的本地电脑运行，支持访问本地文件和资源。需要安装桌面客户端。
                        </p>
                      </div>
                    </label>
                  </div>
                </div>

                {formData.sandbox_config.sandbox_type === 'local' && (
                  <div className="mt-6 p-4 border border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20 rounded-lg space-y-4">
                    <h4 className="font-medium text-purple-900 dark:text-purple-200 flex items-center space-x-2">
                      <Monitor className="w-4 h-4" />
                      <span>本地沙箱配置</span>
                    </h4>
                    
                    <div>
                      <label htmlFor="project-create-tunnel-url" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                        隧道 URL <span className="text-gray-400">(可选)</span>
                      </label>
                      <input
                        type="url"
                        id="project-create-tunnel-url"
                        value={formData.sandbox_config.local_config?.tunnel_url || ''}
                        onChange={(e) => setFormData({
                          ...formData,
                          sandbox_config: {
                            ...formData.sandbox_config,
                            local_config: {
                              ...(formData.sandbox_config.local_config || {
                                workspace_path: '/workspace',
                                tunnel_url: '',
                                host: 'localhost',
                                port: 8765
                              }),
                              tunnel_url: e.target.value
                            }
                          }
                        })}
                        placeholder="wss://your-tunnel.ngrok.io"
                        className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                        disabled={isLoading}
                      />
                      <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">
                        使用 ngrok 或 cloudflare tunnel 生成的公网地址，用于云端平台连接到您的本地沙箱
                      </p>
                    </div>

                    <div>
                      <label htmlFor="project-create-workspace-path" className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1">
                        工作目录 <span className="text-gray-400">(可选)</span>
                      </label>
                      <input
                        type="text"
                        id="project-create-workspace-path"
                        value={formData.sandbox_config.local_config?.workspace_path || ''}
                        onChange={(e) => setFormData({
                          ...formData,
                          sandbox_config: {
                            ...formData.sandbox_config,
                            local_config: {
                              ...(formData.sandbox_config.local_config || {
                                workspace_path: '/workspace',
                                tunnel_url: '',
                                host: 'localhost',
                                port: 8765
                              }),
                              workspace_path: e.target.value
                            }
                          }
                        })}
                        placeholder="/home/user/workspace"
                        className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                        disabled={isLoading}
                      />
                      <p className="mt-1 text-xs text-gray-500 dark:text-slate-400">
                        Agent 可以访问的本地工作目录路径
                      </p>
                    </div>

                    <div className="pt-3 border-t border-purple-200 dark:border-purple-700">
                      <p className="text-sm text-purple-800 dark:text-purple-300">
                        <strong>提示：</strong>选择本地沙箱后，您需要：
                      </p>
                      <ol className="mt-2 text-sm text-purple-700 dark:text-purple-400 list-decimal list-inside space-y-1">
                        <li>下载并安装 MemStack 桌面客户端</li>
                        <li>启动本地沙箱服务</li>
                        <li>在客户端中配置隧道连接</li>
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
