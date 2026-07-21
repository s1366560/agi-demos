/**
 * VirtualGrid Component - Virtualized grid for large datasets
 *
 * High-performance virtual scrolling grid component that only renders visible items.
 * Supports dynamic height estimation, responsive column layout, and test mode.
 *
 * @component
 *
 * @features
 * - Virtual scrolling - dramatically improves performance with large datasets
 * - Dynamic item height estimation for smooth scrolling
 * - Responsive columns (auto-adapts to screen width)
 * - Test environment detection (automatically disables virtualization)
 * - Configurable overscan buffer for smoother scrolling
 * - Empty state handling with customizable message or component
 *
 * @example
 * ```tsx
 * import { VirtualGrid } from '@/components/common/VirtualGrid'
 *
 * function MyList() {
 *   const items = [{ id: 1, name: 'Item 1' }, { id: 2, name: 'Item 2' }]
 *
 *   return (
 *     <VirtualGrid
 *       items={items}
 *       estimateSize={() => 50}
 *       containerHeight={600}
 *       renderItem={(item) => <div>{item.name}</div>}
 *       columns="responsive"
 *       emptyMessage="No items found"
 *     />
 *   )
 * }
 * ```
 */

import React, { useRef, memo, useMemo } from 'react';

import { useVirtualizer } from '@tanstack/react-virtual';
import { Tags } from 'lucide-react';

export interface VirtualGridProps<T> {
  /** Array of items to render */
  items: T[];
  /** Render function for each item - receives the item and its index */
  renderItem: (item: T, index: number) => React.ReactNode;
  /** Estimated height of each item in pixels - used for virtual scroll calculation */
  estimateSize: () => number;
  /** Fixed height of the scroll container in pixels */
  containerHeight: number;
  /** Number of items to render outside visible area for smoother scrolling (default: 5) */
  overscan?: number | undefined;
  /** Message to display when items array is empty */
  emptyMessage?: string | undefined;
  /** Custom component to render when empty - takes precedence over emptyMessage */
  emptyComponent?: React.ReactNode | undefined;
  /** Number of columns: 1, 2, or 'responsive' for 1 on mobile, 2 on desktop.
   * Note: virtualization only applies to single-column layouts; multi-column
   * grids render all items (virtual rows are always full-width). */
  columns?: 1 | 2 | 'responsive' | undefined;
  /** Optional className for the grid container */
  className?: string | undefined;
}

type VitestWindow = Window & {
  __vitest__?: {
    isFake?: boolean;
  };
};

function isVitestWindowFake(): boolean {
  return typeof window !== 'undefined' && (window as VitestWindow).__vitest__?.isFake === true;
}

function getItemKey(item: unknown, index: number): string {
  if (item && typeof item === 'object') {
    const record = item as Record<string, unknown>;
    if (typeof record.uuid === 'string' || typeof record.uuid === 'number') {
      return String(record.uuid);
    }
    if (typeof record.id === 'string' || typeof record.id === 'number') {
      return String(record.id);
    }
  }
  return String(index);
}

/**
 * Internal VirtualGrid component implementation
 */
function VirtualGridInternal<T>({
  items,
  renderItem,
  estimateSize,
  containerHeight,
  overscan = 5,
  emptyMessage,
  emptyComponent,
  columns = 'responsive',
  className = '',
}: VirtualGridProps<T>) {
  const parentRef = useRef<HTMLDivElement>(null);

  // Detect test environment - render all items without virtualization
  const isTestEnvironment = process.env.NODE_ENV === 'test' || isVitestWindowFake();

  // For small item counts, test environment, or multi-column layouts
  // (virtual rows are full-width, so grid columns cannot apply), render all.
  const shouldRenderAll = items.length <= 10 || isTestEnvironment || columns !== 1;

  // Determine grid columns classes - use useMemo for derived state
  const gridClasses = useMemo(() => {
    const base = 'grid gap-4';
    switch (columns) {
      case 1:
        return `${base} grid-cols-1`;
      case 2:
        return `${base} grid-cols-1 md:grid-cols-2`;
      case 'responsive':
      default:
        return `${base} grid-cols-1 md:grid-cols-2`;
    }
  }, [columns]);

  // Set up virtual row virtualizer - MUST be before any early returns
  // This ensures hooks are called in consistent order
  // eslint-disable-next-line react-hooks/incompatible-library
  const rowVirtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize,
    overscan,
  });

  // Get virtual rows
  const virtualRows = rowVirtualizer.getVirtualItems();
  const totalSize = rowVirtualizer.getTotalSize();

  // Handle empty state
  if (items.length === 0) {
    if (emptyComponent) {
      return <>{emptyComponent}</>;
    }
    if (emptyMessage) {
      return (
        <div
          className={`flex items-center justify-center ${className}`}
          style={{ height: containerHeight }}
        >
          <div className="text-center text-slate-500 dark:text-slate-400">
            <Tags size={36} className="mb-2 mx-auto" />
            <p>{emptyMessage}</p>
          </div>
        </div>
      );
    }
    return null;
  }

  // In test environment or with small datasets, render without virtualization
  if (shouldRenderAll) {
    return (
      <div data-testid="virtual-grid" className={gridClasses} style={{ padding: '1rem' }}>
        {items.map((item, index) => (
          <React.Fragment key={getItemKey(item, index)}>{renderItem(item, index)}</React.Fragment>
        ))}
      </div>
    );
  }

  return (
    <div
      ref={parentRef}
      data-testid="virtual-scroll-container"
      className="overflow-auto"
      style={{ height: containerHeight }}
    >
      <div
        data-testid="virtual-grid"
        className={gridClasses}
        role="list"
        aria-rowcount={items.length}
        style={{
          position: 'relative',
          height: totalSize,
          width: '100%',
          padding: '1rem',
        }}
      >
        {virtualRows.map((virtualRow) => {
          const item = items[virtualRow.index];
          if (!item) return null;

          return (
            <div
              key={virtualRow.key}
              data-testid={`virtual-row-${String(virtualRow.index)}`}
              role="listitem"
              aria-rowindex={virtualRow.index + 1}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${String(virtualRow.start)}px)`,
              }}
            >
              {renderItem(item, virtualRow.index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * Memoized VirtualGrid component.
 * Prevents unnecessary re-renders when parent components update.
 */
export const VirtualGrid = memo(VirtualGridInternal) as <T>(
  props: VirtualGridProps<T>
) => React.ReactElement;
