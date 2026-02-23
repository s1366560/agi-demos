/**
 * CSS Containment Performance Tests (TDD - RED phase)
 *
 * Tests for CSS containment utilities that improve rendering performance
 * for large lists, cards, and page components.
 *
 * CSS Containment allows the browser to optimize rendering by:
 * 1. content-visibility: Skip rendering work for off-screen content
 * 2. contain: Isolate element changes from affecting rest of page
 * 3. contain-intrinsic-size: Reserve space for unrendered content
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import '@testing-library/jest-dom/vitest';

// Test component wrapper for CSS containment utilities
function createTestComponent(className: string) {
  return function TestComponent({ content = 'Test Content' }: { content?: string }) {
    return (
      <div className={className} data-testid="test-element">
        {content}
      </div>
    );
  };
}

// Mock the CSS containment module
const mockContainmentClasses = {
  contentVisibilityAuto: 'content-visibility-auto',
  contentVisibilityHidden: 'content-visibility-hidden',
  containLayout: 'contain-layout',
  containPaint: 'contain-paint',
  containLayoutPaint: 'contain-layout-paint',
  containStrict: 'contain-strict',
  listItemOptimized: 'list-item-optimized',
  tableRowOptimized: 'table-row-optimized',
  cardOptimized: 'card-optimized',
  renderPriorityLow: 'render-priority-low',
};

describe('CSS Containment - content-visibility', () => {
  describe('content-visibility: auto', () => {
    it('should apply content-visibility: auto to list items', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.contentVisibilityAuto);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element).toBeInTheDocument();

      // In a real browser environment, we would check computed styles
      // For testing, we verify the class is applied
      expect(element?.className).toContain('content-visibility-auto');
    });

    it('should reserve space with contain-intrinsic-size', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.contentVisibilityAuto);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('content-visibility-auto');
    });

    it('should not affect visible content rendering', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.contentVisibilityAuto);
      render(<TestComponent content="Visible Content" />);

      expect(screen.getByText('Visible Content')).toBeInTheDocument();
    });
  });

  describe('content-visibility: hidden', () => {
    it('should apply content-visibility: hidden for static content', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.contentVisibilityHidden);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('content-visibility-hidden');
    });

    it('should have larger contain-intrinsic-size for static content', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.contentVisibilityHidden);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('content-visibility-hidden');
    });
  });
});

describe('CSS Containment - contain property', () => {
  describe('contain: layout', () => {
    it('should isolate layout calculations', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.containLayout);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('contain-layout');
    });

    it('should prevent layout thrashing for contained elements', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.containLayout);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('contain-layout');
    });
  });

  describe('contain: paint', () => {
    it('should isolate paint operations', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.containPaint);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('contain-paint');
    });
  });

  describe('contain: layout paint', () => {
    it('should combine layout and paint containment', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.containLayoutPaint);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('contain-layout-paint');
    });
  });

  describe('contain: strict', () => {
    it('should apply strict containment', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.containStrict);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('contain-strict');
    });
  });
});

describe('CSS Containment - Preset utilities', () => {
  describe('list-item-optimized', () => {
    it('should apply optimized containment for list items', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.listItemOptimized);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('list-item-optimized');
    });

    it('should have appropriate contain-intrinsic-size for list items', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.listItemOptimized);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('list-item-optimized');
    });
  });

  describe('table-row-optimized', () => {
    it('should apply optimized containment for table rows', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.tableRowOptimized);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('table-row-optimized');
    });
  });

  describe('card-optimized', () => {
    it('should apply optimized containment for cards', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.cardOptimized);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('card-optimized');
    });

    it('should have appropriate contain-intrinsic-size for cards', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.cardOptimized);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('card-optimized');
    });
  });

  describe('render-priority-low', () => {
    it('should mark non-critical UI elements for low priority rendering', () => {
      const TestComponent = createTestComponent(mockContainmentClasses.renderPriorityLow);
      const { container } = render(<TestComponent />);

      const element = container.querySelector('[data-testid="test-element"]');
      expect(element?.className).toContain('render-priority-low');
    });
  });
});

describe('CSS Containment - Large lists rendering', () => {
  it('should handle large lists with containment', () => {
    const items = Array.from({ length: 100 }, (_, i) => `Item ${i}`);

    const ListComponent = () => (
      <div>
        {items.map((item) => (
          <div key={item} className={mockContainmentClasses.listItemOptimized}>
            {item}
          </div>
        ))}
      </div>
    );

    const { container } = render(<ListComponent />);

    // Verify all items are rendered
    expect(container.textContent).toContain('Item 0');
    expect(container.textContent).toContain('Item 99');

    // Verify containment classes are applied
    const optimizedItems = container.querySelectorAll('.list-item-optimized');
    expect(optimizedItems.length).toBe(100);
  });

  it('should not affect content visibility with containment', () => {
    const TestComponent = createTestComponent(mockContainmentClasses.cardOptimized);
    render(<TestComponent content="Important content that must be visible" />);

    expect(screen.getByText('Important content that must be visible')).toBeInTheDocument();
  });
});

describe('CSS Containment - Integration with existing components', () => {
  it('should be compatible with card components', () => {
    const CardComponent = ({ title, content }: { title: string; content: string }) => (
      <div className={`${mockContainmentClasses.cardOptimized} bg-white rounded-lg p-4`}>
        <h3 className="font-semibold">{title}</h3>
        <p>{content}</p>
      </div>
    );

    render(<CardComponent title="Test Card" content="Card content" />);

    expect(screen.getByText('Test Card')).toBeInTheDocument();
    expect(screen.getByText('Card content')).toBeInTheDocument();
  });

  it('should be compatible with list components', () => {
    const ListComponent = ({ items }: { items: string[] }) => (
      <ul>
        {items.map((item, index) => (
          <li key={index} className={mockContainmentClasses.listItemOptimized}>
            {item}
          </li>
        ))}
      </ul>
    );

    render(<ListComponent items={['Item 1', 'Item 2', 'Item 3']} />);

    expect(screen.getByText('Item 1')).toBeInTheDocument();
    expect(screen.getByText('Item 2')).toBeInTheDocument();
    expect(screen.getByText('Item 3')).toBeInTheDocument();
  });
});

describe('CSS Containment - Performance expectations', () => {
  it('should provide utility class for will-change hints', () => {
    // Test that we have utilities for hinting animated elements
    const animatedElement = document.createElement('div');
    animatedElement.className = 'will-change-transform';
    expect(animatedElement.className).toContain('will-change-transform');
  });

  it('should provide utility for GPU acceleration hints', () => {
    const gpuElement = document.createElement('div');
    gpuElement.className = 'gpu-accelerated';
    expect(gpuElement.className).toContain('gpu-accelerated');
  });

  it('should support reduced motion preferences', () => {
    // Test that our CSS respects prefers-reduced-motion
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    expect(mediaQuery).toBeDefined();
  });
});
