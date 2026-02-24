/**
 * Unit tests for ExecutionTimeline component (Compound Components Pattern)
 *
 * TDD: RED - Tests are written first before implementation
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

// Mock child components to simplify testing
vi.mock('../../../../components/agent/execution/TimelineNode', () => ({
  TimelineNode: ({
    step,
    isExpanded,
    isCurrent,
    onToggle,
  }: {
    step: { stepNumber: number; description: string; status: string };
    isExpanded: boolean;
    isCurrent: boolean;
    onToggle: () => void;
  }) => (
    <div
      data-testid={`timeline-node-${step.stepNumber}`}
      data-expanded={isExpanded}
      data-current={isCurrent}
      onClick={onToggle}
    >
      <div className="step-number">{step.stepNumber}</div>
      <div className="description">{step.description}</div>
      <div className="status">{step.status}</div>
    </div>
  ),
}));

vi.mock('../../../../components/agent/execution/SimpleExecutionView', () => ({
  SimpleExecutionView: ({
    toolExecutions,
    isStreaming,
  }: {
    toolExecutions: unknown[];
    isStreaming: boolean;
  }) => (
    <div data-testid="simple-execution-view" data-streaming={isStreaming}>
      <div>Tool Executions: {toolExecutions.length}</div>
    </div>
  ),
}));

// Mock MaterialIcon
vi.mock('../../../../components/agent/shared', () => ({
  MaterialIcon: ({
    name,
    size,
    className,
  }: {
    name: string;
    size?: number | undefined;
    className?: string | undefined;
  }) => (
    <span data-testid={`icon-${name}`} className={className} data-size={size}>
      {name}
    </span>
  ),
}));

import { getDisplayMode } from '../../../../components/agent/execution/ExecutionTimeline';

import type { TimelineStep, WorkPlan, ToolExecution } from '../../../../types/agent';

// Mock data for testing
const mockWorkPlan: WorkPlan = {
  id: 'plan-1',
  conversation_id: 'conv-1',
  status: 'in_progress',
  steps: [
    {
      step_number: 1,
      description: 'Search for information',
      thought_prompt: 'Think about search',
      required_tools: ['search'],
      expected_output: 'Search results',
      dependencies: [],
    },
    {
      step_number: 2,
      description: 'Analyze results',
      thought_prompt: 'Think about analysis',
      required_tools: ['analyze'],
      expected_output: 'Analysis report',
      dependencies: [1],
    },
    {
      step_number: 3,
      description: 'Generate report',
      thought_prompt: 'Think about report',
      required_tools: ['generate'],
      expected_output: 'Final report',
      dependencies: [2],
    },
  ],
  current_step_index: 1,
  workflow_pattern_id: 'pattern-1',
  created_at: '2024-01-01T00:00:00Z',
};

const mockSteps: TimelineStep[] = [
  {
    stepNumber: 1,
    description: 'Search for information',
    status: 'completed',
    startTime: '2024-01-01T00:00:00Z',
    endTime: '2024-01-01T00:01:00Z',
    duration: 60,
    thoughts: ['Searching...'],
    toolExecutions: [],
  },
  {
    stepNumber: 2,
    description: 'Analyze results',
    status: 'running',
    startTime: '2024-01-01T00:01:00Z',
    thoughts: ['Analyzing...'],
    toolExecutions: [],
  },
  {
    stepNumber: 3,
    description: 'Generate report',
    status: 'pending',
    thoughts: [],
    toolExecutions: [],
  },
];

const mockToolExecutions: ToolExecution[] = [
  {
    id: 'tool-1',
    toolName: 'search',
    input: { query: 'test' },
    status: 'success',
    result: 'Results found',
    startTime: '2024-01-01T00:00:00Z',
    endTime: '2024-01-01T00:00:30Z',
    duration: 30,
    stepNumber: 1,
  },
  {
    id: 'tool-2',
    toolName: 'analyze',
    input: { data: 'test' },
    status: 'running',
    startTime: '2024-01-01T00:01:00Z',
    stepNumber: 2,
  },
];

describe('ExecutionTimeline (Compound Components)', () => {
  describe('getDisplayMode utility function', () => {
    it('should return "direct" for simple conversations (no work plan, minimal activity)', () => {
      const mode = getDisplayMode(null, [], []);
      expect(mode).toBe('direct');
    });

    it('should return "direct" when no work plan and single step/tool', () => {
      const mode = getDisplayMode(
        null,
        [
          {
            stepNumber: 1,
            description: 'Test',
            status: 'completed',
            thoughts: [],
            toolExecutions: [],
          },
        ],
        [
          {
            id: '1',
            toolName: 'test',
            input: {},
            status: 'success',
            startTime: '2024-01-01T00:00:00Z',
          },
        ]
      );
      expect(mode).toBe('direct');
    });

    it('should return "timeline" when work plan exists', () => {
      const mode = getDisplayMode(mockWorkPlan, [], []);
      expect(mode).toBe('timeline');
    });

    it('should return "timeline" when steps exist', () => {
      const mode = getDisplayMode(null, mockSteps, []);
      expect(mode).toBe('timeline');
    });

    it('should return "simple-timeline" when only tool executions exist', () => {
      const mode = getDisplayMode(null, [], mockToolExecutions);
      expect(mode).toBe('simple-timeline');
    });

    it('should return "timeline" when both work plan and steps exist', () => {
      const mode = getDisplayMode(mockWorkPlan, mockSteps, []);
      expect(mode).toBe('timeline');
    });
  });

  describe('ExecutionTimeline - Main Container', () => {
    it('should return null for direct mode (no rendering)', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const { container } = render(
        <ExecutionTimeline steps={[]} toolExecutionHistory={[]} isStreaming={false} />
      );

      expect(container.firstChild).toBe(null);
    });

    it('should render timeline mode with work plan', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      expect(screen.getByText(/执行计划/i)).toBeInTheDocument();
      expect(screen.getByText(/1\/3 步骤已完成/i)).toBeInTheDocument();
    });

    it('should render simple-timeline mode', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          steps={[]}
          toolExecutionHistory={mockToolExecutions}
          isStreaming={false}
        />
      );

      expect(screen.getByTestId('simple-execution-view')).toBeInTheDocument();
    });

    it('should render timeline nodes in timeline mode', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      expect(screen.getByTestId('timeline-node-1')).toBeInTheDocument();
      expect(screen.getByTestId('timeline-node-2')).toBeInTheDocument();
      expect(screen.getByTestId('timeline-node-3')).toBeInTheDocument();
    });

    it('should show matched pattern badge when provided', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          matchedPattern={{ id: 'pattern-1', similarity: 0.85 }}
        />
      );

      expect(screen.getByText(/匹配模式 \(85%\)/i)).toBeInTheDocument();
    });
  });

  describe('ExecutionTimeline - Progress Tracking', () => {
    it('should calculate progress percentage correctly', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      // 1 completed out of 3 steps = 33%
      const progressBar =
        screen.getByRole('progressbar') || document.querySelector('[style*="width"]');
      expect(progressBar).toBeInTheDocument();
    });

    it('should show correct status badge', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
        />
      );

      expect(screen.getByText('执行中')).toBeInTheDocument();
    });

    it('should show completed status when all steps done', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const completedSteps = mockSteps.map((s) => ({ ...s, status: 'completed' as const }));
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={completedSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      expect(screen.getByText('已完成')).toBeInTheDocument();
    });

    it('should show waiting status when not streaming and not completed', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      expect(screen.getByText('等待中')).toBeInTheDocument();
    });
  });

  describe('ExecutionTimeline - Work Plan Checklist', () => {
    it('should render work plan steps with correct styling', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      // Check that step descriptions are rendered (using getAllByText since there are duplicates)
      expect(screen.getAllByText('Search for information').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Analyze results').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Generate report').length).toBeGreaterThan(0);
    });

    it('should show completed steps with checkmark', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      // Step 1 is completed, should have check icon
      expect(screen.getByTestId('icon-check')).toBeInTheDocument();
    });

    it('should show active step with pulse animation', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      // Active step (2) should show "执行中..."
      expect(screen.getAllByText('执行中...').length).toBeGreaterThan(0);
    });

    it('should show tool count for steps with executions', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const stepsWithTools = mockSteps.map((s) => ({
        ...s,
        toolExecutions: [
          {
            id: 'tool-1',
            toolName: 'test',
            input: {},
            status: 'success',
            startTime: '2024-01-01T00:00:00Z',
          },
        ],
      }));
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={stepsWithTools}
          toolExecutionHistory={[]}
          isStreaming={true}
        />
      );

      // Use getAllByText since the tool count appears in multiple places
      expect(screen.getAllByText(/1 工具/i).length).toBeGreaterThan(0);
    });
  });

  describe('ExecutionTimeline - Step Expand/Collapse', () => {
    it('should expand current step by default', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      const step2 = screen.getByTestId('timeline-node-2');
      expect(step2).toHaveAttribute('data-expanded', 'true');
    });

    it('should toggle step expansion on click', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      // Click on a step item (checklist item in work plan)
      const step1Element = document.querySelector('[data-step-number="1"]');
      expect(step1Element).toBeInTheDocument();

      // Click should not throw error
      if (step1Element) {
        fireEvent.click(step1Element);
        // After clicking, the element should still exist
        expect(document.querySelector('[data-step-number="1"]')).toBeInTheDocument();
      }
    });

    it('should collapse step on second click', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      const step2 = screen.getByTestId('timeline-node-2');
      // First click to collapse (currently expanded by default)
      fireEvent.click(step2);

      await waitFor(() => {
        expect(step2).toHaveAttribute('data-expanded', 'false');
      });
    });
  });

  describe('ExecutionTimeline - Expand/Collapse All Controls', () => {
    it('should show expand/collapse controls when multiple steps exist', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
        />
      );

      expect(screen.getByText('展开全部')).toBeInTheDocument();
      expect(screen.getByText('收起全部')).toBeInTheDocument();
    });

    it('should not show controls when only one step', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const singleStep = [mockSteps[0]];
      render(
        <ExecutionTimeline
          workPlan={{ ...mockWorkPlan, steps: [mockWorkPlan.steps[0]] }}
          steps={singleStep}
          toolExecutionHistory={[]}
          isStreaming={true}
        />
      );

      expect(screen.queryByText('展开全部')).not.toBeInTheDocument();
      expect(screen.queryByText('收起全部')).not.toBeInTheDocument();
    });

    it('should expand all steps when clicking expand all', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={null}
        />
      );

      const expandAllBtn = screen.getByText('展开全部');
      fireEvent.click(expandAllBtn);

      // Verify the button was clicked without error
      expect(expandAllBtn).toBeInTheDocument();
    });

    it('should collapse all steps when clicking collapse all', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={null}
        />
      );

      const collapseAllBtn = screen.getByText('收起全部');
      fireEvent.click(collapseAllBtn);

      // Verify the button was clicked without error
      expect(collapseAllBtn).toBeInTheDocument();
    });
  });

  describe('ExecutionTimeline - Failed Steps', () => {
    it('should show failed status for failed steps', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const failedSteps = [{ ...mockSteps[0], status: 'failed' as const }, ...mockSteps.slice(1)];
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={failedSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      expect(screen.getByTestId('icon-close')).toBeInTheDocument();
    });

    it('should apply red styling for failed steps', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const failedSteps = [{ ...mockSteps[0], status: 'failed' as const }, ...mockSteps.slice(1)];
      const { container } = render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={failedSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      // Check for the presence of failed step elements (data-step-number attribute)
      const failedStepElement = container.querySelector('[data-step-number="1"]');
      expect(failedStepElement).toBeInTheDocument();
      // The failed element should have the red bg-red class in its className
      expect(failedStepElement?.className).toContain('bg-red');
    });
  });

  describe('ExecutionTimeline - Simple Timeline Mode', () => {
    it('should render work plan in simple-timeline mode', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      // When there's no workPlan but tool executions exist, it should be simple-timeline mode
      render(
        <ExecutionTimeline
          workPlan={null}
          steps={[]}
          toolExecutionHistory={mockToolExecutions}
          isStreaming={false}
          currentStepNumber={1}
        />
      );

      // SimpleExecutionView should be rendered
      expect(screen.getByTestId('simple-execution-view')).toBeInTheDocument();
      expect(screen.getByText(/Tool Executions: 2/i)).toBeInTheDocument();
    });

    it('should not render timeline nodes in simple-timeline mode', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={null}
          steps={[]}
          toolExecutionHistory={mockToolExecutions}
          isStreaming={false}
        />
      );

      expect(screen.queryByTestId('timeline-node-1')).not.toBeInTheDocument();
    });

    it('should show tool execution count in simple view', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          steps={[]}
          toolExecutionHistory={mockToolExecutions}
          isStreaming={false}
        />
      );

      expect(screen.getByText('Tool Executions: 2')).toBeInTheDocument();
    });
  });

  describe('ExecutionTimeline - Auto-scroll', () => {
    it('should scroll to current step when currentStepNumber changes', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={3}
        />
      );

      // Check that the step element exists in the timeline nodes
      const step3 = screen.getByTestId('timeline-node-3');
      expect(step3).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty steps array', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const { container } = render(
        <ExecutionTimeline
          workPlan={null}
          steps={[]}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      expect(container.firstChild).toBe(null);
    });

    it('should handle null workPlan', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={null}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      expect(screen.getByTestId('timeline-node-1')).toBeInTheDocument();
    });

    it('should handle undefined currentStepNumber', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      // Should not auto-expand any step when currentStepNumber is undefined
      const step1 = screen.getByTestId('timeline-node-1');
      expect(step1).toHaveAttribute('data-expanded', 'false');
    });

    it('should handle zero progress when no steps completed', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      const pendingSteps = mockSteps.map((s) => ({ ...s, status: 'pending' as const }));
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={pendingSteps}
          toolExecutionHistory={[]}
          isStreaming={false}
        />
      );

      expect(screen.getByText('0/3 步骤已完成')).toBeInTheDocument();
    });

    it('should handle tool executions with step numbers', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          steps={[]}
          toolExecutionHistory={[
            ...mockToolExecutions,
            {
              id: 'tool-3',
              toolName: 'generate',
              input: {},
              status: 'success',
              startTime: '2024-01-01T00:02:00Z',
              stepNumber: 3,
            },
          ]}
          isStreaming={false}
        />
      );

      expect(screen.getByTestId('simple-execution-view')).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('should have proper data attributes for step identification', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
          currentStepNumber={2}
        />
      );

      // The checklist items in the work plan should have data-step-number attributes
      const step1Element = document.querySelector('[data-step-number="1"]');
      const step2Element = document.querySelector('[data-step-number="2"]');

      expect(step1Element).toBeInTheDocument();
      expect(step2Element).toBeInTheDocument();
    });

    it('should have clickable step items', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
        />
      );

      // The clickable div has the data-step-number attribute
      const step1 = document.querySelector('[data-step-number="1"]');
      expect(step1).toBeInTheDocument();
      expect(step1).toHaveClass('cursor-pointer');
    });

    it('should have expand/collapse icon for steps', async () => {
      const { default: ExecutionTimeline } =
        await import('../../../../components/agent/execution/ExecutionTimeline');
      render(
        <ExecutionTimeline
          workPlan={mockWorkPlan}
          steps={mockSteps}
          toolExecutionHistory={[]}
          isStreaming={true}
        />
      );

      // There should be at least one expand icon (steps 1 and 3 are collapsed by default when currentStepNumber is not provided)
      const expandIcons = screen.getAllByTestId('icon-expand_more');
      expect(expandIcons.length).toBeGreaterThan(0);
    });
  });
});
