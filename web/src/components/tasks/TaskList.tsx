/**
 * TaskList Component (Compound Components Pattern)
 *
 * Displays a list of background tasks with filtering, pagination, and actions.
 *
 * Compound Components:
 * - TaskList: Main container
 * - TaskList.Header: Search and filter controls
 * - TaskList.Item: Single task item
 * - TaskList.Pagination: Pagination controls
 * - TaskList.EmptyState: Empty state display
 */

import React, { useState, useCallback, useEffect, useMemo, createContext, useContext } from 'react'

import { format } from 'date-fns'
import {
  RefreshCw,
  Search,
  MoreVertical,
  ChevronLeft,
  ChevronRight,
  Ban
} from 'lucide-react'

import { taskAPI } from '../../services/api'

interface Task {
  id: string
  task_type?: string
  name: string
  status: string
  created_at: string
  completed_at?: string | null
  error?: string | null
  worker_id?: string | null
  retries?: number
  duration?: string | null
  entity_id?: string
  entity_type?: string
  // Computed properties
  statusColor?: string
  statusDot?: string
  formattedDate?: string
  shortId?: string
  canRetry?: boolean
  canStop?: boolean
}

interface TaskListContextValue {
  tasks: Task[]
  loading: boolean
  refreshing: boolean
  searchQuery: string
  setSearchQuery: (query: string) => void
  statusFilter: string
  setStatusFilter: (filter: string) => void
  offset: number
  setOffset: (offset: number) => void
  limit: number
  handleRefresh: () => void
  handleRetry: (taskId: string) => Promise<void>
  handleStop: (taskId: string) => Promise<void>
  entityId?: string
  entityType?: string
  embedded?: boolean
}

const TaskListContext = createContext<TaskListContextValue | null>(null)

const useTaskListContext = () => {
  const context = useContext(TaskListContext)
  if (!context) {
    throw new Error('TaskList compound components must be used within TaskList')
  }
  return context
}

interface TaskListProps {
  entityId?: string
  entityType?: string
  embedded?: boolean
}

// ============================================
// TaskList.Header
// ============================================

interface HeaderProps {
  children?: React.ReactNode
}

export const Header: React.FC<HeaderProps> = ({ children }) => {
  const { searchQuery, setSearchQuery, statusFilter, setStatusFilter, handleRefresh, refreshing } = useTaskListContext()

  return (
    <>
      {children || (
        <div className="p-4 border-b border-slate-200 dark:border-slate-700 flex flex-col sm:flex-row gap-4 justify-between items-center bg-slate-50/50 dark:bg-slate-800">
          <h3 className="text-slate-900 dark:text-white text-base font-bold whitespace-nowrap">Tasks</h3>
          <div className="flex flex-wrap gap-3 w-full sm:w-auto">
            <div className="relative grow sm:grow-0">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Search className="text-slate-400 size-5" />
              </div>
              <input
                className="block w-full sm:w-64 pl-10 pr-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg leading-5 bg-white dark:bg-slate-800 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary sm:text-sm dark:text-white transition-all"
                placeholder="Search Task ID or Name..."
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <select
              className="block w-auto pl-3 pr-10 py-2 text-base border-slate-300 dark:border-slate-600 focus:outline-none focus:ring-primary focus:border-primary sm:text-sm rounded-lg bg-white dark:bg-slate-800 dark:text-white"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option>All Statuses</option>
              <option>Completed</option>
              <option>Processing</option>
              <option>Failed</option>
              <option>Pending</option>
            </select>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="p-2 border border-slate-300 dark:border-slate-600 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw className={`size-5 ${refreshing ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ============================================
// TaskList.Item
// ============================================

interface ItemProps {
  task: Task
  children?: React.ReactNode
}

export const Item: React.FC<ItemProps> = ({ task, children }) => {
  const { handleRetry, handleStop, entityId } = useTaskListContext()

  return (
    <tr className="hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
      {children || (
        <>
          <td className="px-6 py-4 whitespace-nowrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${task.statusColor}`}>
              <span className={`size-1.5 rounded-full mr-1.5 ${task.status === 'Processing' ? 'animate-pulse' : ''} ${task.statusDot}`}></span>
              {task.status}
            </span>
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-300">
            {task.name}
            <div className="text-xs text-slate-400 font-mono mt-0.5">{task.shortId}...</div>
          </td>
          {!entityId && (
            <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400 font-mono">
              {task.entity_id ? `${task.entity_type}:${task.entity_id.substring(0, 8)}...` : '-'}
            </td>
          )}
          <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">
            {task.duration || '-'}
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500 dark:text-slate-400">
            {task.formattedDate}
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
            <div className="flex items-center justify-end gap-2">
              {task.canRetry && (
                <button
                  onClick={() => handleRetry(task.id)}
                  className="text-primary hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 font-medium text-xs mr-2"
                >
                  Retry
                </button>
              )}
              {task.canStop && (
                <button
                  onClick={() => handleStop(task.id)}
                  className="text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 font-medium text-xs mr-2 flex items-center gap-1"
                >
                  <Ban className="size-3" /> Stop
                </button>
              )}
              <button className="text-slate-500 hover:text-primary dark:text-slate-400 dark:hover:text-white">
                <MoreVertical className="size-5" />
              </button>
            </div>
          </td>
        </>
      )}
    </tr>
  )
}

// ============================================
// TaskList.Pagination
// ============================================

interface PaginationProps {
  children?: React.ReactNode
}

export const Pagination: React.FC<PaginationProps> = ({ children }) => {
  const { filteredTasks, offset, setOffset, limit, tasks } = useTaskListContext() as TaskListContextValue & { filteredTasks: Task[] }

  return (
    <>
      {children || (
        <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 flex items-center justify-between">
          <div className="text-sm text-slate-500 dark:text-slate-400">
            Showing {filteredTasks.length} tasks
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset === 0}
              className="px-3 py-1 border border-slate-200 dark:border-slate-600 rounded bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-300 text-sm hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50 flex items-center gap-1"
            >
              <ChevronLeft className="size-4" /> Previous
            </button>
            <button
              onClick={() => setOffset(offset + limit)}
              disabled={tasks.length < limit}
              className="px-3 py-1 border border-slate-200 dark:border-slate-600 rounded bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-300 text-sm hover:bg-slate-50 dark:hover:bg-slate-700 disabled:opacity-50 flex items-center gap-1"
            >
              Next <ChevronRight className="size-4" />
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ============================================
// TaskList.EmptyState
// ============================================

interface EmptyStateProps {
  children?: React.ReactNode
  colSpan?: number
}

export const EmptyState: React.FC<EmptyStateProps> = ({ children, colSpan = 6 }) => {
  return (
    <tr>
      <td colSpan={colSpan} className="px-6 py-12 text-center text-slate-500">
        {children || (
          <div className="flex flex-col items-center gap-2">
            <Search className="size-8 text-slate-300" />
            <p>No tasks found</p>
          </div>
        )}
      </td>
    </tr>
  )
}

// ============================================
// TaskList (Main Container)
// ============================================

const TaskListImpl: React.FC<TaskListProps> = ({ entityId, entityType, embedded = false }) => {
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // Filters
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('All Statuses')
  const [limit] = useState(50)
  const [offset, setOffset] = useState(0)

  const fetchTasks = useCallback(async () => {
    try {
      const data = await taskAPI.getRecentTasks({
        limit,
        offset,
        search: searchQuery || undefined,
        status: statusFilter !== 'All Statuses' ? statusFilter : undefined,
        task_type: entityType
      })
      const tasks: Task[] = data.map(item => ({
        id: item.id,
        task_type: item.task_type,
        name: item.task_type || item.id,
        status: item.status,
        created_at: item.created_at,
      }))
      setTasks(tasks)
      setLoading(false)
      setRefreshing(false)
    } catch (error) {
      console.error('Failed to fetch tasks:', error)
      setLoading(false)
      setRefreshing(false)
    }
  }, [limit, offset, searchQuery, statusFilter, entityType])

  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 5000)
    return () => clearInterval(interval)
  }, [fetchTasks])

  const handleRefresh = () => {
    setRefreshing(true)
    fetchTasks()
  }

  const handleRetry = async (taskId: string) => {
    try {
      await taskAPI.retryTask(taskId)
      fetchTasks()
    } catch (error) {
      console.error(`Failed to retry task ${taskId}:`, error)
      alert('Failed to retry task. Please try again.')
    }
  }

  const handleStop = async (taskId: string) => {
    if (!confirm('Are you sure you want to stop this task?')) return
    try {
      await taskAPI.stopTask(taskId)
      fetchTasks()
    } catch (error) {
      console.error(`Failed to stop task ${taskId}:`, error)
      alert('Failed to stop task. Please try again.')
    }
  }

  // Status color helpers
  const getStatusColor = useCallback((status: string): string => {
    const colorMap: Record<string, string> = {
      completed: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-200',
      failed: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200',
      processing: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-200',
      stopped: 'bg-gray-200 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
      pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-200',
    }
    return colorMap[status.toLowerCase()] || 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
  }, [])

  const getStatusDot = useCallback((status: string): string => {
    const dotMap: Record<string, string> = {
      completed: 'bg-green-600',
      failed: 'bg-red-600',
      processing: 'bg-blue-600',
      stopped: 'bg-gray-600',
      pending: 'bg-yellow-600',
    }
    return dotMap[status.toLowerCase()] || 'bg-gray-500'
  }, [])

  // Memoize filtered and formatted tasks
  const filteredTasks = useMemo(() => {
    return tasks.map(task => ({
      ...task,
      statusColor: getStatusColor(task.status),
      statusDot: getStatusDot(task.status),
      formattedDate: format(new Date(task.created_at), 'MMM d, HH:mm:ss'),
      shortId: task.id.substring(0, 8),
      canRetry: task.status === 'Failed',
      canStop: task.status === 'Pending' || task.status === 'Processing',
    }))
  }, [tasks, getStatusColor, getStatusDot])

  const contextValue: TaskListContextValue = {
    tasks,
    loading,
    refreshing,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    offset,
    setOffset,
    limit,
    handleRefresh,
    handleRetry,
    handleStop,
    entityId,
    entityType,
    embedded,
  }

  // Provide filteredTasks to child components through context
  ;(contextValue as any).filteredTasks = filteredTasks

  if (loading && !tasks.length) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <TaskListContext.Provider value={contextValue}>
      <div className={`flex flex-col rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-sm overflow-hidden ${embedded ? 'border-0 shadow-none' : ''}`}>
        {!embedded && <Header />}

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-700">
            <thead className="bg-slate-50 dark:bg-slate-800/50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider" scope="col">Status</th>
                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider" scope="col">Type</th>
                {!entityId && (
                  <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider" scope="col">Entity</th>
                )}
                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider" scope="col">Duration</th>
                <th className="px-6 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider" scope="col">Timestamp</th>
                <th className="relative px-6 py-3" scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="bg-white dark:bg-slate-800 divide-y divide-slate-200 dark:divide-slate-700">
              {filteredTasks.length > 0 ? (
                filteredTasks.map((task) => (
                  <Item key={task.id} task={task} />
                ))
              ) : (
                <EmptyState colSpan={entityId ? 5 : 6} />
              )}
            </tbody>
          </table>
        </div>

        {!embedded && <Pagination />}
      </div>
    </TaskListContext.Provider>
  )
}

// Attach compound components
const TaskList = Object.assign(TaskListImpl, {
  Header,
  Item,
  Pagination,
  EmptyState,
})

export default TaskList
export { TaskList }
