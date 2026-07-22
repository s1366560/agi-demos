import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ConversationPickerModal } from '@/components/agent/comparison/ConversationPickerModal';
import { SaveTemplateModal } from '@/components/agent/chat/SaveTemplateModal';
import { ShortcutOverlay } from '@/components/agent/chat/ShortcutOverlay';
import { VariableInputModal } from '@/components/agent/chat/VariableInputModal';

import type { Conversation } from '@/types/agent';

const comparisonCandidate: Conversation = {
  id: 'candidate',
  project_id: 'project-1',
  tenant_id: 'tenant-1',
  user_id: 'user-1',
  title: 'Incident review',
  status: 'active',
  message_count: 4,
  created_at: '2026-06-17T00:00:00Z',
  updated_at: '2026-06-17T01:00:00Z',
};

describe('agent custom modal accessibility', () => {
  it('exposes template variable inputs through a named dialog', () => {
    const onClose = vi.fn();
    render(
      <VariableInputModal
        visible
        template={{
          title: 'Greeting',
          content: 'Hello {{name}}',
          variables: [
            {
              name: 'name',
              description: 'Who should receive the greeting',
              default_value: 'Alice',
              required: true,
            },
          ],
        }}
        onClose={onClose}
        onSubmit={vi.fn()}
      />
    );

    const dialog = screen.getByRole('dialog', { name: 'Greeting' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByLabelText(/name/)).toHaveAttribute('aria-required', 'true');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('labels the save-template dialog controls and closes on Escape', () => {
    const onClose = vi.fn();
    render(
      <SaveTemplateModal
        visible
        content="Summarize the incident report."
        onClose={onClose}
        onSave={vi.fn()}
      />
    );

    expect(screen.getByRole('dialog', { name: 'Save as Template' })).toHaveAttribute(
      'aria-modal',
      'true'
    );
    expect(screen.getByLabelText('Template name')).toHaveFocus();
    expect(screen.getByLabelText('Category')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('names the conversation picker dialog and its search field', () => {
    const onClose = vi.fn();
    render(
      <ConversationPickerModal
        visible
        currentConversationId="current"
        conversations={[comparisonCandidate]}
        onClose={onClose}
        onSelect={vi.fn()}
      />
    );

    expect(screen.getByRole('dialog', { name: 'Select conversation to compare' })).toHaveAttribute(
      'aria-modal',
      'true'
    );
    expect(screen.getByRole('textbox', { name: 'Search conversations…' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });

  it('opens keyboard shortcuts as a named dialog', async () => {
    render(<ShortcutOverlay />);

    fireEvent.keyDown(window, { key: '/', ctrlKey: true });

    await waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Keyboard Shortcuts' })).toHaveAttribute(
        'aria-modal',
        'true'
      );
    });
  });
});
