/**
 * RenderModeSwitch.test.tsx
 *
 * Tests for the RenderModeSwitch component that allows users to toggle
 * between grouped and timeline rendering modes.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { RenderModeSwitch } from '../../components/agent/RenderModeSwitch';

describe('RenderModeSwitch', () => {
  const mockOnToggle = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('should render the switch component', () => {
      render(
        <RenderModeSwitch
          mode="grouped"
          onToggle={mockOnToggle}
        />
      );

      expect(screen.getByTestId('render-mode-switch')).toBeInTheDocument();
    });

    it('should display current mode label', () => {
      render(
        <RenderModeSwitch
          mode="grouped"
          onToggle={mockOnToggle}
        />
      );

      expect(screen.getByText('Grouped')).toBeInTheDocument();
    });

    it('should show "Timeline" label when in timeline mode', () => {
      render(
        <RenderModeSwitch
          mode="timeline"
          onToggle={mockOnToggle}
        />
      );

      expect(screen.getByText('Timeline')).toBeInTheDocument();
    });
  });

  describe('Interaction', () => {
    it('should call onToggle when clicked in grouped mode', () => {
      render(
        <RenderModeSwitch
          mode="grouped"
          onToggle={mockOnToggle}
        />
      );

      const toggle = screen.getByRole('switch');
      fireEvent.click(toggle);

      expect(mockOnToggle).toHaveBeenCalledTimes(1);
      expect(mockOnToggle).toHaveBeenCalledWith('timeline');
    });

    it('should call onToggle when clicked in timeline mode', () => {
      render(
        <RenderModeSwitch
          mode="timeline"
          onToggle={mockOnToggle}
        />
      );

      const toggle = screen.getByRole('switch');
      fireEvent.click(toggle);

      expect(mockOnToggle).toHaveBeenCalledTimes(1);
      expect(mockOnToggle).toHaveBeenCalledWith('grouped');
    });

    it('should toggle mode on each click', () => {
      const { rerender } = render(
        <RenderModeSwitch
          mode="grouped"
          onToggle={mockOnToggle}
        />
      );

      // First click
      fireEvent.click(screen.getByRole('switch'));
      expect(mockOnToggle).toHaveBeenLastCalledWith('timeline');

      // Update props and click again
      rerender(
        <RenderModeSwitch
          mode="timeline"
          onToggle={mockOnToggle}
        />
      );
      fireEvent.click(screen.getByRole('switch'));
      expect(mockOnToggle).toHaveBeenLastCalledWith('grouped');
    });
  });

  describe('Accessibility', () => {
    it('should have proper ARIA attributes', () => {
      render(
        <RenderModeSwitch
          mode="grouped"
          onToggle={mockOnToggle}
        />
      );

      const switchElement = screen.getByRole('switch');
      expect(switchElement).toBeInTheDocument();
      expect(switchElement).toHaveAttribute('aria-checked', 'false');
    });

    it('should update aria-checked when mode changes', () => {
      const { rerender } = render(
        <RenderModeSwitch
          mode="grouped"
          onToggle={mockOnToggle}
        />
      );

      const switchElement = screen.getByRole('switch');
      expect(switchElement).toHaveAttribute('aria-checked', 'false');

      // Rerender with timeline mode
      rerender(
        <RenderModeSwitch
          mode="timeline"
          onToggle={mockOnToggle}
        />
      );

      expect(switchElement).toHaveAttribute('aria-checked', 'true');
    });
  });

  describe('Visual States', () => {
    it('should show active state for grouped mode', () => {
      render(
        <RenderModeSwitch
          mode="grouped"
          onToggle={mockOnToggle}
        />
      );

      const groupedText = screen.getByText('Grouped');
      expect(groupedText).toHaveClass(/text-primary/);
    });

    it('should show active state for timeline mode', () => {
      render(
        <RenderModeSwitch
          mode="timeline"
          onToggle={mockOnToggle}
        />
      );

      const timelineText = screen.getByText('Timeline');
      expect(timelineText).toHaveClass(/text-primary/);
    });
  });
});
