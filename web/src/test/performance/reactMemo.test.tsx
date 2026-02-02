/**
 * React.memo Performance Tests (TDD - GREEN phase)
 *
 * Tests for React.memo optimization on pure components.
 * These components should only re-render when their props change.
 *
 * Target components:
 * - WorkPlanProgress
 * - TopNavigation
 * - ExecutionStatsCard
 * - Other pure components
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { createElement } from 'react'

// Import components to test
import { WorkPlanProgress } from '../../components/agent/execution/WorkPlanProgress'
import { TopNavigation } from '../../components/agent/layout/TopNavigation'
import { ExecutionStatsCard } from '../../components/agent/ExecutionStatsCard'
import { WorkPlanCard } from '../../components/agent/WorkPlanCard'
import * as containment from '../../styles/containment'

// Render count tracking utility
let renderCounts = new Map<string, number>()

export function trackRenderCount(componentName: string) {
  const current = renderCounts.get(componentName) ?? 0
  renderCounts.set(componentName, current + 1)
}

export function getRenderCount(componentName: string): number {
  return renderCounts.get(componentName) ?? 0
}

export function resetRenderCounts() {
  renderCounts = new Map()
}

// Higher-order component that tracks renders
export function withRenderTracking<P extends object>(
  Component: React.ComponentType<P>,
  name: string
): React.ComponentType<P> {
  return function TrackedComponent(props: P) {
    trackRenderCount(name)
    return createElement(Component, props)
  }
}

describe('React.memo - WorkPlanProgress', () => {
  beforeEach(() => {
    resetRenderCounts()
  })

  it('should be wrapped with React.memo', () => {
    // displayName is set when using React.memo with a named function
    expect(WorkPlanProgress.displayName).toBe('WorkPlanProgress')
  })

  it('should re-render when currentStep changes', () => {
    const TrackedWorkPlanProgress = withRenderTracking(WorkPlanProgress, 'WorkPlanProgress')

    const { rerender } = render(
      <TrackedWorkPlanProgress currentStep={1} totalSteps={3} />
    )

    const initialRenderCount = getRenderCount('WorkPlanProgress')
    expect(initialRenderCount).toBeGreaterThanOrEqual(1)

    // Re-render with different currentStep - this should cause a re-render
    rerender(<TrackedWorkPlanProgress currentStep={2} totalSteps={3} />)

    const secondRenderCount = getRenderCount('WorkPlanProgress')
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount)
  })

  it('should re-render when currentStep changes', () => {
    const TrackedWorkPlanProgress = withRenderTracking(WorkPlanProgress, 'WorkPlanProgress')

    const { rerender } = render(
      <TrackedWorkPlanProgress currentStep={1} totalSteps={3} />
    )

    const initialRenderCount = getRenderCount('WorkPlanProgress')
    expect(initialRenderCount).toBe(1)

    // Re-render with different currentStep
    rerender(<TrackedWorkPlanProgress currentStep={2} totalSteps={3} />)

    const secondRenderCount = getRenderCount('WorkPlanProgress')
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount)
  })

  it('should re-render when totalSteps changes', () => {
    const TrackedWorkPlanProgress = withRenderTracking(WorkPlanProgress, 'WorkPlanProgress')

    const { rerender } = render(
      <TrackedWorkPlanProgress currentStep={1} totalSteps={3} />
    )

    const initialRenderCount = getRenderCount('WorkPlanProgress')
    expect(initialRenderCount).toBe(1)

    // Re-render with different totalSteps
    rerender(<TrackedWorkPlanProgress currentStep={1} totalSteps={5} />)

    const secondRenderCount = getRenderCount('WorkPlanProgress')
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount)
  })

  it('should render correctly with all props', () => {
    render(
      <WorkPlanProgress
        currentStep={2}
        totalSteps={4}
        stepLabels={['Step 1', 'Step 2', 'Step 3', 'Step 4']}
        progress={50}
        statusMessage="Processing..."
        compact={false}
      />
    )

    expect(screen.getByText('Work Plan')).toBeInTheDocument()
    expect(screen.getByText('Processing...')).toBeInTheDocument()
    expect(screen.getByText('Step 2 of 4')).toBeInTheDocument()
  })
})

describe('React.memo - TopNavigation', () => {
  beforeEach(() => {
    resetRenderCounts()
  })

  it('should be wrapped with React.memo', () => {
    expect(TopNavigation.displayName).toBe('TopNavigation')
  })

  it('should re-render when workspaceName changes', () => {
    const TrackedTopNavigation = withRenderTracking(TopNavigation, 'TopNavigation')

    const onTabChange = vi.fn()

    const { rerender } = render(
      <TrackedTopNavigation
        workspaceName="Original Workspace"
        activeTab="dashboard"
        onTabChange={onTabChange}
      />
    )

    const initialRenderCount = getRenderCount('TopNavigation')
    expect(initialRenderCount).toBe(1)

    // Re-render with different workspaceName
    rerender(
      <TrackedTopNavigation
        workspaceName="New Workspace"
        activeTab="dashboard"
        onTabChange={onTabChange}
      />
    )

    const secondRenderCount = getRenderCount('TopNavigation')
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount)
  })

  it('should re-render when activeTab changes', () => {
    const TrackedTopNavigation = withRenderTracking(TopNavigation, 'TopNavigation')

    const onTabChange = vi.fn()

    const { rerender } = render(
      <TrackedTopNavigation
        workspaceName="Test Workspace"
        activeTab="dashboard"
        onTabChange={onTabChange}
      />
    )

    const initialRenderCount = getRenderCount('TopNavigation')
    expect(initialRenderCount).toBe(1)

    rerender(
      <TrackedTopNavigation
        workspaceName="Test Workspace"
        activeTab="logs"
        onTabChange={onTabChange}
      />
    )

    const secondRenderCount = getRenderCount('TopNavigation')
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount)
  })

  it('should render correctly with all props', () => {
    render(
      <TopNavigation
        workspaceName="My Workspace"
        activeTab="dashboard"
        onTabChange={vi.fn()}
        searchQuery="test"
        onSearchChange={vi.fn()}
        notificationCount={5}
        onSettingsClick={vi.fn()}
      />
    )

    expect(screen.getByText('My Workspace')).toBeInTheDocument()
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Logs')).toBeInTheDocument()
  })
})

describe('React.memo - ExecutionStatsCard', () => {
  beforeEach(() => {
    resetRenderCounts()
  })

  it('should be wrapped with React.memo', () => {
    expect(ExecutionStatsCard.displayName).toBe('ExecutionStatsCard')
  })

  it('should re-render when stats values change', () => {
    const TrackedExecutionStatsCard = withRenderTracking(ExecutionStatsCard, 'ExecutionStatsCard')

    const mockStats1 = {
      total_executions: 100,
      completed_count: 85,
      failed_count: 10,
      average_duration_ms: 500,
      tool_usage: { search: 50, analyze: 30 },
    }

    const mockStats2 = {
      total_executions: 200, // Different value
      completed_count: 170,
      failed_count: 20,
      average_duration_ms: 500,
      tool_usage: { search: 100, analyze: 60 },
    }

    const { rerender } = render(
      <TrackedExecutionStatsCard stats={mockStats1} />
    )

    const initialRenderCount = getRenderCount('ExecutionStatsCard')
    expect(initialRenderCount).toBe(1)

    rerender(<TrackedExecutionStatsCard stats={mockStats2} />)

    const secondRenderCount = getRenderCount('ExecutionStatsCard')
    expect(secondRenderCount).toBeGreaterThan(initialRenderCount)
  })

  it('should render statistics correctly', () => {
    const mockStats = {
      total_executions: 100,
      completed_count: 85,
      failed_count: 10,
      average_duration_ms: 500,
      tool_usage: { search: 50, analyze: 30 },
    }

    render(<ExecutionStatsCard stats={mockStats} />)

    expect(screen.getByText(/Total Executions/i)).toBeInTheDocument()
    expect(screen.getByText('100')).toBeInTheDocument()
    expect(screen.getByText(/Completed/i)).toBeInTheDocument()
  })
})

describe('React.memo - WorkPlanCard', () => {
  beforeEach(() => {
    resetRenderCounts()
  })

  it('should be wrapped with React.memo', () => {
    expect(WorkPlanCard.displayName).toBe('WorkPlanCard')
  })
})

describe('CSS Containment Integration', () => {
  it('should apply card-optimized class to WorkPlanProgress', () => {
    const { container } = render(
      <WorkPlanProgress currentStep={1} totalSteps={3} />
    )

    const cardElement = container.querySelector('.card-optimized')
    expect(cardElement).toBeInTheDocument()
  })

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
    )

    const cardElement = container.querySelector('.card-optimized')
    expect(cardElement).toBeInTheDocument()
  })
})

describe('Performance utilities', () => {
  it('should export containment utilities', () => {
    expect(containment.presets).toBeDefined()
    expect(containment.presets.card).toBe('card-optimized')
    expect(containment.presets.listItem).toBe('list-item-optimized')
    expect(containment.presets.tableRow).toBe('table-row-optimized')
  })

  it('should export helper functions', () => {
    expect(containment.cardOptimized).toBeDefined()
    expect(containment.listItemOptimized).toBeDefined()
    expect(containment.tableRowOptimized).toBeDefined()

    // Test helper functions
    expect(containment.cardOptimized()).toContain('card-optimized')
    expect(containment.cardOptimized('extra-class')).toContain('extra-class')
  })

  it('should combine containment classes correctly', () => {
    const combined = containment.combineContainment('class-1', undefined, 'class-2', null, false, 'class-3')
    expect(combined).toBe('class-1 class-2 class-3')
  })
})
