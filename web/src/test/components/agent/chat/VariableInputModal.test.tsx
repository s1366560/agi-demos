import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { VariableInputModal } from '@/components/agent/chat/VariableInputModal';

describe('VariableInputModal', () => {
  it('submits templates without variables after render', async () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(
      <VariableInputModal
        visible
        template={{ title: 'Plain template', content: 'No variables here' }}
        onSubmit={onSubmit}
        onClose={onClose}
      />
    );

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('No variables here');
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('resets values when switching templates', () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();
    const { rerender } = render(
      <VariableInputModal
        visible
        template={{
          title: 'Greeting',
          content: 'Hello {{name}}',
          variables: [
            {
              name: 'name',
              description: '',
              default_value: 'Alice',
              required: true,
            },
          ],
        }}
        onSubmit={onSubmit}
        onClose={onClose}
      />
    );

    fireEvent.change(screen.getByDisplayValue('Alice'), { target: { value: 'Bob' } });

    rerender(
      <VariableInputModal
        visible
        template={{
          title: 'Topic',
          content: 'Task {{topic}}',
          variables: [
            {
              name: 'topic',
              description: '',
              default_value: 'Security',
              required: true,
            },
          ],
        }}
        onSubmit={onSubmit}
        onClose={onClose}
      />
    );

    expect(screen.queryByDisplayValue('Bob')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('Security')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Use Template' }));

    expect(onSubmit).toHaveBeenCalledWith('Task Security');
    expect(onClose).toHaveBeenCalled();
  });
});
