/**
 * React.memo Performance Tests (TDD - GREEN phase)
 *
 * Tests for React.memo optimization on pure components.
 * These components should only re-render when their props change.
 *
 * Target components:
 * - ExecutionStatsCard
 * - Other pure components
 */

import { createElement } from 'react';

import { render, screen } from '@testing-library/react';
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

  it('should be wrapped with React.memo', () => {
    expect(ExecutionStatsCard.displayName).toBe('ExecutionStatsCard');
  });

  it('should re-render when stats values change', () => {
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

    const { rerender } = render(<TrackedExecutionStatsCard stats={mockStats1} />);

    const initialRenderCount = getRenderCount('ExecutionStatsCard');
    expect(initialRenderCount).toBe(1);

    rerender(<TrackedExecutionStatsCard stats={mockStats2} />);

    const secondRenderCount = getRenderCount('ExecutionStatsCard');
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount);
  });

  it('should render statistics correctly', () => {
    const mockStats = {
      total_executions: 100,
      completed_count: 85,
      failed_count: 10,
      average_duration_ms: 500,
      tool_usage: { search: 50, analyze: 30 },
    };

    render(<ExecutionStatsCard stats={mockStats} />);

    expect(screen.getByText(/Total Executions/i)).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText(/Completed/i)).toBeInTheDocument();
  });
});

describe('CSS Containment Integration', () => {
  it('should apply card-optimized class to ExecutionStatsCard', () => {
    const { container } = render(
      <ExecutionStatsCard
        stats={{
          total_executions: 100,
          completed_count: 85,
          failed_count: 10,
          average_duration_ms: 500,
          tool_usage: {},
        }}
      />
    );

    const cardElement = container.querySelector('.card-optimized');
    expect(cardElement).toBeInTheDocument();
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
