/**
 * React.memo Performance Tests (TDD - GREEN phase)
 *
 * Tests for component optimization patterns including render tracking,
 * lazy-loaded Ant Design components, and CSS containment utilities.
 *
 * Target components:
 * - ExecutionStatsCard (plain function component using lazy Antd wrappers)
 * - CSS containment utilities
 */

import { createElement, Suspense } from 'react';

import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import '@testing-library/jest-dom/vitest';

// Import components to test
import { ExecutionStatsCard } from '../../components/agent/ExecutionStatsCard';
import * as containment from '../../styles/containment';
// Render count tracking utility
let renderCounts = new Map<string, number>();

function trackRenderCount(componentName: string) {
  const current = renderCounts.get(componentName) ?? 0;
  renderCounts.set(componentName, current + 1);
}

function getRenderCount(componentName: string): number {
  return renderCounts.get(componentName) ?? 0;
}

function resetRenderCounts() {
  renderCounts = new Map();
}

// Higher-order component that tracks renders
function withRenderTracking<P extends object>(
  Component: React.ComponentType<P>,
  name: string
): React.ComponentType<P> {
  return function TrackedComponent(props: P) {
    trackRenderCount(name);
    return createElement(Component, props);
  };
}

describe('React.memo - ExecutionStatsCard', () => {
  beforeEach(() => {
    resetRenderCounts();
  });

  it('should be a valid function component', () => {
    // ExecutionStatsCard is a plain function component (not wrapped with React.memo)
    expect(typeof ExecutionStatsCard).toBe('function');
    expect(ExecutionStatsCard.name).toBe('ExecutionStatsCard');
  });

  it('should re-render when stats values change', async () => {
    const TrackedExecutionStatsCard = withRenderTracking(ExecutionStatsCard, 'ExecutionStatsCard');

    const mockStats1 = {
      total_executions: 100,
      completed_count: 85,
      failed_count: 10,
      average_duration_ms: 500,
      tool_usage: { search: 50, analyze: 30 },
    };

    const mockStats2 = {
      total_executions: 200, // Different value
      completed_count: 170,
      failed_count: 20,
      average_duration_ms: 500,
      tool_usage: { search: 100, analyze: 60 },
    };

    const { rerender } = render(
      <Suspense fallback={<div>Loading...</div>}>
        <TrackedExecutionStatsCard stats={mockStats1} />
      </Suspense>
    );

    await waitFor(() => {
      expect(screen.getByText(/Execution Statistics/i)).toBeInTheDocument();
    });

    const initialRenderCount = getRenderCount('ExecutionStatsCard');
    // May be 1 or 2 depending on StrictMode double-render
    expect(initialRenderCount).toBeGreaterThanOrEqual(1);

    rerender(
      <Suspense fallback={<div>Loading...</div>}>
        <TrackedExecutionStatsCard stats={mockStats2} />
      </Suspense>
    );

    const secondRenderCount = getRenderCount('ExecutionStatsCard');
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount);
  });

  it('should render statistics correctly with lazy components', async () => {
    const mockStats = {
      total_executions: 100,
      completed_count: 85,
      failed_count: 10,
      average_duration_ms: 500,
      tool_usage: { search: 50, analyze: 30 },
    };

    render(
      <Suspense fallback={<div>Loading...</div>}>
        <ExecutionStatsCard stats={mockStats} />
      </Suspense>
    );

    // Lazy Ant Design components load asynchronously; wait for them to resolve
    await waitFor(() => {
      expect(screen.getByText(/Execution Statistics/i)).toBeInTheDocument();
    });
  });
});

describe('CSS Containment Integration', () => {
  it('should render ExecutionStatsCard without crashing', async () => {
    // ExecutionStatsCard uses LazyCard (not the card-optimized CSS class directly).
    // Verify the component renders without errors.
    const { container } = render(
      <Suspense fallback={<div>Loading...</div>}>
        <ExecutionStatsCard
          stats={{
            total_executions: 100,
            completed_count: 85,
            failed_count: 10,
            average_duration_ms: 500,
            tool_usage: {},
          }}
        />
      </Suspense>
    );

    // Component should render something (even if lazy components show fallback)
    expect(container.firstChild).not.toBeNull();

    await waitFor(() => {
      expect(screen.getByText(/Execution Statistics/i)).toBeInTheDocument();
    });
  });
});

describe('Performance utilities', () => {
  it('should export containment utilities', () => {
    expect(containment.presets).toBeDefined();
    expect(containment.presets.card).toBe('card-optimized');
    expect(containment.presets.listItem).toBe('list-item-optimized');
    expect(containment.presets.tableRow).toBe('table-row-optimized');
  });

  it('should export helper functions', () => {
    expect(containment.cardOptimized).toBeDefined();
    expect(containment.listItemOptimized).toBeDefined();
    expect(containment.tableRowOptimized).toBeDefined();

    // Test helper functions
    expect(containment.cardOptimized()).toContain('card-optimized');
    expect(containment.cardOptimized('extra-class')).toContain('extra-class');
  });

  it('should combine containment classes correctly', () => {
    const combined = containment.combineContainment(
      'class-1',
      undefined,
      'class-2',
      null,
      false,
      'class-3'
    );
    expect(combined).toBe('class-1 class-2 class-3');
  });
});
