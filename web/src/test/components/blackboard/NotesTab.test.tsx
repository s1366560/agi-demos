import { describe, expect, it } from 'vitest';

import { NotesTab } from '@/components/blackboard/tabs/NotesTab';
import { render, screen } from '@/test/utils';

describe('NotesTab', () => {
  it('marks notes as a hosted non-authoritative projection', () => {
    render(<NotesTab notes={[]} />);

    const boundaryBadge = screen.getByText('blackboard.notesSurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });
});
