import React, { useState } from 'react';

import { X, Brain, AlertCircle, Type, Hash, Settings } from 'lucide-react';

import { useMemoryStore } from '../stores/memory';
import { useProjectStore } from '../stores/project';

interface MemoryCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: (() => void) | undefined;
}

export const MemoryCreateModal: React.FC<MemoryCreateModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const { createMemory, extractEntities, extractRelationships, isLoading, error } =
    useMemoryStore();
  const { currentProject } = useProjectStore();

  const [formData, setFormData] = useState({
    title: '',
    content: '',
    content_type: 'text' as const,
    author_id: '',
    metadata: {} as any,
  });

  const [extractedEntities, setExtractedEntities] = useState<any[]>([]);
  const [extractedRelationships, setExtractedRelationships] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'basic' | 'extraction' | 'advanced'>('basic');
  const [isExtracting, setIsExtracting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentProject) return;

    try {
      const memoryData = {
        ...formData,
        entities: extractedEntities,
        relationships: extractedRelationships,
        project_id: currentProject.id,
      };

      await createMemory(currentProject.id, memoryData);
      onSuccess?.();
      onClose();
      resetForm();
    } catch (_error) {
      // Error is handled in store
    }
  };

  const handleExtractEntities = async () => {
    if (!currentProject || !formData.content.trim()) return;

    setIsExtracting(true);
    try {
      const entities = await extractEntities(currentProject.id, formData.content);
      setExtractedEntities(entities);
    } catch (_error) {
      // Error is handled in store
    } finally {
      setIsExtracting(false);
    }
  };

  const handleExtractRelationships = async () => {
    if (!currentProject || !formData.content.trim()) return;

    setIsExtracting(true);
    try {
      const relationships = await extractRelationships(currentProject.id, formData.content);
      setExtractedRelationships(relationships);
    } catch (_error) {
      // Error is handled in store
    } finally {
      setIsExtracting(false);
    }
  };

  const resetForm = () => {
    setFormData({
      title: '',
      content: '',
      content_type: 'text',
      author_id: '',
      metadata: {},
    });
    setExtractedEntities([]);
    setExtractedRelationships([]);
    setActiveTab('basic');
  };

  const handleClose = () => {
    onClose();
    resetForm();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-xl w-full max-w-4xl mx-4 max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <Brain className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">创建记忆</h2>
          </div>
          <button
            onClick={handleClose}
            className="p-1 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 rounded-md transition-colors"
            aria-label="关闭创建记忆弹窗"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-b border-gray-200 dark:border-slate-800">
          <nav className="flex space-x-8 px-6">
            <button
              onClick={() => { setActiveTab('basic'); }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'basic'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Type className="h-4 w-4" />
                <span>基础信息</span>
              </div>
            </button>
            <button
              onClick={() => { setActiveTab('extraction'); }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'extraction'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Hash className="h-4 w-4" />
                <span>实体提取</span>
              </div>
            </button>
            <button
              onClick={() => { setActiveTab('advanced'); }}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === 'advanced'
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                <Settings className="h-4 w-4" />
                <span>高级设置</span>
              </div>
            </button>
          </nav>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto" id="memory-form">
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
                    htmlFor="memory-create-title"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    记忆标题 *
                  </label>
                  <input
                    type="text"
                    id="memory-create-title"
                    value={formData.title}
                    onChange={(e) => { setFormData({ ...formData, title: e.target.value }); }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder="输入记忆标题"
                    required
                    disabled={isLoading}
                    aria-required="true"
                  />
                </div>

                <div>
                  <label
                    htmlFor="memory-create-content"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    记忆内容 *
                  </label>
                  <textarea
                    id="memory-create-content"
                    value={formData.content}
                    onChange={(e) => { setFormData({ ...formData, content: e.target.value }); }}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder="输入记忆内容"
                    rows={6}
                    required
                    disabled={isLoading}
                    aria-required="true"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="memory-create-type"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      记忆类型
                    </label>
                    <select
                      id="memory-create-type"
                      value={formData.content_type}
                      onChange={(e) =>
                        { setFormData({ ...formData, content_type: e.target.value as any }); }
                      }
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
                      disabled={isLoading}
                    >
                      <option value="text">文本</option>
                      <option value="document">文档</option>
                      <option value="image">图片</option>
                      <option value="video">视频</option>
                    </select>
                  </div>

                  <div>
                    <label
                      htmlFor="memory-create-author"
                      className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                    >
                      用户ID
                    </label>
                    <input
                      type="text"
                      id="memory-create-author"
                      value={formData.author_id}
                      onChange={(e) => { setFormData({ ...formData, author_id: e.target.value }); }}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                      placeholder="输入用户ID（可选）"
                      disabled={isLoading}
                      aria-describedby="memory-create-author-help"
                    />
                    <span
                      id="memory-create-author-help"
                      className="text-xs text-gray-500 dark:text-slate-400"
                    >
                      可选：记录创建此记忆的用户
                    </span>
                  </div>
                </div>
              </>
            )}

            {activeTab === 'extraction' && (
              <>
                <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-900/30 rounded-md p-4 mb-4">
                  <div className="flex items-center space-x-2 mb-2">
                    <Brain className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                    <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                      AI 实体提取
                    </span>
                  </div>
                  <p className="text-sm text-blue-700 dark:text-blue-300">
                    点击下面的按钮来自动提取文本中的实体和关系。确保你已经在基础信息中输入了内容。
                  </p>
                </div>

                <div className="flex space-x-4 mb-4">
                  <button
                    type="button"
                    onClick={handleExtractEntities}
                    disabled={!formData.content.trim() || isExtracting || isLoading}
                    className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isExtracting ? (
                      <div className="flex items-center space-x-2">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>提取中...</span>
                      </div>
                    ) : (
                      '提取实体'
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={handleExtractRelationships}
                    disabled={!formData.content.trim() || isExtracting || isLoading}
                    className="px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isExtracting ? (
                      <div className="flex items-center space-x-2">
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        <span>提取中...</span>
                      </div>
                    ) : (
                      '提取关系'
                    )}
                  </button>
                </div>

                {extractedEntities.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                      提取的实体
                    </h4>
                    <div className="grid grid-cols-2 gap-2">
                      {extractedEntities.map((entity, index) => (
                        <div
                          key={index}
                          className="flex items-center space-x-2 p-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-900/30 rounded-md"
                        >
                          <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                          <span className="text-sm text-green-800 dark:text-green-200">
                            {entity.name}
                          </span>
                          <span className="text-xs text-green-600 dark:text-green-400">
                            ({entity.type})
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {extractedRelationships.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                      提取的关系
                    </h4>
                    <div className="space-y-2">
                      {extractedRelationships.map((relationship, index) => (
                        <div
                          key={index}
                          className="flex items-center space-x-2 p-2 bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-900/30 rounded-md"
                        >
                          <div className="w-2 h-2 bg-purple-500 rounded-full"></div>
                          <span className="text-sm text-purple-800 dark:text-purple-200">
                            {relationship.source_id} → {relationship.target_id}
                          </span>
                          <span className="text-xs text-purple-600 dark:text-purple-400">
                            ({relationship.type})
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {activeTab === 'advanced' && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-2">
                    元数据设置
                  </label>
                  <div className="space-y-3">
                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="enable_search"
                        checked={formData.metadata?.enable_search ?? true}
                        onChange={(e) =>
                          { setFormData({
                            ...formData,
                            metadata: {
                              ...formData.metadata,
                              enable_search: e.target.checked,
                            },
                          }); }
                        }
                        className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800"
                        disabled={isLoading}
                      />
                      <label
                        htmlFor="enable_search"
                        className="text-sm text-gray-700 dark:text-slate-300"
                      >
                        启用搜索
                      </label>
                    </div>
                    <div className="flex items-center space-x-2">
                      <input
                        type="checkbox"
                        id="enable_graph"
                        checked={formData.metadata?.enable_graph ?? true}
                        onChange={(e) =>
                          { setFormData({
                            ...formData,
                            metadata: {
                              ...formData.metadata,
                              enable_graph: e.target.checked,
                            },
                          }); }
                        }
                        className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800"
                        disabled={isLoading}
                      />
                      <label
                        htmlFor="enable_graph"
                        className="text-sm text-gray-700 dark:text-slate-300"
                      >
                        启用图谱
                      </label>
                    </div>
                  </div>
                </div>

                <div>
                  <label
                    htmlFor="memory-create-tags"
                    className="block text-sm font-medium text-gray-700 dark:text-slate-300 mb-1"
                  >
                    标签
                  </label>
                  <input
                    type="text"
                    id="memory-create-tags"
                    value={formData.metadata?.tags?.join(', ') || ''}
                    onChange={(e) =>
                      { setFormData({
                        ...formData,
                        metadata: {
                          ...formData.metadata,
                          tags: e.target.value
                            .split(',')
                            .map((tag) => tag.trim())
                            .filter(Boolean),
                        },
                      }); }
                    }
                    className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
                    placeholder="输入标签，用逗号分隔"
                    disabled={isLoading}
                    aria-describedby="memory-create-tags-help"
                  />
                  <span
                    id="memory-create-tags-help"
                    className="text-xs text-gray-500 dark:text-slate-400"
                  >
                    使用逗号分隔多个标签
                  </span>
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
            form="memory-form"
            className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isLoading || !formData.title.trim() || !formData.content.trim()}
            onClick={handleSubmit}
          >
            {isLoading ? (
              <div className="flex items-center justify-center space-x-2">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>创建中...</span>
              </div>
            ) : (
              '创建记忆'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
