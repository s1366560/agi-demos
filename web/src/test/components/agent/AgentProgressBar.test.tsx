/**
 * Unit tests for AgentProgressBar component (T050)
 *
 * This component displays the overall progress of agent execution,
 * including work plan steps and current execution status.
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import '@testing-library/jest-dom/vitest';
import { AgentProgressBar } from '../../../components/agent/AgentProgressBar';

describe('AgentProgressBar', () => {
  describe('Rendering', () => {
    it('should render progress bar container', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" />);

      const progressBar = screen.getByTestId('agent-progress-bar');
      expect(progressBar).toBeInTheDocument();
    });

    it('should display current and total step numbers', () => {
      render(<AgentProgressBar current={2} total={5} status="step_executing" />);

      expect(screen.getByText(/2 \/ 5/i)).toBeInTheDocument();
    });

    it('should show percentage completion', () => {
      render(<AgentProgressBar current={1} total={4} status="step_executing" />);

      const percentageElements = screen.getAllByText('25%');
      expect(percentageElements.length).toBeGreaterThan(0);
    });

    it('should display status label', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" />);

      expect(screen.getByText(/Executing/i)).toBeInTheDocument();
    });
  });

  describe('Progress Bar Visual', () => {
    it('should show progress based on current/total', () => {
      render(<AgentProgressBar current={2} total={4} status="step_executing" />);

      // Ant Design Progress component handles the visual fill
      // Verify the percentage is displayed correctly
      const percentageElements = screen.getAllByText('50%');
      expect(percentageElements.length).toBeGreaterThan(0);
    });

    it('should show status class on progress bar', () => {
      const { container } = render(
        <AgentProgressBar current={1} total={3} status="step_executing" />
      );

      const progressBar = container.querySelector('.ant-progress');
      expect(progressBar).toBeInTheDocument();
    });

    it('should show progress striped class for executing status', () => {
      const { container } = render(
        <AgentProgressBar current={1} total={3} status="step_executing" />
      );

      const progressFill = container.querySelector('.progress-striped');
      expect(progressFill).toBeInTheDocument();
    });
  });

  describe('Status Labels', () => {
    it('should show "Planning" status when work_planning', () => {
      render(<AgentProgressBar current={0} total={3} status="work_planning" />);

      expect(screen.getByText(/planning/i)).toBeInTheDocument();
    });

    it('should show "Executing" status when step_executing', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" />);

      expect(screen.getByText(/executing/i)).toBeInTheDocument();
    });

    it('should show "Thinking" status when thinking', () => {
      render(<AgentProgressBar current={0} total={3} status="thinking" />);

      expect(screen.getByText(/thinking/i)).toBeInTheDocument();
    });

    it('should show "Completed" status when completed', () => {
      render(<AgentProgressBar current={3} total={3} status="completed" />);

      expect(screen.getByText(/completed/i)).toBeInTheDocument();
    });

    it('should show "Failed" status when failed', () => {
      render(<AgentProgressBar current={1} total={3} status="failed" />);

      expect(screen.getByText(/failed/i)).toBeInTheDocument();
    });
  });

  describe('Step Indicators', () => {
    it('should show dots for each step when showSteps is true', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" showSteps={true} />);

      const dots = screen.getAllByTestId(/-dot$/);
      expect(dots).toHaveLength(3);
    });

    it('should highlight completed steps', () => {
      render(<AgentProgressBar current={2} total={4} status="step_executing" showSteps={true} />);

      const completedDots = screen.getAllByTestId('completed-dot');
      expect(completedDots).toHaveLength(1);
    });

    it('should highlight current step', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" showSteps={true} />);

      const currentDot = screen.getByTestId('current-dot');
      expect(currentDot).toBeInTheDocument();
    });

    it('should show pending steps as inactive', () => {
      render(<AgentProgressBar current={1} total={4} status="step_executing" showSteps={true} />);

      const pendingDots = screen.getAllByTestId('pending-dot');
      expect(pendingDots).toHaveLength(3); // Steps 2, 3, 4
    });
  });

  describe('Edge Cases', () => {
    it('should handle 0 current / 0 total', () => {
      render(<AgentProgressBar current={0} total={0} status="thinking" />);

      const percentageElements = screen.getAllByText('0%');
      expect(percentageElements.length).toBeGreaterThan(0);
    });

    it('should handle current equal to total (100%)', () => {
      render(<AgentProgressBar current={5} total={5} status="completed" />);

      const percentageElements = screen.getAllByText('100%');
      expect(percentageElements.length).toBeGreaterThan(0);
    });

    it('should handle single step', () => {
      render(<AgentProgressBar current={0} total={1} status="step_executing" />);

      expect(screen.getByText(/0 \/ 1/i)).toBeInTheDocument();
    });

    it('should handle many steps (10+)', () => {
      render(<AgentProgressBar current={5} total={10} status="step_executing" />);

      const percentageElements = screen.getAllByText('50%');
      expect(percentageElements.length).toBeGreaterThan(0);
      expect(screen.getByText(/5 \/ 10/i)).toBeInTheDocument();
    });
  });

  describe('Compact Mode', () => {
    it('should show minimal info in compact mode', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" compact={true} />);

      expect(screen.getByTestId('agent-progress-bar')).toHaveClass('compact');
    });

    it('should hide step dots in compact mode', () => {
      render(
        <AgentProgressBar
          current={1}
          total={3}
          status="step_executing"
          showSteps={true}
          compact={true}
        />
      );

      expect(screen.queryByTestId('step-dot')).not.toBeInTheDocument();
    });

    it('should show only percentage in compact mode', () => {
      render(<AgentProgressBar current={2} total={4} status="step_executing" compact={true} />);

      expect(screen.getByText('50%')).toBeInTheDocument();
      expect(screen.queryByText(/2 \/ 4/i)).not.toBeInTheDocument();
    });
  });

  describe('Labels', () => {
    it('should show custom label when provided', () => {
      render(
        <AgentProgressBar
          current={1}
          total={3}
          status="step_executing"
          label="Searching memories..."
        />
      );

      expect(screen.getByText(/Searching memories/i)).toBeInTheDocument();
    });

    it('should use default label when none provided', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" />);

      expect(screen.getByText(/Executing/i)).toBeInTheDocument();
    });

    it('should show estimated time remaining when provided', () => {
      render(
        <AgentProgressBar
          current={1}
          total={3}
          status="step_executing"
          estimatedTimeRemaining="~30s"
        />
      );

      expect(screen.getByText(/~30s/)).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('should have proper ARIA role', () => {
      render(<AgentProgressBar current={1} total={3} status="step_executing" />);

      const progressBar = screen.getByTestId('agent-progress-bar');
      expect(progressBar).toHaveAttribute('role', 'progressbar');
    });

    it('should have proper ARIA values', () => {
      render(<AgentProgressBar current={2} total={5} status="step_executing" />);

      const progressBar = screen.getByTestId('agent-progress-bar');
      expect(progressBar).toHaveAttribute('aria-valuenow', '2');
      expect(progressBar).toHaveAttribute('aria-valuemin', '0');
      expect(progressBar).toHaveAttribute('aria-valuemax', '5');
    });

    it('should announce status changes', () => {
      const { rerender } = render(
        <AgentProgressBar current={1} total={3} status="step_executing" />
      );

      const progressBar = screen.getByTestId('agent-progress-bar');
      expect(progressBar).toHaveAttribute('aria-live', 'polite');

      rerender(<AgentProgressBar current={2} total={3} status="completed" />);

      expect(screen.getByText(/completed/i)).toBeInTheDocument();
    });
  });

  describe('Animation', () => {
    it('should show animate class when animate is true', () => {
      const { container } = render(
        <AgentProgressBar current={1} total={3} status="step_executing" animate={true} />
      );

      const progressFill = container.querySelector('.animate-progress');
      expect(progressFill).toBeInTheDocument();
    });

    it('should not show animate class when animate is false', () => {
      const { container } = render(
        <AgentProgressBar current={1} total={3} status="step_executing" animate={false} />
      );

      const progressFill = container.querySelector('.animate-progress');
      expect(progressFill).not.toBeInTheDocument();
    });
  });
});
