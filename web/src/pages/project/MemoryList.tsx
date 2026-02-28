/**
 * MemoryList Compound Component
 *
 * A compound component pattern for managing Memories with modular sub-components.
 * Features virtual list rendering, SSE progress tracking, and search/filter.
 *
 * @example
 * ```tsx
 * import { MemoryList } from './MemoryList';
 *
 * <MemoryList />
 * ```
 */

import React, { useCallback, useEffect, useState, useMemo, useContext, useRef, memo } from 'react';

import { useParams, Link } from 'react-router-dom';

import { useVirtualizer } from '@tanstack/react-virtual';
import { useDebounce } from 'use-debounce';

import { formatDateOnly } from '@/utils/date';

import { memoryAPI } from '../../services/api';
import { Memory } from '../../types/memory';

// ============================================================================
// Types
// ============================================================================

export interface MemoryTaskProgress {
  [memoryId: string]: {
    progress: number;
    message: string;
    taskId: string;
  };
}

// ============================================================================
// Constants
// ============================================================================

const TEXTS = {
  title: 'Memories',
  subtitle: 'All stored memories in your knowledge graph',
  addMemory: 'Add Memory',
  searchPlaceholder: 'Search memories...',
  filterLabel: 'Filter',
  allTypes: 'All Types',
  noMemories: 'No memories yet. Create your first memory to get started.',
  loading: 'Loading...',
  projectNotFound: 'Project not found',
  retry: 'Retry',

  // Table headers
  tableName: 'Name',
  tableType: 'Type',
  tableStatus: 'Status',
  tableProcessing: 'Processing',
  tableCreated: 'Created',

  // Status badges
  statusEnabled: 'Enabled',
  statusDisabled: 'Disabled',
  statusCompleted: 'Completed',
  statusProcessing: 'Processing',
  statusFailed: 'Failed',
  statusPending: 'Pending',

  // Delete modal
  deleteTitle: 'Delete Memory',
  deleteMessage: 'Are you sure you want to delete this memory? This action cannot be undone.',
  deleteConfirm: 'Delete',
  deleteCancel: 'Cancel',

  // Actions
  deleteMemory: 'Delete memory',
  reprocess: 'Reprocess',
};

const ROW_HEIGHT = 80;

// ============================================================================
// Helper Functions
// ============================================================================

const getProcessingStatusStyles = (status: string | undefined) => {
  switch (status) {
    case 'FAILED':
      return {
        badge: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
        dot: 'bg-red-500',
      };
    case 'COMPLETED':
      return {
        badge: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
        dot: 'bg-green-500',
      };
    default:
      return {
        badge: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
        dot: 'bg-yellow-500 animate-pulse',
      };
  }
};

// ============================================================================
// Marker Symbols
// ============================================================================

const HeaderMarker = Symbol('MemoryList.Header');
const ToolbarMarker = Symbol('MemoryList.Toolbar');
const VirtualListMarker = Symbol('MemoryList.VirtualList');
const MemoryRowMarker = Symbol('MemoryList.MemoryRow');
const StatusBadgeMarker = Symbol('MemoryList.StatusBadge');
const EmptyMarker = Symbol('MemoryList.Empty');
const LoadingMarker = Symbol('MemoryList.Loading');
const ErrorMarker = Symbol('MemoryList.Error');
const DeleteModalMarker = Symbol('MemoryList.DeleteModal');

// ============================================================================
// Context
// ============================================================================

interface MemoryListState {
  memories: Memory[];
  isLoading: boolean;
  fetchError: string | null;
  search: string;
  debouncedSearch: string;
  deletingId: string | null;
  isDeleteModalOpen: boolean;
  memoryToDelete: Memory | null;
  taskProgress: MemoryTaskProgress;
}

interface MemoryListActions {
  setSearch: (search: string) => void;
  confirmDelete: (memory: Memory) => void;
  handleDelete: () => Promise<void>;
  handleReprocess: (id: string) => Promise<void>;
  fetchMemories: () => Promise<void>;
  closeDeleteModal: () => void;
  setTaskProgress: React.Dispatch<React.SetStateAction<MemoryTaskProgress>>;
}

interface MemoryListContextType {
  state: MemoryListState;
  actions: MemoryListActions;
  projectId: string;
}

const MemoryListContext = React.createContext<MemoryListContextType | null>(null);

const useMemoryListContext = (): MemoryListContextType => {
  const context = useContext(MemoryListContext);
  if (!context) {
    throw new Error('MemoryList sub-components must be used within MemoryList');
  }
  return context;
};

// Optional hook for testing
const useMemoryListContextOptional = (): MemoryListContextType | null => {
  return useContext(MemoryListContext);
};

// ============================================================================
// Main Component
// ============================================================================

interface MemoryListProps {
  className?: string | undefined;
}

const MemoryListInternal: React.FC<MemoryListProps> = ({ className = '' }) => {
  const { projectId } = useParams<{ projectId: string }>();

  // State
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebounce(search, 300);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [memoryToDelete, setMemoryToDelete] = useState<Memory | null>(null);
  const [taskProgress, setTaskProgress] = useState<MemoryTaskProgress>({});

  const parentRef = useRef<HTMLDivElement>(null);

  // Filter memories
  const filteredMemories = useMemo(() => {
    if (!debouncedSearch) return memories;
    const lowerSearch = debouncedSearch.toLowerCase();
    return memories.filter(
      (m) =>
        m.title?.toLowerCase().includes(lowerSearch) ||
        m.content_type?.toLowerCase().includes(lowerSearch)
    );
  }, [memories, debouncedSearch]);

  // Virtual list
  const virtualizer = useVirtualizer({
    count: filteredMemories.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 5,
  });

  // Fetch memories
  const fetchMemories = useCallback(async () => {
    if (!projectId) return;
    setIsLoading(true);
    setFetchError(null);
    try {
      const data = await memoryAPI.list(projectId, { page_size: 100 });
      setMemories(data.memories || []);
    } catch (error) {
      console.error('Failed to list memories:', error);
      setFetchError('Failed to load memories. Please check your connection and try again.');
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  // Delete handlers
  const confirmDelete = useCallback((memory: Memory) => {
    setMemoryToDelete(memory);
    setIsDeleteModalOpen(true);
  }, []);

  const closeDeleteModal = useCallback(() => {
    if (!deletingId) {
      setIsDeleteModalOpen(false);
      setMemoryToDelete(null);
    }
  }, [deletingId]);

  const handleDelete = useCallback(async () => {
    if (!memoryToDelete || !projectId) return;
    setDeletingId(memoryToDelete.id);
    try {
      await memoryAPI.delete(projectId, memoryToDelete.id);
      await fetchMemories();
      setIsDeleteModalOpen(false);
      setMemoryToDelete(null);
    } catch (error) {
      console.error('Failed to delete memory:', error);
    } finally {
      setDeletingId(null);
    }
  }, [memoryToDelete, projectId, fetchMemories]);

  const handleReprocess = useCallback(
    async (id: string) => {
      if (!projectId) return;
      try {
        await memoryAPI.reprocess(projectId, id);
        setMemories((prev) =>
          prev.map((m) => (m.id === id ? { ...m, processing_status: 'PENDING' } : m))
        );
      } catch (error) {
        console.error('Failed to reprocess:', error);
      }
    },
    [projectId]
  );

  // Initial fetch
  useEffect(() => {
    fetchMemories();
  }, [fetchMemories]);

  // Context value
  const state: MemoryListState = {
    memories,
    isLoading,
    fetchError,
    search,
    debouncedSearch,
    deletingId,
    isDeleteModalOpen,
    memoryToDelete,
    taskProgress,
  };

  const actions: MemoryListActions = {
    setSearch,
    confirmDelete,
    handleDelete,
    handleReprocess,
    fetchMemories,
    closeDeleteModal,
    setTaskProgress,
  };

  if (!projectId) {
    return <MemoryList.Error error={TEXTS.projectNotFound} />;
  }

  return (
    <MemoryListContext.Provider value={{ state, actions, projectId }}>
      <div className={className || 'max-w-7xl mx-auto flex flex-col gap-8'}>
        <MemoryList.Header />
        <MemoryList.Toolbar />
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm overflow-hidden">
          {fetchError ? (
            <MemoryList.Error error={fetchError} onRetry={actions.fetchMemories} />
          ) : isLoading ? (
            <MemoryList.Loading />
          ) : filteredMemories.length === 0 ? (
            <MemoryList.Empty />
          ) : (
            <MemoryList.VirtualList
              parentRef={parentRef}
              virtualizer={virtualizer}
              filteredMemories={filteredMemories}
              totalSize={virtualizer.getTotalSize()}
            />
          )}
        </div>
        {isDeleteModalOpen && memoryToDelete && (
          <MemoryList.DeleteModal
            isOpen={isDeleteModalOpen}
            onClose={closeDeleteModal}
            onConfirm={handleDelete}
            memoryTitle={memoryToDelete.title || 'Untitled'}
            isDeleting={deletingId === memoryToDelete.id}
          />
        )}
      </div>
    </MemoryListContext.Provider>
  );
};

MemoryListInternal.displayName = 'MemoryList';

// ============================================================================
// Header Sub-Component
// ============================================================================

interface HeaderProps {
  className?: string | undefined;
  projectId?: string | undefined;
}

const HeaderInternal: React.FC<HeaderProps> = ({ className = '', projectId: propProjectId }) => {
  const context = useMemoryListContextOptional();
  const projectId = propProjectId ?? context?.projectId ?? 'test-project-1';

  return (
    <div className={`flex flex-wrap items-center justify-between gap-4 ${className}`}>
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
          {TEXTS.title}
        </h1>
        <p className="text-sm text-slate-500">{TEXTS.subtitle}</p>
      </div>
      <Link to={`/project/${projectId}/memories/new`}>
        <button className="flex items-center gap-2 bg-blue-600 dark:bg-blue-700 hover:bg-blue-700 text-white px-5 py-2.5 rounded-lg text-sm font-medium shadow-lg shadow-blue-900/20 transition-all active:scale-95">
          <span className="material-symbols-outlined text-lg">add</span>
          <span>{TEXTS.addMemory}</span>
        </button>
      </Link>
    </div>
  );
};

HeaderInternal.displayName = 'MemoryList.Header';

// ============================================================================
// Toolbar Sub-Component
// ============================================================================

interface ToolbarProps {
  className?: string | undefined;
  search?: string | undefined;
  onSearchChange?: ((value: string) => void) | undefined;
}

const ToolbarInternal: React.FC<ToolbarProps> = ({
  className = '',
  search: propSearch,
  onSearchChange: propOnSearchChange,
}) => {
  const context = useMemoryListContextOptional();
  const search = propSearch ?? context?.state.search ?? '';
  const onSearchChange = propOnSearchChange ?? context?.actions.setSearch;

  return (
    <div
      className={`flex flex-col md:flex-row gap-4 justify-between items-center bg-white dark:bg-surface-dark p-2 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm ${className}`}
    >
      <div className="relative w-full md:max-w-md">
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <span className="material-symbols-outlined text-slate-400">search</span>
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange?.(e.target.value)}
          className="block w-full pl-10 pr-3 py-2.5 border-none rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-blue-600/20 focus:bg-white dark:focus:bg-slate-700 transition-all outline-none"
          placeholder={TEXTS.searchPlaceholder}
        />
      </div>
      <div className="flex items-center gap-2 w-full md:w-auto overflow-x-auto pb-2 md:pb-0 px-2 md:px-0">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-1">
          {TEXTS.filterLabel}
        </span>
        <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-600/10 text-blue-600 dark:text-blue-400 border border-blue-600/20 text-sm font-medium whitespace-nowrap transition-colors">
          {TEXTS.allTypes}
          <span className="material-symbols-outlined text-lg">arrow_drop_down</span>
        </button>
      </div>
    </div>
  );
};

ToolbarInternal.displayName = 'MemoryList.Toolbar';

// ============================================================================
// VirtualList Sub-Component
// ============================================================================

interface VirtualListProps {
  parentRef: React.RefObject<HTMLDivElement | null>;
  virtualizer: ReturnType<typeof useVirtualizer<HTMLDivElement, Element>>;
  filteredMemories: Memory[];
  totalSize: number;
  className?: string | undefined;
}

const VirtualListInternal: React.FC<VirtualListProps> = memo(
  ({ parentRef, virtualizer, filteredMemories, totalSize, className = '' }) => {
    const { state: _state, actions: _actions, projectId: _projectId } = useMemoryListContext();

    return (
      <div className={`overflow-x-auto ${className}`}>
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-10">
            <tr>
              <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {TEXTS.tableName}
              </th>
              <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {TEXTS.tableType}
              </th>
              <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {TEXTS.tableStatus}
              </th>
              <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {TEXTS.tableProcessing}
              </th>
              <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400 text-right">
                {TEXTS.tableCreated}
              </th>
              <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400"></th>
            </tr>
          </thead>
        </table>
        <div
          ref={parentRef}
          className="overflow-auto"
          style={{ height: `${Math.min(filteredMemories.length * ROW_HEIGHT, 600)}px` }}
        >
          <table
            className="w-full text-left text-sm"
            style={{ position: 'relative', height: `${totalSize}px` }}
          >
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const memory = filteredMemories[virtualRow.index];
                return memory ? (
                  <MemoryList.MemoryRow
                    key={virtualRow.key}
                    memory={memory}
                    index={virtualRow.index}
                  />
                ) : null;
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  }
);

VirtualListInternal.displayName = 'MemoryList.VirtualList';

// ============================================================================
// StatusBadge Sub-Component
// ============================================================================

interface StatusBadgeProps {
  status?: string | undefined;
  progress?: number | undefined;
  className?: string | undefined;
}

const getStatusText = (status: string | undefined): string => {
  switch (status) {
    case 'COMPLETED':
      return TEXTS.statusCompleted;
    case 'PROCESSING':
      return TEXTS.statusProcessing;
    case 'FAILED':
      return TEXTS.statusFailed;
    case 'PENDING':
      return TEXTS.statusPending;
    default:
      return TEXTS.statusPending;
  }
};

const StatusBadgeInternal: React.FC<StatusBadgeProps> = memo(
  ({ status, progress, className = '' }) => {
    const styles = getProcessingStatusStyles(status);

    return (
      <div className={`flex flex-col gap-1 ${className}`}>
        <span
          className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${styles.badge}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`}></span>
          {progress !== undefined ? `${progress}%` : getStatusText(status)}
        </span>
        {progress !== undefined && (
          <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}
      </div>
    );
  }
);

StatusBadgeInternal.displayName = 'MemoryList.StatusBadge';

// ============================================================================
// MemoryRow Sub-Component
// ============================================================================

interface MemoryRowProps {
  memory: Memory;
  index: number;
  onDelete?: ((memory: Memory) => void) | undefined;
  projectId?: string | undefined;
}

const MemoryRowInternal: React.FC<MemoryRowProps> = memo(
  ({ memory, index, onDelete: propOnDelete, projectId: propProjectId }) => {
    const context = useMemoryListContextOptional();
    const state = context?.state;
    const actions = context?.actions;
    const projectId = propProjectId ?? context?.projectId ?? 'test-project-1';
    const onDelete = propOnDelete ?? actions?.confirmDelete;
    const progress = state?.taskProgress[memory.id]?.progress;

    return (
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
              <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
                description
              </span>
            </div>
            <div>
              <Link
                to={`/project/${projectId}/memory/${memory.id}`}
                className="font-medium text-slate-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
              >
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
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
              memory.status === 'DISABLED'
                ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                : 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${memory.status === 'DISABLED' ? 'bg-red-500' : 'bg-green-500'}`}
            ></span>
            {memory.status || TEXTS.statusEnabled}
          </span>
        </td>
        <td className="px-6 py-3">
          <MemoryList.StatusBadge status={memory.processing_status} progress={progress} />
        </td>
        <td className="px-6 py-3 text-slate-600 dark:text-slate-300 text-right">
          {memory.created_at ? formatDateOnly(memory.created_at) : '-'}
        </td>
        <td className="px-6 py-3 text-right">
          <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
            {actions && (
              <button
                onClick={() => actions.handleReprocess(memory.id)}
                className="text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                title={TEXTS.reprocess}
              >
                <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
                  refresh
                </span>
              </button>
            )}
            {onDelete && (
              <button
                onClick={() => {
                  onDelete(memory);
                }}
                disabled={state?.deletingId === memory.id}
                className="text-slate-400 hover:text-red-500 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                title={TEXTS.deleteMemory}
              >
                {state?.deletingId === memory.id ? (
                  <span
                    className="material-symbols-outlined animate-spin"
                    style={{ fontSize: '20px' }}
                  >
                    progress_activity
                  </span>
                ) : (
                  <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
                    delete
                  </span>
                )}
              </button>
            )}
          </div>
        </td>
      </tr>
    );
  }
);

MemoryRowInternal.displayName = 'MemoryList.MemoryRow';

// ============================================================================
// Empty Sub-Component
// ============================================================================

const EmptyInternal: React.FC<{ className?: string | undefined }> = ({ className = '' }) => (
  <div className={`p-8 text-center text-slate-500 ${className}`}>{TEXTS.noMemories}</div>
);

EmptyInternal.displayName = 'MemoryList.Empty';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC<{ className?: string | undefined }> = ({ className = '' }) => (
  <div className={`p-10 text-center text-slate-500 ${className}`}>{TEXTS.loading}</div>
);

LoadingInternal.displayName = 'MemoryList.Loading';

// ============================================================================
// Error Sub-Component
// ============================================================================

interface ErrorProps {
  error: string;
  onRetry?: (() => void) | undefined;
  className?: string | undefined;
}

const ErrorInternal: React.FC<ErrorProps> = ({ error, onRetry, className = '' }) => (
  <div className={`p-8 text-center ${className}`}>
    <div className="flex flex-col items-center gap-4">
      <span className="material-symbols-outlined text-red-500 text-4xl">error</span>
      <p className="text-red-600 dark:text-red-400">{error}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          {TEXTS.retry}
        </button>
      )}
    </div>
  </div>
);

ErrorInternal.displayName = 'MemoryList.Error';

// ============================================================================
// DeleteModal Sub-Component
// ============================================================================

interface DeleteModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  memoryTitle: string;
  isDeleting?: boolean | undefined;
  className?: string | undefined;
}

const DeleteModalInternal: React.FC<DeleteModalProps> = memo(
  ({ isOpen, onClose, onConfirm, memoryTitle, isDeleting = false, className = '' }) => {
    if (!isOpen) return null;

    return (
      <div
        className={`fixed inset-0 z-50 flex items-center justify-center bg-black/50 ${className}`}
      >
        <div className="bg-white dark:bg-surface-dark rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
            {TEXTS.deleteTitle}
          </h3>
          <p className="text-slate-600 dark:text-slate-300 mb-6">
            {TEXTS.deleteMessage}
            <br />
            <span className="font-medium text-slate-900 dark:text-white">"{memoryTitle}"</span>
          </p>
          <div className="flex justify-end gap-3">
            <button
              onClick={onClose}
              disabled={isDeleting}
              className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
            >
              {TEXTS.deleteCancel}
            </button>
            <button
              onClick={onConfirm}
              disabled={isDeleting}
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
            >
              {isDeleting ? TEXTS.loading : TEXTS.deleteConfirm}
            </button>
          </div>
        </div>
      </div>
    );
  }
);

DeleteModalInternal.displayName = 'MemoryList.DeleteModal';

// ============================================================================
// Attach Sub-Components to Main Component
// ============================================================================

const attachMarker = <P extends object>(component: React.FC<P>, marker: symbol) => {
  (component as any)[marker] = true;
  return component;
};

// Export the compound component
export const MemoryList = Object.assign(MemoryListInternal, {
  Header: attachMarker(HeaderInternal, HeaderMarker),
  Toolbar: attachMarker(ToolbarInternal, ToolbarMarker),
  VirtualList: attachMarker(VirtualListInternal, VirtualListMarker),
  MemoryRow: attachMarker(MemoryRowInternal, MemoryRowMarker),
  StatusBadge: attachMarker(StatusBadgeInternal, StatusBadgeMarker),
  Empty: attachMarker(EmptyInternal, EmptyMarker),
  Loading: attachMarker(LoadingInternal, LoadingMarker),
  Error: attachMarker(ErrorInternal, ErrorMarker),
  DeleteModal: attachMarker(DeleteModalInternal, DeleteModalMarker),
  useContext: useMemoryListContext,
});

export default MemoryList;
