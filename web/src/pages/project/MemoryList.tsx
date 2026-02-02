import React, { useEffect, useState, useCallback, useRef, memo } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useLazyMessage } from '@/components/ui/lazyAntd'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useDebounce } from 'use-debounce'
import { memoryAPI } from '../../services/api'
import { Memory } from '../../types/memory'
import { DeleteConfirmationModal } from '@/components/shared/modals/DeleteConfirmationModal'
import { subscribeToTask, TaskStatus } from '../../hooks/useTaskSSE'

// Track task progress for each memory
interface MemoryTaskProgress {
    [memoryId: string]: {
        progress: number;
        message: string;
        taskId: string;
    };
}

// Helper to get processing status styles - replaces nested ternaries for readability
const getProcessingStatusStyles = (status: string | undefined) => {
    switch (status) {
        case 'FAILED':
            return {
                badge: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
                dot: 'bg-red-500'
            };
        case 'COMPLETED':
            return {
                badge: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
                dot: 'bg-green-500'
            };
        default:
            return {
                badge: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
                dot: 'bg-yellow-500 animate-pulse'
            };
    }
};

const MemoryListInternal: React.FC = () => {
    const { t } = useTranslation()
    const message = useLazyMessage()
    const { projectId } = useParams()
    const [memories, setMemories] = useState<Memory[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const [fetchError, setFetchError] = useState<string | null>(null)
    const [searchInput, setSearchInput] = useState('') // Input state (immediate)
    const [deletingId, setDeletingId] = useState<string | null>(null)
    const [deleteModalOpen, setDeleteModalOpen] = useState(false)
    const [itemToDelete, setItemToDelete] = useState<string | null>(null)
    const [taskProgress, setTaskProgress] = useState<MemoryTaskProgress>({})
    const sseCleanupRef = useRef<Map<string, () => void>>(new Map())

    // Debounced search value for filtering (300ms delay)
    const [debouncedSearch] = useDebounce(searchInput, 300)

    // Filter memories client-side by title and content type (uses debounced search)
    const filteredMemories = memories.filter(m =>
        m.title?.toLowerCase().includes(debouncedSearch.toLowerCase()) ||
        m.content_type?.toLowerCase().includes(debouncedSearch.toLowerCase())
    )

    // Virtual row height (estimated)
    const ROW_HEIGHT = 80
    const parentRef = useRef<HTMLDivElement>(null)

    // Virtual list for memory rows
    const virtualizer = useVirtualizer({
        count: filteredMemories.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => ROW_HEIGHT,
        overscan: 5,
    })

    const fetchMemories = useCallback(async () => {
        if (projectId) {
            setIsLoading(true)
            setFetchError(null)
            try {
                const data = await memoryAPI.list(projectId, {
                    page_size: 100
                })
                setMemories(data.memories || [])
            } catch (error) {
                console.error('Failed to list memories:', error)
                setFetchError(t('project.memories.errors.loadFailed', 'Failed to load memories. Please check your connection and try again.'))
            } finally {
                setIsLoading(false)
            }
        }
    }, [projectId, t])

    // Subscribe to SSE for processing memories
    // Using memory.id and memory.task_id as parameters to avoid stale closure issues
    const subscribeToMemoryTask = useCallback((memoryId: string, taskId: string) => {
        if (!taskId) return;

        // Don't re-subscribe if already subscribed
        if (sseCleanupRef.current.has(memoryId)) return;

        console.log(`📡 Subscribing to SSE for memory ${memoryId}, task ${taskId}`);

        const cleanup = subscribeToTask(taskId, {
            onProgress: (task: TaskStatus) => {
                setTaskProgress(prev => ({
                    ...prev,
                    [memoryId]: {
                        progress: task.progress,
                        message: task.message,
                        taskId: task.task_id,
                    }
                }));
            },
            onCompleted: () => {
                console.log(`✅ Memory ${memoryId} processing completed`);
                // Update memory status locally
                setMemories(prev => prev.map(m =>
                    m.id === memoryId ? { ...m, processing_status: 'COMPLETED' } : m
                ));
                // Clear progress
                setTaskProgress(prev => {
                    const newProgress = { ...prev };
                    delete newProgress[memoryId];
                    return newProgress;
                });
                // Cleanup subscription
                sseCleanupRef.current.delete(memoryId);
            },
            onFailed: () => {
                console.log(`❌ Memory ${memoryId} processing failed`);
                setMemories(prev => prev.map(m =>
                    m.id === memoryId ? { ...m, processing_status: 'FAILED' } : m
                ));
                setTaskProgress(prev => {
                    const newProgress = { ...prev };
                    delete newProgress[memoryId];
                    return newProgress;
                });
                sseCleanupRef.current.delete(memoryId);
            },
            onError: () => {
                // On error, fall back to polling
                sseCleanupRef.current.delete(memoryId);
            }
        });

        sseCleanupRef.current.set(memoryId, cleanup);
    }, []);

    // Cleanup all SSE connections on unmount
    useEffect(() => {
        const cleanupMap = sseCleanupRef.current;
        return () => {
            cleanupMap.forEach(cleanup => cleanup());
            cleanupMap.clear();
        };
    }, []);

    // Subscribe to SSE for memories with PENDING/PROCESSING status
    useEffect(() => {
        memories.forEach(memory => {
            if ((memory.processing_status === 'PENDING' || memory.processing_status === 'PROCESSING') && memory.task_id) {
                subscribeToMemoryTask(memory.id, memory.task_id);
            } else if (memory.processing_status === 'COMPLETED' || memory.processing_status === 'FAILED') {
                // Cleanup stale SSE connections for memories that are no longer processing
                const cleanup = sseCleanupRef.current.get(memory.id);
                if (cleanup) {
                    cleanup();
                    sseCleanupRef.current.delete(memory.id);
                }
            }
        });
    }, [memories, subscribeToMemoryTask]);

    // Fallback polling for processing status (less frequent when SSE is active)
    useEffect(() => {
        let interval: NodeJS.Timeout

        // Check if any memories are processing or pending without SSE connection
        const hasProcessingMemories = memories.some(m =>
            (m.processing_status === 'PROCESSING' || m.processing_status === 'PENDING') &&
            !sseCleanupRef.current.has(m.id)
        )

        if (hasProcessingMemories && projectId) {
            interval = setInterval(async () => {
                try {
                    const data = await memoryAPI.list(projectId, {
                        page_size: 100
                    })
                    setMemories(data.memories || [])
                } catch (error) {
                    console.error('Failed to poll memories:', error)
                }
            }, 10000) // Poll every 10 seconds as fallback when SSE is not available
        }

        return () => {
            if (interval) clearInterval(interval)
        }
    }, [memories, projectId])

    useEffect(() => {
        fetchMemories()
    }, [fetchMemories])

    const confirmDelete = (memoryId: string) => {
        setItemToDelete(memoryId)
        setDeleteModalOpen(true)
    }

    const handleDelete = async () => {
        if (!itemToDelete || !projectId) return

        setDeletingId(itemToDelete)
        try {
            await memoryAPI.delete(projectId, itemToDelete)
            await fetchMemories()
            setDeleteModalOpen(false)
            setItemToDelete(null)
        } catch (error) {
            console.error('Failed to delete memory:', error)
            message?.error(t('project.memories.errors.deleteFailed', 'Failed to delete memory'))
        } finally {
            setDeletingId(null)
        }
    }

    const handleReprocess = async (memoryId: string) => {
        if (!projectId) return
        try {
            await memoryAPI.reprocess(projectId, memoryId)
            // Optimistically update status
            setMemories(prev => prev.map(m =>
                m.id === memoryId ? { ...m, processing_status: 'PENDING' } : m
            ))
        } catch (error) {
            console.error('Failed to reprocess:', error)
            message?.error(t('project.memories.errors.reprocessFailed', 'Failed to start processing. Please try again.'))
        }
    }

    // Memoized row renderer for virtualized list
    // Must be before early returns to follow rules of hooks
    const VirtualRow = useCallback(({ index, memory }: { index: number; memory: Memory }) => (
        <tr
            key={memory.id}
            className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors group"
            style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${index * ROW_HEIGHT}px)`,
            }}
        >
            <td className="px-6 py-3">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400">
                        <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>description</span>
                    </div>
                    <div>
                        <Link to={`/project/${projectId}/memory/${memory.id}`} className="font-medium text-slate-900 dark:text-white hover:text-primary transition-colors">
                            {memory.title || 'Untitled'}
                        </Link>
                        <div className="text-xs text-slate-500">
                            <span className="font-mono opacity-70">{memory.id.substring(0, 8)}...</span>
                        </div>
                    </div>
                </div>
            </td>
            <td className="px-6 py-3 text-slate-600 dark:text-slate-300 capitalize">
                {memory.content_type || 'Unknown'}
            </td>
            <td className="px-6 py-3">
                <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${memory.status === 'DISABLED'
                    ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    : 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                    }`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${memory.status === 'DISABLED' ? 'bg-red-500' : 'bg-green-500'
                        }`}></span>
                    {memory.status || 'ENABLED'}
                </span>
            </td>
            <td className="px-6 py-3">
                <div className="flex flex-col gap-1">
                    {(() => {
                        const statusStyles = getProcessingStatusStyles(memory.processing_status);
                        return (
                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${statusStyles.badge}`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${statusStyles.dot}`}></span>
                                {taskProgress[memory.id]
                                    ? `${taskProgress[memory.id].progress}%`
                                    : (memory.processing_status || 'PENDING')
                                }
                            </span>
                        );
                    })()}
                    {taskProgress[memory.id] && (
                        <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                            <div
                                className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300 ease-out"
                                style={{ width: `${taskProgress[memory.id].progress}%` }}
                            />
                        </div>
                    )}
                </div>
            </td>
            <td className="px-6 py-3 text-slate-600 dark:text-slate-300 text-right">
                {memory.created_at ? new Date(memory.created_at).toLocaleDateString() : '-'}
            </td>
            <td className="px-6 py-3 text-right">
                <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                        onClick={() => handleReprocess(memory.id)}
                        className="text-slate-400 hover:text-primary p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                        title={t('project.memories.actions.reprocess')}
                    >
                        <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>refresh</span>
                    </button>
                    <button
                        onClick={() => confirmDelete(memory.id)}
                        disabled={deletingId === memory.id}
                        className="text-slate-400 hover:text-red-500 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                        title={t('common.delete')}
                    >
                        {deletingId === memory.id ? (
                            <span className="material-symbols-outlined animate-spin" style={{ fontSize: '20px' }}>progress_activity</span>
                        ) : (
                            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>delete</span>
                        )}
                    </button>
                </div>
            </td>
        </tr>
    ), [projectId, taskProgress, deletingId, t, handleReprocess, confirmDelete])

    if (!projectId) {
        return <div className="p-8 text-center text-slate-500">Project not found</div>
    }

    return (
        <div className="max-w-7xl mx-auto flex flex-col gap-8">
            {deleteModalOpen && (
                <DeleteConfirmationModal
                    isOpen={deleteModalOpen}
                    onClose={() => {
                        if (!deletingId) {
                            setDeleteModalOpen(false)
                            setItemToDelete(null)
                        }
                    }}
                    onConfirm={handleDelete}
                    title={t('common.actions.deleteMemory')}
                    message={t('common.actions.deleteMemoryConfirm')}
                    isDeleting={!!deletingId}
                />
            )}
            {/* Header Area */}
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex flex-col gap-1">
                    <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">{t('project.memories.title')}</h1>
                    <p className="text-sm text-slate-500">{t('project.memories.subtitle')}</p>
                </div>
                <Link to={`/project/${projectId}/memories/new`}>
                    <button className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white px-5 py-2.5 rounded-lg text-sm font-medium shadow-lg shadow-primary/20 flex items-center gap-2 transition-all active:scale-95">
                        <span className="material-symbols-outlined text-lg">add</span>
                        {t('project.memories.addMemory')}
                    </button>
                </Link>
            </div>

            {/* Toolbar */}
            <div className="flex flex-col md:flex-row gap-4 justify-between items-center bg-white dark:bg-surface-dark p-2 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
                {/* Search */}
                <div className="relative w-full md:max-w-md">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <span className="material-symbols-outlined text-slate-400">search</span>
                    </div>
                    <input
                        type="text"
                        value={searchInput}
                        onChange={(e) => setSearchInput(e.target.value)}
                        className="block w-full pl-10 pr-3 py-2.5 border-none rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-primary/20 focus:bg-white dark:focus:bg-slate-700 transition-all outline-none"
                        placeholder={t('project.memories.searchPlaceholder')}
                    />
                </div>
                {/* Filters */}
                <div className="flex items-center gap-2 w-full md:w-auto overflow-x-auto pb-2 md:pb-0 px-2 md:px-0">
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-1">{t('tenant.projects.filter')}</span>
                    <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary/10 text-primary border border-primary/20 text-sm font-medium whitespace-nowrap transition-colors">
                        {t('project.memories.filter.all_types')}
                        <span className="material-symbols-outlined text-lg">arrow_drop_down</span>
                    </button>
                </div>
            </div>

            {/* Memories List */}
            <div className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm overflow-hidden">
                {fetchError ? (
                    <div className="p-8 text-center">
                        <div className="flex flex-col items-center gap-4">
                            <span className="material-symbols-outlined text-red-500 text-4xl">error</span>
                            <p className="text-red-600 dark:text-red-400">{fetchError}</p>
                            <button
                                onClick={() => fetchMemories()}
                                className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors"
                            >
                                {t('common.retry', 'Retry')}
                            </button>
                        </div>
                    </div>
                ) : isLoading ? (
                    <div className="p-10 text-center text-slate-500">{t('common.loading')}</div>
                ) : filteredMemories.length === 0 ? (
                    <div className="p-8 text-center text-slate-500">
                        {t('project.memories.noMemories')}
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left text-sm">
                            <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-10">
                                <tr>
                                    <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">{t('common.forms.name')}</th>
                                    <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">{t('common.forms.type')}</th>
                                    <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">{t('project.memories.dataStatus')}</th>
                                    <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">{t('project.memories.processing')}</th>
                                    <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400 text-right">{t('project.memories.columns.created')}</th>
                                    <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400"></th>
                                </tr>
                            </thead>
                        </table>
                        {/* Virtualized list container */}
                        <div
                            ref={parentRef}
                            className="overflow-auto"
                            style={{ height: `${Math.min(filteredMemories.length * ROW_HEIGHT, 600)}px` }}
                        >
                            <table className="w-full text-left text-sm" style={{ position: 'relative', height: `${virtualizer.getTotalSize()}px` }}>
                                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                                    {virtualizer.getVirtualItems().map((virtualRow) => (
                                        <VirtualRow
                                            key={virtualRow.key}
                                            index={virtualRow.index}
                                            memory={filteredMemories[virtualRow.index]}
                                        />
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

/**
 * Memoized MemoryList page component.
 * Prevents unnecessary re-renders when parent components update.
 */
export const MemoryList = memo(MemoryListInternal)
