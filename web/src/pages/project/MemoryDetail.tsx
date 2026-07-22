import React, { useEffect, useState, useCallback, useRef } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';

import {
  Database,
  Download,
  FileEdit,
  FileText,
  GitBranch,
  History,
  Loader2,
  Network,
  Pencil,
  RefreshCw,
  Share2,
  Tag,
  Trash2,
} from 'lucide-react';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { formatDateOnly, formatDateTime } from '@/utils/date';

import { EditMemoryModal } from '@/components/project/EditMemoryModal';
import { DeleteConfirmationModal } from '@/components/shared/modals/DeleteConfirmationModal';
import { useLazyMessage } from '@/components/ui/lazyAntd';

import { TaskList } from '../../components/tasks/TaskList';
import { subscribeToTask, TaskStatus } from '../../hooks/useTaskSSE';
import { memoryAPI } from '../../services/api';
import { Memory } from '../../types/memory';
import { logger } from '../../utils/logger';

interface ProcessingProgress {
  progress: number;
  message: string;
  taskId: string;
}

function getMemoryMetadataTags(metadata: Record<string, unknown>): string[] {
  const tags = metadata.tags;
  return Array.isArray(tags) ? tags.filter((tag): tag is string => typeof tag === 'string') : [];
}

function buildMemoryExportFilename(memory: Memory): string {
  const baseName = memory.title || memory.id || 'memory';
  const safeName = baseName
    .trim()
    .replace(/[^\w.-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `${safeName || 'memory'}.json`;
}

function getProcessingStatusClass(status: Memory['processing_status']): string {
  if (status === 'FAILED') {
    return 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300';
  }

  if (status === 'COMPLETED') {
    return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300';
  }

  return 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-300';
}

export const MemoryDetail: React.FC = () => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const { projectId, memoryId } = useParams();
  const navigate = useNavigate();
  const { projectBasePath } = useProjectBasePath();
  const [memory, setMemory] = useState<Memory | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  const initialTab =
    tabParam === 'metadata' || tabParam === 'raw' || tabParam === 'tasks' ? tabParam : 'content';
  const [activeTab, setActiveTab] = useState<'content' | 'metadata' | 'raw' | 'tasks'>(initialTab);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [processingProgress, setProcessingProgress] = useState<ProcessingProgress | null>(null);
  const sseCleanupRef = useRef<(() => void) | null>(null);
  const fetchRequestSeqRef = useRef(0);

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
    if (!projectId || !memoryId) {
      return;
    }

    const requestSeq = fetchRequestSeqRef.current + 1;
    fetchRequestSeqRef.current = requestSeq;

    const fetchMemory = async () => {
      setIsLoading(true);
      setLoadError(null);
      try {
        const data = await memoryAPI.get(projectId, memoryId);
        if (fetchRequestSeqRef.current !== requestSeq) {
          return;
        }

        setMemory(data);
        // If memory is processing and has task_id, subscribe to SSE
        if (
          (data.processing_status === 'PENDING' || data.processing_status === 'PROCESSING') &&
          data.task_id
        ) {
          subscribeToMemoryTask(data.task_id);
        }
      } catch (error) {
        if (fetchRequestSeqRef.current === requestSeq) {
          logger.error('[MemoryDetail] Failed to fetch memory:', error);
          setLoadError(t('project.memories.detail.load_failed', 'Failed to load this memory.'));
        }
      } finally {
        if (fetchRequestSeqRef.current === requestSeq) {
          setIsLoading(false);
        }
      }
    };
    void fetchMemory();

    return () => {
      if (fetchRequestSeqRef.current === requestSeq) {
        fetchRequestSeqRef.current += 1;
      }
    };
  }, [projectId, memoryId, subscribeToMemoryTask, reloadToken, t]);

  if (!projectId || !memoryId) {
    return (
      <div className="p-8 text-center text-slate-500">
        {t('project.memories.detail.invalid_params')}
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-8 text-center text-slate-500" role="status">
        {t('project.memories.detail.loading')}
      </div>
    );
  }

  if (loadError && !memory) {
    return (
      <div className="flex flex-col items-center gap-3 p-8 text-center" role="alert">
        <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
        <button
          type="button"
          onClick={() => {
            setReloadToken((value) => value + 1);
          }}
          className="inline-flex h-9 items-center rounded-md bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus-visible:ring-slate-50/20"
        >
          {t('common.retry', 'Retry')}
        </button>
      </div>
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
        logger.error('[MemoryDetail] Failed to refresh memory:', error);
      }
    }
  };

  const handleDelete = async () => {
    if (!projectId || !memoryId) return;

    setIsDeleting(true);
    try {
      await memoryAPI.delete(projectId, memoryId);
      void navigate(`${projectBasePath}/memories`);
    } catch (error) {
      logger.error('[MemoryDetail] Failed to delete memory:', error);
      message?.error(t('project.memories.detail.delete_failed'));
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
      logger.error('[MemoryDetail] Failed to reprocess:', error);
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

  const handleShare = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      message?.success(t('memory.detail.linkCopied'));
    } catch (error) {
      console.error('Failed to copy memory link:', error);
      message?.error(t('memory.detail.linkCopyFailed'));
    }
  };

  const handleExport = () => {
    try {
      const blob = new Blob([JSON.stringify(memory, null, 2)], {
        type: 'application/json;charset=utf-8',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = buildMemoryExportFilename(memory);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      message?.success(t('memory.detail.exportSuccess', { defaultValue: 'Memory exported' }));
    } catch (error) {
      logger.error('[MemoryDetail] Failed to export memory:', error);
      message?.error(t('memory.detail.exportFailed', { defaultValue: 'Failed to export memory' }));
    }
  };

  const handleTabChange = (tabId: typeof activeTab) => {
    setActiveTab(tabId);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (tabId === 'content') {
          next.delete('tab');
        } else {
          next.set('tab', tabId);
        }
        return next;
      },
      { replace: true }
    );
  };

  const metadataTags = getMemoryMetadataTags(memory.metadata);
  const tabs: Array<{ id: typeof activeTab; label: string }> = [
    { id: 'content', label: t('project.memories.detail.tabs.content') },
    { id: 'metadata', label: t('project.memories.detail.tabs.metadata') },
    { id: 'raw', label: t('project.memories.detail.tabs.raw') },
    { id: 'tasks', label: t('project.memories.detail.tabs.tasks') },
  ];

  return (
    <div className="flex h-full overflow-hidden">
      {deleteModalOpen && (
        <DeleteConfirmationModal
          isOpen={deleteModalOpen}
          onClose={() => {
            setDeleteModalOpen(false);
          }}
          onConfirm={() => {
            void handleDelete();
          }}
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
          onUpdate={() => {
            void refreshMemory();
          }}
          projectId={projectId}
        />
      )}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        <header className="sticky top-0 z-10 flex min-h-16 items-center justify-between gap-4 border-b border-slate-200 bg-white px-5 dark:border-slate-800 dark:bg-surface-dark">
          <div className="flex min-w-0 items-center gap-2 overflow-hidden whitespace-nowrap">
            <Link
              to={projectBasePath}
              className="text-sm font-medium text-slate-500 transition-colors hover:text-slate-950 dark:text-slate-400 dark:hover:text-white"
            >
              {t('common.project')}
            </Link>
            <span className="text-slate-400 text-sm">/</span>
            <Link
              to={`${projectBasePath}/memories`}
              className="text-sm font-medium text-slate-500 transition-colors hover:text-slate-950 dark:text-slate-400 dark:hover:text-white"
            >
              {t('project.memories.title')}
            </Link>
            <span className="text-slate-400 text-sm">/</span>
            <div className="flex min-w-0 items-center gap-2">
              <span className="max-w-[18rem] truncate text-sm font-medium text-slate-950 dark:text-white">
                {memory.title || t('common.untitled')}
              </span>
              <span
                className={`h-2 w-2 rounded-full ${
                  memory.processing_status === 'FAILED'
                    ? 'bg-red-500'
                    : memory.processing_status === 'COMPLETED'
                      ? 'bg-emerald-500'
                      : 'bg-amber-500'
                }`}
                title={memory.processing_status}
              />
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => {
                void handleReprocess();
              }}
              disabled={
                isReprocessing ||
                memory.processing_status === 'PROCESSING' ||
                memory.processing_status === 'PENDING'
              }
              aria-label={t('project.memories.actions.reprocess', {
                defaultValue: 'Reprocess',
              })}
              className={`p-2 rounded-lg transition-[color,background-color,border-color,box-shadow,opacity,transform] flex items-center gap-1 ${
                isReprocessing ||
                memory.processing_status === 'PROCESSING' ||
                memory.processing_status === 'PENDING'
                  ? 'text-slate-300 dark:text-slate-600 cursor-not-allowed'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white'
              }`}
              title={t('project.memories.actions.reprocess', {
                defaultValue: 'Reprocess',
              })}
            >
              {isReprocessing ? (
                <Loader2 size={16} className="animate-spin motion-reduce:animate-none" />
              ) : (
                <RefreshCw size={16} />
              )}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditModalOpen(true);
              }}
              aria-label={t('common.edit', 'Edit')}
              className="rounded-lg p-2 text-slate-500 transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:bg-slate-100 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
              title={t('common.edit', 'Edit')}
            >
              <Pencil size={20} />
            </button>
            <button
              type="button"
              onClick={() => {
                setDeleteModalOpen(true);
              }}
              aria-label={t('common.delete', 'Delete')}
              className="rounded-lg p-2 text-slate-500 transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:bg-red-50 hover:text-red-600 dark:text-slate-400 dark:hover:bg-red-900/20 dark:hover:text-red-400"
              title={t('common.delete', 'Delete')}
            >
              <Trash2 size={20} />
            </button>
            <div className="w-px h-6 bg-slate-200 dark:bg-slate-700 mx-1"></div>
            <button
              type="button"
              aria-label={t('memory.detail.shareAria')}
              onClick={() => {
                void handleShare();
              }}
              className="rounded-lg p-2 text-slate-500 transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:bg-slate-100 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
              title={t('memory.detail.shareTitle', 'Share')}
            >
              <Share2 size={20} />
            </button>
            <button
              type="button"
              aria-label={t('memory.detail.downloadAria')}
              onClick={handleExport}
              className="rounded-lg p-2 text-slate-500 transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:bg-slate-100 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
              title={t('memory.detail.exportTitle', 'Export')}
            >
              <Download size={20} />
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto bg-slate-50 dark:bg-background-dark">
          <div className="mx-auto grid max-w-7xl gap-4 p-4 md:gap-5 md:p-5 2xl:grid-cols-[minmax(0,1fr)_22rem]">
            <section className="min-w-0 overflow-hidden rounded-md border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)] dark:border-slate-800 dark:bg-surface-dark">
              <div className="border-b border-slate-200 px-4 py-5 dark:border-slate-800 md:px-6">
                <div className="flex min-w-0 flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
                  <div className="flex min-w-0 gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
                      <FileText size={22} />
                    </div>
                    <div className="min-w-0">
                      <div className="mb-3 flex flex-wrap items-center gap-2">
                        <span
                          className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase ${getProcessingStatusClass(memory.processing_status)}`}
                        >
                          {memory.processing_status}
                        </span>
                        <span
                          className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase ${
                            memory.status === 'DISABLED'
                              ? 'border-red-200 bg-white text-red-700 dark:border-red-900/60 dark:bg-slate-950 dark:text-red-300'
                              : 'border-slate-200 bg-white text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200'
                          }`}
                        >
                          {memory.status === 'DISABLED'
                            ? t('common.status.unavailable')
                            : t('common.status.available')}
                        </span>
                      </div>
                      <h1 className="max-w-4xl break-words text-2xl font-semibold leading-tight text-slate-950 dark:text-white md:text-3xl">
                        {memory.title || t('common.untitled')}
                      </h1>
                      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-500 dark:text-slate-400">
                        <span className="capitalize">
                          {t('project.memories.detail.type')}: {memory.content_type}
                        </span>
                        <span>{formatDateOnly(memory.created_at)}</span>
                        <span>
                          {t('memory.detail.version', { defaultValue: 'Version' })} {memory.version}
                        </span>
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setEditModalOpen(true);
                    }}
                    className="inline-flex h-9 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md bg-slate-950 px-3.5 text-sm font-medium text-white transition-colors hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-200 max-lg:w-full"
                  >
                    <FileEdit size={16} />
                    {t('project.memories.detail.edit_memory')}
                  </button>
                </div>

                <div className="mt-5 grid grid-cols-2 border border-slate-200 dark:border-slate-800 lg:grid-cols-4">
                  <div className="border-r border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-500">
                      <Database size={14} />
                      {t('project.memories.detail.type')}
                    </div>
                    <div className="mt-2 text-sm font-semibold capitalize text-slate-950 dark:text-white">
                      {memory.content_type}
                    </div>
                  </div>
                  <div className="border-r border-slate-200 p-4 dark:border-slate-800">
                    <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-500">
                      <Network size={14} />
                      {t('memory.detail.entities', { defaultValue: 'Entities' })}
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950 dark:text-white">
                      {memory.entities.length}
                    </div>
                  </div>
                  <div className="border-r border-t border-slate-200 p-4 dark:border-slate-800 lg:border-t-0">
                    <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-500">
                      <GitBranch size={14} />
                      {t('memory.detail.relationships', { defaultValue: 'Relations' })}
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950 dark:text-white">
                      {memory.relationships.length}
                    </div>
                  </div>
                  <div className="border-t border-slate-200 p-4 dark:border-slate-800 lg:border-t-0">
                    <div className="flex items-center gap-2 text-xs font-medium uppercase text-slate-500">
                      <History size={14} />
                      {t('memory.detail.created', { defaultValue: 'Created' })}
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-950 dark:text-white">
                      {formatDateOnly(memory.created_at)}
                    </div>
                  </div>
                </div>
              </div>

              {(processingProgress ||
                memory.processing_status === 'PENDING' ||
                memory.processing_status === 'PROCESSING') && (
                <div className="border-b border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/60 md:px-6">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="rounded-md border border-slate-200 bg-white p-2 dark:border-slate-700 dark:bg-slate-950">
                        <Loader2
                          size={20}
                          className="animate-spin text-slate-700 motion-reduce:animate-none dark:text-slate-200"
                        />
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                          {t('project.memories.detail.processing', 'Processing Memory')}
                        </h3>
                        <p className="text-xs text-slate-600 dark:text-slate-400">
                          {processingProgress?.message ||
                            t(
                              'project.memories.detail.extracting_knowledge',
                              'Extracting knowledge…'
                            )}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-bold tabular-nums text-slate-950 dark:text-white">
                        {processingProgress?.progress ?? 0}%
                      </div>
                    </div>
                  </div>
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
                    role="progressbar"
                    aria-valuenow={processingProgress?.progress ?? 0}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={t('project.memories.detail.processing', 'Processing Memory')}
                  >
                    <div
                      className="h-full bg-slate-950 transition-[width] duration-300 ease-out motion-reduce:transition-none dark:bg-white"
                      style={{ width: `${String(processingProgress?.progress ?? 0)}%` }}
                    />
                  </div>
                </div>
              )}

              <div className="border-b border-slate-200 px-4 dark:border-slate-800 md:px-6">
                <div className="flex gap-1 overflow-x-auto py-3" role="tablist">
                  {tabs.map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={activeTab === tab.id}
                      onClick={() => {
                        handleTabChange(tab.id);
                      }}
                      className={`h-8 rounded-md px-3 text-sm font-medium transition-colors ${
                        activeTab === tab.id
                          ? 'bg-slate-950 text-white dark:bg-white dark:text-slate-950'
                          : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>

              <div
                className="min-h-[360px] p-4 text-base leading-7 text-slate-800 dark:text-slate-200 md:p-6"
                role="tabpanel"
              >
                {activeTab === 'content' && (
                  <div className="max-w-4xl whitespace-pre-wrap text-[15px] leading-7">
                    {memory.content || t('project.memories.detail.no_content')}
                  </div>
                )}
                {activeTab === 'metadata' && (
                  <div className="grid gap-3 text-sm md:grid-cols-2">
                    <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900">
                      <span className="mb-1 block text-xs font-semibold uppercase text-slate-500">
                        {t('project.memories.detail.metadata.id')}
                      </span>
                      <span className="break-all font-mono text-slate-900 dark:text-slate-100">
                        {memory.id}
                      </span>
                    </div>
                    <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900">
                      <span className="mb-1 block text-xs font-semibold uppercase text-slate-500">
                        {t('project.memories.detail.type')}
                      </span>
                      <span className="capitalize text-slate-900 dark:text-slate-100">
                        {memory.content_type}
                      </span>
                    </div>
                    <div className="rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900 md:col-span-2">
                      <span className="mb-1 block text-xs font-semibold uppercase text-slate-500">
                        {t('project.memories.detail.metadata.custom')}
                      </span>
                      <pre className="overflow-auto text-xs font-mono leading-6 text-slate-800 dark:text-slate-200">
                        {JSON.stringify(memory.metadata, null, 2)}
                      </pre>
                    </div>
                  </div>
                )}
                {activeTab === 'raw' && (
                  <div className="overflow-auto rounded-md bg-slate-950 p-4 font-mono text-xs leading-6 text-slate-200">
                    <pre>{JSON.stringify(memory, null, 2)}</pre>
                  </div>
                )}
                {activeTab === 'tasks' && (
                  <TaskList entityId={memoryId} entityType="memory" embedded />
                )}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-4 py-4 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400 md:px-6">
                <div className="flex items-center gap-2">
                  <History size={16} />
                  {t('common.created_at')} {formatDateTime(memory.created_at)}
                </div>
                <div>ID: {memory.id.slice(0, 12)}…</div>
              </div>
            </section>

            <aside className="grid gap-4 md:grid-cols-2 2xl:sticky 2xl:top-20 2xl:flex 2xl:flex-col 2xl:self-start">
              <section className="rounded-md border border-slate-200 bg-white dark:border-slate-800 dark:bg-surface-dark">
                <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
                  <h2 className="flex items-center gap-2 text-xs font-semibold uppercase text-slate-700 dark:text-slate-200">
                    <Network size={15} />
                    {t('project.memories.detail.sidebar.knowledge_context')}
                  </h2>
                </div>
                <div className="space-y-5 p-4">
                  <div>
                    <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-slate-500">
                      <Tag size={14} />
                      {t('project.memories.detail.sidebar.tags')}
                    </h3>
                    <div className="flex flex-wrap gap-2">
                      {metadataTags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                        >
                          #{tag}
                        </span>
                      ))}
                      {metadataTags.length === 0 && (
                        <span className="text-xs text-slate-500">
                          {t('project.memories.detail.sidebar.no_tags')}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 divide-x divide-slate-200 border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                    <div className="p-3">
                      <div className="text-xs text-slate-500">
                        {t('memory.detail.entities', { defaultValue: 'Entities' })}
                      </div>
                      <div className="mt-1 text-2xl font-semibold text-slate-950 dark:text-white">
                        {memory.entities.length}
                      </div>
                    </div>
                    <div className="p-3">
                      <div className="text-xs text-slate-500">
                        {t('memory.detail.relationships', { defaultValue: 'Relations' })}
                      </div>
                      <div className="mt-1 text-2xl font-semibold text-slate-950 dark:text-white">
                        {memory.relationships.length}
                      </div>
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-md border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-surface-dark">
                <h2 className="mb-4 text-xs font-semibold uppercase text-slate-500">
                  {t('memory.detail.record', { defaultValue: 'Record' })}
                </h2>
                <dl className="space-y-3">
                  <div>
                    <dt className="text-xs text-slate-500">ID</dt>
                    <dd className="mt-1 break-all font-mono text-xs text-slate-800 dark:text-slate-200">
                      {memory.id}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-xs text-slate-500">
                      {t('memory.detail.created', { defaultValue: 'Created' })}
                    </dt>
                    <dd className="text-xs text-slate-800 dark:text-slate-200">
                      {formatDateTime(memory.created_at)}
                    </dd>
                  </div>
                  {memory.updated_at && (
                    <div className="flex justify-between gap-4">
                      <dt className="text-xs text-slate-500">
                        {t('memory.detail.updated', { defaultValue: 'Updated' })}
                      </dt>
                      <dd className="text-xs text-slate-800 dark:text-slate-200">
                        {formatDateTime(memory.updated_at)}
                      </dd>
                    </div>
                  )}
                </dl>
              </section>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
};
