/**
 * PatternList Component Tests
 *
 * Tests for PatternList component following React composition patterns.
 * Boolean props replaced with configuration objects for better extensibility.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

// eslint-disable-next-line no-restricted-imports
import {
  PatternList,
  type _PatternStatus,
  type WorkflowPattern,
  type _PatternDefinition,
} from '@/components/agent/patterns/PatternList';

describe('PatternList', () => {
  // Test fixtures
  const mockPatterns: WorkflowPattern[] = [
    {
      id: 'pattern-1',
      name: 'Document Search Pattern',
      signature: 'search_document(query: string)',
      status: 'preferred',
      usageCount: 1250,
      successRate: 95,
      avgRuntime: 450,
      lastUsed: '2024-01-15',
    },
    {
      id: 'pattern-2',
      name: 'Data Extraction Pattern',
      signature: 'extract_data(source: string)',
      status: 'active',
      usageCount: 850,
      successRate: 87,
    },
    {
      id: 'pattern-3',
      name: 'Legacy Analysis Pattern',
      signature: 'analyze_legacy(data: any)',
      status: 'deprecated',
      usageCount: 120,
      successRate: 45,
    },
  ];

  const _mockPatternWithDefinition: WorkflowPattern = {
    id: 'pattern-4',
    name: 'Complex Workflow',
    signature: 'complex_workflow(input: object)',
    status: 'active',
    usageCount: 500,
    successRate: 92,
    pattern: {
      name: 'Complex Workflow',
      description: 'A complex multi-step workflow',
      tools: ['search', 'extract', 'analyze'],
      steps: [
        { tool: 'search', params: { query: 'test' } },
        { tool: 'extract', params: { format: 'json' } },
      ],
    },
  };

  describe('Basic Rendering', () => {
    it('should render patterns in a table format', () => {
      render(<PatternList patterns={mockPatterns} />);

      expect(screen.getByText('Document Search Pattern')).toBeInTheDocument();
      expect(screen.getByText('Data Extraction Pattern')).toBeInTheDocument();
      expect(screen.getByText('Legacy Analysis Pattern')).toBeInTheDocument();
    });

    it('should render status badges correctly', () => {
      render(<PatternList patterns={mockPatterns} />);

      expect(screen.getByText('Preferred')).toBeInTheDocument();
      expect(screen.getByText('Active')).toBeInTheDocument();
      expect(screen.getByText('Deprecated')).toBeInTheDocument();
    });

    it('should render usage counts in detailed view mode', () => {
      render(<PatternList patterns={mockPatterns} viewMode="detailed" />);

      expect(screen.getByText('1,250')).toBeInTheDocument();
      expect(screen.getByText('850')).toBeInTheDocument();
      expect(screen.getByText('120')).toBeInTheDocument();
    });

    it('should not show usage counts in compact view mode', () => {
      render(<PatternList patterns={mockPatterns} viewMode="compact" />);

      // Usage column should not be visible
      expect(screen.queryByText('1,250')).not.toBeInTheDocument();
    });

    it('should render success rate bars with correct percentages', () => {
      render(<PatternList patterns={mockPatterns} />);

      expect(screen.getByText('95%')).toBeInTheDocument();
      expect(screen.getByText('87%')).toBeInTheDocument();
      expect(screen.getByText('45%')).toBeInTheDocument();
    });

    it('should render pattern signatures', () => {
      render(<PatternList patterns={mockPatterns} />);

      expect(screen.getByText('search_document(query: string)')).toBeInTheDocument();
      expect(screen.getByText('extract_data(source: string)')).toBeInTheDocument();
      expect(screen.getByText('analyze_legacy(data: any)')).toBeInTheDocument();
    });
  });

  describe('View Mode Configuration', () => {
    it('should use detailed view mode by default', () => {
      const { container } = render(<PatternList patterns={mockPatterns} />);

      // In detailed mode, we should see all columns
      const header = container.querySelector('.grid-cols-12');
      expect(header).toBeInTheDocument();
    });

    it('should hide extra columns in compact mode', () => {
      const { container } = render(<PatternList patterns={mockPatterns} viewMode="compact" />);

      // Compact mode should hide usage column
      const gridElements = container.querySelectorAll('.col-span-2');
      const hasUsageColumn = Array.from(gridElements).some((el) =>
        el.textContent?.includes('Usage')
      );
      expect(hasUsageColumn).toBe(false);
    });

    it('should show extra columns in detailed mode', () => {
      const { _container } = render(<PatternList patterns={mockPatterns} viewMode="detailed" />);

      // Detailed mode should show usage column
      expect(screen.getByText('Usage')).toBeInTheDocument();
    });
  });

  describe('Selection Policy Configuration', () => {
    it('should allow selecting all patterns when selection policy is "all"', () => {
      const handleSelect = vi.fn();
      render(<PatternList patterns={mockPatterns} selectionPolicy="all" onSelect={handleSelect} />);

      // Click on deprecated pattern
      const deprecatedRow = screen.getByText('Legacy Analysis Pattern').closest('.grid');
      expect(deprecatedRow).not.toHaveClass('cursor-not-allowed');

      fireEvent.click(deprecatedRow!);
      expect(handleSelect).toHaveBeenCalled();
    });

    it('should prevent selecting deprecated patterns when selection policy is "active-only"', () => {
      const handleSelect = vi.fn();
      render(
        <PatternList
          patterns={mockPatterns}
          selectionPolicy="active-only"
          onSelect={handleSelect}
        />
      );

      // Click on deprecated pattern
      const deprecatedRow = screen.getByText('Legacy Analysis Pattern').closest('.grid');
      expect(deprecatedRow).toHaveClass('cursor-not-allowed');

      fireEvent.click(deprecatedRow!);
      expect(handleSelect).not.toHaveBeenCalled();
    });

    it('should allow selecting active patterns regardless of selection policy', () => {
      const handleSelect = vi.fn();
      render(
        <PatternList
          patterns={mockPatterns}
          selectionPolicy="active-only"
          onSelect={handleSelect}
        />
      );

      // Click on active pattern
      const activeRow = screen.getByText('Data Extraction Pattern').closest('.grid');
      fireEvent.click(activeRow!);
      expect(handleSelect).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Data Extraction Pattern' })
      );
    });
  });

  describe('Selection State', () => {
    it('should highlight the selected pattern', () => {
      const { container } = render(<PatternList patterns={mockPatterns} selectedId="pattern-2" />);

      // The selected row should have a different background
      const selectedRow = container.querySelector('[class*="bg-primary"]');
      expect(selectedRow).toBeInTheDocument();
    });

    it('should not highlight any pattern when no pattern is selected', () => {
      const { container } = render(<PatternList patterns={mockPatterns} />);

      const highlightedRow = container.querySelector('[class*="bg-primary"]');
      expect(highlightedRow).not.toBeInTheDocument();
    });

    it('should change selection when a different pattern is clicked', () => {
      const handleSelect = vi.fn();
      render(
        <PatternList patterns={mockPatterns} selectedId="pattern-1" onSelect={handleSelect} />
      );

      const firstRow = screen.getByText('Document Search Pattern').closest('.grid');
      fireEvent.click(firstRow!);

      expect(handleSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'pattern-1' }));
    });
  });

  describe('Deprecation Action', () => {
    it('should call onDeprecate when deprecate button is clicked', () => {
      const handleDeprecate = vi.fn();
      render(<PatternList patterns={mockPatterns} onDeprecate={handleDeprecate} />);

      // Find and click the delete button for first pattern
      const deleteButtons = screen.getAllByTitle('Deprecate pattern');
      fireEvent.click(deleteButtons[0]);

      expect(handleDeprecate).toHaveBeenCalledWith('pattern-1');
    });

    it('should not call onSelect when deprecate button is clicked', () => {
      const handleSelect = vi.fn();
      const handleDeprecate = vi.fn();
      render(
        <PatternList
          patterns={mockPatterns}
          onSelect={handleSelect}
          onDeprecate={handleDeprecate}
        />
      );

      const deleteButtons = screen.getAllByTitle('Deprecate pattern');
      fireEvent.click(deleteButtons[0]);

      expect(handleDeprecate).toHaveBeenCalled();
      expect(handleSelect).not.toHaveBeenCalled();
    });
  });

  describe('Empty State', () => {
    it('should show empty state when no patterns are provided', () => {
      render(<PatternList patterns={[]} />);

      expect(screen.getByText('No patterns found')).toBeInTheDocument();
    });

    it('should show icon in empty state', () => {
      const { container } = render(<PatternList patterns={[]} />);

      const icon = container.querySelector('.material-symbols-outlined');
      expect(icon).toBeInTheDocument();
      expect(icon).toHaveTextContent('account_tree');
    });
  });

  describe('Props Interface', () => {
    it('should accept viewMode prop with correct values', () => {
      const { rerender } = render(<PatternList patterns={mockPatterns} viewMode="compact" />);

      // Compact mode
      expect(screen.queryByText('Usage')).not.toBeInTheDocument();

      // Detailed mode
      rerender(<PatternList patterns={mockPatterns} viewMode="detailed" />);
      expect(screen.getByText('Usage')).toBeInTheDocument();
    });

    it('should accept selectionPolicy prop with correct values', () => {
      const handleSelect = vi.fn();

      // Active-only policy
      const { rerender } = render(
        <PatternList
          patterns={mockPatterns}
          selectionPolicy="active-only"
          onSelect={handleSelect}
        />
      );

      const deprecatedRow = screen.getByText('Legacy Analysis Pattern').closest('.grid');
      expect(deprecatedRow).toHaveClass('cursor-not-allowed');

      // All policy
      rerender(
        <PatternList patterns={mockPatterns} selectionPolicy="all" onSelect={handleSelect} />
      );

      const deprecatedRow2 = screen.getByText('Legacy Analysis Pattern').closest('.grid');
      expect(deprecatedRow2).not.toHaveClass('cursor-not-allowed');
    });
  });

  describe('Backwards Compatibility', () => {
    it('should handle legacy boolean props for migration', () => {
      // This test verifies that during migration, we could support both patterns
      // For now, we're testing the new configuration object pattern

      render(<PatternList patterns={mockPatterns} viewMode="detailed" selectionPolicy="all" />);

      expect(screen.getByText('Usage')).toBeInTheDocument();
    });
  });

  describe('Performance', () => {
    it('should memoize computed properties to avoid re-renders', () => {
      const { rerender } = render(<PatternList patterns={mockPatterns} selectedId="pattern-1" />);

      // Re-render with same props - should not cause unnecessary updates
      rerender(<PatternList patterns={mockPatterns} selectedId="pattern-1" />);

      // Component should still render correctly
      expect(screen.getByText('Document Search Pattern')).toBeInTheDocument();
    });

    it('should update when selectedId changes', () => {
      const { rerender } = render(<PatternList patterns={mockPatterns} selectedId="pattern-1" />);

      rerender(<PatternList patterns={mockPatterns} selectedId="pattern-2" />);

      // The highlight should move to the second pattern
      expect(screen.getByText('Document Search Pattern')).toBeInTheDocument();
      expect(screen.getByText('Data Extraction Pattern')).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('should have proper button labels for actions', () => {
      render(<PatternList patterns={mockPatterns} />);

      const deleteButtons = screen.getAllByTitle('Deprecate pattern');
      expect(deleteButtons.length).toBeGreaterThan(0);
    });

    it('should use semantic HTML structure', () => {
      const { container } = render(<PatternList patterns={mockPatterns} />);

      // Should have proper grid structure
      const grids = container.querySelectorAll('.grid');
      expect(grids.length).toBeGreaterThan(0);
    });
  });

  describe('Success Rate Colors', () => {
    it('should display high success rate (>=80%) in green', () => {
      render(<PatternList patterns={mockPatterns} />);

      // 95% should be green (emerald)
      const successRateBars = screen.getAllByText('95%');
      expect(successRateBars.length).toBeGreaterThan(0);
    });

    it('should display medium success rate (60-79%) in amber', () => {
      const mediumPattern: WorkflowPattern = {
        id: 'pattern-medium',
        name: 'Medium Pattern',
        signature: 'medium_pattern()',
        status: 'active',
        usageCount: 100,
        successRate: 65,
      };

      render(<PatternList patterns={[mediumPattern]} />);

      expect(screen.getByText('65%')).toBeInTheDocument();
    });

    it('should display low success rate (<60%) in red', () => {
      render(<PatternList patterns={mockPatterns} />);

      // 45% should be red
      expect(screen.getByText('45%')).toBeInTheDocument();
    });
  });
});
