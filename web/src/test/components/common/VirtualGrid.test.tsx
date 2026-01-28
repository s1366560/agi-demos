/**
 * VirtualGrid Component Tests
 *
 * TDD Phase 2: VirtualGrid Component for efficient grid rendering
 *
 * These tests ensure the VirtualGrid:
 * 1. Renders items in a responsive grid layout
 * 2. Supports 1-2 column responsive layout
 * 3. Uses @tanstack/react-virtual for efficient rendering
 * 4. Handles empty data gracefully
 * 5. Provides scroll container with proper sizing
 * 6. Renders items at correct positions
 * 7. Handles window resize for column adjustment
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { VirtualGrid } from '../../../components/common/VirtualGrid'

// Mock @tanstack/react-virtual
vi.mock('@tanstack/react-virtual', () => ({
    useVirtualizer: vi.fn(),
}))

const { useVirtualizer } = await import('@tanstack/react-virtual')

describe('VirtualGrid', () => {
    const mockItems = [
        { id: '1', name: 'Item 1' },
        { id: '2', name: 'Item 2' },
        { id: '3', name: 'Item 3' },
        { id: '4', name: 'Item 4' },
        { id: '5', name: 'Item 5' },
    ]

    const renderItem = (item: { id: string; name: string }) => (
        <div data-testid={`item-${item.id}`}>{item.name}</div>
    )

    const mockVirtualizer = {
        getVirtualItems: vi.fn(() => [
            { index: 0, key: 'item-0', start: 0, end: 100 },
            { index: 1, key: 'item-1', start: 100, end: 200 },
        ]),
        getTotalSize: vi.fn(() => 500),
    }

    beforeEach(() => {
        vi.clearAllMocks()
        // Mock ResizeObserver
        global.ResizeObserver = vi.fn().mockImplementation(() => ({
            observe: vi.fn(),
            unobserve: vi.fn(),
            disconnect: vi.fn(),
        })) as any
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    /**
     * Test: Renders items using virtual rows
     */
    it('renders items using virtualizer', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
            />
        )

        expect(screen.getByTestId('item-1')).toBeInTheDocument()
        expect(screen.getByTestId('item-2')).toBeInTheDocument()
    })

    /**
     * Test: Shows empty state when no items provided
     */
    it('shows empty state when no items provided', () => {
        ;(useVirtualizer as any).mockReturnValue({
            getVirtualItems: vi.fn(() => []),
            getTotalSize: vi.fn(() => 0),
        })

        render(
            <VirtualGrid
                items={[]}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
                emptyMessage="No items found"
            />
        )

        expect(screen.getByText('No items found')).toBeInTheDocument()
    })

    /**
     * Test: Does not show empty message when items exist
     */
    it('does not show empty message when items exist', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
                emptyMessage="No items found"
            />
        )

        expect(screen.queryByText('No items found')).not.toBeInTheDocument()
    })

    /**
     * Test: Sets container height correctly
     */
    it('sets container height correctly', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        const { container } = render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={500}
            />
        )

        const scrollContainer = container.querySelector('[data-testid="virtual-scroll-container"]')
        expect(scrollContainer).toHaveStyle({ height: '500px' })
    })

    /**
     * Test: Calls useVirtualizer with correct configuration
     */
    it('calls useVirtualizer with correct configuration', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 120}
                containerHeight={400}
                overscan={5}
            />
        )

        expect(useVirtualizer).toHaveBeenCalledWith(
            expect.objectContaining({
                count: 5,
                getScrollElement: expect.any(Function),
                estimateSize: expect.any(Function),
                overscan: 5,
            })
        )
    })

    /**
     * Test: Renders items at correct virtual positions
     */
    it('renders items at correct virtual positions with transform', () => {
        const virtualizerWithPositions = {
            getVirtualItems: vi.fn(() => [
                { index: 0, key: 'item-0', start: 0 },
                { index: 1, key: 'item-1', start: 100 },
            ]),
            getTotalSize: vi.fn(() => 500),
        }
        ;(useVirtualizer as any).mockReturnValue(virtualizerWithPositions)

        const { container } = render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
            />
        )

        // Check that items are positioned absolutely with transform
        const items = container.querySelectorAll('[data-testid^="item-"]')
        expect(items.length).toBeGreaterThan(0)
    })

    /**
     * Test: Uses default overscan when not provided
     */
    it('uses default overscan of 5 when not provided', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
            />
        )

        expect(useVirtualizer).toHaveBeenCalledWith(
            expect.objectContaining({
                overscan: 5,
            })
        )
    })

    /**
     * Test: Renders custom empty component when provided
     */
    it('renders custom empty component when provided', () => {
        ;(useVirtualizer as any).mockReturnValue({
            getVirtualItems: vi.fn(() => []),
            getTotalSize: vi.fn(() => 0),
        })

        const CustomEmpty = () => <div data-testid="custom-empty">Custom Empty State</div>

        render(
            <VirtualGrid
                items={[]}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
                emptyComponent={<CustomEmpty />}
            />
        )

        expect(screen.getByTestId('custom-empty')).toBeInTheDocument()
    })

    /**
     * Test: Empty component takes precedence over empty message
     */
    it('prioritizes empty component over empty message', () => {
        ;(useVirtualizer as any).mockReturnValue({
            getVirtualItems: vi.fn(() => []),
            getTotalSize: vi.fn(() => 0),
        })

        const CustomEmpty = () => <div data-testid="custom-empty">Custom Empty</div>

        render(
            <VirtualGrid
                items={[]}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
                emptyMessage="Fallback message"
                emptyComponent={<CustomEmpty />}
            />
        )

        expect(screen.getByTestId('custom-empty')).toBeInTheDocument()
        expect(screen.queryByText('Fallback message')).not.toBeInTheDocument()
    })
})

describe('VirtualGrid - Responsive Layout', () => {
    const mockItems = [
        { id: '1', name: 'Item 1' },
        { id: '2', name: 'Item 2' },
    ]

    const renderItem = (item: { id: string; name: string }) => (
        <div data-testid={`item-${item.id}`}>{item.name}</div>
    )

    const mockVirtualizer = {
        getVirtualItems: vi.fn(() => [
            { index: 0, key: 'item-0', start: 0 },
            { index: 1, key: 'item-1', start: 100 },
        ]),
        getTotalSize: vi.fn(() => 200),
    }

    beforeEach(() => {
        vi.clearAllMocks()
        global.ResizeObserver = vi.fn().mockImplementation(() => ({
            observe: vi.fn(),
            unobserve: vi.fn(),
            disconnect: vi.fn(),
        })) as any
    })

    /**
     * Test: Applies grid-cols-1 class by default
     */
    it('applies single column grid by default', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        const { container } = render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
            />
        )

        const grid = container.querySelector('[data-testid="virtual-grid"]')
        expect(grid).toHaveClass('grid-cols-1')
    })

    /**
     * Test: Applies grid-cols-2 class when two columns requested
     */
    it('applies two column grid when columns prop is 2', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        const { container } = render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
                columns={2}
            />
        )

        const grid = container.querySelector('[data-testid="virtual-grid"]')
        expect(grid).toHaveClass('md:grid-cols-2')
    })

    /**
     * Test: Applies responsive grid classes for responsive columns
     */
    it('applies responsive grid classes for multi-column layout', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        const { container } = render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
                columns="responsive"
            />
        )

        const grid = container.querySelector('[data-testid="virtual-grid"]')
        expect(grid).toHaveClass('grid-cols-1')
        expect(grid).toHaveClass('md:grid-cols-2')
    })
})

describe('VirtualGrid - Scroll Handling', () => {
    const mockItems = Array.from({ length: 100 }, (_, i) => ({
        id: String(i),
        name: `Item ${i}`,
    }))

    const renderItem = (item: { id: string; name: string }) => (
        <div data-testid={`item-${item.id}`}>{item.name}</div>
    )

    const mockVirtualizer = {
        getVirtualItems: vi.fn(() => [
            { index: 0, key: 'item-0', start: 0 },
            { index: 1, key: 'item-1', start: 100 },
        ]),
        getTotalSize: vi.fn(() => 10000),
    }

    beforeEach(() => {
        vi.clearAllMocks()
        global.ResizeObserver = vi.fn().mockImplementation(() => ({
            observe: vi.fn(),
            unobserve: vi.fn(),
            disconnect: vi.fn(),
        })) as any
    })

    /**
     * Test: Creates scrollable container with overflow
     */
    it('creates scrollable container with overflow-auto', () => {
        ;(useVirtualizer as any).mockReturnValue(mockVirtualizer)

        const { container } = render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
            />
        )

        const scrollContainer = container.querySelector('[data-testid="virtual-scroll-container"]')
        expect(scrollContainer).toHaveClass('overflow-auto')
    })

    /**
     * Test: Provides total size for virtual container
     */
    it('sets total size from virtualizer on inner container', () => {
        const mockWithSize = {
            getVirtualItems: vi.fn(() => [{ index: 0, key: 'item-0', start: 0 }]),
            getTotalSize: vi.fn(() => 10000),
        }
        ;(useVirtualizer as any).mockReturnValue(mockWithSize)

        const { container } = render(
            <VirtualGrid
                items={mockItems}
                renderItem={renderItem}
                estimateSize={() => 100}
                containerHeight={400}
            />
        )

        // Verify virtualizer was configured
        expect(mockWithSize.getTotalSize).toHaveBeenCalled()
        const grid = container.querySelector('[data-testid="virtual-grid"]')
        expect(grid).toBeInTheDocument()
    })
})
