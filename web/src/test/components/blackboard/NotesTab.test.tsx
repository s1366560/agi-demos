import { describe, expect, it } from 'vitest';

import { NotesTab } from '@/components/blackboard/tabs/NotesTab';
import { render, screen } from '@/test/utils';

describe('NotesTab', () => {
  it('marks notes as a hosted non-authoritative projection', () => {
    render(<NotesTab notes={[]} />);

    const hostedBadge = screen.getByText('blackboard.notesSurfaceHint').closest('div');
    expect(hostedBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(hostedBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');

    const derivedBadge = screen.getByText('blackboard.notesDerivedHint').closest('div');
    expect(derivedBadge).toHaveAttribute('data-blackboard-surface', 'derived');
    expect(derivedBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });
});
