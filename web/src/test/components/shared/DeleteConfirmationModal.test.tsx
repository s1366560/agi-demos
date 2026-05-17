import { describe, expect, it, vi } from 'vitest';

import { DeleteConfirmationModal } from '../../../components/shared/modals/DeleteConfirmationModal';
import { fireEvent, render } from '../../utils';

describe('DeleteConfirmationModal', () => {
  it('closes on Escape when deletion is idle', () => {
    const onClose = vi.fn();
    render(
      <DeleteConfirmationModal
        isOpen
        onClose={onClose}
        onConfirm={vi.fn()}
        title="Delete item"
        message="This cannot be undone."
      />
    );

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not close on Escape while deletion is in progress', () => {
    const onClose = vi.fn();
    render(
      <DeleteConfirmationModal
        isOpen
        onClose={onClose}
        onConfirm={vi.fn()}
        title="Delete item"
        message="This cannot be undone."
        isDeleting
      />
    );

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(onClose).not.toHaveBeenCalled();
  });
});
