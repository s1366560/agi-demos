import React, { useEffect, useState, useCallback } from 'react';
import { Brain, Search, Plus, Clock, User, Tag, AlertCircle, Eye, Trash2 } from 'lucide-react';
import { useMemoryStore } from '../stores/memory';
import { useProjectStore } from '../stores/project';
import { Memory } from '../types/memory';
import { MemoryCreateModal } from './MemoryCreateModal';
import { MemoryDetailModal } from './MemoryDetailModal';

interface MemoryManagerProps {
  onMemorySelect?: (memory: Memory) => void;
}

export const MemoryManager: React.FC<MemoryManagerProps> = ({ onMemorySelect }) => {
  const { currentProject } = useProjectStore();
  const { 
    memories, 
    currentMemory, 
    listMemories, 
    deleteMemory, 
    setCurrentMemory, 
    isLoading, 
    error 
  } = useMemoryStore();
  
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterType, setFilterType] = useState<string>('all');
  const [filterUser, setFilterUser] = useState<string>('');
  const [dateRange, setDateRange] = useState<{ start?: Date; end?: Date }>({});

  const loadMemories = useCallback(async () => {
    if (!currentProject) return;
    
    const params: any = {};
    if (searchTerm) params.search = searchTerm;
    if (filterType !== 'all') params.content_type = filterType;
    if (filterUser) params.author_id = filterUser;
    if (dateRange.start) params.start_date = dateRange.start.toISOString();
    if (dateRange.end) params.end_date = dateRange.end.toISOString();
    
    try {
      await listMemories(currentProject.id, params);
    } catch (_error) {
      console.error('Failed to load memories:', error);
    }
  }, [currentProject, searchTerm, filterType, filterUser, dateRange, listMemories, error]);

  useEffect(() => {
    if (currentProject) {
      loadMemories();
    }
  }, [currentProject, loadMemories]);

  const handleMemorySelect = (memory: Memory) => {
    setCurrentMemory(memory);
    onMemorySelect?.(memory);
  };

  const handleViewMemory = (memory: Memory) => {
    setCurrentMemory(memory);
    setIsDetailModalOpen(true);
  };

  const handleDeleteMemory = async (memoryId: string) => {
    if (!currentProject) return;
    
    if (window.confirm('确定要删除这条记忆吗？此操作不可恢复。')) {
      try {
        await deleteMemory(currentProject.id, memoryId);
      } catch (_error) {
        // Error is handled in store
      }
    }
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case 'text': return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
      case 'document': return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
      case 'image': return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300';
      case 'video': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300';
      default: return 'bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-200';
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('zh-CN', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (!currentProject) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8">
        <div className="text-center">
          <Brain className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
          <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">请先选择项目</h3>
          <p className="text-gray-600 dark:text-slate-400">选择一个项目来查看和管理记忆</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800 p-8">
        <div className="flex items-center justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 dark:border-blue-400"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800">
      <div className="p-6 border-b border-gray-200 dark:border-slate-800">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center space-x-2">
            <Brain className="h-5 w-5 text-gray-600 dark:text-slate-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">记忆管理</h3>
            <span className="text-sm text-gray-500 dark:text-slate-500">({memories.length} 条)</span>
          </div>
          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors text-sm"
          >
            <Plus className="h-4 w-4" />
            <span>新建记忆</span>
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400 dark:text-slate-500" />
            <input
              type="text"
              placeholder="搜索记忆内容..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && loadMemories()}
              className="w-full pl-10 pr-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
            />
          </div>
          
          <div>
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white"
            >
              <option value="all">所有类型</option>
              <option value="text">文本</option>
              <option value="document">文档</option>
              <option value="image">图片</option>
              <option value="video">视频</option>
            </select>
          </div>

          <div>
            <input
              type="text"
              placeholder="按用户筛选..."
              value={filterUser}
              onChange={(e) => setFilterUser(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-slate-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white dark:bg-slate-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-slate-500"
            />
          </div>

          <div className="flex space-x-2">
            <button
              onClick={loadMemories}
              className="flex-1 px-3 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors text-sm"
            >
              搜索
            </button>
            <button
              onClick={() => {
                setSearchTerm('');
                setFilterType('all');
                setFilterUser('');
                setDateRange({});
              }}
              className="px-3 py-2 border border-gray-300 dark:border-slate-600 text-gray-700 dark:text-slate-300 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 transition-colors text-sm"
            >
              重置
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-900/30">
          <div className="flex items-center space-x-2">
            <AlertCircle className="h-4 w-4 text-red-600 dark:text-red-400" />
            <span className="text-sm text-red-800 dark:text-red-300">{error}</span>
          </div>
        </div>
      )}

      <div className="p-6">
        {memories.length === 0 ? (
          <div className="text-center py-8">
            <Brain className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
            <h4 className="text-lg font-medium text-gray-900 dark:text-white mb-2">暂无记忆</h4>
            <p className="text-gray-600 dark:text-slate-400 mb-4">
              {searchTerm || filterType !== 'all' || filterUser
                ? '没有找到匹配的记忆'
                : '开始创建你的第一条记忆'
              }
            </p>
            {!searchTerm && filterType === 'all' && !filterUser && (
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
              >
                创建记忆
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            {memories.map((memory) => (
              <div
                key={memory.id}
                className={`p-4 rounded-lg border cursor-pointer transition-all ${
                  currentMemory?.id === memory.id
                    ? 'border-blue-500 dark:border-blue-400 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-slate-700 hover:border-gray-300 dark:hover:border-slate-600 hover:bg-gray-50 dark:hover:bg-slate-800'
                }`}
                onClick={() => handleMemorySelect(memory)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center space-x-3 flex-1">
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${getTypeColor(memory.content_type)}`}>
                      {memory.content_type}
                    </span>
                    <div className="flex items-center space-x-2 text-sm text-gray-500 dark:text-slate-500">
                      {memory.author_id && (
                        <div className="flex items-center space-x-1">
                          <User className="h-3 w-3" />
                          <span>{memory.author_id}</span>
                        </div>
                      )}
                      <div className="flex items-center space-x-1">
                        <Clock className="h-3 w-3" />
                        <span>{formatDate(memory.created_at)}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleViewMemory(memory);
                      }}
                      className="p-1 text-gray-400 dark:text-slate-500 hover:text-blue-600 dark:hover:text-blue-400 rounded-md transition-colors"
                    >
                      <Eye className="h-4 w-4" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteMemory(memory.id);
                      }}
                      className="p-1 text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 rounded-md transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                <div className="mb-3">
                  <h4 className="text-sm font-medium text-gray-900 dark:text-white mb-2">{memory.title}</h4>
                  <p className="text-sm text-gray-600 dark:text-slate-400 line-clamp-3">{memory.content}</p>
                </div>

                {memory.entities && memory.entities.length > 0 && (
                  <div className="mb-2">
                    <div className="flex items-center space-x-2 mb-1">
                      <Tag className="h-3 w-3 text-gray-400 dark:text-slate-500" />
                      <span className="text-xs text-gray-500 dark:text-slate-500">实体</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {memory.entities.slice(0, 5).map((entity, index) => (
                        <span
                          key={index}
                          className="px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-300 text-xs rounded-full"
                        >
                          {entity.name}
                        </span>
                      ))}
                      {memory.entities.length > 5 && (
                        <span className="px-2 py-1 bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 text-xs rounded-full">
                          +{memory.entities.length - 5}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {memory.relationships && memory.relationships.length > 0 && (
                  <div>
                    <div className="flex items-center space-x-2 mb-1">
                      <div className="w-3 h-3 bg-purple-500 rounded-full" />
                      <span className="text-xs text-gray-500 dark:text-slate-500">关系</span>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {memory.relationships.slice(0, 3).map((relationship, index) => (
                        <span
                          key={index}
                          className="px-2 py-1 bg-purple-100 dark:bg-purple-900/30 text-purple-800 dark:text-purple-300 text-xs rounded-full"
                        >
                          {relationship.source_id} → {relationship.target_id}
                        </span>
                      ))}
                      {memory.relationships.length > 3 && (
                        <span className="px-2 py-1 bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 text-xs rounded-full">
                          +{memory.relationships.length - 3}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <MemoryCreateModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onSuccess={() => {
          if (currentProject) {
            loadMemories();
          }
        }}
      />

      <MemoryDetailModal
        isOpen={isDetailModalOpen}
        onClose={() => setIsDetailModalOpen(false)}
        memory={currentMemory}
      />
    </div>
  );
};
