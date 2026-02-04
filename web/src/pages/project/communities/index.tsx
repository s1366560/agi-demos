/**
 * CommunitiesList Compound Component
 *
 * Implements the compound component pattern for the CommunitiesList page.
 * Allows flexible composition of sub-components while maintaining shared state.
 */

import React, { createContext, useContext, useState, useCallback, useMemo, useEffect, memo } from 'react'
import { useParams } from 'react-router-dom'
import { logger } from '../../../utils/logger'
import { graphService } from '../../../services/graphService'
import { TaskList } from '../../../components/tasks/TaskList'
import { createApiUrl } from '../../../services/client/urlUtils'
import { VirtualGrid } from '../../../components/common'
import type { Community, Entity, BackgroundTask } from './types'

// ========================================
// Constants
// ========================================

const TEXTS = {
  title: 'Communities',
  subtitle: 'Automatically detected groups of related entities in the knowledge graph',
  rebuild: 'Rebuild Communities',
  rebuilding: 'Rebuilding...',
  refresh: 'Refresh',
  confirmRebuild: 'This will rebuild all communities from scratch. Continue?',
  cancel: 'Cancel',
  dismiss: 'Dismiss',
  progress: 'Progress',
  communitiesCount: 'Communities',
  connectionsCount: 'Connections',
  error: 'Error',
  taskError: 'Error',
  showing: 'Showing {{count}} of {{total}} communities',
  page: 'Page {{current}} of {{total}}',
  loading: 'Loading communities...',
  emptyTitle: 'No communities found',
  emptyDesc: 'Add more episodes to enable community detection',
  communityDetails: 'Community Details',
  name: 'Name',
  members: 'Members',
  summary: 'Summary',
  uuid: 'UUID',
  created: 'Created',
  tasks: 'Tasks',
  communityMembers: 'Community Members',
  noMembers: 'No members loaded',
  selectPrompt: 'Select a community to view details',
  clickPrompt: 'Click on any community card to see its members',
  infoTitle: 'About Communities',
  infoDesc: 'Communities are automatically detected groups of related entities.',
} as const

// Helper function for simple interpolation
function formatTemplate(template: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replace(`{{${key}}}`, String(value)),
    template
  )
}

// ========================================
// Context
// ========================================

interface CommunitiesListContextValue {
  // State
  communities: Community[]
  selectedCommunity: Community | null
  members: Entity[]
  loading: boolean
  error: string | null
  rebuilding: boolean
  totalCount: number
  page: number
  limit: number
  currentTask: BackgroundTask | null

  // Actions
  loadCommunities: () => Promise<void>
  selectCommunity: (community: Community) => void
  closeDetail: () => void
  rebuildCommunities: () => Promise<void>
  cancelTask: () => Promise<void>
  setPage: (page: number) => void
  clearError: () => void
  dismissTask: () => void

  // Computed
  totalPages: number
  hasNextPage: boolean
  hasPrevPage: boolean
}

const CommunitiesListContext = createContext<CommunitiesListContextValue | null>(null)

function useCommunitiesListContext(): CommunitiesListContextValue {
  const context = useContext(CommunitiesListContext)
  if (!context) {
    throw Error('CommunitiesList sub-components must be used within CommunitiesList')
  }
  return context
}

// ========================================
// Color Palette (outside component for stability)
// ========================================

const COMMUNITY_COLORS = [
  'from-blue-500 to-cyan-500',
  'from-purple-500 to-pink-500',
  'from-emerald-500 to-teal-500',
  'from-orange-500 to-amber-500',
  'from-rose-500 to-red-500',
] as const

// ========================================
// Root Component
// ========================================

interface CommunitiesListProviderProps {
  children: React.ReactNode
  projectId?: string
  limit?: number
}

const CommunitiesListProvider: React.FC<CommunitiesListProviderProps> = memo(({
  children,
  projectId: propProjectId,
  limit: propLimit = 20
}) => {
  const { projectId: urlProjectId } = useParams()
  const projectId = propProjectId || urlProjectId

  // State
  const [communities, setCommunities] = useState<Community[]>([])
  const [selectedCommunity, setSelectedCommunity] = useState<Community | null>(null)
  const [members, setMembers] = useState<Entity[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rebuilding, setRebuilding] = useState(false)
  const [totalCount, setTotalCount] = useState(0)
  const [page, setPage] = useState(0)
  const [currentTask, setCurrentTask] = useState<BackgroundTask | null>(null)

  // Load communities
  const loadCommunities = useCallback(async () => {
    if (!projectId) return

    setLoading(true)
    setError(null)
    try {
      logger.debug('Loading communities...', { projectId, limit: propLimit, offset: page * propLimit })

      const result = await graphService.listCommunities({
        tenant_id: undefined,
        project_id: projectId,
        min_members: 1,
        limit: propLimit,
        offset: page * propLimit,
      })

      logger.debug('Communities loaded:', {
        count: result.communities.length,
        total: result.total,
      })

      setCommunities(result.communities)
      setTotalCount(result.total || result.communities.length)
    } catch (err: any) {
      logger.error('Failed to load communities:', err)
      setError(err.response?.data?.detail || err.message || 'Failed to load communities')
    } finally {
      setLoading(false)
    }
  }, [projectId, page, propLimit])

  // Load members
  const loadMembers = useCallback(async (communityUuid: string) => {
    try {
      const result = await graphService.getCommunityMembers(communityUuid, 100)
      setMembers(result.members)
    } catch (err) {
      logger.error('Failed to load members:', err)
    }
  }, [])

  // Stream task status
  const streamTaskStatus = useCallback((taskId: string) => {
    const streamUrl = createApiUrl(`/tasks/${taskId}/stream`)
    const eventSource = new EventSource(streamUrl)

    eventSource.onopen = () => {
      logger.debug('SSE connection opened')
    }

    eventSource.addEventListener('progress', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        const statusMap: Record<string, string> = {
          'processing': 'running',
          'pending': 'pending',
          'completed': 'completed',
          'failed': 'failed'
        }
        const normalizedStatus = statusMap[data.status?.toLowerCase()] || data.status?.toLowerCase() || 'pending'

        setCurrentTask({
          task_id: data.id,
          task_type: 'rebuild_communities',
          status: normalizedStatus as any,
          created_at: new Date().toISOString(),
          progress: data.progress || 0,
          message: data.message || 'Processing...',
          result: data.result,
          error: data.error
        })
      } catch (err) {
        logger.error('Failed to parse progress event:', err)
      }
    })

    eventSource.addEventListener('completed', (e: MessageEvent) => {
      try {
        const task = JSON.parse(e.data)
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
          error: task.error
        })

        setRebuilding(false)
        eventSource.close()
        loadCommunities()

        setTimeout(() => {
          setCurrentTask(null)
        }, 5000)
      } catch (err) {
        logger.error('Failed to parse completed event:', err)
      }
    })

    eventSource.addEventListener('failed', (e: MessageEvent) => {
      try {
        const task = JSON.parse(e.data)
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
          error: task.error || 'Unknown error'
        })

        setRebuilding(false)
        setError(`Rebuild failed: ${task.error || 'Unknown error'}`)
        eventSource.close()
      } catch (err) {
        logger.error('Failed to parse failed event:', err)
      }
    })

    eventSource.onerror = () => {
      logger.error('SSE connection error')
      if (eventSource.readyState === 2) {
        eventSource.close()
        setRebuilding(false)
        setError('Failed to connect to task updates. Please refresh the page.')
      }
    }

    return eventSource
  }, [loadCommunities])

  // Rebuild communities
  const rebuildCommunities = useCallback(async () => {
    if (!confirm(TEXTS.confirmRebuild)) {
      return
    }

    setRebuilding(true)
    setError(null)

    try {
      logger.debug(`Starting community rebuild for project: ${projectId}`)

      const result = await graphService.rebuildCommunities(true, projectId)

      if (result.task_id) {
        streamTaskStatus(result.task_id)
      } else {
        await loadCommunities()
        alert(`Success! ${result.message}`)
        setRebuilding(false)
      }
    } catch (err: any) {
      logger.error('Failed to rebuild communities:', err)
      const errorMsg = err.response?.data?.detail || err.message || 'Failed to start community rebuild'
      setError(`Failed to rebuild: ${errorMsg}`)
      setRebuilding(false)
    }
  }, [projectId, streamTaskStatus, loadCommunities])

  // Cancel task
  const cancelTask = useCallback(async () => {
    if (!currentTask) return

    try {
      await graphService.cancelTask(currentTask.task_id)
      setCurrentTask(null)
      setRebuilding(false)
      alert('Task cancelled')
    } catch (err: any) {
      logger.error('Failed to cancel task:', err)
      setError('Failed to cancel task')
    }
  }, [currentTask])

  // Select community
  const selectCommunity = useCallback((community: Community) => {
    setSelectedCommunity(community)
    loadMembers(community.uuid)
  }, [loadMembers])

  // Close detail
  const closeDetail = useCallback(() => {
    setSelectedCommunity(null)
    setMembers([])
  }, [])

  // Clear error
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  // Dismiss task
  const dismissTask = useCallback(() => {
    setCurrentTask(null)
  }, [])

  // Computed values
  const totalPages = useMemo(() => Math.ceil(totalCount / propLimit), [totalCount, propLimit])
  const hasNextPage = useMemo(() => (page + 1) * propLimit < totalCount, [page, propLimit, totalCount])
  const hasPrevPage = useMemo(() => page > 0, [page])

  // Initial load
  useEffect(() => {
    loadCommunities()
  }, [loadCommunities])

  const contextValue = useMemo<CommunitiesListContextValue>(() => ({
    communities,
    selectedCommunity,
    members,
    loading,
    error,
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
  }), [
    communities,
    selectedCommunity,
    members,
    loading,
    error,
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
    setPage,
    clearError,
    dismissTask,
    totalPages,
    hasNextPage,
    hasPrevPage,
  ])

  return (
    <CommunitiesListContext.Provider value={contextValue}>
      <div data-testid="communities-list-root" className="space-y-6">
        {children}
      </div>
    </CommunitiesListContext.Provider>
  )
})

CommunitiesListProvider.displayName = 'CommunitiesListProvider'

// ========================================
// Sub-Components
// ========================================

const Header: React.FC = memo(() => {
  const { rebuildCommunities, loadCommunities, loading, rebuilding } = useCommunitiesListContext()

  return (
    <div className="flex justify-between items-start">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {TEXTS.title}
        </h1>
        <p className="text-slate-600 dark:text-slate-400 mt-1">
          {TEXTS.subtitle}
        </p>
      </div>
      <div className="flex gap-2">
        <button
          onClick={rebuildCommunities}
          disabled={rebuilding}
          className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span className="material-symbols-outlined">
            {rebuilding ? 'progress_activity' : 'refresh'}
          </span>
          {rebuilding ? TEXTS.rebuilding : TEXTS.rebuild}
        </button>
        <button
          onClick={loadCommunities}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
        >
          <span className="material-symbols-outlined">refresh</span>
          {TEXTS.refresh}
        </button>
      </div>
    </div>
  )
})
Header.displayName = 'CommunitiesList.Header'

const Stats: React.FC = memo(() => {
  const { communities, totalCount, page, limit } = useCommunitiesListContext()

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-6 text-sm">
          <span className="text-slate-600 dark:text-slate-400">
            {formatTemplate(TEXTS.showing, {
              count: communities.length,
              total: totalCount.toLocaleString()
            })}
          </span>
        </div>
        {totalCount > limit && (
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {formatTemplate(TEXTS.page, {
              current: page + 1,
              total: Math.ceil(totalCount / limit)
            })}
          </div>
        )}
      </div>
    </div>
  )
})
Stats.displayName = 'CommunitiesList.Stats'

const List: React.FC = memo(() => {
  const { communities, selectedCommunity, selectCommunity, loading } = useCommunitiesListContext()

  if (loading) {
    return (
      <div data-testid="loading-indicator" className="text-center py-12">
        <span className="material-symbols-outlined text-4xl text-slate-400 animate-spin">
          progress_activity
        </span>
        <p className="text-slate-500 mt-2">{TEXTS.loading}</p>
      </div>
    )
  }

  const getCommunityColor = (index: number) => {
    return COMMUNITY_COLORS[index % COMMUNITY_COLORS.length]
  }

  return (
    <VirtualGrid
      items={communities}
      renderItem={(community: Community, index: number) => (
        <div
          onClick={() => selectCommunity(community)}
          className={`bg-white dark:bg-slate-800 rounded-lg border p-5 cursor-pointer transition-all hover:shadow-md ${
            selectedCommunity?.uuid === community.uuid
              ? 'border-purple-500 shadow-md ring-2 ring-purple-500 ring-opacity-20'
              : 'border-slate-200 dark:border-slate-700'
          }`}
        >
          <div className="flex items-start justify-between mb-3">
            <div className={`p-3 rounded-lg bg-gradient-to-br ${getCommunityColor(index)} text-white`}>
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
              Created: {new Date(community.created_at).toLocaleDateString()}
            </div>
          )}
        </div>
      )}
      estimateSize={() => 180}
      containerHeight={600}
      overscan={3}
      columns="responsive"
      emptyComponent={
        <div className="text-center py-12 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
          <span className="material-symbols-outlined text-4xl text-slate-400">groups</span>
          <p className="text-slate-500 mt-2">{TEXTS.emptyTitle}</p>
          <p className="text-sm text-slate-400 mt-1">
            {TEXTS.emptyDesc}
          </p>
        </div>
      }
    />
  )
})
List.displayName = 'CommunitiesList.List'

const Pagination: React.FC = memo(() => {
  const { page, totalPages, hasNextPage, hasPrevPage, setPage } = useCommunitiesListContext()

  if (totalPages <= 1) return null

  return (
    <div className="flex items-center justify-center gap-4 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
      <button
        onClick={() => setPage(Math.max(0, page - 1))}
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
        onClick={() => setPage(page + 1)}
        disabled={!hasNextPage}
        className="px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
      >
        Next
        <span className="material-symbols-outlined text-sm">chevron_right</span>
      </button>
    </div>
  )
})
Pagination.displayName = 'CommunitiesList.Pagination'

const Detail: React.FC = memo(() => {
  const { selectedCommunity, members, closeDetail } = useCommunitiesListContext()

  if (!selectedCommunity) {
    return (
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-12 text-center sticky top-6">
        <span className="material-symbols-outlined text-4xl text-slate-400">groups</span>
        <p className="text-slate-500 mt-2">{TEXTS.selectPrompt}</p>
        <p className="text-sm text-slate-400 mt-1">
          {TEXTS.clickPrompt}
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6 sticky top-6">
      <div className="flex items-start justify-between mb-4">
        <h2 className="text-lg font-bold text-slate-900 dark:text-white">
          {TEXTS.communityDetails}
        </h2>
        <button
          onClick={closeDetail}
          className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
        >
          <span className="material-symbols-outlined">close</span>
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-xs font-semibold text-slate-500 uppercase">{TEXTS.name}</label>
          <p className="text-slate-900 dark:text-white font-medium mt-1">
            {selectedCommunity.name || 'Unnamed Community'}
          </p>
        </div>

        <div>
          <label className="text-xs font-semibold text-slate-500 uppercase">{TEXTS.members}</label>
          <p className="text-2xl font-bold text-purple-600">
            {selectedCommunity.member_count}
          </p>
        </div>

        {selectedCommunity.summary && (
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase">{TEXTS.summary}</label>
            <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
              {selectedCommunity.summary}
            </p>
          </div>
        )}

        <div>
          <label className="text-xs font-semibold text-slate-500 uppercase">{TEXTS.uuid}</label>
          <p className="text-xs text-slate-500 dark:text-slate-400 font-mono break-all mt-1">
            {selectedCommunity.uuid}
          </p>
        </div>

        {selectedCommunity.created_at && (
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase">{TEXTS.created}</label>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {new Date(selectedCommunity.created_at).toLocaleString()}
            </p>
          </div>
        )}

        <div>
          <label className="text-xs font-semibold text-slate-500 uppercase">{TEXTS.tasks}</label>
          <div className="mt-2">
            <TaskList entityId={selectedCommunity.uuid} entityType="community" embedded />
          </div>
        </div>

        <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-3">
            {formatTemplate(TEXTS.communityMembers, { count: members.length })}
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
                  <div className="text-xs text-slate-500">
                    {member.entity_type}
                  </div>
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
            <p className="text-sm text-slate-500">{TEXTS.noMembers}</p>
          )}
        </div>
      </div>
    </div>
  )
})
Detail.displayName = 'CommunitiesList.Detail'

const TaskStatus: React.FC = memo(() => {
  const { currentTask, cancelTask, dismissTask } = useCommunitiesListContext()

  if (!currentTask) return null

  return (
    <div className={`rounded-lg p-4 border ${
      currentTask.status === 'completed' ? 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800' :
      currentTask.status === 'failed' ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800' :
      currentTask.status === 'running' ? 'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800' :
      'bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700'
    }`}>
      <div className="flex items-start gap-3">
        <span className={`material-symbols-outlined text-2xl ${
          currentTask.status === 'completed' ? 'text-green-600 dark:text-green-400' :
          currentTask.status === 'failed' ? 'text-red-600 dark:text-red-400' :
          currentTask.status === 'running' ? 'text-blue-600 dark:text-blue-400 animate-spin' :
          'text-slate-400'
        }`}>
          {currentTask.status === 'running' ? 'progress_activity' :
           currentTask.status === 'completed' ? 'check_circle' :
           currentTask.status === 'failed' ? 'error' : 'schedule'}
        </span>
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <h3 className={`font-semibold ${
              currentTask.status === 'completed' ? 'text-green-900 dark:text-green-300' :
              currentTask.status === 'failed' ? 'text-red-900 dark:text-red-300' :
              'text-slate-900 dark:text-white'
            }`}>
              {currentTask.status === 'running' ? 'Rebuilding Communities...' :
               currentTask.status === 'completed' ? 'Rebuild Completed Successfully' :
               currentTask.status === 'failed' ? 'Rebuild Failed' :
               'Rebuild Scheduled'}
            </h3>
            {(currentTask.status === 'running' || currentTask.status === 'pending') && (
              <button
                onClick={cancelTask}
                className="px-3 py-1 text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors"
              >
                {TEXTS.cancel}
              </button>
            )}
            {currentTask.status === 'failed' && (
              <button
                onClick={dismissTask}
                className="px-3 py-1 text-xs font-medium bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
              >
                {TEXTS.dismiss}
              </button>
            )}
          </div>
          <p className={`text-sm mt-1 ${
            currentTask.status === 'completed' ? 'text-green-800 dark:text-green-400' :
            currentTask.status === 'failed' ? 'text-red-800 dark:text-red-400' :
            'text-slate-600 dark:text-slate-400'
          }`}>
            {currentTask.message}
          </p>
          {currentTask.status === 'running' && currentTask.progress > 0 && (
            <div className="mt-2">
              <div className="flex items-center justify-between text-xs text-slate-600 dark:text-slate-400 mb-1">
                <span>{TEXTS.progress}</span>
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
                  <span className="text-slate-500 dark:text-slate-400">{TEXTS.communitiesCount}</span>
                  <p className="font-semibold text-slate-900 dark:text-white">
                    {currentTask.result.communities_count || 0}
                  </p>
                </div>
                <div>
                  <span className="text-slate-500 dark:text-slate-400">{TEXTS.connectionsCount}</span>
                  <p className="font-semibold text-slate-900 dark:text-white">
                    {currentTask.result.edges_count || 0}
                  </p>
                </div>
              </div>
            </div>
          )}
          {currentTask.error && currentTask.status === 'failed' && (
            <div className="mt-2 p-2 bg-red-100 dark:bg-red-900/30 rounded text-sm text-red-800 dark:text-red-400">
              <strong>{TEXTS.taskError}:</strong> {currentTask.error}
            </div>
          )}
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Task ID: <code className="font-mono">{currentTask.task_id}</code>
          </div>
        </div>
      </div>
    </div>
  )
})
TaskStatus.displayName = 'CommunitiesList.TaskStatus'

const Error: React.FC = memo(() => {
  const { error, clearError } = useCommunitiesListContext()

  if (!error) return null

  return (
    <div data-testid="error-message" className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 flex items-start gap-3">
      <span className="material-symbols-outlined text-red-600 dark:text-red-400">error</span>
      <div>
        <h3 className="font-semibold text-red-900 dark:text-red-300">{TEXTS.error}</h3>
        <p className="text-sm text-red-800 dark:text-red-400">{error}</p>
      </div>
      <button
        onClick={clearError}
        className="ml-auto text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
      >
        <span className="material-symbols-outlined">close</span>
      </button>
    </div>
  )
})
Error.displayName = 'CommunitiesList.Error'

// ========================================
// Info Component
// ========================================

const Info: React.FC = memo(() => {
  return (
    <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
      <div className="flex gap-3">
        <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-2xl">info</span>
        <div>
          <h3 className="text-sm font-semibold text-blue-900 dark:text-blue-300">
            {TEXTS.infoTitle}
          </h3>
          <p className="text-sm text-blue-800 dark:text-blue-400 mt-1">
            {TEXTS.infoDesc}
          </p>
        </div>
      </div>
    </div>
  )
})
Info.displayName = 'CommunitiesList.Info'

// ========================================
// Root Component (default export)
// ========================================

interface RootProps {
  projectId?: string
  limit?: number
  children?: React.ReactNode
}

const Root: React.FC<RootProps> = memo(({ children, projectId, limit }) => {
  return (
    <CommunitiesListProvider projectId={projectId} limit={limit}>
      {children ?? (
        <>
          <Header />
          <TaskStatus />
          <Error />
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
  )
})

Root.displayName = 'CommunitiesList'

// ========================================
// Compound Component Assembly
// ========================================

const CommunitiesList = Root as any

CommunitiesList.Header = Header
CommunitiesList.Stats = Stats
CommunitiesList.List = List
CommunitiesList.Pagination = Pagination
CommunitiesList.Detail = Detail
CommunitiesList.TaskStatus = TaskStatus
CommunitiesList.Error = Error
CommunitiesList.Info = Info
CommunitiesList.Root = Root
CommunitiesList.Provider = CommunitiesListProvider

export { CommunitiesList }
