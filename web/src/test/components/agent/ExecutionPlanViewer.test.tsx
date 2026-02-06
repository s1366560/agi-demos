/**
 * Tests for ExecutionPlanViewer component
 *
 * TDD Approach: Tests written first, implementation to follow
 */

import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ExecutionPlanViewer } from '../../../components/agent/ExecutionPlanViewer';
import { ExecutionPlan, ExecutionPlanStatus, ExecutionStep } from '../../../types/agent';

// Mock the hook
const mockUsePlanModeEvents = vi.fn();

vi.mock('../../../hooks/usePlanModeEvents', () => ({
  usePlanModeEvents: () => mockUsePlanModeEvents(),
}));

describe('ExecutionPlanViewer', () => {
  let mockPlan: ExecutionPlan;
  let mockSteps: ExecutionStep[];

  beforeEach(() => {
    vi.clearAllMocks();

    mockSteps = [
      {
        step_id: 'step-1',
        description: 'Read file from disk',
        tool_name: 'read_file',
        tool_input: { path: '/test/file.txt' },
        dependencies: [],
        status: 'completed',
        result: 'File content',
        started_at: '2026-01-29T00:00:00Z',
        completed_at: '2026-01-29T00:00:01Z',
      },
      {
        step_id: 'step-2',
        description: 'Process data with transformation',
        tool_name: 'transform_data',
        tool_input: { data: 'test' },
        dependencies: ['step-1'],
        status: 'running',
        started_at: '2026-01-29T00:00:02Z',
      },
      {
        step_id: 'step-3',
        description: 'Write results to database',
        tool_name: 'write_db',
        tool_input: { table: 'results' },
        dependencies: ['step-2'],
        status: 'pending',
      },
      {
        step_id: 'step-4',
        description: 'Failed step example',
        tool_name: 'failing_tool',
        tool_input: {},
        dependencies: [],
        status: 'failed',
        error: 'Tool execution failed',
        started_at: '2026-01-29T00:00:00Z',
        completed_at: '2026-01-29T00:00:01Z',
      },
    ];

    mockPlan = {
      id: 'plan-123',
      conversation_id: 'conv-123',
      user_query: 'Test query for planning',
      steps: mockSteps,
      status: 'executing' as ExecutionPlanStatus,
      reflection_enabled: true,
      max_reflection_cycles: 3,
      completed_steps: ['step-1'],
      failed_steps: ['step-4'],
      progress_percentage: 25,
      is_complete: false,
      started_at: '2026-01-29T00:00:00Z',
    };
  });

  describe('Progress Overview', () => {
    it('displays progress overview with correct statistics', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Check total steps
      expect(screen.getByText(/Total Steps:\s*4/i)).toBeInTheDocument();

      // Check completed steps
      expect(screen.getByText(/Completed:\s*1/i)).toBeInTheDocument();

      // Check failed steps
      expect(screen.getByText(/Failed:\s*1/i)).toBeInTheDocument();

      // Check progress percentage
      expect(screen.getByText(/25%/)).toBeInTheDocument();
    });

    it('displays progress bar with correct percentage', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Progress bar should be visible
      const progressBar = screen.getByRole('progressbar');
      expect(progressBar).toBeInTheDocument();
      expect(progressBar).toHaveAttribute('aria-valuenow', '25');
    });

    it('calculates remaining steps correctly', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // 4 total - 1 completed - 1 failed = 2 remaining
      expect(screen.getByText(/Remaining:\s*2/i)).toBeInTheDocument();
    });

    it('shows estimated time remaining when available', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      const planWithTiming = {
        ...mockPlan,
        started_at: '2026-01-29T00:00:00Z',
      };

      render(<ExecutionPlanViewer planId="plan-123" plan={planWithTiming} />);

      // Estimated time should be displayed (calculated from timing)
      expect(screen.getByText(/Estimated Time:/i)).toBeInTheDocument();
    });
  });

  describe('Steps List', () => {
    it('renders all steps in order', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // All step descriptions should be visible
      expect(screen.getByText('Read file from disk')).toBeInTheDocument();
      expect(screen.getByText('Process data with transformation')).toBeInTheDocument();
      expect(screen.getByText('Write results to database')).toBeInTheDocument();
      expect(screen.getByText('Failed step example')).toBeInTheDocument();
    });

    it('displays correct status icons for each step', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Check for status indicators (icons)
      const stepItems = screen.getAllByTestId(/step-item-/);
      expect(stepItems).toHaveLength(4);

      // Completed step should have success indicator
      const completedStep = screen.getByTestId('step-item-step-1');
      expect(completedStep).toHaveClass(/status-completed/);

      // Running step should have loading indicator
      const runningStep = screen.getByTestId('step-item-step-2');
      expect(runningStep).toHaveClass(/status-running/);

      // Pending step should have default indicator
      const pendingStep = screen.getByTestId('step-item-step-3');
      expect(pendingStep).toHaveClass(/status-pending/);

      // Failed step should have error indicator
      const failedStep = screen.getByTestId('step-item-step-4');
      expect(failedStep).toHaveClass(/status-failed/);
    });

    it('shows step details on expansion', async () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Click on a step to expand
      const stepItem = screen.getByTestId('step-item-step-1');

      // Before expansion, details should not be visible
      expect(screen.queryByTestId('step-details-step-1')).not.toBeInTheDocument();

      // Click to expand using fireEvent
      fireEvent.click(stepItem);

      // After expansion, details should be visible
      await waitFor(() => {
        expect(screen.getByTestId('step-details-step-1')).toBeInTheDocument();
        expect(screen.getByText(/Tool:/i)).toBeInTheDocument();
      });
    });

    it('displays step tool information', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Tool names should be displayed
      expect(screen.getByText(/read_file/)).toBeInTheDocument();
      expect(screen.getByText(/transform_data/)).toBeInTheDocument();
      expect(screen.getByText(/write_db/)).toBeInTheDocument();
      expect(screen.getByText(/failing_tool/)).toBeInTheDocument();
    });

    it('displays error message for failed steps', async () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Failed step - need to expand to see error
      const failedStep = screen.getByTestId('step-item-step-4');
      fireEvent.click(failedStep);

      await waitFor(() => {
        expect(screen.getByTestId('step-details-step-4')).toBeInTheDocument();
        expect(screen.getByText(/Tool execution failed/i)).toBeInTheDocument();
      });
    });

    it('shows dependencies between steps', async () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // step-2 depends on step-1 - need to expand
      const step2 = screen.getByTestId('step-item-step-2');
      fireEvent.click(step2);

      await waitFor(() => {
        expect(screen.getByTestId('step-details-step-2')).toBeInTheDocument();
        expect(screen.getByText(/Depends on:/i)).toBeInTheDocument();
      });

      // step-3 depends on step-2 - need to expand
      const step3 = screen.getByTestId('step-item-step-3');
      fireEvent.click(step3);

      await waitFor(() => {
        expect(screen.getByTestId('step-details-step-3')).toBeInTheDocument();
      });
    });
  });

  describe('Reflections List', () => {
    it('displays reflections when present', () => {
      const mockReflections = [
        {
          id: 'ref-1',
          timestamp: '2026-01-29T00:00:10Z',
          cycle_number: 1,
          summary: 'Plan needs adjustment',
          suggested_changes: ['Add validation step', 'Improve error handling'],
        },
      ];

      mockUsePlanModeEvents.mockReturnValue({
        reflections: mockReflections,
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      expect(screen.getByText(/Reflections/i)).toBeInTheDocument();
      expect(screen.getByText('Plan needs adjustment')).toBeInTheDocument();
      expect(screen.getByText('Add validation step')).toBeInTheDocument();
      expect(screen.getByText('Improve error handling')).toBeInTheDocument();
    });

    it('shows reflection cycle number', () => {
      const mockReflections = [
        {
          id: 'ref-1',
          timestamp: '2026-01-29T00:00:10Z',
          cycle_number: 2,
          summary: 'Second reflection',
          suggested_changes: [],
        },
      ];

      mockUsePlanModeEvents.mockReturnValue({
        reflections: mockReflections,
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      expect(screen.getByText(/Cycle 2/i)).toBeInTheDocument();
    });

    it('does not display reflections section when no reflections', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      expect(screen.queryByText(/Reflections/i)).not.toBeInTheDocument();
    });
  });

  describe('Adjustments History', () => {
    it('displays plan adjustments when present', () => {
      const mockAdjustments = [
        {
          id: 'adj-1',
          timestamp: '2026-01-29T00:00:20Z',
          type: 'step_added',
          description: 'Added validation step',
          step_id: 'step-5',
        },
      ];

      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: mockAdjustments,
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      expect(screen.getByText(/Adjustments/i)).toBeInTheDocument();
      expect(screen.getByText('Added validation step')).toBeInTheDocument();
    });

    it('shows adjustment type with appropriate icon', () => {
      const mockAdjustments = [
        {
          id: 'adj-1',
          timestamp: '2026-01-29T00:00:20Z',
          type: 'step_removed' as const,
          description: 'Removed redundant step',
          step_id: 'step-2',
        },
      ];

      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: mockAdjustments,
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      const adjustmentCard = screen.getByTestId('adjustment-adj-1');
      expect(adjustmentCard).toHaveClass(/adjustment-item/);
    });

    it('does not display adjustments section when no adjustments', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      expect(screen.queryByText(/Adjustments/i)).not.toBeInTheDocument();
    });
  });

  describe('Real-time Updates', () => {
    it('updates step status when SSE event received', async () => {
      const { rerender } = render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Initial state: step-3 is pending
      expect(screen.getByTestId('step-item-step-3')).toHaveClass(/status-pending/);

      // Simulate SSE update
      const updatedPlan: ExecutionPlan = {
        ...mockPlan,
        steps: mockSteps.map((s) =>
          s.step_id === 'step-3'
            ? { ...s, status: 'running' as const, started_at: '2026-01-29T00:00:05Z' }
            : s
        ),
      };

      rerender(<ExecutionPlanViewer planId="plan-123" plan={updatedPlan} />);

      // After update: step-3 should be running
      await waitFor(() => {
        expect(screen.getByTestId('step-item-step-3')).toHaveClass(/status-running/);
      });
    });

    it('updates progress percentage when steps complete', async () => {
      const { rerender } = render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Initial progress: 25%
      expect(screen.getByText('25%')).toBeInTheDocument();

      // Complete more steps
      const updatedPlan: ExecutionPlan = {
        ...mockPlan,
        steps: mockSteps.map((s) =>
          s.step_id === 'step-3'
            ? {
                ...s,
                status: 'completed' as const,
                result: 'Done',
                completed_at: '2026-01-29T00:00:06Z',
              }
            : s
        ),
        completed_steps: ['step-1', 'step-3'],
        progress_percentage: 50,
      };

      rerender(<ExecutionPlanViewer planId="plan-123" plan={updatedPlan} />);

      // Updated progress: 50%
      await waitFor(() => {
        expect(screen.getByText('50%')).toBeInTheDocument();
      });
    });
  });

  describe('Execution Statistics', () => {
    it('displays execution duration when plan is running', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      expect(screen.getByText(/Duration:/i)).toBeInTheDocument();
    });

    it('shows completion time when plan is completed', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      const completedPlan: ExecutionPlan = {
        ...mockPlan,
        status: 'completed' as ExecutionPlanStatus,
        completed_at: '2026-01-29T00:01:00Z',
        is_complete: true,
        progress_percentage: 100,
      };

      render(<ExecutionPlanViewer planId="plan-123" plan={completedPlan} />);

      expect(screen.getByText(/Completed at:/i)).toBeInTheDocument();
    });

    it('displays reflection cycles info when enabled', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      expect(screen.getByText(/Reflection Cycles:\s*0\/3/i)).toBeInTheDocument();
    });
  });

  describe('Empty States', () => {
    it('displays loading state when plan is null', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={null} />);

      expect(screen.getByText(/Loading plan.../i)).toBeInTheDocument();
    });

    it('displays message when plan has no steps', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      const emptyPlan: ExecutionPlan = {
        ...mockPlan,
        steps: [],
        is_complete: true,
        progress_percentage: 100,
      };

      render(<ExecutionPlanViewer planId="plan-123" plan={emptyPlan} />);

      expect(screen.getByText(/No steps in this plan/i)).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('has proper ARIA labels', () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Progress bar should have aria-label
      const progressBar = screen.getByRole('progressbar');
      expect(progressBar).toHaveAttribute('aria-label', 'Plan execution progress');

      // Steps should be in a list
      const stepsList = screen.getByRole('list');
      expect(stepsList).toBeInTheDocument();
    });

    it('supports keyboard navigation', async () => {
      mockUsePlanModeEvents.mockReturnValue({
        reflections: [],
        adjustments: [],
      });

      render(<ExecutionPlanViewer planId="plan-123" plan={mockPlan} />);

      // Step items should be clickable/div with role=button
      const stepItems = screen.getAllByTestId(/step-item-/);
      expect(stepItems.length).toBeGreaterThan(0);

      const firstStep = stepItems[0];
      expect(firstStep).toHaveAttribute('role', 'button');
      expect(firstStep).toHaveAttribute('tabIndex', '0');

      // Test keyboard navigation - Enter key
      fireEvent.keyDown(firstStep, { key: 'Enter', code: 'Enter' });

      await waitFor(() => {
        expect(screen.getByTestId('step-details-step-1')).toBeInTheDocument();
      });
    });
  });
});
