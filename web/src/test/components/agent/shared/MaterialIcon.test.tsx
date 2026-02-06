/**
 * MaterialIcon Component Tests
 *
 * Tests for MaterialIcon component following React 19 best practices.
 * In React 19, forwardRef is no longer needed - components can accept ref directly.
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { MaterialIcon } from '@/components/agent/shared/MaterialIcon';

describe('MaterialIcon', () => {
  describe('Basic Rendering', () => {
    it('should render an icon with default props', () => {
      render(<MaterialIcon name="search" />);

      const icon = screen.getByText('search');
      expect(icon).toBeInTheDocument();
      expect(icon).toHaveClass('material-symbols-outlined');
    });

    it('should render with custom size', () => {
      render(<MaterialIcon name="home" size={32} />);

      const icon = screen.getByText('home');
      expect(icon).toBeInTheDocument();
      expect(icon.style.fontSize).toBe('32px');
    });

    it('should render with custom weight', () => {
      render(<MaterialIcon name="settings" weight={700} />);

      const icon = screen.getByText('settings');
      expect(icon).toBeInTheDocument();
      expect(icon.style.fontVariationSettings).toBe('0 700 0 24');
    });

    it('should render filled variant', () => {
      render(<MaterialIcon name="star" filled />);

      const icon = screen.getByText('star');
      expect(icon).toBeInTheDocument();
      expect(icon.style.fontVariationSettings).toBe('FILL 400 0 24');
    });

    it('should render with filled and custom weight', () => {
      render(<MaterialIcon name="star" filled weight={600} />);

      const icon = screen.getByText('star');
      expect(icon).toBeInTheDocument();
      expect(icon.style.fontVariationSettings).toBe('FILL 600 0 24');
    });
  });

  describe('Styling', () => {
    it('should apply custom className', () => {
      render(<MaterialIcon name="search" className="text-blue-500" />);

      const icon = screen.getByText('search');
      expect(icon).toHaveClass('text-blue-500');
      expect(icon).toHaveClass('material-symbols-outlined');
    });

    it('should apply custom style props', () => {
      render(<MaterialIcon name="search" style={{ color: 'red' }} />);

      const icon = screen.getByText('search');
      expect(icon.style.color).toBe('red');
    });

    it('should merge custom styles with default styles', () => {
      const { container } = render(
        <MaterialIcon name="search" size={20} style={{ color: 'blue', margin: '10px' }} />
      );

      const icon = container.querySelector('.material-symbols-outlined');
      expect(icon).toBeInTheDocument();
      expect(icon?.style.fontSize).toBe('20px');
      expect(icon?.style.color).toBe('blue');
      expect(icon?.style.margin).toBe('10px');
    });
  });

  describe('Props Spreading', () => {
    it('should spread additional HTML attributes to span', () => {
      render(<MaterialIcon name="search" data-testid="custom-icon" aria-label="Search" />);

      const icon = screen.getByTestId('custom-icon');
      expect(icon).toHaveAttribute('aria-label', 'Search');
    });

    it('should support onClick handler', () => {
      const handleClick = vi.fn();
      render(<MaterialIcon name="search" onClick={handleClick} />);

      const icon = screen.getByText('search');
      icon.click();
      expect(handleClick).toHaveBeenCalledTimes(1);
    });
  });

  describe('Ref Support (React 19)', () => {
    it('should accept ref prop directly without forwardRef', () => {
      let refElement: HTMLSpanElement | null = null;

      const TestComponent = () => {
        const ref = (el: HTMLSpanElement | null) => {
          refElement = el;
        };

        return <MaterialIcon name="search" ref={ref} />;
      };

      render(<TestComponent />);

      expect(refElement).toBeInstanceOf(HTMLSpanElement);
      expect(refElement).toHaveTextContent('search');
    });

    it('should pass ref to the underlying span element', () => {
      let capturedRef: any = null;

      render(
        <MaterialIcon
          name="home"
          ref={(el) => {
            capturedRef = el;
          }}
        />
      );

      expect(capturedRef).toBeInstanceOf(HTMLSpanElement);
      expect(capturedRef?.className).toContain('material-symbols-outlined');
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty icon name', () => {
      const { container } = render(<MaterialIcon name="" />);

      const icon = container.querySelector('.material-symbols-outlined');
      expect(icon).toBeInTheDocument();
      expect(icon).toHaveClass('material-symbols-outlined');
      expect(icon?.textContent).toBe('');
    });

    it('should handle special characters in icon name', () => {
      render(<MaterialIcon name="add_circle" />);

      const icon = screen.getByText('add_circle');
      expect(icon).toBeInTheDocument();
    });

    it('should handle size of 0', () => {
      render(<MaterialIcon name="search" size={0} />);

      const icon = screen.getByText('search');
      expect(icon.style.fontSize).toBe('0px');
    });

    it('should handle very large size', () => {
      render(<MaterialIcon name="search" size={200} />);

      const icon = screen.getByText('search');
      expect(icon.style.fontSize).toBe('200px');
    });

    it('should handle weight at boundary values', () => {
      const { rerender } = render(<MaterialIcon name="search" weight={0} />);

      let icon = screen.getByText('search');
      expect(icon.style.fontVariationSettings).toBe('0 0 0 24');

      rerender(<MaterialIcon name="search" weight={900} />);
      icon = screen.getByText('search');
      expect(icon.style.fontVariationSettings).toBe('0 900 0 24');
    });
  });

  describe('Line Height', () => {
    it('should always have line-height of 1', () => {
      render(<MaterialIcon name="search" />);

      const icon = screen.getByText('search');
      expect(icon.style.lineHeight).toBe('1');
    });
  });
});
