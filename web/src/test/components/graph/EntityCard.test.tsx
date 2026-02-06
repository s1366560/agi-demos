/**
 * EntityCard Component Tests
 *
 * TDD Phase 1: EntityCard Component Extraction
 *
 * These tests ensure the EntityCard:
 * 1. Renders entity information correctly
 * 2. Displays entity type badge with proper colors
 * 3. Shows entity summary with line clamp
 * 4. Displays created date
 * 5. Handles click events
 * 6. Shows selected state styling
 * 7. Handles missing data gracefully
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { EntityCard } from '../../../components/graph/EntityCard';

// Mock useTranslation
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, defaultValue?: string) => defaultValue || key,
  }),
}));

describe('EntityCard', () => {
  const mockEntity = {
    uuid: 'test-uuid-123',
    name: 'Test Entity',
    entity_type: 'Person',
    summary: 'This is a test entity summary that describes the entity in detail.',
    created_at: '2024-01-15T10:30:00Z',
  };

  const mockOnClick = vi.fn();

  /**
   * Test: Renders entity name
   */
  it('renders entity name', () => {
    render(<EntityCard entity={mockEntity} onClick={mockOnClick} />);

    expect(screen.getByText('Test Entity')).toBeInTheDocument();
  });

  /**
   * Test: Renders entity type badge
   */
  it('renders entity type badge', () => {
    render(<EntityCard entity={mockEntity} onClick={mockOnClick} />);

    expect(screen.getByText('Person')).toBeInTheDocument();
  });

  /**
   * Test: Renders entity summary
   */
  it('renders entity summary when provided', () => {
    render(<EntityCard entity={mockEntity} onClick={mockOnClick} />);

    expect(
      screen.getByText('This is a test entity summary that describes the entity in detail.')
    ).toBeInTheDocument();
  });

  /**
   * Test: Does not render summary when not provided
   */
  it('does not render summary element when not provided', () => {
    const entityWithoutSummary = { ...mockEntity, summary: '' };
    const { container } = render(
      <EntityCard entity={entityWithoutSummary} onClick={mockOnClick} />
    );

    // Summary paragraph should not be in the document when empty
    const summaryElement = container.querySelector('.text-slate-600.dark\\:\\text-slate-400');
    expect(summaryElement).not.toBeInTheDocument();
  });

  /**
   * Test: Renders created date
   */
  it('renders created date in formatted format', () => {
    render(<EntityCard entity={mockEntity} onClick={mockOnClick} />);

    // Should contain the formatted date (locale specific, so we check for the label)
    expect(screen.getByText(/created/i)).toBeInTheDocument();
  });

  /**
   * Test: Handles click event
   */
  it('calls onClick when card is clicked', () => {
    render(<EntityCard entity={mockEntity} onClick={mockOnClick} />);

    const card = screen.getByText('Test Entity').closest('div.cursor-pointer');
    fireEvent.click(card!);

    expect(mockOnClick).toHaveBeenCalledTimes(1);
  });

  /**
   * Test: Shows selected state styling when isSelected is true
   */
  it('applies selected state styling when isSelected is true', () => {
    const { container } = render(
      <EntityCard entity={mockEntity} onClick={mockOnClick} isSelected={true} />
    );

    const card = container.querySelector('.cursor-pointer');
    expect(card).toHaveClass('border-blue-500');
    expect(card).toHaveClass('shadow-md');
    expect(card).toHaveClass('ring-2');
  });

  /**
   * Test: Does not show selected state when isSelected is false
   */
  it('does not apply selected state styling when isSelected is false', () => {
    const { container } = render(
      <EntityCard entity={mockEntity} onClick={mockOnClick} isSelected={false} />
    );

    const card = container.querySelector('.cursor-pointer');
    expect(card).not.toHaveClass('border-blue-500');
    expect(card).not.toHaveClass('shadow-md');
    expect(card).toHaveClass('border-slate-200');
  });

  /**
   * Test: Renders unknown type when entity_type is missing
   */
  it('renders Unknown type when entity_type is not provided', () => {
    const entityWithoutType = { ...mockEntity, entity_type: '' };
    render(<EntityCard entity={entityWithoutType} onClick={mockOnClick} />);

    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });

  /**
   * Test: Handles undefined created_at gracefully
   */
  it('displays Unknown for created date when created_at is not provided', () => {
    const entityWithoutDate = { ...mockEntity, created_at: undefined };
    render(<EntityCard entity={entityWithoutDate} onClick={mockOnClick} />);

    expect(screen.getByText(/Unknown/i)).toBeInTheDocument();
  });
});

describe('EntityCard - Entity Type Colors', () => {
  const mockOnClick = vi.fn();

  /**
   * Test: Person type has correct color classes
   */
  it('applies correct color classes for Person entity type', () => {
    const personEntity = {
      uuid: 'person-1',
      name: 'John Doe',
      entity_type: 'Person',
      summary: 'A person',
      created_at: '2024-01-01T00:00:00Z',
    };

    const { container } = render(<EntityCard entity={personEntity} onClick={mockOnClick} />);

    const badge = container.querySelector('.rounded-full.text-xs.font-medium');
    expect(badge).toHaveClass('bg-rose-100');
    expect(badge).toHaveClass('text-rose-800');
  });

  /**
   * Test: Organization type has correct color classes
   */
  it('applies correct color classes for Organization entity type', () => {
    const orgEntity = {
      uuid: 'org-1',
      name: 'Acme Corp',
      entity_type: 'Organization',
      summary: 'An organization',
      created_at: '2024-01-01T00:00:00Z',
    };

    const { container } = render(<EntityCard entity={orgEntity} onClick={mockOnClick} />);

    const badge = container.querySelector('.rounded-full.text-xs.font-medium');
    expect(badge).toHaveClass('bg-cyan-100');
    expect(badge).toHaveClass('text-cyan-800');
  });

  /**
   * Test: Custom entity type gets a color from palette
   */
  it('applies a color from palette for custom entity types', () => {
    const customEntity = {
      uuid: 'custom-1',
      name: 'Custom Thing',
      entity_type: 'CustomType',
      summary: 'A custom entity type',
      created_at: '2024-01-01T00:00:00Z',
    };

    const { container } = render(<EntityCard entity={customEntity} onClick={mockOnClick} />);

    const badge = container.querySelector('.rounded-full.text-xs.font-medium');
    expect(badge).toBeInTheDocument();
    // Should have one of the color classes from the palette
    const badgeClasses = badge?.className || '';
    // Check for at least one bg- color class
    expect(badgeClasses).toMatch(/bg-\w+-100/);
  });
});

describe('EntityCard - Accessibility', () => {
  const mockEntity = {
    uuid: 'test-uuid-123',
    name: 'Test Entity',
    entity_type: 'Person',
    summary: 'Summary text',
    created_at: '2024-01-15T10:30:00Z',
  };
  const mockOnClick = vi.fn();

  /**
   * Test: Card is clickable via keyboard
   */
  it('can be activated via Enter key', () => {
    render(<EntityCard entity={mockEntity} onClick={mockOnClick} />);

    const card = screen.getByText('Test Entity').closest('div');
    fireEvent.keyDown(card!, { key: 'Enter', code: 'Enter' });

    expect(mockOnClick).toHaveBeenCalled();
  });
});
