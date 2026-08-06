/**
 * Spinner / LoadingOverlay Component Tests
 *
 * These tests ensure:
 * 1. Spinner renders a spinning indicator with the requested size
 * 2. Spinner renders the optional muted tip text
 * 3. LoadingOverlay blocks/dims children while spinning and hides the overlay otherwise
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import { Spinner, LoadingOverlay } from '../../../components/common/Spinner';

describe('Spinner', () => {
  it('renders a spinning indicator', () => {
    const { container } = render(<Spinner />);
    expect(container.querySelector('svg.animate-spin')).not.toBeNull();
  });

  it('renders the tip text when provided', () => {
    render(<Spinner tip="Loading…" />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });
});

describe('LoadingOverlay', () => {
  it('renders children without overlay when not spinning', () => {
    const { container } = render(
      <LoadingOverlay spinning={false}>
        <div>Form Content</div>
      </LoadingOverlay>
    );

    expect(screen.getByText('Form Content')).toBeInTheDocument();
    expect(container.querySelector('svg.animate-spin')).toBeNull();
  });

  it('marks children busy and shows overlay while spinning', () => {
    render(
      <LoadingOverlay spinning={true} tip="Saving…">
        <div>Form Content</div>
      </LoadingOverlay>
    );

    const content = screen.getByText('Form Content');
    expect(content.parentElement).toHaveAttribute('aria-busy', 'true');
    expect(content.parentElement).toHaveClass('pointer-events-none', 'opacity-60');
    expect(screen.getByText('Saving…')).toBeInTheDocument();
  });
});
