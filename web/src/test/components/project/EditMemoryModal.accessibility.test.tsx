import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { EditMemoryModal } from '@/components/project/EditMemoryModal';

import type { Memory } from '@/types/memory';

const memory: Memory = {
  id: 'memory-1',
  project_id: 'project-1',
  title: 'Research note',
  content: 'A useful memory.',
  content_type: 'text',
  tags: ['research'],
  entities: [],
  relationships: [],
  version: 1,
  author_id: 'user-1',
  collaborators: [],
  is_public: false,
  status: 'ENABLED',
  processing_status: 'COMPLETED',
  metadata: {},
  created_at: '2026-06-17T00:00:00Z',
};

describe('EditMemoryModal accessibility', () => {
  it('renders as a labelled dialog and closes on Escape', () => {
    const onClose = vi.fn();

    render(
      <EditMemoryModal
        isOpen
        memory={memory}
        onClose={onClose}
        onUpdate={vi.fn()}
        projectId="project-1"
      />
    );

    expect(screen.getByRole('dialog', { name: 'Edit memory' })).toHaveAttribute(
      'aria-modal',
      'true'
    );
    expect(screen.getByLabelText(/Title/)).toHaveFocus();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
