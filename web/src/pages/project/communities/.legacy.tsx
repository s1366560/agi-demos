import React, { useState, useEffect, useCallback, useMemo, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { formatDateOnly, formatDateTime } from '@/utils/date';

import { VirtualGrid } from '../../components/common';
import { TaskList } from '../../components/tasks/TaskList';
import { createApiUrl } from '../../services/client/urlUtils';
import { graphService } from '../../services/graphService';
import { logger } from '../../utils/logger';

interface Community {
  uuid: string;
  name: string;
  summary: string;
  member_count: number;
  formed_at?: string | undefined;
  created_at?: string | undefined;
}

interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string;
}

interface BackgroundTask {
  task_id: string;
  task_type: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  created_at: string;
  started_at?: string | undefined;
  completed_at?: string | undefined;
  progress: number;
  message: string;
  result?: any | undefined;
  error?: string | undefined;
}

// Color palette for community cards - defined outside component for stability
const COMMUNITY_COLORS = [
  'from-blue-500 to-cyan-500',
  'from-purple-500 to-pink-500',
  'from-emerald-500 to-teal-500',
  'from-orange-500 to-amber-500',
  'from-rose-500 to-red-500',
] as const;

const CommunitiesListInternal: React.FC = () => {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const [communities, setCommunities] = useState<Community[]>([]);
  const [selectedCommunity, setSelectedCommunity] = useState<Community | null>(null);
  const [members, setMembers] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(0);
  const limit = 20;

  // Background task state
  const [currentTask, setCurrentTask] = useState<BackgroundTask | null>(null);

  const loadCommunities = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      logger.debug('Loading communities...', { projectId, limit, offset: page * limit });

      const result = await graphService.listCommunities({
        tenant_id: undefined,
        project_id: projectId,
        min_members: 1,
        limit,
        offset: page * limit,
      });

      logger.debug('Communities loaded:', {
        count: result.communities.length,
        total: result.total,
        communities: result.communities,
      });

      setCommunities(result.communities);
      setTotalCount(result.total || result.communities.length);
    } catch (err: any) {
      logger.error('Failed to load communities:', err);
      logger.error('Error details:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status,
      });
      setError(err.response?.data?.detail || err.message || 'Failed to load communities');
    } finally {
      setLoading(false);
    }
  }, [projectId, page]);

  const loadMembers = async (communityUuid: string) => {
    try {
      const result = await graphService.getCommunityMembers(communityUuid, 100);
      setMembers(result.members);
    } catch (err) {
      logger.error('Failed to load members:', err);
    }
  };

  const streamTaskStatus = useCallback(
    (taskId: string) => {
      logger.debug(`📡 Connecting to SSE stream for task: ${taskId}`);

      // Use centralized URL utility for SSE endpoint
      const streamUrl = createApiUrl(`/tasks/${taskId}/stream`);
      logger.debug(`📡 Connecting to SSE: ${streamUrl}`);

      const eventSource = new EventSource(streamUrl);

      // Log connection open
      eventSource.onopen = () => {
        logger.debug('✅ SSE connection opened successfully');
      };

      // Log all messages for debugging
      eventSource.onmessage = (e) => {
        logger.debug('📨 SSE message received (no event type):', e.data);
      };

      // Handle progress updates
      eventSource.addEventListener('progress', (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          logger.debug(`📊 Task progress:`, data);

          // Map backend status to frontend status
          // Backend sends: "processing", "completed", "failed"
          // Frontend expects: "running", "completed", "failed"
          const statusMap: Record<string, string> = {
            processing: 'running',
            pending: 'pending',
            completed: 'completed',
            failed: 'failed',
          };
          const normalizedStatus =
            statusMap[data.status?.toLowerCase()] || data.status?.toLowerCase() || 'pending';

          setCurrentTask({
            task_id: data.id,
            task_type: 'rebuild_communities',
            status: normalizedStatus as any,
            created_at: new Date().toISOString(),
            progress: data.progress || 0,
            message: data.message || 'Processing...',
            result: data.result,
            error: data.error,
          });
        } catch (err) {
          logger.error('Failed to parse progress event:', err);
        }
      });

      // Handle task completion
      eventSource.addEventListener('completed', (e: MessageEvent) => {
        try {
          const task = JSON.parse(e.data);
          logger.debug(`✅ Task completed:`, task);

          setCurrentTask({
            task_id: task.id,
            task_type: task.name,
            status: 'completed',
            created_at: task.created_at,
            started_at: task.started_at,
            completed_at: task.completed_at,
            progress: task.progress || 100,
            message: task.message || 'Community rebuild completed',
            result: task.result,
            error: task.error,
          });

          setRebuilding(false);
          eventSource.close();

          // Reload communities
          loadCommunities()
            .then(() => {
              const communitiesCount = task.result?.communities_count || 0;
              const edgesCount = task.result?.edges_count || 0;
              logger.debug(
                `✅ Rebuild completed: ${communitiesCount} communities, ${edgesCount} edges`
              );
            })
            .catch((loadErr: any) => {
              logger.error('Failed to reload communities:', loadErr);
              setError(
                'Communities rebuilt but failed to refresh the list. Please manually refresh.'
              );
            });

          // Clear task status after 5 seconds
          setTimeout(() => {
            setCurrentTask(null);
          }, 5000);
        } catch (err) {
          logger.error('Failed to parse completed event:', err);
        }
      });

      // Handle task failure
      eventSource.addEventListener('failed', (e: MessageEvent) => {
        try {
          const task = JSON.parse(e.data);
          logger.error(`❌ Task failed:`, task);

          setCurrentTask({
            task_id: task.id,
            task_type: task.name,
            status: 'failed',
            created_at: task.created_at,
            started_at: task.started_at,
            completed_at: task.completed_at,
            progress: task.progress || 0,
            message: task.message || 'Community rebuild failed',
            result: task.result,
            error: task.error || 'Unknown error',
          });

          setRebuilding(false);
          setError(`Rebuild failed: ${task.error || 'Unknown error'}`);
          eventSource.close();
        } catch (err) {
          logger.error('Failed to parse failed event:', err);
        }
      });

      // Handle connection errors
      eventSource.onerror = (e) => {
        logger.error('❌ SSE connection error:', e);
        logger.error('   ReadyState:', eventSource.readyState);

        // EventSource.CLOSED = 2, CONNECTING = 0, OPEN = 1
        if (eventSource.readyState === 2) {
          logger.error('   Connection CLOSED - check for CORS errors');
          eventSource.close();
          setRebuilding(false);
          setError('Failed to connect to task updates. Please refresh the page.');
        }
      };

      // Handle error events from server
      eventSource.addEventListener('error', (e: MessageEvent) => {
        try {
          const error = JSON.parse(e.data);
          logger.error(`❌ Server error event:`, error);
          setRebuilding(false);
          setError(error.error || error.message || 'Unknown error');
          eventSource.close();
        } catch (err) {
          logger.error('❌ Failed to parse error event:', err);
        }
      });

      // Store eventSource reference for cleanup
      return eventSource;
    },
    [loadCommunities]
  );

  const handleRebuildCommunities = async () => {
    if (!confirm(t('project.graph.communities.confirm_rebuild'))) {
      return;
    }

    setRebuilding(true);
    setError(null);

    try {
      logger.debug(`🔄 Starting community rebuild for project: ${projectId}`);

      // Start background rebuild with project_id
      const result = await graphService.rebuildCommunities(true, projectId); // background=true, projectId from URL

      logger.debug(`✅ Rebuild task submitted:`, result);

      if (result.task_id) {
        // Start streaming task status using SSE
        logger.debug(`📊 Starting to stream task status for: ${result.task_id}`);
        streamTaskStatus(result.task_id);
      } else {
        // Fallback to synchronous mode
        logger.debug('⚠️ No task_id returned, assuming synchronous mode');
        await loadCommunities();
        alert(`Success! ${result.message}`);
        setRebuilding(false);
      }
    } catch (err: any) {
      logger.error('❌ Failed to rebuild communities:', err);
      logger.error('Error details:', {
        message: err.message,
        response: err.response?.data,
        status: err.response?.status,
      });
      const errorMsg =
        err.response?.data?.detail || err.message || 'Failed to start community rebuild';
      setError(`Failed to rebuild: ${errorMsg}`);
      setRebuilding(false);
    }
  };

  const handleCancelTask = async () => {
    if (!currentTask) return;

    try {
      await graphService.cancelTask(currentTask.task_id);
      setCurrentTask(null);
      setRebuilding(false);
      alert('Task cancelled');
    } catch (err: any) {
      logger.error('Failed to cancel task:', err);
      setError('Failed to cancel task');
    }
  };

  const handleCommunityClick = (community: Community) => {
    setSelectedCommunity(community);
    loadMembers(community.uuid);
  };

  useEffect(() => {
    loadCommunities();
  }, [loadCommunities]);

  // Memoized color function to avoid re-creation
  const getCommunityColor = useCallback((index: number) => {
    return COMMUNITY_COLORS[index % COMMUNITY_COLORS.length];
  }, []);

  // Memoize computed values for pagination
  const totalPages = useMemo(() => Math.ceil(totalCount / limit), [totalCount, limit]);
  const hasNextPage = useMemo(() => (page + 1) * limit < totalCount, [page, limit, totalCount]);
  const hasPrevPage = useMemo(() => page > 0, [page]);

  // Memoize dismiss task handler
  const handleDismissTask = useCallback(() => {
    setCurrentTask(null);
  }, []);

  // Memoize clear error handler
  const handleClearError = useCallback(() => {
    setError(null);
  }, []);

  // Memoize close detail panel handler
  const handleCloseDetail = useCallback(() => {
    setSelectedCommunity(null);
    setMembers([]);
  }, []);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('project.graph.communities.title')}
          </h1>
          <p className="text-slate-600 dark:text-slate-400 mt-1">
            {t('project.graph.communities.subtitle')}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleRebuildCommunities}
            disabled={rebuilding}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span className="material-symbols-outlined">
              {rebuilding ? 'progress_activity' : 'refresh'}
            </span>
            {rebuilding
              ? t('project.graph.communities.rebuilding')
              : t('project.graph.communities.rebuild')}
          </button>
          <button
            onClick={loadCommunities}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined">refresh</span>
            {t('project.graph.communities.refresh')}
          </button>
        </div>
      </div>

      {/* Background Task Status */}
      {currentTask && (
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
            <span
              className={`material-symbols-outlined text-2xl ${
                currentTask.status === 'completed'
                  ? 'text-green-600 dark:text-green-400'
                  : currentTask.status === 'failed'
                    ? 'text-red-600 dark:text-red-400'
                    : currentTask.status === 'running'
                      ? 'text-blue-600 dark:text-blue-400 animate-spin'
                      : 'text-slate-400'
              }`}
            >
              {currentTask.status === 'running'
                ? 'progress_activity'
                : currentTask.status === 'completed'
                  ? 'check_circle'
                  : currentTask.status === 'failed'
                    ? 'error'
                    : 'schedule'}
            </span>
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
                    ? 'Rebuilding Communities...'
                    : currentTask.status === 'completed'
                      ? 'Rebuild Completed Successfully'
                      : currentTask.status === 'failed'
                        ? 'Rebuild Failed'
                        : 'Rebuild Scheduled'}
                </h3>
                {(currentTask.status === 'running' || currentTask.status === 'pending') && (
                  <button
                    onClick={handleCancelTask}
                    className="px-3 py-1 text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
                  >
                    {t('project.graph.communities.task.cancel')}
                  </button>
                )}
                {currentTask.status === 'failed' && (
                  <button
                    onClick={handleDismissTask}
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
                      className="bg-blue-600 dark:bg-blue-500 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${currentTask.progress}%` }}
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
                Task ID: <code className="font-mono">{currentTask.task_id}</code>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start gap-3">
          <span className="material-symbols-outlined text-red-600 dark:text-red-400">error</span>
          <div>
            <h3 className="font-semibold text-red-900 dark:text-red-300">Error</h3>
            <p className="text-sm text-red-800 dark:text-red-400">{error}</p>
          </div>
          <button
            onClick={handleClearError}
            className="ml-auto text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
          >
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
      )}

      {/* Stats Bar */}
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Communities List */}
        <div className="lg:col-span-2 space-y-4">
          {loading ? (
            <div className="text-center py-12">
              <span className="material-symbols-outlined text-4xl text-slate-400 animate-spin">
                progress_activity
              </span>
              <p className="text-slate-500 mt-2">{t('project.graph.communities.empty.loading')}</p>
            </div>
          ) : (
            <>
              {/* Virtual Grid for community cards */}
              <VirtualGrid
                items={communities}
                renderItem={(community: Community, index: number) => (
                  <div
                    onClick={() => handleCommunityClick(community)}
                    className={`bg-white dark:bg-slate-800 rounded-lg border p-5 cursor-pointer transition-all hover:shadow-md ${
                      selectedCommunity?.uuid === community.uuid
                        ? 'border-purple-500 shadow-md ring-2 ring-purple-500 ring-opacity-20'
                        : 'border-slate-200 dark:border-slate-700'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div
                        className={`p-3 rounded-lg bg-gradient-to-br ${getCommunityColor(index)} text-white`}
                      >
                        <span className="material-symbols-outlined">groups</span>
                      </div>
                      <span className="bg-purple-100 dark:bg-purple-900/30 text-purple-800 dark:text-purple-400 px-2 py-1 rounded-full text-xs font-medium">
                        {community.member_count} members
                      </span>
                    </div>
                    <h3 className="font-semibold text-slate-900 dark:text-white mb-2">
                      {community.name || `Community ${index + 1}`}
                    </h3>
                    {community.summary && (
                      <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-2">
                        {community.summary}
                      </p>
                    )}
                    {community.created_at && (
                      <div className="mt-2 text-xs text-slate-500">
                        Created: {formatDateOnly(community.created_at)}
                      </div>
                    )}
                  </div>
                )}
                estimateSize={() => 180} // Estimated height for each community card
                containerHeight={600} // Fixed height for scroll container
                overscan={3}
                columns="responsive"
                emptyComponent={
                  <div className="text-center py-12 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
                    <span className="material-symbols-outlined text-4xl text-slate-400">
                      groups
                    </span>
                    <p className="text-slate-500 mt-2">
                      {t('project.graph.communities.empty.title')}
                    </p>
                    <p className="text-sm text-slate-400 mt-1">
                      {t('project.graph.communities.empty.desc')}
                    </p>
                  </div>
                }
              />

              {/* Pagination */}
              {totalCount > limit && (
                <div className="flex items-center justify-center gap-4 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={!hasPrevPage}
                    className="px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    <span className="material-symbols-outlined text-sm">chevron_left</span>
                    Previous
                  </button>
                  <span className="text-sm text-slate-600 dark:text-slate-400">
                    Page {page + 1} of {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => p + 1)}
                    disabled={!hasNextPage}
                    className="px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    Next
                    <span className="material-symbols-outlined text-sm">chevron_right</span>
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Community Detail Panel */}
        <div className="lg:col-span-1">
          {selectedCommunity ? (
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6 sticky top-6">
              <div className="flex items-start justify-between mb-4">
                <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                  Community Details
                </h2>
                <button
                  onClick={handleCloseDetail}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                >
                  <span className="material-symbols-outlined">close</span>
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">Name</label>
                  <p className="text-slate-900 dark:text-white font-medium mt-1">
                    {selectedCommunity.name || 'Unnamed Community'}
                  </p>
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">Members</label>
                  <p className="text-2xl font-bold text-purple-600">
                    {selectedCommunity.member_count}
                  </p>
                </div>

                {selectedCommunity.summary && (
                  <div>
                    <label className="text-xs font-semibold text-slate-500 uppercase">
                      Summary
                    </label>
                    <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
                      {selectedCommunity.summary}
                    </p>
                  </div>
                )}

                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">UUID</label>
                  <p className="text-xs text-slate-500 dark:text-slate-400 font-mono break-all mt-1">
                    {selectedCommunity.uuid}
                  </p>
                </div>

                {selectedCommunity.created_at && (
                  <div>
                    <label className="text-xs font-semibold text-slate-500 uppercase">
                      Created
                    </label>
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      {formatDateTime(selectedCommunity.created_at)}
                    </p>
                  </div>
                )}

                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">Tasks</label>
                  <div className="mt-2">
                    <TaskList entityId={selectedCommunity.uuid} entityType="community" embedded />
                  </div>
                </div>

                {/* Members List */}
                <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-3">
                    Community Members ({members.length})
                  </h3>
                  {members.length > 0 ? (
                    <div className="space-y-2 max-h-64 overflow-y-auto">
                      {members.slice(0, 20).map((member) => (
                        <div
                          key={member.uuid}
                          className="p-2 bg-slate-50 dark:bg-slate-900 rounded-md text-sm hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                        >
                          <div className="font-medium text-slate-900 dark:text-white">
                            {member.name}
                          </div>
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
                          ...and {members.length - 20} more
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500">No members loaded</p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-12 text-center sticky top-6">
              <span className="material-symbols-outlined text-4xl text-slate-400">groups</span>
              <p className="text-slate-500 mt-2">Select a community to view details</p>
              <p className="text-sm text-slate-400 mt-1">
                Click on any community card to see its members
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Info Card */}
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <div className="flex gap-3">
          <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-2xl">
            info
          </span>
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
    </div>
  );
};

/**
 * Memoized CommunitiesList page component.
 * Prevents unnecessary re-renders when parent components update.
 */
export const CommunitiesList = memo(CommunitiesListInternal);
