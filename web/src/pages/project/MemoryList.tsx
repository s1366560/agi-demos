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
import { useParams, Link, useSearchParams } from 'react-router-dom';

import { useVirtualizer } from '@tanstack/react-virtual';
import { message } from 'antd';
import {
  AlertCircle,
  Database,
  FileImage,
  FileText,
  FileVideo,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from 'lucide-react';
import { useDebounce } from 'use-debounce';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { formatDateOnly } from '@/utils/date';

import { AppModal } from '@/components/common';
import { Pagination } from '@/components/shared/Pagination';

import { memoryAPI } from '../../services/api';
import { logger } from '../../utils/logger';

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
  eyebrow: 'Project knowledge',
  title: 'Memories',
  subtitle: 'All stored memories in your knowledge graph',
  addMemory: 'Add Memory',
  searchPlaceholder: 'Search memories…',
  filterLabel: 'Filter',
  allTypes: 'All Types',
  contentTypeLabel: 'Memory type',
  totalMetric: 'Total',
  activeMetric: 'Active',
  indexingMetric: 'Indexing',
  countSummary: '{{shown}} of {{total}} shown',
  paginationSummary: '{{start}}-{{end}} of {{total}}',
  rowsPerPage: 'Rows',
  previousPage: 'Previous page',
  nextPage: 'Next page',
  contentTypes: {
    text: 'Text',
    document: 'Document',
    image: 'Image',
    video: 'Video',
  },
  noMemories: 'No memories yet. Create your first memory to get started.',
  emptyTitle: 'No memories found',
  emptySubtitle: 'Create a memory to start indexing project knowledge.',
  emptyCreateButton: 'Create Memory',
  loading: 'Loading…',
  projectNotFound: 'Project not found',
  retry: 'Retry',
  refresh: 'Refresh',
  untitled: 'Untitled',
  fetchFailed: 'Failed to load memories. Please check your connection and try again.',
  deleteSuccess: 'Memory deleted',
  deleteFailed: 'Failed to delete memory',
  reprocessFailed: 'Failed to start processing. Please try again.',

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

function formatCountSummary(template: string, shown: number, total: number): string {
  return template.replace('{{shown}}', String(shown)).replace('{{total}}', String(total));
}

function useMemoryListTexts(): MemoryListTexts {
  const { t } = useTranslation();

  return useMemo(
    () => ({
      eyebrow: textFallback(t, 'project.memories.eyebrow', TEXTS.eyebrow),
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
      totalMetric: textFallback(t, 'project.memories.metrics.total', TEXTS.totalMetric),
      activeMetric: textFallback(t, 'project.memories.metrics.active', TEXTS.activeMetric),
      indexingMetric: textFallback(t, 'project.memories.metrics.indexing', TEXTS.indexingMetric),
      countSummary: textFallback(t, 'project.memories.filter.summary', TEXTS.countSummary),
      paginationSummary: textFallback(
        t,
        'project.memories.pagination.summary',
        TEXTS.paginationSummary
      ),
      rowsPerPage: textFallback(t, 'project.memories.pagination.rowsPerPage', TEXTS.rowsPerPage),
      previousPage: textFallback(t, 'project.memories.pagination.previousPage', TEXTS.previousPage),
      nextPage: textFallback(t, 'project.memories.pagination.nextPage', TEXTS.nextPage),
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
      emptyTitle: textFallback(t, 'project.memories.empty.title', TEXTS.emptyTitle),
      emptySubtitle: textFallback(t, 'project.memories.empty.subtitle', TEXTS.emptySubtitle),
      emptyCreateButton: textFallback(
        t,
        'project.memories.empty.create_button',
        TEXTS.emptyCreateButton
      ),
      loading: textFallback(t, 'common.loading', TEXTS.loading),
      projectNotFound: textFallback(t, 'project.overview.not_found', TEXTS.projectNotFound),
      retry: textFallback(t, 'common.retry', TEXTS.retry),
      refresh: textFallback(t, 'common.refresh', TEXTS.refresh),
      untitled: textFallback(t, 'common.untitled', TEXTS.untitled),
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
      fetchFailed: textFallback(t, 'project.memories.loadFailed', TEXTS.fetchFailed),
      deleteSuccess: textFallback(t, 'common.status.deleted', TEXTS.deleteSuccess),
      deleteFailed: textFallback(t, 'common.errors.delete_failed', TEXTS.deleteFailed),
      reprocessFailed: textFallback(
        t,
        'project.memories.errors.reprocessFailed',
        TEXTS.reprocessFailed
      ),
    }),
    [t]
  );
}

const ROW_HEIGHT = 72;
const DEFAULT_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
const TABLE_MIN_WIDTH_CLASS = 'min-w-[960px]';
const MEMORY_TABLE_COLUMNS = [
  { key: 'name', width: '330px' },
  { key: 'type', width: '110px' },
  { key: 'status', width: '130px' },
  { key: 'processing', width: '150px' },
  { key: 'created', width: '130px' },
  { key: 'actions', width: '110px' },
] as const;
const EMPTY_MEMORIES: Memory[] = [];
const VALID_MEMORY_TYPE_FILTERS: readonly MemoryTypeFilter[] = [
  'text',
  'document',
  'image',
  'video',
];

const parsePositiveIntParam = (value: string | null): number | null => {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

const parseMemoryTypeParam = (value: string | null): MemoryTypeFilter =>
  value !== null && (VALID_MEMORY_TYPE_FILTERS as readonly string[]).includes(value)
    ? (value as MemoryTypeFilter)
    : 'all';

// ============================================================================
// Helper Functions
// ============================================================================

const getProcessingStatusStyles = (status: string | undefined) => {
  switch (status) {
    case 'FAILED':
      return {
        badge:
          'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
        dot: 'bg-error',
        progress: 'bg-error dark:bg-error-light',
      };
    case 'COMPLETED':
      return {
        badge:
          'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
        dot: 'bg-success',
        progress: 'bg-success dark:bg-success-light',
      };
    default:
      return {
        badge:
          'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark',
        dot: 'bg-warning animate-pulse motion-reduce:animate-none',
        progress: 'bg-warning dark:bg-warning-light',
      };
  }
};

function MemoryTableColGroup(): React.ReactElement {
  return (
    <colgroup>
      {MEMORY_TABLE_COLUMNS.map((column) => (
        <col key={column.key} style={{ width: column.width }} />
      ))}
    </colgroup>
  );
}

const normalizeMemory = (memory: MemoryApiItem, untitled: string): Memory => ({
  id: memory.id,
  project_id: memory.project_id ?? '',
  title: memory.title ?? untitled,
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
const PaginationMarker = Symbol('MemoryList.Pagination');

// ============================================================================
// Context
// ============================================================================

interface MemoryListState {
  memories: Memory[];
  total: number;
  page: number;
  pageSize: number;
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
  setPage: (page: number) => void;
  setPageSize: (pageSize: number) => void;
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
  const [searchParams, setSearchParams] = useSearchParams();
  const texts = useMemoryListTexts();

  // State (filters/pagination seed from the URL query so views survive reload and sharing)
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(() => parsePositiveIntParam(searchParams.get('page')) ?? 1);
  const [pageSize, setPageSize] = useState(() => {
    const parsed = parsePositiveIntParam(searchParams.get('page_size'));
    return parsed !== null && (PAGE_SIZE_OPTIONS as readonly number[]).includes(parsed)
      ? parsed
      : DEFAULT_PAGE_SIZE;
  });
  const [isLoading, setIsLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '');
  const [debouncedSearch] = useDebounce(search, 300);
  const [contentTypeFilter, setContentTypeFilter] = useState<MemoryTypeFilter>(() =>
    parseMemoryTypeParam(searchParams.get('type'))
  );
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [memoryToDelete, setMemoryToDelete] = useState<Memory | null>(null);
  const [taskProgress, setTaskProgress] = useState<MemoryTaskProgress>({});

  const parentRef = useRef<HTMLDivElement>(null);
  const fetchSequenceRef = useRef(0);

  const filteredMemories = memories;

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
    const sequence = fetchSequenceRef.current + 1;
    fetchSequenceRef.current = sequence;
    setIsLoading(true);
    setFetchError(null);
    try {
      const trimmedSearch = debouncedSearch.trim();
      const data = await memoryAPI.list(projectId, {
        page,
        page_size: pageSize,
        ...(trimmedSearch ? { search: trimmedSearch } : {}),
        ...(contentTypeFilter !== 'all' ? { content_type: contentTypeFilter } : {}),
      });
      if (fetchSequenceRef.current !== sequence) return;
      const normalizedMemories = data.memories.map((memory) =>
        normalizeMemory(memory, texts.untitled)
      );
      if (normalizedMemories.length === 0 && data.total > 0 && data.page > 1) {
        setPage(Math.max(1, data.page - 1));
        return;
      }
      setMemories(normalizedMemories);
      setTotal(data.total);
      setPage(data.page);
      setPageSize(data.page_size);
    } catch (error) {
      if (fetchSequenceRef.current !== sequence) return;
      logger.error('[MemoryList] Failed to list memories:', error);
      setFetchError(texts.fetchFailed);
    } finally {
      if (fetchSequenceRef.current === sequence) {
        setIsLoading(false);
      }
    }
  }, [contentTypeFilter, debouncedSearch, page, pageSize, projectId, texts.fetchFailed, texts.untitled]);

  useEffect(() => {
    setPage(1);
  }, [contentTypeFilter, debouncedSearch]);

  // Reflect search/filter/pagination in the URL so views survive reload and sharing.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    const trimmedSearch = debouncedSearch.trim();
    if (trimmedSearch) {
      next.set('q', trimmedSearch);
    } else {
      next.delete('q');
    }
    if (contentTypeFilter !== 'all') {
      next.set('type', contentTypeFilter);
    } else {
      next.delete('type');
    }
    if (page > 1) {
      next.set('page', String(page));
    } else {
      next.delete('page');
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      next.set('page_size', String(pageSize));
    } else {
      next.delete('page_size');
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [contentTypeFilter, debouncedSearch, page, pageSize, searchParams, setSearchParams]);

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
      message.success(texts.deleteSuccess);
      setIsDeleteModalOpen(false);
      setMemoryToDelete(null);
    } catch (error) {
      logger.error('[MemoryList] Failed to delete memory:', error);
      // Keep the modal open so the user can retry or cancel.
      message.error(texts.deleteFailed);
    } finally {
      setDeletingId(null);
    }
  }, [memoryToDelete, projectId, fetchMemories, texts.deleteSuccess, texts.deleteFailed]);

  const handleReprocess = useCallback(
    async (id: string) => {
      if (!projectId) return;
      try {
        await memoryAPI.reprocess(projectId, id);
        setMemories((prev) =>
          prev.map((m) => (m.id === id ? { ...m, processing_status: 'PENDING' } : m))
        );
      } catch (error) {
        logger.error('[MemoryList] Failed to reprocess:', error);
        message.error(texts.reprocessFailed);
      }
    },
    [projectId, texts.reprocessFailed]
  );

  // Initial fetch
  useEffect(() => {
    void fetchMemories();
  }, [fetchMemories]);

  // Context value
  const state: MemoryListState = {
    memories,
    total,
    page,
    pageSize,
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
    setPage,
    setPageSize,
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
      <div className={className || 'mx-auto flex w-full max-w-none flex-col gap-5'}>
        <MemoryList.Header />
        <div className="overflow-hidden rounded-md bg-white shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-surface-dark dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]">
          <MemoryList.Toolbar />
          <div className="border-t border-slate-200 dark:border-slate-800">
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
          {!fetchError && !isLoading && total > 0 && <MemoryList.Pagination />}
        </div>
        {isDeleteModalOpen && memoryToDelete && (
          <MemoryList.DeleteModal
            isOpen={isDeleteModalOpen}
            onClose={closeDeleteModal}
            onConfirm={() => {
              void handleDelete();
            }}
            memoryTitle={memoryToDelete.title || texts.untitled}
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
  const context = useMemoryListContextOptional();
  const memories = context?.state.memories ?? EMPTY_MEMORIES;
  const total = context?.state.total ?? memories.length;
  const activeCount = memories.filter((memory) => memory.status !== 'DISABLED').length;
  const indexingCount = memories.filter((memory) =>
    ['PENDING', 'PROCESSING'].includes(memory.processing_status)
  ).length;
  const stats = [
    { label: texts.totalMetric, value: total },
    { label: texts.activeMetric, value: activeCount },
    { label: texts.indexingMetric, value: indexingCount },
  ];

  return (
    <div className={`flex flex-wrap items-start justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        <div className="mb-2 inline-flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
          <Database size={14} aria-hidden="true" />
          <span>{texts.eyebrow}</span>
        </div>
        <h1 className="text-[22px] font-semibold leading-7 text-slate-950 dark:text-slate-50">
          {texts.title}
        </h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{texts.subtitle}</p>
        <dl className="mt-4 flex flex-wrap gap-2">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="inline-flex h-7 items-center gap-2 rounded-full border border-slate-200 bg-white px-3 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400"
            >
              <dt>{stat.label}</dt>
              <dd className="font-semibold text-slate-950 dark:text-slate-100">{stat.value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="flex items-center gap-2">
        {context && (
          <button
            type="button"
            onClick={() => {
              void context.actions.fetchMemories();
            }}
            disabled={context.state.isLoading}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-950/10 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:focus:ring-slate-50/10"
          >
            {context.state.isLoading ? (
              <Loader2
                size={16}
                className="animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
            ) : (
              <RefreshCw size={16} aria-hidden="true" />
            )}
            <span>{texts.refresh}</span>
          </button>
        )}
        <Link
          to={`${projectBasePath}/memories/new`}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus:ring-slate-50/20"
        >
          <Plus size={16} aria-hidden="true" />
          <span>{texts.addMemory}</span>
        </Link>
      </div>
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
  const memories = context?.state.memories ?? EMPTY_MEMORIES;
  const total = context?.state.total ?? memories.length;
  const typeCounts = useMemo(
    () => ({
      all: memories.length,
      text: memories.filter((memory) => memory.content_type === 'text').length,
      document: memories.filter((memory) => memory.content_type === 'document').length,
      image: memories.filter((memory) => memory.content_type === 'image').length,
      video: memories.filter((memory) => memory.content_type === 'video').length,
    }),
    [memories]
  );
  const shownCount = memories.length;
  const filterOptions: Array<{ value: MemoryTypeFilter; label: string; count: number }> = [
    { value: 'all', label: texts.allTypes, count: typeCounts.all },
    { value: 'text', label: texts.contentTypes.text, count: typeCounts.text },
    { value: 'document', label: texts.contentTypes.document, count: typeCounts.document },
    { value: 'image', label: texts.contentTypes.image, count: typeCounts.image },
    { value: 'video', label: texts.contentTypes.video, count: typeCounts.video },
  ];

  return (
    <div
      className={`flex flex-col gap-3 bg-white p-3 dark:bg-surface-dark lg:flex-row lg:items-center lg:justify-between ${className}`}
    >
      <div className="flex w-full flex-col gap-2 lg:max-w-md">
        <div className="relative">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
            <Search size={16} className="text-slate-400" />
          </div>
          <input
            type="search"
            value={search}
            onChange={(e) => onSearchChange?.(e.target.value)}
            className="block h-9 w-full rounded-md border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-950 outline-none transition-colors placeholder:text-slate-400 hover:border-slate-300 focus:border-slate-950 focus:ring-2 focus:ring-slate-950/10 dark:border-slate-800 dark:bg-slate-900/30 dark:text-slate-50 dark:hover:border-slate-700 dark:focus:border-slate-400 dark:focus:ring-slate-50/10"
            aria-label={texts.searchPlaceholder}
            placeholder={texts.searchPlaceholder}
          />
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {formatCountSummary(texts.countSummary, shownCount, total)}
        </p>
      </div>
      <div className="flex w-full flex-col gap-2 lg:w-auto lg:items-end">
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {texts.filterLabel}
        </span>
        <div
          className="flex w-full gap-1 overflow-x-auto rounded-md border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-950/30 lg:w-auto"
          role="group"
          aria-label={texts.contentTypeLabel}
        >
          {filterOptions.map((option) => {
            const isActive = contentTypeFilter === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={isActive}
                aria-label={option.label}
                onClick={() => {
                  onContentTypeFilterChange?.(option.value);
                }}
                className={`inline-flex h-8 shrink-0 items-center gap-2 rounded px-2.5 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:focus:ring-slate-50/10 ${
                  isActive
                    ? 'bg-white text-slate-950 shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-slate-800 dark:text-slate-50 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]'
                    : 'text-slate-500 hover:bg-white hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100'
                }`}
              >
                <span>{option.label}</span>
                <span
                  className={`rounded-full px-1.5 text-[11px] leading-5 ${
                    isActive
                      ? 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200'
                      : 'bg-white text-slate-400 dark:bg-slate-900 dark:text-slate-500'
                  }`}
                >
                  {option.count}
                </span>
              </button>
            );
          })}
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
        <table className={`w-full ${TABLE_MIN_WIDTH_CLASS} table-fixed text-left text-sm`}>
          <MemoryTableColGroup />
          <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-900/60">
            <tr>
              <th className="px-5 py-2.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                <span className="ml-12 inline-block">{texts.tableName}</span>
              </th>
              <th className="px-5 py-2.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                {texts.tableType}
              </th>
              <th className="px-5 py-2.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                {texts.tableStatus}
              </th>
              <th className="px-5 py-2.5 text-xs font-medium text-slate-500 dark:text-slate-400">
                {texts.tableProcessing}
              </th>
              <th className="px-5 py-2.5 text-right text-xs font-medium text-slate-500 dark:text-slate-400">
                {texts.tableCreated}
              </th>
              <th className="px-5 py-2.5 text-xs font-medium text-slate-500 dark:text-slate-400"></th>
            </tr>
          </thead>
        </table>
        <div
          ref={parentRef}
          data-testid="memory-list-vertical-scroll"
          className={`${TABLE_MIN_WIDTH_CLASS} overflow-x-hidden overflow-y-auto`}
          style={{ height: `${String(Math.min(filteredMemories.length * ROW_HEIGHT, 600))}px` }}
        >
          <table
            className="w-full table-fixed text-left text-sm"
            style={{ position: 'relative', height: `${String(totalSize)}px` }}
          >
            <MemoryTableColGroup />
            <tbody>
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
          className={`inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${styles.badge}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${styles.dot}`}></span>
          {progress !== undefined ? `${String(progress)}%` : getStatusText(status, texts)}
        </span>
        {progress !== undefined && (
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
            <div
              className={`h-full transition-[width] duration-300 ease-out ${styles.progress}`}
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

const getContentTypeText = (
  contentType: Memory['content_type'] | undefined,
  texts: MemoryListTexts
): string => {
  switch (contentType) {
    case 'document':
      return texts.contentTypes.document;
    case 'image':
      return texts.contentTypes.image;
    case 'video':
      return texts.contentTypes.video;
    case 'text':
    default:
      return texts.contentTypes.text;
  }
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
    const TypeIcon =
      memory.content_type === 'image'
        ? FileImage
        : memory.content_type === 'video'
          ? FileVideo
          : FileText;
    const isDisabled = memory.status === 'DISABLED';

    return (
      <tr
        key={memory.id}
        className="group border-b border-slate-100 transition-colors hover:bg-slate-50/80 dark:border-slate-800 dark:hover:bg-slate-900/40"
        style={{
          display: 'table',
          position: 'absolute',
          tableLayout: 'fixed',
          top: 0,
          left: 0,
          width: '100%',
          height: `${String(ROW_HEIGHT)}px`,
          transform: `translateY(${String(index * ROW_HEIGHT)}px)`,
        }}
      >
        <td className="w-[330px] px-5 py-2">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400">
              <TypeIcon size={16} aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <Link
                to={`${projectBasePath}/memory/${memory.id}`}
                className="block truncate font-medium text-slate-950 transition-colors hover:text-primary dark:text-slate-50 dark:hover:text-primary-light"
              >
                {memory.title || texts.untitled}
              </Link>
              <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                <span className="font-mono opacity-70">{memory.id.substring(0, 8)}…</span>
              </div>
            </div>
          </div>
        </td>
        <td className="w-[110px] px-5 py-2 text-slate-600 dark:text-slate-300">
          <span className="inline-flex items-center gap-2 whitespace-nowrap">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-slate-600"></span>
            {getContentTypeText(memory.content_type, texts)}
          </span>
        </td>
        <td className="w-[130px] px-5 py-2">
          <span
            className={`inline-flex w-fit items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium ${
              isDisabled
                ? 'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark'
                : 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${isDisabled ? 'bg-error' : 'bg-success'}`}
            ></span>
            {getMemoryStatusText(memory.status, texts)}
          </span>
        </td>
        <td className="w-[150px] px-5 py-2">
          <MemoryList.StatusBadge status={memory.processing_status} progress={progress} />
        </td>
        <td className="w-[130px] px-5 py-2 text-right font-mono text-xs text-slate-500 dark:text-slate-400">
          <span className="whitespace-nowrap">{formatDateOnly(memory.created_at)}</span>
        </td>
        <td className="w-[110px] px-5 py-2 text-right">
          <div className="flex items-center justify-end gap-1 opacity-100 transition-opacity sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100">
            {actions && (
              <button
                type="button"
                onClick={() => {
                  void actions.handleReprocess(memory.id);
                }}
                className="inline-flex h-8 w-8 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-primary focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:hover:bg-slate-800 dark:hover:text-primary-light dark:focus:ring-slate-50/10"
                aria-label={texts.reprocess}
                title={texts.reprocess}
              >
                <RefreshCw size={16} aria-hidden="true" />
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                onClick={() => {
                  onDelete(memory);
                }}
                disabled={state?.deletingId === memory.id}
                className="inline-flex h-8 w-8 items-center justify-center rounded text-slate-400 transition-colors hover:bg-error-bg hover:text-error focus:outline-none focus:ring-2 focus:ring-error/20 disabled:opacity-50 dark:hover:bg-error-bg-dark dark:hover:text-error-light"
                aria-label={texts.deleteMemory}
                title={texts.deleteMemory}
              >
                {state?.deletingId === memory.id ? (
                  <Loader2
                    size={16}
                    className="animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                ) : (
                  <Trash2 size={16} aria-hidden="true" />
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
  const { projectBasePath } = useProjectBasePath();

  return (
    <div
      className={`flex flex-col items-center justify-center px-6 py-16 text-center ${className}`}
    >
      <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400">
        <FileText size={18} aria-hidden="true" />
      </div>
      <h2 className="text-base font-semibold text-slate-950 dark:text-slate-50">
        {texts.emptyTitle}
      </h2>
      <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">
        {texts.emptySubtitle}
      </p>
      <Link
        to={`${projectBasePath}/memories/new`}
        className="mt-5 inline-flex h-9 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-50 dark:hover:bg-slate-800 dark:focus:ring-slate-50/10"
      >
        <Plus size={16} aria-hidden="true" />
        <span>{texts.emptyCreateButton}</span>
      </Link>
    </div>
  );
};

EmptyInternal.displayName = 'MemoryList.Empty';

// ============================================================================
// Loading Sub-Component
// ============================================================================

const LoadingInternal: React.FC<{ className?: string | undefined }> = ({ className = '' }) => {
  const texts = useMemoryListTexts();
  return (
    <div className={`space-y-0 ${className}`} role="status" aria-label={texts.loading}>
      {Array.from({ length: 6 }, (_, row) => (
        <div
          key={`memory-skeleton-${String(row)}`}
          className="flex h-[72px] items-center gap-4 border-b border-slate-100 px-5 dark:border-slate-800"
        >
          <div className="h-9 w-9 animate-pulse rounded-md bg-slate-100 motion-reduce:animate-none dark:bg-slate-800"></div>
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-3 w-1/3 animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-800"></div>
            <div className="h-2.5 w-24 animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-800"></div>
          </div>
          <div className="hidden h-6 w-20 animate-pulse rounded-full bg-slate-100 motion-reduce:animate-none dark:bg-slate-800 sm:block"></div>
          <div className="hidden h-6 w-24 animate-pulse rounded-full bg-slate-100 motion-reduce:animate-none dark:bg-slate-800 md:block"></div>
        </div>
      ))}
    </div>
  );
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
    <div className={`px-6 py-14 text-center ${className}`} role="alert">
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-md border border-error-border bg-error-bg text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-error-light">
          <AlertCircle size={18} aria-hidden="true" />
        </div>
        <p className="max-w-md text-sm text-status-text-error dark:text-status-text-error-dark">
          {error}
        </p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex h-9 items-center rounded-md bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus:ring-slate-50/20"
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
// Pagination Sub-Component
// ============================================================================

const PaginationInternal: React.FC<{ className?: string | undefined }> = ({ className = '' }) => {
  const { state, actions } = useMemoryListContext();
  const texts = useMemoryListTexts();
  const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));

  return (
    <Pagination
      page={state.page - 1}
      totalPages={totalPages}
      onPageChange={(nextPage) => {
        actions.setPage(nextPage + 1);
      }}
      totalItems={state.total}
      pageSize={state.pageSize}
      pageSizeOptions={PAGE_SIZE_OPTIONS}
      onPageSizeChange={(nextPageSize) => {
        actions.setPageSize(nextPageSize);
        actions.setPage(1);
      }}
      previousLabel={texts.previousPage}
      nextLabel={texts.nextPage}
      className={`border-t border-slate-200 bg-slate-50/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/20 ${className}`}
    />
  );
};

PaginationInternal.displayName = 'MemoryList.Pagination';

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

    return (
      <AppModal
        open={isOpen}
        onClose={onClose}
        title={texts.deleteTitle}
        size="sm"
        className={className}
        footer={
          <>
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
          </>
        }
      >
        <p className="text-slate-600 dark:text-slate-300">
          {texts.deleteMessage}
          <br />
          <span className="font-medium text-slate-900 dark:text-white">“{memoryTitle}”</span>
        </p>
      </AppModal>
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
  Pagination: attachMarker(PaginationInternal, PaginationMarker),
  DeleteModal: attachMarker(DeleteModalInternal, DeleteModalMarker),
  useContext: useMemoryListContext,
});

export default MemoryList;
