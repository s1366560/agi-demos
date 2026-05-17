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

import { useTranslation } from 'react-i18next';
import { useParams, Link } from 'react-router-dom';

import { useVirtualizer } from '@tanstack/react-virtual';
import {
  AlertCircle,
  ChevronDown,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';
import { useDebounce } from 'use-debounce';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { formatDateOnly } from '@/utils/date';

import { memoryAPI } from '../../services/api';

import type { Memory } from '../../types/memory';
import type { TFunction } from 'i18next';

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

type MemoryApiItem = Partial<Memory> & Pick<Memory, 'id'>;
type MemoryTypeFilter = Memory['content_type'] | 'all';

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
  contentTypeLabel: 'Memory type',
  contentTypes: {
    text: 'Text',
    document: 'Document',
    image: 'Image',
    video: 'Video',
  },
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

type MemoryListTexts = typeof TEXTS;

function textFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

function useMemoryListTexts(): MemoryListTexts {
  const { t } = useTranslation();

  return useMemo(
    () => ({
      title: textFallback(t, 'project.memories.title', TEXTS.title),
      subtitle: textFallback(t, 'project.memories.subtitle', TEXTS.subtitle),
      addMemory: textFallback(t, 'project.memories.addMemory', TEXTS.addMemory),
      searchPlaceholder: textFallback(
        t,
        'project.memories.searchPlaceholder',
        TEXTS.searchPlaceholder
      ),
      filterLabel: textFallback(t, 'project.memories.filter.label', TEXTS.filterLabel),
      allTypes: textFallback(t, 'project.memories.filter.all_types', TEXTS.allTypes),
      contentTypeLabel: textFallback(
        t,
        'project.memories.contentTypeLabel',
        TEXTS.contentTypeLabel
      ),
      contentTypes: {
        text: textFallback(t, 'project.memories.contentTypes.text', TEXTS.contentTypes.text),
        document: textFallback(
          t,
          'project.memories.contentTypes.document',
          TEXTS.contentTypes.document
        ),
        image: textFallback(t, 'project.memories.contentTypes.image', TEXTS.contentTypes.image),
        video: textFallback(t, 'project.memories.contentTypes.video', TEXTS.contentTypes.video),
      },
      noMemories: textFallback(t, 'project.memories.noMemories', TEXTS.noMemories),
      loading: textFallback(t, 'common.loading', TEXTS.loading),
      projectNotFound: textFallback(t, 'project.overview.not_found', TEXTS.projectNotFound),
      retry: textFallback(t, 'common.retry', TEXTS.retry),
      tableName: textFallback(t, 'project.memories.columns.name', TEXTS.tableName),
      tableType: textFallback(t, 'project.memories.columns.type', TEXTS.tableType),
      tableStatus: textFallback(t, 'project.memories.columns.status', TEXTS.tableStatus),
      tableProcessing: textFallback(
        t,
        'project.memories.columns.processing',
        TEXTS.tableProcessing
      ),
      tableCreated: textFallback(t, 'project.memories.columns.created', TEXTS.tableCreated),
      statusEnabled: textFallback(t, 'common.status.enabled', TEXTS.statusEnabled),
      statusDisabled: textFallback(t, 'common.status.disabled', TEXTS.statusDisabled),
      statusCompleted: textFallback(t, 'project.memories.status.completed', TEXTS.statusCompleted),
      statusProcessing: textFallback(
        t,
        'project.memories.status.processing',
        TEXTS.statusProcessing
      ),
      statusFailed: textFallback(t, 'project.memories.status.failed', TEXTS.statusFailed),
      statusPending: textFallback(t, 'project.memories.status.pending', TEXTS.statusPending),
      deleteTitle: textFallback(t, 'project.memories.delete.title', TEXTS.deleteTitle),
      deleteMessage: textFallback(t, 'project.memories.delete.message', TEXTS.deleteMessage),
      deleteConfirm: textFallback(t, 'common.delete', TEXTS.deleteConfirm),
      deleteCancel: textFallback(t, 'common.cancel', TEXTS.deleteCancel),
      deleteMemory: textFallback(t, 'project.memories.delete.actionLabel', TEXTS.deleteMemory),
      reprocess: textFallback(t, 'project.memories.actions.reprocess', TEXTS.reprocess),
    }),
    [t]
  );
}

const ROW_HEIGHT = 80;
const TABLE_MIN_WIDTH_CLASS = 'min-w-[920px]';

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
        dot: 'bg-yellow-500 animate-pulse motion-reduce:animate-none',
      };
  }
};

const normalizeMemory = (memory: MemoryApiItem): Memory => ({
  id: memory.id,
  project_id: memory.project_id ?? '',
  title: memory.title ?? 'Untitled',
  content: memory.content ?? '',
  content_type: memory.content_type ?? 'text',
  tags: memory.tags ?? [],
  entities: memory.entities ?? [],
  relationships: memory.relationships ?? [],
  version: memory.version ?? 1,
  author_id: memory.author_id ?? '',
  collaborators: memory.collaborators ?? [],
  is_public: memory.is_public ?? false,
  status: memory.status ?? 'ENABLED',
  processing_status: memory.processing_status ?? 'PENDING',
  metadata: memory.metadata ?? {},
  created_at: memory.created_at ?? '',
  updated_at: memory.updated_at,
  task_id: memory.task_id,
});

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
  contentTypeFilter: MemoryTypeFilter;
  deletingId: string | null;
  isDeleteModalOpen: boolean;
  memoryToDelete: Memory | null;
  taskProgress: MemoryTaskProgress;
}

interface MemoryListActions {
  setSearch: (search: string) => void;
  setContentTypeFilter: (contentType: MemoryTypeFilter) => void;
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
  const texts = useMemoryListTexts();

  // State
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [debouncedSearch] = useDebounce(search, 300);
  const [contentTypeFilter, setContentTypeFilter] = useState<MemoryTypeFilter>('all');
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [memoryToDelete, setMemoryToDelete] = useState<Memory | null>(null);
  const [taskProgress, setTaskProgress] = useState<MemoryTaskProgress>({});

  const parentRef = useRef<HTMLDivElement>(null);

  // Filter memories
  const filteredMemories = useMemo(() => {
    const lowerSearch = debouncedSearch.toLowerCase();
    return memories.filter(
      (m) =>
        (contentTypeFilter === 'all' || m.content_type === contentTypeFilter) &&
        (!lowerSearch ||
          m.title.toLowerCase().includes(lowerSearch) ||
          m.content_type.toLowerCase().includes(lowerSearch))
    );
  }, [memories, debouncedSearch, contentTypeFilter]);

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
      setMemories(data.memories.map(normalizeMemory));
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
    void fetchMemories();
  }, [fetchMemories]);

  // Context value
  const state: MemoryListState = {
    memories,
    isLoading,
    fetchError,
    search,
    debouncedSearch,
    contentTypeFilter,
    deletingId,
    isDeleteModalOpen,
    memoryToDelete,
    taskProgress,
  };

  const actions: MemoryListActions = {
    setSearch,
    setContentTypeFilter,
    confirmDelete,
    handleDelete,
    handleReprocess,
    fetchMemories,
    closeDeleteModal,
    setTaskProgress,
  };

  if (!projectId) {
    return <MemoryList.Error error={texts.projectNotFound} />;
  }

  return (
    <MemoryListContext.Provider value={{ state, actions, projectId }}>
      <div className={className || 'max-w-7xl mx-auto flex flex-col gap-8'}>
        <MemoryList.Header />
        <MemoryList.Toolbar />
        <div className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm overflow-hidden">
          {fetchError ? (
            <MemoryList.Error
              error={fetchError}
              onRetry={() => {
                void actions.fetchMemories();
              }}
            />
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
            onConfirm={() => {
              void handleDelete();
            }}
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

const HeaderInternal: React.FC<HeaderProps> = ({ className = '' }) => {
  const { projectBasePath } = useProjectBasePath();
  const texts = useMemoryListTexts();

  return (
    <div className={`flex flex-wrap items-center justify-between gap-4 ${className}`}>
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
          {texts.title}
        </h1>
        <p className="text-sm text-slate-500">{texts.subtitle}</p>
      </div>
      <Link
        to={`${projectBasePath}/memories/new`}
        className="flex items-center gap-2 bg-blue-600 dark:bg-blue-700 hover:bg-blue-700 text-white px-5 py-2.5 rounded-lg text-sm font-medium shadow-lg shadow-blue-900/20 transition-[color,background-color,border-color,box-shadow,opacity,transform] active:scale-95"
      >
        <Plus size={18} />
        <span>{texts.addMemory}</span>
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
  contentTypeFilter?: MemoryTypeFilter | undefined;
  onContentTypeFilterChange?: ((value: MemoryTypeFilter) => void) | undefined;
}

const ToolbarInternal: React.FC<ToolbarProps> = ({
  className = '',
  search: propSearch,
  onSearchChange: propOnSearchChange,
  contentTypeFilter: propContentTypeFilter,
  onContentTypeFilterChange: propOnContentTypeFilterChange,
}) => {
  const context = useMemoryListContextOptional();
  const texts = useMemoryListTexts();
  const search = propSearch ?? context?.state.search ?? '';
  const onSearchChange = propOnSearchChange ?? context?.actions.setSearch;
  const contentTypeFilter = propContentTypeFilter ?? context?.state.contentTypeFilter ?? 'all';
  const onContentTypeFilterChange =
    propOnContentTypeFilterChange ?? context?.actions.setContentTypeFilter;

  return (
    <div
      className={`flex flex-col md:flex-row gap-4 justify-between items-center bg-white dark:bg-surface-dark p-2 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm ${className}`}
    >
      <div className="relative w-full md:max-w-md">
        <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
          <Search size={16} className="text-slate-400" />
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange?.(e.target.value)}
          className="block w-full pl-10 pr-3 py-2.5 border-none rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:ring-2 focus:ring-blue-600/20 focus:bg-white dark:focus:bg-slate-700 transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none"
          aria-label={texts.searchPlaceholder}
          placeholder={texts.searchPlaceholder}
        />
      </div>
      <div className="flex items-center gap-2 w-full md:w-auto overflow-x-auto pb-2 md:pb-0 px-2 md:px-0">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-1">
          {texts.filterLabel}
        </span>
        <label className="sr-only" htmlFor="memory-type-filter">
          {texts.contentTypeLabel}
        </label>
        <div className="relative">
          <select
            id="memory-type-filter"
            value={contentTypeFilter}
            onChange={(event) => {
              onContentTypeFilterChange?.(event.target.value as MemoryTypeFilter);
            }}
            className="appearance-none rounded-lg border border-blue-600/20 bg-blue-600/10 py-1.5 pl-3 pr-8 text-sm font-medium text-blue-600 transition-colors hover:border-blue-600/40 focus:outline-none focus:ring-2 focus:ring-blue-600/20 dark:text-blue-400"
          >
            <option value="all">{texts.allTypes}</option>
            <option value="text">{texts.contentTypes.text}</option>
            <option value="document">{texts.contentTypes.document}</option>
            <option value="image">{texts.contentTypes.image}</option>
            <option value="video">{texts.contentTypes.video}</option>
          </select>
          <ChevronDown
            size={16}
            className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-blue-600 dark:text-blue-400"
          />
        </div>
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
    const texts = useMemoryListTexts();

    return (
      <div data-testid="memory-list-horizontal-scroll" className={`overflow-x-auto ${className}`}>
        <table className={`w-full ${TABLE_MIN_WIDTH_CLASS} text-left text-sm`}>
          <thead className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-10">
            <tr>
              <th className="w-[320px] px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {texts.tableName}
              </th>
              <th className="w-[110px] px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {texts.tableType}
              </th>
              <th className="w-[140px] px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {texts.tableStatus}
              </th>
              <th className="w-[150px] px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                {texts.tableProcessing}
              </th>
              <th className="w-[120px] px-6 py-3 font-semibold text-slate-500 dark:text-slate-400 text-right">
                {texts.tableCreated}
              </th>
              <th className="w-[100px] px-6 py-3 font-semibold text-slate-500 dark:text-slate-400"></th>
            </tr>
          </thead>
        </table>
        <div
          ref={parentRef}
          data-testid="memory-list-vertical-scroll"
          className={`${TABLE_MIN_WIDTH_CLASS} overflow-y-auto`}
          style={{ height: `${String(Math.min(filteredMemories.length * ROW_HEIGHT, 600))}px` }}
        >
          <table
            className="w-full text-left text-sm"
            style={{ position: 'relative', height: `${String(totalSize)}px` }}
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

const getStatusText = (status: string | undefined, texts: MemoryListTexts): string => {
  switch (status) {
    case 'COMPLETED':
      return texts.statusCompleted;
    case 'PROCESSING':
      return texts.statusProcessing;
    case 'FAILED':
      return texts.statusFailed;
    case 'PENDING':
      return texts.statusPending;
    default:
      return texts.statusPending;
  }
};

const StatusBadgeInternal: React.FC<StatusBadgeProps> = memo(
  ({ status, progress, className = '' }) => {
    const texts = useMemoryListTexts();
    const styles = getProcessingStatusStyles(status);

    return (
      <div className={`flex flex-col gap-1 ${className}`}>
        <span
          className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${styles.badge}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`}></span>
          {progress !== undefined ? `${String(progress)}%` : getStatusText(status, texts)}
        </span>
        {progress !== undefined && (
          <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-[width] duration-300 ease-out"
              style={{ width: `${String(progress)}%` }}
            />
          </div>
        )}
      </div>
    );
  }
);

StatusBadgeInternal.displayName = 'MemoryList.StatusBadge';

const getMemoryStatusText = (status: string | undefined, texts: MemoryListTexts): string => {
  if (status === 'DISABLED') return texts.statusDisabled;
  return texts.statusEnabled;
};

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
  ({ memory, index, onDelete: propOnDelete }) => {
    const context = useMemoryListContextOptional();
    const state = context?.state;
    const actions = context?.actions;
    const { projectBasePath } = useProjectBasePath();
    const texts = useMemoryListTexts();
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
          transform: `translateY(${String(index * ROW_HEIGHT)}px)`,
        }}
      >
        <td className="w-[320px] px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="shrink-0 p-2 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400">
              <FileText size={16} style={{ fontSize: '20px' }} />
            </div>
            <div className="min-w-0">
              <Link
                to={`${projectBasePath}/memory/${memory.id}`}
                className="block max-w-[220px] truncate font-medium text-slate-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors sm:max-w-none"
              >
                {memory.title || 'Untitled'}
              </Link>
              <div className="text-xs text-slate-500">
                <span className="font-mono opacity-70">{memory.id.substring(0, 8)}...</span>
              </div>
            </div>
          </div>
        </td>
        <td className="w-[110px] px-6 py-3 text-slate-600 dark:text-slate-300 capitalize">
          {memory.content_type}
        </td>
        <td className="w-[140px] px-6 py-3">
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
            {getMemoryStatusText(memory.status, texts)}
          </span>
        </td>
        <td className="w-[150px] px-6 py-3">
          <MemoryList.StatusBadge status={memory.processing_status} progress={progress} />
        </td>
        <td className="w-[120px] px-6 py-3 text-slate-600 dark:text-slate-300 text-right">
          {formatDateOnly(memory.created_at)}
        </td>
        <td className="w-[100px] px-6 py-3 text-right">
          <div className="flex items-center justify-end gap-2 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100">
            {actions && (
              <button
                type="button"
                onClick={() => {
                  void actions.handleReprocess(memory.id);
                }}
                className="text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                title={texts.reprocess}
              >
                <RefreshCw size={16} style={{ fontSize: '20px' }} />
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                onClick={() => {
                  onDelete(memory);
                }}
                disabled={state?.deletingId === memory.id}
                className="text-slate-400 hover:text-red-500 p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                title={texts.deleteMemory}
              >
                {state?.deletingId === memory.id ? (
                  <Loader2
                    size={16}
                    className="animate-spin motion-reduce:animate-none"
                    style={{ fontSize: '20px' }}
                  />
                ) : (
                  <Trash2 size={16} style={{ fontSize: '20px' }} />
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

const EmptyInternal: React.FC<{ className?: string | undefined }> = ({ className = '' }) => {
  const texts = useMemoryListTexts();
  return <div className={`p-8 text-center text-slate-500 ${className}`}>{texts.noMemories}</div>;
};

EmptyInternal.displayName = 'MemoryList.Empty';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC<{ className?: string | undefined }> = ({ className = '' }) => {
  const texts = useMemoryListTexts();
  return <div className={`p-10 text-center text-slate-500 ${className}`}>{texts.loading}</div>;
};

LoadingInternal.displayName = 'MemoryList.Loading';

// ============================================================================
// Error Sub-Component
// ============================================================================

interface ErrorProps {
  error: string;
  onRetry?: (() => void) | undefined;
  className?: string | undefined;
}

const ErrorInternal: React.FC<ErrorProps> = ({ error, onRetry, className = '' }) => {
  const texts = useMemoryListTexts();
  return (
    <div className={`p-8 text-center ${className}`}>
      <div className="flex flex-col items-center gap-4">
        <AlertCircle size={32} className="text-red-500" />
        <p className="text-red-600 dark:text-red-400">{error}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            {texts.retry}
          </button>
        )}
      </div>
    </div>
  );
};

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
    const texts = useMemoryListTexts();
    if (!isOpen) return null;

    return (
      <div
        className={`fixed inset-0 z-50 flex items-center justify-center bg-black/50 ${className}`}
      >
        <div className="bg-white dark:bg-surface-dark rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
            {texts.deleteTitle}
          </h3>
          <p className="text-slate-600 dark:text-slate-300 mb-6">
            {texts.deleteMessage}
            <br />
            <span className="font-medium text-slate-900 dark:text-white">"{memoryTitle}"</span>
          </p>
          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              disabled={isDeleting}
              className="px-4 py-2 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
            >
              {texts.deleteCancel}
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isDeleting}
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
            >
              {isDeleting ? texts.loading : texts.deleteConfirm}
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

const attachMarker = <C extends object>(component: C, marker: symbol): C => {
  Object.defineProperty(component, marker, {
    value: true,
  });
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
