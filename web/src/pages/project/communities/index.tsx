/**
 * CommunitiesList Compound Component
 *
 * Implements the compound component pattern for the CommunitiesList page.
 * Allows flexible composition of sub-components while maintaining shared state.
 */

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  useEffect,
  memo,
} from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { message } from 'antd';
import {
  AlertCircle,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  Clock,
  Info as InfoIcon,
  Loader2,
  RefreshCw,
  Users,
  X,
} from 'lucide-react';

import { formatDateOnly, formatDateTime } from '@/utils/date';

import { VirtualGrid } from '../../../components/common';
import { TaskList } from '../../../components/tasks/TaskList';
import { graphService } from '../../../services/graphService';
import { subscribeToTaskEvents } from '../../../services/taskStream';
import { confirmAction } from '../../../utils/confirmAction';
import { logger } from '../../../utils/logger';

import type { Community, Entity, BackgroundTask } from './types';

// ========================================
// Context
// ========================================

interface CommunitiesListContextValue {
  // State
  communities: Community[];
  selectedCommunity: Community | null;
  members: Entity[];
  loading: boolean;
  error: string | null;
  rebuilding: boolean;
  totalCount: number;
  page: number;
  limit: number;
  currentTask: BackgroundTask | null;

  // Actions
  loadCommunities: () => Promise<void>;
  selectCommunity: (community: Community) => void;
  closeDetail: () => void;
  rebuildCommunities: () => Promise<void>;
  cancelTask: () => Promise<void>;
  setPage: (page: number) => void;
  clearError: () => void;
  dismissTask: () => void;

  // Computed
  totalPages: number;
  hasNextPage: boolean;
  hasPrevPage: boolean;
}

const CommunitiesListContext = createContext<CommunitiesListContextValue | null>(null);

function useCommunitiesListContext(): CommunitiesListContextValue {
  const context = useContext(CommunitiesListContext);
  if (!context) {
    throw Error('CommunitiesList sub-components must be used within CommunitiesList');
  }
  return context;
}

// ========================================
// Structured parsing helpers
// ========================================

type RecordValue = Record<string, unknown>;
type ErrorSource = 'load' | 'rebuild' | 'task' | 'cancel';

interface ErrorState {
  message: string;
  source: ErrorSource;
}

const TASK_STATUS_MAP: Record<string, BackgroundTask['status']> = {
  processing: 'running',
  running: 'running',
  pending: 'pending',
  completed: 'completed',
  failed: 'failed',
  cancelled: 'cancelled',
};

function isRecord(value: unknown): value is RecordValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseEventRecord(rawData: string): RecordValue | null {
  try {
    const data = JSON.parse(rawData) as unknown;
    return isRecord(data) ? data : null;
  } catch (error) {
    logger.error('Failed to parse task event:', error);
    return null;
  }
}

function getStringField(record: RecordValue, field: string): string | undefined {
  const value = record[field];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function getNumberField(record: RecordValue, field: string): number | undefined {
  const value = record[field];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }

  if (!isRecord(error)) {
    return fallback;
  }

  const response = error.response;
  if (isRecord(response)) {
    const data = response.data;
    if (isRecord(data)) {
      const detail = getStringField(data, 'detail');
      if (detail) return detail;
    }
  }

  return getStringField(error, 'message') ?? fallback;
}

function getTaskResult(value: unknown): BackgroundTask['result'] {
  if (!isRecord(value)) return undefined;

  const communitiesCount = getNumberField(value, 'communities_count');
  const edgesCount = getNumberField(value, 'edges_count');

  if (communitiesCount === undefined && edgesCount === undefined) {
    return undefined;
  }

  return {
    communities_count: communitiesCount,
    edges_count: edgesCount,
  };
}

function normalizeTaskStatus(value: unknown): BackgroundTask['status'] {
  if (typeof value !== 'string') return 'pending';
  return TASK_STATUS_MAP[value.toLowerCase()] ?? 'pending';
}

function buildTaskFromRecord(
  record: RecordValue,
  options: {
    status?: BackgroundTask['status'] | undefined;
    taskTypeFallback: string;
    messageFallback: string;
    progressFallback: number;
    createdAtFallback?: string | undefined;
  }
): BackgroundTask {
  return {
    task_id: getStringField(record, 'id') ?? getStringField(record, 'task_id') ?? 'unknown',
    task_type: getStringField(record, 'name') ?? options.taskTypeFallback,
    status: options.status ?? normalizeTaskStatus(record.status),
    created_at:
      getStringField(record, 'created_at') ?? options.createdAtFallback ?? new Date().toISOString(),
    started_at: getStringField(record, 'started_at'),
    completed_at: getStringField(record, 'completed_at'),
    progress: getNumberField(record, 'progress') ?? options.progressFallback,
    message: getStringField(record, 'message') ?? options.messageFallback,
    result: getTaskResult(record.result),
    error: getStringField(record, 'error'),
  };
}

const DEFAULT_COMMUNITY_ICON_CLASS =
  'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900';

const COMMUNITY_ICON_CLASSES = [
  DEFAULT_COMMUNITY_ICON_CLASS,
  'bg-slate-700 text-white dark:bg-slate-200 dark:text-slate-950',
  'bg-slate-600 text-white dark:bg-slate-300 dark:text-slate-950',
  'bg-zinc-700 text-white dark:bg-zinc-200 dark:text-zinc-950',
  'bg-stone-700 text-white dark:bg-stone-200 dark:text-stone-950',
] as const;

function getCommunityIconClass(index: number): string {
  return (
    COMMUNITY_ICON_CLASSES[index % COMMUNITY_ICON_CLASSES.length] ?? DEFAULT_COMMUNITY_ICON_CLASS
  );
}

function formatPercent(value: number): string {
  return `${String(Math.max(0, Math.min(100, value)))}%`;
}

// ========================================
// Root Component
// ========================================

interface CommunitiesListProviderProps {
  children: React.ReactNode;
  projectId?: string | undefined;
  tenantId?: string | undefined;
  limit?: number | undefined;
}

const CommunitiesListProvider: React.FC<CommunitiesListProviderProps> = memo(
  ({ children, projectId: propProjectId, tenantId: propTenantId, limit: propLimit = 20 }) => {
    const { t } = useTranslation();
    const { tenantId: urlTenantId, projectId: urlProjectId } = useParams();
    const tenantId = propTenantId || urlTenantId;
    const projectId = propProjectId || urlProjectId;

    // State
    const [communities, setCommunities] = useState<Community[]>([]);
    const [selectedCommunity, setSelectedCommunity] = useState<Community | null>(null);
    const [members, setMembers] = useState<Entity[]>([]);
    const [loading, setLoading] = useState(true);
    const [errorState, setErrorState] = useState<ErrorState | null>(null);
    const [rebuilding, setRebuilding] = useState(false);
    const [totalCount, setTotalCount] = useState(0);
    const [page, setPage] = useState(0);
    const [currentTask, setCurrentTask] = useState<BackgroundTask | null>(null);

    // Load communities
    const loadCommunities = useCallback(async () => {
      if (!projectId) return;

      setLoading(true);
      setErrorState((current) => (current?.source === 'load' ? null : current));
      try {
        logger.debug('Loading communities...', {
          projectId,
          limit: propLimit,
          offset: page * propLimit,
        });

        const result = await graphService.listCommunities({
          tenant_id: tenantId,
          project_id: projectId,
          min_members: 1,
          limit: propLimit,
          offset: page * propLimit,
        });

        logger.debug('Communities loaded:', {
          count: result.communities.length,
          total: result.total,
        });

        setCommunities(result.communities);
        setTotalCount(result.total || result.communities.length);
      } catch (err: unknown) {
        logger.error('Failed to load communities:', err);
        setErrorState({
          message: getErrorMessage(err, t('project.graph.communities.messages.load_failed')),
          source: 'load',
        });
      } finally {
        setLoading(false);
      }
    }, [tenantId, projectId, page, propLimit, t]);

    // Load members
    const loadMembers = useCallback(async (communityUuid: string) => {
      try {
        const result = await graphService.getCommunityMembers(communityUuid, 100);
        setMembers(result.members);
      } catch (err) {
        logger.error('Failed to load members:', err);
      }
    }, []);

    // Stream task status
    const streamTaskStatus = useCallback(
      (taskId: string) => {
        return subscribeToTaskEvents(taskId, {
          onOpen: () => {
            logger.debug('SSE connection opened');
          },
          onProgress: (event) => {
            const data = parseEventRecord(event.data);
            if (!data) return;

            setCurrentTask(
              buildTaskFromRecord(data, {
                taskTypeFallback: 'rebuild_communities',
                messageFallback: t('project.graph.communities.task.processing'),
                progressFallback: 0,
              })
            );
          },
          onCompleted: (event) => {
            const task = parseEventRecord(event.data);
            if (!task) return;

            setCurrentTask(
              buildTaskFromRecord(task, {
                status: 'completed',
                taskTypeFallback: 'rebuild_communities',
                messageFallback: t('project.graph.communities.task.completed_message'),
                progressFallback: 100,
              })
            );

            setRebuilding(false);
            void loadCommunities();

            setTimeout(() => {
              setCurrentTask(null);
            }, 5000);
          },
          onFailed: (event) => {
            const task = parseEventRecord(event.data);
            if (!task) return;

            const taskError =
              getStringField(task, 'error') ??
              t('project.graph.communities.messages.unknown_error');

            setCurrentTask(
              buildTaskFromRecord(task, {
                status: 'failed',
                taskTypeFallback: 'rebuild_communities',
                messageFallback: t('project.graph.communities.task.failed_message'),
                progressFallback: 0,
              })
            );

            setRebuilding(false);
            setErrorState({
              message: t('project.graph.communities.messages.rebuild_failed_with_error', {
                error: taskError,
              }),
              source: 'task',
            });
          },
          onError: (error) => {
            logger.error('SSE connection error:', error);
            setRebuilding(false);
            setErrorState({
              message: t('project.graph.communities.messages.task_updates_failed'),
              source: 'task',
            });
          },
        });
      },
      [loadCommunities, t]
    );

    // Rebuild communities
    const rebuildCommunities = useCallback(async () => {
      if (
        !(await confirmAction({
          title: t('project.graph.communities.confirm_rebuild'),
          danger: true,
        }))
      ) {
        return;
      }

      setRebuilding(true);
      setErrorState((current) => (current?.source === 'rebuild' ? null : current));

      try {
        logger.debug('Starting community rebuild', { projectId });

        const result = await graphService.rebuildCommunities(true, projectId);

        if (result.task_id) {
          streamTaskStatus(result.task_id);
        } else {
          await loadCommunities();
          void message.success(
            result.message || t('project.graph.communities.messages.rebuild_success')
          );
          setRebuilding(false);
        }
      } catch (err: unknown) {
        logger.error('Failed to rebuild communities:', err);
        const errorMsg = getErrorMessage(
          err,
          t('project.graph.communities.messages.rebuild_start_failed')
        );
        setErrorState({
          message: t('project.graph.communities.messages.rebuild_failed_with_error', {
            error: errorMsg,
          }),
          source: 'rebuild',
        });
        setRebuilding(false);
      }
    }, [projectId, streamTaskStatus, loadCommunities, t]);

    // Cancel task
    const cancelTask = useCallback(async () => {
      if (!currentTask) return;

      try {
        await graphService.cancelTask(currentTask.task_id);
        setCurrentTask(null);
        setRebuilding(false);
        void message.info(t('project.graph.communities.messages.task_cancelled'));
      } catch (err: unknown) {
        logger.error('Failed to cancel task:', err);
        setErrorState({
          message: t('project.graph.communities.messages.task_cancel_failed'),
          source: 'cancel',
        });
      }
    }, [currentTask, t]);

    // Select community
    const selectCommunity = useCallback(
      (community: Community) => {
        setSelectedCommunity(community);
        void loadMembers(community.uuid);
      },
      [loadMembers]
    );

    // Close detail
    const closeDetail = useCallback(() => {
      setSelectedCommunity(null);
      setMembers([]);
    }, []);

    // Clear error
    const clearError = useCallback(() => {
      setErrorState(null);
    }, []);

    // Dismiss task
    const dismissTask = useCallback(() => {
      setCurrentTask(null);
    }, []);

    // Computed values
    const totalPages = useMemo(() => Math.ceil(totalCount / propLimit), [totalCount, propLimit]);
    const hasNextPage = useMemo(
      () => (page + 1) * propLimit < totalCount,
      [page, propLimit, totalCount]
    );
    const hasPrevPage = useMemo(() => page > 0, [page]);

    // Initial load
    useEffect(() => {
      void loadCommunities();
    }, [loadCommunities]);

    const contextValue = useMemo<CommunitiesListContextValue>(
      () => ({
        communities,
        selectedCommunity,
        members,
        loading,
        error: errorState?.message ?? null,
        rebuilding,
        totalCount,
        page,
        limit: propLimit,
        currentTask,
        loadCommunities,
        selectCommunity,
        closeDetail,
        rebuildCommunities,
        cancelTask,
        setPage,
        clearError,
        dismissTask,
        totalPages,
        hasNextPage,
        hasPrevPage,
      }),
      [
        communities,
        selectedCommunity,
        members,
        loading,
        errorState,
        rebuilding,
        totalCount,
        page,
        propLimit,
        currentTask,
        loadCommunities,
        selectCommunity,
        closeDetail,
        rebuildCommunities,
        cancelTask,
        clearError,
        dismissTask,
        totalPages,
        hasNextPage,
        hasPrevPage,
      ]
    );

    return (
      <CommunitiesListContext.Provider value={contextValue}>
        <div data-testid="communities-list-root" className="min-w-0 space-y-6">
          {children}
        </div>
      </CommunitiesListContext.Provider>
    );
  }
);

CommunitiesListProvider.displayName = 'CommunitiesListProvider';

// ========================================
// Sub-Components
// ========================================

const Header: React.FC = memo(() => {
  const { t } = useTranslation();
  const { rebuildCommunities, loadCommunities, loading, rebuilding } = useCommunitiesListContext();

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('project.graph.communities.title')}
        </h1>
        <p className="mt-1 break-words text-slate-600 dark:text-slate-400">
          {t('project.graph.communities.subtitle')}
        </p>
      </div>
      <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
        <button
          type="button"
          onClick={() => {
            void rebuildCommunities();
          }}
          disabled={rebuilding}
          className="flex items-center justify-center gap-2 rounded-md bg-slate-950 px-4 py-2 text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-slate-200"
        >
          <AlertCircle size={16} />
          {rebuilding
            ? t('project.graph.communities.rebuilding')
            : t('project.graph.communities.rebuild')}
        </button>
        <button
          type="button"
          onClick={() => {
            void loadCommunities();
          }}
          disabled={loading}
          className="flex items-center justify-center gap-2 rounded-md bg-slate-100 px-4 py-2 text-slate-700 transition-colors hover:bg-slate-200 disabled:opacity-50 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
        >
          <RefreshCw size={16} />
          {t('project.graph.communities.refresh')}
        </button>
      </div>
    </div>
  );
});
Header.displayName = 'CommunitiesList.Header';

const Stats: React.FC = memo(() => {
  const { t } = useTranslation();
  const { communities, totalCount, page, limit } = useCommunitiesListContext();

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-6 text-sm">
          <span className="text-slate-600 dark:text-slate-400">
            {t('project.graph.communities.stats.showing', {
              count: communities.length,
              total: totalCount.toLocaleString(),
            })}
          </span>
        </div>
        {totalCount > limit && (
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {t('project.graph.communities.stats.page', {
              current: page + 1,
              total: Math.ceil(totalCount / limit),
            })}
          </div>
        )}
      </div>
    </div>
  );
});
Stats.displayName = 'CommunitiesList.Stats';

const List: React.FC = memo(() => {
  const { t } = useTranslation();
  const { communities, selectedCommunity, selectCommunity, loading } = useCommunitiesListContext();

  if (loading) {
    return (
      <div data-testid="loading-indicator" className="text-center py-12">
        <Loader2 size={32} className="text-slate-400 animate-spin motion-reduce:animate-none" />
        <p className="text-slate-500 mt-2">{t('project.graph.communities.empty.loading')}</p>
      </div>
    );
  }

  return (
    <VirtualGrid
      items={communities}
      renderItem={(community: Community, index: number) => (
        <button
          type="button"
          onClick={() => {
            selectCommunity(community);
          }}
          className={`text-left block w-full bg-white dark:bg-slate-800 rounded-lg border p-5 cursor-pointer transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:shadow-md ${
            selectedCommunity?.uuid === community.uuid
              ? 'border-purple-500 shadow-md ring-2 ring-purple-500 ring-opacity-20'
              : 'border-slate-200 dark:border-slate-700'
          }`}
        >
          <div className="flex items-start justify-between mb-3">
            <div className={`p-3 rounded-md ${getCommunityIconClass(index)}`}>
              <Users size={16} />
            </div>
            <span className="bg-slate-100 dark:bg-slate-900/60 text-slate-700 dark:text-slate-300 px-2 py-1 rounded-full text-xs font-medium">
              {t('project.graph.communities.card.members', { count: community.member_count })}
            </span>
          </div>
          <h3 className="font-semibold text-slate-900 dark:text-white mb-2">
            {community.name ||
              t('project.graph.communities.card.default_name', { index: index + 1 })}
          </h3>
          {community.summary && (
            <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-2">
              {community.summary}
            </p>
          )}
          {community.created_at && (
            <div className="mt-2 text-xs text-slate-500">
              {t('project.graph.communities.card.created', {
                date: formatDateOnly(community.created_at),
              })}
            </div>
          )}
        </button>
      )}
      estimateSize={() => 180}
      containerHeight={600}
      overscan={3}
      columns="responsive"
      emptyComponent={
        <div className="text-center py-12 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <Users size={32} className="text-slate-400" />
          <p className="text-slate-500 mt-2">{t('project.graph.communities.empty.title')}</p>
          <p className="text-sm text-slate-400 mt-1">{t('project.graph.communities.empty.desc')}</p>
        </div>
      }
    />
  );
});
List.displayName = 'CommunitiesList.List';

const Pagination: React.FC = memo(() => {
  const { t } = useTranslation();
  const { page, totalPages, hasNextPage, hasPrevPage, setPage } = useCommunitiesListContext();

  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-4 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <button
        type="button"
        onClick={() => {
          setPage(Math.max(0, page - 1));
        }}
        disabled={!hasPrevPage}
        className="px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
      >
        <ChevronLeft size={14} />
        {t('common.previous')}
      </button>
      <span className="text-sm text-slate-600 dark:text-slate-400">
        {t('project.graph.communities.stats.page', { current: page + 1, total: totalPages })}
      </span>
      <button
        type="button"
        onClick={() => {
          setPage(page + 1);
        }}
        disabled={!hasNextPage}
        className="px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
      >
        {t('common.next')}
        <ChevronRight size={14} />
      </button>
    </div>
  );
});
Pagination.displayName = 'CommunitiesList.Pagination';

const Detail: React.FC = memo(() => {
  const { t } = useTranslation();
  const { selectedCommunity, members, closeDetail } = useCommunitiesListContext();

  if (!selectedCommunity) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-12 text-center sticky top-6">
        <Users size={32} className="text-slate-400" />
        <p className="text-slate-500 mt-2">{t('project.graph.communities.detail.select_prompt')}</p>
        <p className="text-sm text-slate-400 mt-1">
          {t('project.graph.communities.detail.click_prompt')}
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6 sticky top-6">
      <div className="flex items-start justify-between mb-4">
        <h2 className="text-lg font-bold text-slate-900 dark:text-white">
          {t('project.graph.communities.detail.title')}
        </h2>
        <button
          type="button"
          onClick={closeDetail}
          aria-label={t('project.graph.communities.detail.close')}
          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
        >
          <X size={16} />
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <span className="text-xs font-semibold text-slate-500 uppercase">
            {t('project.graph.communities.detail.name')}
          </span>
          <p className="text-slate-900 dark:text-white font-medium mt-1">
            {selectedCommunity.name || t('project.graph.communities.detail.unnamed')}
          </p>
        </div>

        <div>
          <span className="text-xs font-semibold text-slate-500 uppercase">
            {t('project.graph.communities.detail.members')}
          </span>
          <p className="text-2xl font-bold text-purple-600">{selectedCommunity.member_count}</p>
        </div>

        {selectedCommunity.summary && (
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase">
              {t('project.graph.communities.detail.summary')}
            </span>
            <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
              {selectedCommunity.summary}
            </p>
          </div>
        )}

        <div>
          <span className="text-xs font-semibold text-slate-500 uppercase">
            {t('project.graph.communities.detail.uuid')}
          </span>
          <p className="text-xs text-slate-500 dark:text-slate-400 font-mono break-all mt-1">
            {selectedCommunity.uuid}
          </p>
        </div>

        {selectedCommunity.created_at && (
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase">
              {t('project.graph.communities.detail.created')}
            </span>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {formatDateTime(selectedCommunity.created_at)}
            </p>
          </div>
        )}

        <div>
          <span className="text-xs font-semibold text-slate-500 uppercase">
            {t('project.graph.communities.detail.tasks')}
          </span>
          <div className="mt-2">
            <TaskList entityId={selectedCommunity.uuid} entityType="community" embedded />
          </div>
        </div>

        <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-3">
            {t('project.graph.communities.detail.member_list', { count: members.length })}
          </h3>
          {members.length > 0 ? (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {members.slice(0, 20).map((member) => (
                <div
                  key={member.uuid}
                  className="p-2 bg-slate-50 dark:bg-slate-900 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <div className="font-medium text-slate-900 dark:text-white">{member.name}</div>
                  <div className="text-xs text-slate-500">{member.entity_type}</div>
                  {member.summary && (
                    <div className="text-xs text-slate-600 dark:text-slate-400 mt-1 line-clamp-1">
                      {member.summary}
                    </div>
                  )}
                </div>
              ))}
              {members.length > 20 && (
                <div className="text-center text-sm text-slate-500 pt-2">
                  {t('project.graph.communities.detail.more_members', {
                    count: members.length - 20,
                  })}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-500">
              {t('project.graph.communities.detail.no_members')}
            </p>
          )}
        </div>
      </div>
    </div>
  );
});
Detail.displayName = 'CommunitiesList.Detail';

const TaskStatus: React.FC = memo(() => {
  const { t } = useTranslation();
  const { currentTask, cancelTask, dismissTask } = useCommunitiesListContext();

  if (!currentTask) return null;

  return (
    <div
      className={`rounded-lg p-4 border ${
        currentTask.status === 'completed'
          ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800'
          : currentTask.status === 'failed'
            ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
            : currentTask.status === 'running'
              ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800'
              : 'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700'
      }`}
    >
      <div className="flex items-start gap-3">
        {currentTask.status === 'running' ? (
          <Loader2
            size={24}
            className="text-blue-600 dark:text-blue-400 animate-spin motion-reduce:animate-none"
          />
        ) : currentTask.status === 'completed' ? (
          <CheckCircle size={24} className="text-green-600 dark:text-green-400" />
        ) : currentTask.status === 'failed' ? (
          <AlertCircle size={24} className="text-red-600 dark:text-red-400" />
        ) : (
          <Clock size={24} className="text-slate-400" />
        )}
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <h3
              className={`font-semibold ${
                currentTask.status === 'completed'
                  ? 'text-green-900 dark:text-green-300'
                  : currentTask.status === 'failed'
                    ? 'text-red-900 dark:text-red-300'
                    : 'text-slate-900 dark:text-white'
              }`}
            >
              {currentTask.status === 'running'
                ? t('project.graph.communities.task.status_running')
                : currentTask.status === 'completed'
                  ? t('project.graph.communities.task.status_completed')
                  : currentTask.status === 'failed'
                    ? t('project.graph.communities.task.status_failed')
                    : t('project.graph.communities.task.status_scheduled')}
            </h3>
            {(currentTask.status === 'running' || currentTask.status === 'pending') && (
              <button
                type="button"
                onClick={() => {
                  void cancelTask();
                }}
                className="px-3 py-1 text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
              >
                {t('project.graph.communities.task.cancel')}
              </button>
            )}
            {currentTask.status === 'failed' && (
              <button
                type="button"
                onClick={dismissTask}
                className="px-3 py-1 text-xs font-medium bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
              >
                {t('project.graph.communities.task.dismiss')}
              </button>
            )}
          </div>
          <p
            className={`text-sm mt-1 ${
              currentTask.status === 'completed'
                ? 'text-green-800 dark:text-green-400'
                : currentTask.status === 'failed'
                  ? 'text-red-800 dark:text-red-400'
                  : 'text-slate-600 dark:text-slate-400'
            }`}
          >
            {currentTask.message}
          </p>
          {currentTask.status === 'running' && currentTask.progress > 0 && (
            <div className="mt-2">
              <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400 mb-1">
                <span>{t('project.graph.communities.task.progress')}</span>
                <span>{currentTask.progress}%</span>
              </div>
              <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2">
                <div
                  className="bg-blue-600 dark:bg-blue-500 h-2 rounded-full transition-[width] duration-300"
                  style={{ width: formatPercent(currentTask.progress) }}
                />
              </div>
            </div>
          )}
          {currentTask.result && currentTask.status === 'completed' && (
            <div className="mt-3 p-3 bg-white dark:bg-slate-900 rounded-md">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-slate-500 dark:text-slate-400">
                    {t('project.graph.communities.task.communities_count')}
                  </span>
                  <p className="font-semibold text-slate-900 dark:text-white">
                    {currentTask.result.communities_count || 0}
                  </p>
                </div>
                <div>
                  <span className="text-slate-500 dark:text-slate-400">
                    {t('project.graph.communities.task.connections_count')}
                  </span>
                  <p className="font-semibold text-slate-900 dark:text-white">
                    {currentTask.result.edges_count || 0}
                  </p>
                </div>
              </div>
            </div>
          )}
          {currentTask.error && currentTask.status === 'failed' && (
            <div className="mt-2 p-2 bg-red-100 dark:bg-red-900/30 rounded text-sm text-red-800 dark:text-red-400">
              <strong>{t('project.graph.communities.task.error')}:</strong> {currentTask.error}
            </div>
          )}
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {t('project.graph.communities.task.id')}:{' '}
            <code className="font-mono">{currentTask.task_id}</code>
          </div>
        </div>
      </div>
    </div>
  );
});
TaskStatus.displayName = 'CommunitiesList.TaskStatus';

const ErrorMessage: React.FC = memo(() => {
  const { t } = useTranslation();
  const { error, clearError } = useCommunitiesListContext();

  if (!error) return null;

  return (
    <div
      data-testid="error-message"
      className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start gap-3"
    >
      <AlertCircle size={16} className="text-red-600 dark:text-red-400" />
      <div>
        <h3 className="font-semibold text-red-900 dark:text-red-300">
          {t('project.graph.communities.task.error')}
        </h3>
        <p className="text-sm text-red-800 dark:text-red-400">{error}</p>
      </div>
      <button
        type="button"
        aria-label={t('project.graph.communities.task.dismiss')}
        title={t('project.graph.communities.task.dismiss')}
        onClick={clearError}
        className="ml-auto text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
      >
        <X size={16} />
      </button>
    </div>
  );
});
ErrorMessage.displayName = 'CommunitiesList.Error';

// ========================================
// Info Component
// ========================================

const Info: React.FC = memo(() => {
  const { t } = useTranslation();
  return (
    <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
      <div className="flex gap-3">
        <InfoIcon size={24} className="text-blue-600 dark:text-blue-400" />
        <div>
          <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-300">
            {t('project.graph.communities.info.title')}
          </h3>
          <p className="text-sm text-blue-800 dark:text-blue-400 mt-1">
            {t('project.graph.communities.info.desc')}
          </p>
        </div>
      </div>
    </div>
  );
});
Info.displayName = 'CommunitiesList.Info';

// ========================================
// Root Component (default export)
// ========================================

interface RootProps {
  projectId?: string | undefined;
  tenantId?: string | undefined;
  limit?: number | undefined;
  children?: React.ReactNode | undefined;
}

const Root: React.FC<RootProps> = memo(({ children, projectId, tenantId, limit }) => {
  return (
    <CommunitiesListProvider projectId={projectId} tenantId={tenantId} limit={limit}>
      {children ?? (
        <>
          <Header />
          <TaskStatus />
          <ErrorMessage />
          <Stats />
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-4">
              <List />
              <Pagination />
            </div>
            <div className="lg:col-span-1">
              <Detail />
            </div>
          </div>
          <Info />
        </>
      )}
    </CommunitiesListProvider>
  );
});

Root.displayName = 'CommunitiesList';

// ========================================
// Compound Component Assembly
// ========================================

interface CommunitiesListCompound extends React.FC<RootProps> {
  Header: typeof Header;
  Stats: typeof Stats;
  List: typeof List;
  Pagination: typeof Pagination;
  Detail: typeof Detail;
  TaskStatus: typeof TaskStatus;
  Error: typeof ErrorMessage;
  Info: typeof Info;
  Root: typeof Root;
  Provider: typeof CommunitiesListProvider;
}

const CommunitiesList = Root as CommunitiesListCompound;

CommunitiesList.Header = Header;
CommunitiesList.Stats = Stats;
CommunitiesList.List = List;
CommunitiesList.Pagination = Pagination;
CommunitiesList.Detail = Detail;
CommunitiesList.TaskStatus = TaskStatus;
CommunitiesList.Error = ErrorMessage;
CommunitiesList.Info = Info;
CommunitiesList.Root = Root;
CommunitiesList.Provider = CommunitiesListProvider;

export { CommunitiesList };
