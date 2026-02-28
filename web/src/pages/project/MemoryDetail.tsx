import React, { useEffect, useState, useCallback, useRef } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, Link, useNavigate } from 'react-router-dom';

import { formatDateOnly, formatDateTime } from '@/utils/date';

import { EditMemoryModal } from '@/components/project/EditMemoryModal';
import { DeleteConfirmationModal } from '@/components/shared/modals/DeleteConfirmationModal';
import { useLazyMessage } from '@/components/ui/lazyAntd';

import { TaskList } from '../../components/tasks/TaskList';
import { subscribeToTask, TaskStatus } from '../../hooks/useTaskSSE';
import { memoryAPI } from '../../services/api';
import { Memory } from '../../types/memory';

interface ProcessingProgress {
  progress: number;
  message: string;
  taskId: string;
}

export const MemoryDetail: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const { projectId, memoryId } = useParams();
  const navigate = useNavigate();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'content' | 'metadata' | 'history' | 'raw' | 'tasks'>(
    'content'
  );
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState<ProcessingProgress | null>(null);
  const sseCleanupRef = useRef<(() => void) | null>(null);

  // Subscribe to SSE for task updates
  const subscribeToMemoryTask = useCallback((taskId: string) => {
    // Cleanup existing subscription
    if (sseCleanupRef.current) {
      sseCleanupRef.current();
      sseCleanupRef.current = null;
    }

    const cleanup = subscribeToTask(taskId, {
      onProgress: (task: TaskStatus) => {
        setProcessingProgress({
          progress: task.progress,
          message: task.message,
          taskId: task.task_id,
        });
      },
      onCompleted: () => {
        setProcessingProgress(null);
        setMemory((prev) => (prev ? { ...prev, processing_status: 'COMPLETED' } : null));
        sseCleanupRef.current = null;
      },
      onFailed: () => {
        setProcessingProgress(null);
        setMemory((prev) => (prev ? { ...prev, processing_status: 'FAILED' } : null));
        sseCleanupRef.current = null;
      },
      onError: () => {
        sseCleanupRef.current = null;
      },
    });

    sseCleanupRef.current = cleanup;
  }, []);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (sseCleanupRef.current) {
        sseCleanupRef.current();
      }
    };
  }, []);

  useEffect(() => {
    const fetchMemory = async () => {
      if (projectId && memoryId) {
        setIsLoading(true);
        try {
          const data = await memoryAPI.get(projectId, memoryId);
          setMemory(data);
          // If memory is processing and has task_id, subscribe to SSE
          if (
            (data.processing_status === 'PENDING' || data.processing_status === 'PROCESSING') &&
            data.task_id
          ) {
            subscribeToMemoryTask(data.task_id);
          }
        } catch (error) {
          console.error('Failed to fetch memory:', error);
        } finally {
          setIsLoading(false);
        }
      }
    };
    fetchMemory();
  }, [projectId, memoryId, subscribeToMemoryTask]);

  if (!projectId || !memoryId) {
    return (
      <div className="p-8 text-center text-slate-500">
        {t('project.memories.detail.invalid_params')}
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-8 text-center text-slate-500">{t('project.memories.detail.loading')}</div>
    );
  }

  if (!memory) {
    return (
      <div className="p-8 text-center text-slate-500">{t('project.memories.detail.not_found')}</div>
    );
  }

  const refreshMemory = async () => {
    if (projectId && memoryId) {
      try {
        const data = await memoryAPI.get(projectId, memoryId);
        setMemory(data);
      } catch (error) {
        console.error('Failed to refresh memory:', error);
      }
    }
  };

  const handleDelete = async () => {
    if (!projectId || !memoryId) return;

    setIsDeleting(true);
    try {
      await memoryAPI.delete(projectId, memoryId);
      navigate(`/project/${projectId}/memories`);
    } catch (error) {
      console.error('Failed to delete memory:', error);
      alert(t('project.memories.detail.delete_failed'));
      setIsDeleting(false);
      setDeleteModalOpen(false);
    }
  };

  const handleReprocess = async () => {
    if (!projectId || !memoryId) return;
    setIsReprocessing(true);
    try {
      const response = await memoryAPI.reprocess(projectId, memoryId);
      // Update memory data to show pending status
      setMemory((prev) =>
        prev ? { ...prev, processing_status: 'PENDING', task_id: response.task_id } : null
      );
      // Subscribe to SSE for real-time updates
      if (response.task_id) {
        subscribeToMemoryTask(response.task_id);
      }
    } catch (error) {
      console.error('Failed to reprocess:', error);
      message?.error(
        t(
          'project.memories.errors.reprocessFailed',
          'Failed to start processing. Please try again.'
        )
      );
    } finally {
      setIsReprocessing(false);
    }
  };

  return (
    <div className="flex h-full overflow-hidden">
      {deleteModalOpen && (
        <DeleteConfirmationModal
          isOpen={deleteModalOpen}
          onClose={() => {
            setDeleteModalOpen(false);
          }}
          onConfirm={handleDelete}
          title={t('project.memories.delete.title')}
          message={t('project.memories.delete.confirmation')}
          isDeleting={isDeleting}
        />
      )}
      {editModalOpen && (
        <EditMemoryModal
          isOpen={editModalOpen}
          onClose={() => {
            setEditModalOpen(false);
          }}
          memory={memory}
          onUpdate={refreshMemory}
          projectId={projectId}
        />
      )}
      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        {/* Top Navigation Bar (Breadcrumbs + Toolbar) */}
        <header className="h-16 border-b border-slate-200 dark:border-slate-800 bg-surface-light/80 dark:bg-surface-dark/80 backdrop-blur-md flex items-center justify-between px-6 z-10 sticky top-0">
          {/* Breadcrumbs */}
          <div className="flex items-center gap-2 overflow-hidden whitespace-nowrap">
            <Link
              to={`/project/${projectId}`}
              className="text-slate-500 hover:text-primary text-sm font-medium transition-colors"
            >
              {t('common.project')}
            </Link>
            <span className="text-slate-400 text-sm">/</span>
            <Link
              to={`/project/${projectId}/memories`}
              className="text-slate-500 hover:text-primary text-sm font-medium transition-colors"
            >
              {t('project.memories.title')}
            </Link>
            <span className="text-slate-400 text-sm">/</span>
            <div className="flex items-center gap-2">
              <span className="text-slate-900 dark:text-white text-sm font-medium truncate max-w-[200px]">
                {memory.title || t('common.untitled')}
              </span>
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                  memory.processing_status === 'FAILED'
                    ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                    : memory.processing_status === 'COMPLETED'
                      ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                      : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400'
                }`}
              >
                {memory.processing_status || t('common.status.pending')}
              </span>
            </div>
          </div>
          {/* Toolbar Actions */}
          <div className="flex items-center gap-1">
            <button
              onClick={handleReprocess}
              disabled={
                isReprocessing ||
                memory.processing_status === 'PROCESSING' ||
                memory.processing_status === 'PENDING'
              }
              className={`p-2 rounded-lg transition-all flex items-center gap-1 ${
                isReprocessing ||
                memory.processing_status === 'PROCESSING' ||
                memory.processing_status === 'PENDING'
                  ? 'text-slate-300 dark:text-slate-600 cursor-not-allowed'
                  : 'text-slate-500 hover:text-primary hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
              }`}
              title={t('project.memories.actions.reprocess') || 'Reprocess'}
            >
              <span
                className={`material-symbols-outlined text-[20px] ${isReprocessing ? 'animate-spin' : ''}`}
              >
                {isReprocessing ? 'progress_activity' : 'refresh'}
              </span>
            </button>
            <button
              onClick={() => {
                setEditModalOpen(true);
              }}
              className="p-2 text-slate-500 hover:text-primary hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 rounded-lg transition-all"
              title="Edit"
            >
              <span className="material-symbols-outlined text-[20px]">edit</span>
            </button>
            <button
              onClick={() => {
                setDeleteModalOpen(true);
              }}
              className="p-2 text-slate-500 hover:text-red-600 hover:bg-red-50 dark:text-slate-400 dark:hover:bg-red-900/20 dark:hover:text-red-400 rounded-lg transition-all"
              title="Delete"
            >
              <span className="material-symbols-outlined text-[20px]">delete</span>
            </button>
            <div className="w-px h-6 bg-slate-200 dark:bg-slate-700 mx-1"></div>
            <button
              className="p-2 text-slate-500 hover:text-primary hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 rounded-lg transition-all"
              title="Share"
            >
              <span className="material-symbols-outlined text-[20px]">share</span>
            </button>
            <button
              className="p-2 text-slate-500 hover:text-primary hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 rounded-lg transition-all"
              title="Export"
            >
              <span className="material-symbols-outlined text-[20px]">download</span>
            </button>
          </div>
        </header>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto bg-background-light dark:bg-background-dark">
          <div className="max-w-5xl mx-auto p-6 md:p-8 flex flex-col gap-6">
            {/* Memory Card */}
            <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 overflow-hidden">
              {/* Profile Header Section */}
              <div className="p-6 md:p-8 pb-0">
                <div className="flex flex-col md:flex-row gap-6 items-start md:items-center justify-between">
                  <div className="flex gap-5 items-center">
                    <div className="relative">
                      <div className="bg-center bg-no-repeat bg-cover rounded-full h-16 w-16 md:h-20 md:w-20 ring-4 ring-slate-50 dark:ring-slate-800 shadow-sm bg-slate-200 flex items-center justify-center text-slate-400">
                        <span className="material-symbols-outlined text-3xl">description</span>
                      </div>
                      <div className="absolute -bottom-1 -right-1 bg-white dark:bg-slate-900 rounded-full p-1 shadow-sm border border-slate-100 dark:border-slate-700">
                        <div
                          className={`rounded-full h-3 w-3 ${memory.status === 'DISABLED' ? 'bg-red-500' : 'bg-green-500'}`}
                          title={
                            memory.status === 'DISABLED'
                              ? t('common.status.unavailable')
                              : t('common.status.available')
                          }
                        ></div>
                      </div>
                    </div>
                    <div className="flex flex-col justify-center gap-1">
                      <h1 className="text-slate-900 dark:text-white text-2xl md:text-3xl font-bold leading-tight tracking-tight">
                        {memory.title || t('common.untitled')}
                      </h1>
                      <p className="text-slate-500 dark:text-slate-400 text-sm md:text-base font-normal flex items-center gap-2 flex-wrap">
                        <span>
                          {t('project.memories.detail.type')}:{' '}
                          <span className="text-slate-900 dark:text-slate-200 font-medium capitalize">
                            {memory.content_type || t('common.unknown')}
                          </span>
                        </span>
                        <span className="w-1 h-1 bg-slate-300 rounded-full"></span>
                        <span>{formatDateOnly(memory.created_at)}</span>
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      setEditModalOpen(true);
                    }}
                    className="bg-primary hover:bg-primary-dark text-white px-4 py-2 rounded-lg font-medium text-sm flex items-center gap-2 transition-colors shadow-sm shadow-primary/20"
                  >
                    <span className="material-symbols-outlined text-[18px]">edit_note</span>
                    {t('project.memories.detail.edit_memory')}
                  </button>
                </div>
              </div>

              {/* Processing Progress Card */}
              {(processingProgress ||
                memory.processing_status === 'PENDING' ||
                memory.processing_status === 'PROCESSING') && (
                <div className="mx-6 md:mx-8 mt-6 rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/20 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="rounded-full bg-indigo-100 dark:bg-indigo-900/50 p-2">
                        <span className="material-symbols-outlined text-indigo-600 dark:text-indigo-400 text-[20px] animate-spin">
                          progress_activity
                        </span>
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                          {t('project.memories.detail.processing') || 'Processing Memory'}
                        </h3>
                        <p className="text-xs text-slate-600 dark:text-slate-400">
                          {processingProgress?.message ||
                            t('project.memories.detail.extracting_knowledge') ||
                            'Extracting knowledge...'}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-bold text-indigo-600 dark:text-indigo-400">
                        {processingProgress?.progress ?? 0}%
                      </div>
                    </div>
                  </div>
                  {/* Progress Bar */}
                  <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2 overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300 ease-out"
                      style={{ width: `${processingProgress?.progress ?? 0}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div className="mt-8 px-6 md:px-8 border-b border-slate-200 dark:border-slate-800">
                <div className="flex gap-8 overflow-x-auto">
                  <button
                    onClick={() => {
                      setActiveTab('content');
                    }}
                    className={`relative flex items-center justify-center pb-4 font-semibold text-sm tracking-wide transition-colors ${
                      activeTab === 'content'
                        ? 'text-primary border-b-2 border-primary'
                        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
                  >
                    {t('project.memories.detail.tabs.content')}
                  </button>
                  <button
                    onClick={() => {
                      setActiveTab('metadata');
                    }}
                    className={`relative flex items-center justify-center pb-4 font-semibold text-sm tracking-wide transition-colors ${
                      activeTab === 'metadata'
                        ? 'text-primary border-b-2 border-primary'
                        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
                  >
                    {t('project.memories.detail.tabs.metadata')}
                  </button>
                  <button
                    onClick={() => {
                      setActiveTab('raw');
                    }}
                    className={`relative flex items-center justify-center pb-4 font-semibold text-sm tracking-wide transition-colors ${
                      activeTab === 'raw'
                        ? 'text-primary border-b-2 border-primary'
                        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
                  >
                    {t('project.memories.detail.tabs.raw')}
                  </button>
                  <button
                    onClick={() => {
                      setActiveTab('tasks');
                    }}
                    className={`relative flex items-center justify-center pb-4 font-semibold text-sm tracking-wide transition-colors ${
                      activeTab === 'tasks'
                        ? 'text-primary border-b-2 border-primary'
                        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                    }`}
                  >
                    {t('project.memories.detail.tabs.tasks')}
                  </button>
                </div>
              </div>
              {/* Content Body */}
              <div className="p-6 md:p-8 text-slate-800 dark:text-slate-200 leading-relaxed text-base md:text-lg min-h-[300px]">
                {activeTab === 'content' && (
                  <div className="prose dark:prose-invert max-w-none whitespace-pre-wrap">
                    {memory.content || t('project.memories.detail.no_content')}
                  </div>
                )}
                {activeTab === 'metadata' && (
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <div className="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg">
                      <span className="block text-xs font-bold text-slate-500 uppercase mb-1">
                        {t('project.memories.detail.metadata.id')}
                      </span>
                      <span className="font-mono break-all">{memory.id}</span>
                    </div>
                    <div className="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg">
                      <span className="block text-xs font-bold text-slate-500 uppercase mb-1">
                        {t('project.memories.detail.type')}
                      </span>
                      <span className="capitalize">{memory.content_type}</span>
                    </div>
                    <div className="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg col-span-2">
                      <span className="block text-xs font-bold text-slate-500 uppercase mb-1">
                        {t('project.memories.detail.metadata.custom')}
                      </span>
                      <pre className="text-xs font-mono overflow-auto">
                        {JSON.stringify(memory.metadata || {}, null, 2)}
                      </pre>
                    </div>
                  </div>
                )}
                {activeTab === 'raw' && (
                  <div className="bg-slate-900 text-slate-200 p-4 rounded-lg font-mono text-xs overflow-auto">
                    <pre>{JSON.stringify(memory, null, 2)}</pre>
                  </div>
                )}
                {activeTab === 'tasks' && (
                  <TaskList entityId={memoryId} entityType="memory" embedded />
                )}
              </div>
              {/* Footer / Activity Snippet */}
              <div className="bg-slate-50 dark:bg-slate-800/50 px-6 py-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-[16px]">history</span>
                  {t('common.created_at')} {formatDateTime(memory.created_at)}
                </div>
                <div>ID: {memory.id ? memory.id.slice(0, 12) : 'N/A'}...</div>
              </div>
            </div>
            {/* Spacer for bottom scroll */}
            <div className="h-10"></div>
          </div>
        </div>
      </main>

      {/* Right Sidebar: Context */}
      <aside className="w-80 bg-surface-light dark:bg-surface-dark border-l border-slate-200 dark:border-slate-800 hidden xl:flex flex-col flex-shrink-0 z-10">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[18px]">hub</span>
            {t('project.memories.detail.sidebar.knowledge_context')}
          </h2>
        </div>
        <div className="overflow-y-auto flex-1 p-5 flex flex-col gap-6">
          {/* Tags */}
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {t('project.memories.detail.sidebar.tags')}
            </h3>
            <div className="flex flex-wrap gap-2">
              {memory.metadata?.tags?.map((tag: string) => (
                <span
                  key={tag}
                  className="px-2.5 py-1 rounded-md text-xs font-medium bg-slate-100 text-slate-600 hover:bg-slate-200 cursor-pointer transition-colors dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                >
                  #{tag}
                </span>
              )) || (
                <span className="text-xs text-slate-500">
                  {t('project.memories.detail.sidebar.no_tags')}
                </span>
              )}
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
};
