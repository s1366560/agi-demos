import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@/test/utils';

import { KeyboardShortcutsPopover } from '@/components/blackboard/KeyboardShortcutsPopover';

describe('KeyboardShortcutsPopover', () => {
  it('exposes the shortcut trigger and dialog with accessible names', () => {
    render(<KeyboardShortcutsPopover moveMode={null} />);

    const trigger = screen.getByRole('button', { name: 'Keyboard shortcuts' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
    expect(screen.getByText('Move focus')).toBeInTheDocument();
  });

  it('closes the dialog on Escape', () => {
    render(<KeyboardShortcutsPopover moveMode={{ kind: 'agent', agentId: 'agent-1' }} />);

    fireEvent.click(screen.getByRole('button', { name: 'Keyboard shortcuts' }));
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
    expect(
      screen.getByText('Use arrow keys to move the selected workstation.')
    ).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument();
  });
});
