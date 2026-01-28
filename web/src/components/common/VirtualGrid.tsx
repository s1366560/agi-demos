/**
 * VirtualGrid Component
 *
 * A responsive virtualized grid component using @tanstack/react-virtual.
 * Efficiently renders large datasets by only rendering visible items.
 *
 * Features:
 * - Responsive 1-2 column layout
 * - Configurable item height estimation
 * - Customizable overscan for smoother scrolling
 * - Empty state handling
 * - Proper scroll container sizing
 */

import React, { useRef, memo } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

export interface VirtualGridProps<T> {
    /** Array of items to render */
    items: T[]
    /** Render function for each item */
    renderItem: (item: T, index: number) => React.ReactNode
    /** Estimated height of each item in pixels */
    estimateSize: () => number
    /** Fixed height of the scroll container */
    containerHeight: number
    /** Number of items to render outside visible area (default: 5) */
    overscan?: number
    /** Message to display when items array is empty */
    emptyMessage?: string
    /** Custom component to render when empty (takes precedence over emptyMessage) */
    emptyComponent?: React.ReactNode
    /** Number of columns: 1, 2, or 'responsive' for 1 on mobile, 2 on desktop */
    columns?: 1 | 2 | 'responsive'
    /** Optional className for the grid container */
    className?: string
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
    const parentRef = useRef<HTMLDivElement>(null)

    // Set up virtual row virtualizer
    const rowVirtualizer = useVirtualizer({
        count: items.length,
        getScrollElement: () => parentRef.current,
        estimateSize,
        overscan,
    })

    // Get virtual rows
    const virtualRows = rowVirtualizer.getVirtualItems()
    const totalSize = rowVirtualizer.getTotalSize()

    // Determine grid columns classes
    const getGridClasses = (): string => {
        const base = 'grid gap-4'
        switch (columns) {
            case 1:
                return `${base} grid-cols-1`
            case 2:
                return `${base} grid-cols-1 md:grid-cols-2`
            case 'responsive':
            default:
                return `${base} grid-cols-1 md:grid-cols-2`
        }
    }

    // Handle empty state
    if (items.length === 0) {
        if (emptyComponent) {
            return <>{emptyComponent}</>
        }
        if (emptyMessage) {
            return (
                <div className={`flex items-center justify-center ${className}`} style={{ height: containerHeight }}>
                    <div className="text-center text-slate-500 dark:text-slate-400">
                        <span className="material-symbols-outlined text-4xl mb-2">category</span>
                        <p>{emptyMessage}</p>
                    </div>
                </div>
            )
        }
        return null
    }

    return (
        <div
            ref={parentRef}
            data-testid="virtual-scroll-container"
            className="overflow-auto"
            style={{ height: `${containerHeight}px` }}
        >
            <div
                data-testid="virtual-grid"
                className={getGridClasses()}
                style={{
                    position: 'relative',
                    height: `${totalSize}px`,
                    width: '100%',
                    padding: '1rem',
                }}
            >
                {virtualRows.map((virtualRow) => {
                    const item = items[virtualRow.index]
                    if (!item) return null

                    return (
                        <div
                            key={virtualRow.key}
                            data-testid={`virtual-row-${virtualRow.index}`}
                            style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                width: '100%',
                                transform: `translateY(${virtualRow.start}px)`,
                            }}
                        >
                            {renderItem(item, virtualRow.index)}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

/**
 * Memoized VirtualGrid component.
 * Prevents unnecessary re-renders when parent components update.
 */
export const VirtualGrid = memo(VirtualGridInternal) as <T>(
    props: VirtualGridProps<T>
) => React.ReactElement
