/**
 * React.memo Performance Tests (TDD - GREEN phase)
 *
 * Tests for component optimization patterns including render tracking,
 * lazy-loaded Ant Design components, and CSS containment utilities.
 *
 * Target components:
 * - CSS containment utilities
 */

import { describe, it, expect } from 'vitest';

import * as containment from '../../styles/containment';

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
