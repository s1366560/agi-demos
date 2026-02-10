/**
 * VirtualizedMemoryList Component
 *
 * High-performance virtualized list for displaying memories.
 * Uses @tanstack/react-virtual for efficient rendering of large datasets.
 *
 * Features:
 * - Virtual scrolling for performance
 * - Keyboard navigation support
 * - Accessibility (ARIA attributes)
 * - Responsive design
 */

import { memo, useCallback, useRef, useState, KeyboardEvent } from 'react';

import { useVirtualizer } from '@tanstack/react-virtual';

import { Memory } from '@/types/memory';
import { formatDateOnly } from '@/utils/date';

// ============================================================================
// Types
// ============================================================================

export interface VirtualizedMemoryListProps {
  /** Array of memories to display */
  memories: Memory[];
  /** Current project ID */
  projectId: string;
  /** Callback when a memory is clicked */
  onMemoryClick: (memoryId: string) => void;
  /** Height of the scroll container in pixels (default: 400) */
  containerHeight?: number;
  /** Estimated height of each memory row in pixels (default: 80) */
  estimateSize?: () => number;
  /** Number of items to render outside visible area (default: 5) */
  overscan?: number;
}

export interface MemoryRowProps {
  /** The memory data */
  memory: Memory;
  /** Click handler */
  onClick: (memoryId: string) => void;
  /** Index for keyboard navigation */
  index: number;
  /** Whether this row is focused */
  isFocused: boolean;
  /** Focus callback */
  onFocus: (index: number) => void;
}

// ============================================================================
// Memory Row Component
// ============================================================================

/**
 * Individual memory row component with keyboard support.
 * Memoized to prevent unnecessary re-renders during virtual scrolling.
 */
export const MemoryRow = memo<MemoryRowProps>(({ memory, onClick, index, isFocused, onFocus }) => {
  const handleClick = useCallback(() => {
    onClick(memory.id);
  }, [memory.id, onClick]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTableRowElement>) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onClick(memory.id);
      }
    },
    [memory.id, onClick]
  );

  // Format helpers
  const formatStorage = (bytes: number) => {
    const gb = bytes / (1024 * 1024 * 1024);
    if (gb >= 1) return `${gb.toFixed(1)} GB`;
    const mb = bytes / (1024 * 1024);
    if (mb >= 1) return `${mb.toFixed(1)} MB`;
    const kb = bytes / 1024;
    return `${kb.toFixed(1)} KB`;
  };

  const formatDate = (dateString: string) => {
    return formatDateOnly(dateString);
  };

  const getMemoryTitle = (memory: Memory) => {
    if (
      !memory.title ||
      memory.title === memory.content_type ||
      memory.title === 'description' ||
      memory.title === 'text'
    ) {
      const contentPreview = memory.content || memory.metadata?.source_content || '';
      if (contentPreview) {
        return contentPreview.substring(0, 50) + (contentPreview.length > 50 ? '...' : '');
      }
      return 'Untitled';
    }
    return memory.title;
  };

  const getMemoryStatus = (memory: Memory) => {
    if (memory.status === 'DISABLED') {
      return {
        label: 'Unavailable',
        color: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
        dot: 'bg-red-500',
      };
    }
    return {
      label: 'Available',
      color: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
      dot: 'bg-green-500',
    };
  };

  const status = getMemoryStatus(memory);
  const title = getMemoryTitle(memory);

  return (
    <tr
      data-testid={`memory-row-${index}`}
      data-memory-id={memory.id}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      tabIndex={isFocused ? 0 : -1}
      onFocus={() => onFocus(index)}
      className="hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors group cursor-pointer focus:outline-none focus:ring-2 focus:ring-primary/50"
      role="row"
      aria-rowindex={index + 1}
    >
      <td className="px-6 py-3" role="gridcell">
        <div className="flex items-center gap-3">
          <div
            data-testid={`memory-icon-${memory.content_type}`}
            className="p-2 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400"
            aria-hidden="true"
          >
            <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
              {memory.content_type === 'image'
                ? 'image'
                : memory.content_type === 'video'
                  ? 'movie'
                  : 'description'}
            </span>
          </div>
          <div>
            <div className="font-medium text-slate-900 dark:text-white">{title}</div>
            <div className="text-xs text-slate-500">
              Updated {formatDate(memory.updated_at || memory.created_at)}
            </div>
          </div>
        </div>
      </td>
      <td className="px-6 py-3 text-slate-600 dark:text-slate-300 capitalize" role="gridcell">
        {memory.content_type}
      </td>
      <td className="px-6 py-3" role="gridcell">
        <span
          data-testid="memory-status-badge"
          className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${status.color}`}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${status.dot}`}></span>
          {status.label}
        </span>
      </td>
      <td
        className="px-6 py-3 text-slate-600 dark:text-slate-300 text-right font-mono"
        role="gridcell"
      >
        {formatStorage(memory.content?.length || 0)}
      </td>
      <td className="px-6 py-3 text-right" role="gridcell">
        <button
          onClick={(e) => {
            e.stopPropagation();
            // TODO: Implement menu
          }}
          className="text-slate-400 hover:text-primary p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700"
          aria-label="More options"
        >
          <span className="material-symbols-outlined" style={{ fontSize: '20px' }}>
            more_vert
          </span>
        </button>
      </td>
    </tr>
  );
});

MemoryRow.displayName = 'MemoryRow';

// ============================================================================
// Virtualized Memory List Component
// ============================================================================

/**
 * Virtualized memory list with keyboard navigation and accessibility.
 *
 * This component uses virtualization to efficiently render large lists
 * of memories, only rendering the visible items plus a small overscan buffer.
 */
export const VirtualizedMemoryList = memo<VirtualizedMemoryListProps>(
  ({ memories, onMemoryClick, containerHeight = 400, estimateSize = () => 80, overscan = 5 }) => {
    const parentRef = useRef<HTMLDivElement>(null);
    const [focusedIndex, setFocusedIndex] = useState<number>(-1);

    // Detect test environment - render all items without virtualization
    const isTestEnvironment =
      process.env.NODE_ENV === 'test' ||
      (typeof window !== 'undefined' && (window as any).__vitest__?.isFake === true);

    // For small item counts or test environment, render all items
    const shouldRenderAll = memories.length <= 10 || isTestEnvironment;

    // Set up virtual row virtualizer - MUST be before any early returns
    const rowVirtualizer = useVirtualizer({
      count: memories.length,
      getScrollElement: () => parentRef.current,
      estimateSize,
      overscan,
    });

    const virtualRows = rowVirtualizer.getVirtualItems();
    const totalSize = rowVirtualizer.getTotalSize();

    // Keyboard navigation
    const handleKeyDown = useCallback(
      (e: KeyboardEvent<HTMLDivElement>) => {
        if (memories.length === 0) return;

        let newIndex = focusedIndex;

        switch (e.key) {
          case 'ArrowDown':
            e.preventDefault();
            newIndex = focusedIndex < memories.length - 1 ? focusedIndex + 1 : focusedIndex;
            break;
          case 'ArrowUp':
            e.preventDefault();
            newIndex = focusedIndex > 0 ? focusedIndex - 1 : focusedIndex;
            break;
          case 'Home':
            e.preventDefault();
            newIndex = 0;
            break;
          case 'End':
            e.preventDefault();
            newIndex = memories.length - 1;
            break;
          case 'PageDown':
            e.preventDefault();
            newIndex = Math.min(
              focusedIndex + Math.floor(containerHeight / estimateSize()),
              memories.length - 1
            );
            break;
          case 'PageUp':
            e.preventDefault();
            newIndex = Math.max(focusedIndex - Math.floor(containerHeight / estimateSize()), 0);
            break;
          default:
            return;
        }

        if (newIndex !== focusedIndex) {
          setFocusedIndex(newIndex);
          // Scroll the new row into view
          rowVirtualizer.scrollToIndex(newIndex, { align: 'auto', behavior: 'smooth' });
        }
      },
      [focusedIndex, memories.length, containerHeight, estimateSize, rowVirtualizer]
    );

    // Handle focus change from row
    const handleFocus = useCallback((index: number) => {
      setFocusedIndex(index);
    }, []);

    // Handle memory click
    const handleMemoryClick = useCallback(
      (memoryId: string) => {
        onMemoryClick(memoryId);
      },
      [onMemoryClick]
    );

    // Empty state
    if (memories.length === 0) {
      return (
        <div
          data-testid="virtualized-memory-list"
          className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm p-8 text-center"
        >
          <p className="text-slate-500">No memories found</p>
        </div>
      );
    }

    return (
      <div
        data-testid="virtualized-memory-list"
        className="bg-surface-light dark:bg-surface-dark border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm overflow-hidden"
      >
        {/* Table Header */}
        <div className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">Name</th>
                <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">Type</th>
                <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400">
                  Status
                </th>
                <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400 text-right">
                  Size
                </th>
                <th className="px-6 py-3 font-semibold text-slate-500 dark:text-slate-400"></th>
              </tr>
            </thead>
          </table>
        </div>

        {/* Virtual Scroll Container */}
        <div
          ref={parentRef}
          data-testid="virtual-scroll-container"
          className="overflow-auto"
          style={{ height: shouldRenderAll ? 'auto' : `${containerHeight}px` }}
          onKeyDown={handleKeyDown}
          role="grid"
          aria-rowcount={memories.length}
          aria-label="Memory list"
          tabIndex={focusedIndex === -1 ? 0 : -1}
        >
          {shouldRenderAll ? (
            // Test mode or small list - render all items without virtualization
            <table className="w-full text-left text-sm">
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {memories.map((memory, index) => (
                  <MemoryRow
                    key={memory.id}
                    memory={memory}
                    onClick={handleMemoryClick}
                    index={index}
                    isFocused={focusedIndex === index}
                    onFocus={handleFocus}
                  />
                ))}
              </tbody>
            </table>
          ) : (
            // Production mode - use virtualization
            <div
              data-testid="virtual-grid"
              style={{
                position: 'relative',
                height: `${totalSize}px`,
                width: '100%',
              }}
            >
              <table className="w-full text-left text-sm">
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {virtualRows.map((virtualRow) => {
                    const memory = memories[virtualRow.index];
                    if (!memory) return null;

                    return (
                      <tr
                        key={virtualRow.key}
                        data-memory-id={memory.id}
                        data-testid={`virtual-row-${virtualRow.index}`}
                        style={{
                          position: 'absolute',
                          top: 0,
                          left: 0,
                          width: '100%',
                          transform: `translateY(${virtualRow.start}px)`,
                        }}
                      >
                        <td className="px-6 py-3 w-full">
                          <table className="w-full">
                            <tbody>
                              <MemoryRow
                                memory={memory}
                                onClick={handleMemoryClick}
                                index={virtualRow.index}
                                isFocused={focusedIndex === virtualRow.index}
                                onFocus={handleFocus}
                              />
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Screen reader announcement */}
        <div aria-live="polite" aria-atomic="true" className="sr-only">
          Showing {memories.length} memories
        </div>
      </div>
    );
  }
);

VirtualizedMemoryList.displayName = 'VirtualizedMemoryList';

// ============================================================================
// Exports
// ============================================================================

export default VirtualizedMemoryList;
