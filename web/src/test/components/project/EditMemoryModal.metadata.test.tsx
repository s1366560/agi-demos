import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { EditMemoryModal } from '@/components/project/EditMemoryModal';
import { memoryAPI } from '@/services/api';

import type { Memory } from '@/types/memory';

vi.mock('@/services/api', () => ({ memoryAPI: { update: vi.fn() } }));

const memory: Memory = {
  id: 'memory-1',
  project_id: 'project-1',
  title: 'Metadata note',
  content: 'Source',
  content_type: 'text',
  tags: ['record-tag'],
  entities: [],
  relationships: [],
  version: 3,
  author_id: 'user-1',
  collaborators: [],
  is_public: false,
  status: 'ENABLED',
  processing_status: 'COMPLETED',
  metadata: { owner: 'Mira' },
  created_at: '2026-09-08T00:00:00Z',
};

function openEditor() {
  const onClose = vi.fn();
  render(
    <EditMemoryModal
      isOpen
      memory={memory}
      projectId="project-1"
      onClose={onClose}
      onUpdate={vi.fn()}
    />
  );
  return onClose;
}

describe('memory metadata editing', () => {
  beforeEach(() => vi.clearAllMocks());

  it('saves nested metadata with the displayed revision and separate tags', async () => {
    vi.mocked(memoryAPI.update).mockResolvedValue(memory);
    const onClose = openEditor();
    const input = screen.getByLabelText('memory.edit.metadataLabel');
    expect(JSON.parse((input as HTMLTextAreaElement).value)).toEqual(memory.metadata);
    const metadata = { review: { labels: ['local'], approved: false, score: 2.5 }, note: null };
    fireEvent.change(input, { target: { value: JSON.stringify(metadata) } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(memoryAPI.update).toHaveBeenCalledWith('project-1', 'memory-1', {
      title: 'Metadata note',
      content: 'Source',
      tags: ['record-tag'],
      version: 3,
      metadata,
    });
  });

  it.each([
    '[]',
    'null',
    '{broken',
    '{"score":1e400}',
    JSON.stringify({ text: '界'.repeat(22000) }),
  ])('retains an invalid draft without sending it (%#)', (draft) => {
    openEditor();
    const input = screen.getByLabelText('memory.edit.metadataLabel');
    fireEvent.change(input, { target: { value: draft } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(screen.getByRole('alert')).toHaveTextContent('memory.edit.metadataInvalid');
    expect(input).toHaveValue(draft);
    expect(memoryAPI.update).not.toHaveBeenCalled();
  });

  it('retains the metadata draft when the server rejects a stale revision', async () => {
    vi.mocked(memoryAPI.update).mockRejectedValue({ response: { status: 409 } });
    const onClose = openEditor();
    const input = screen.getByLabelText('memory.edit.metadataLabel');
    fireEvent.change(input, { target: { value: '{"owner":"Cedar"}' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByRole('alert');
    expect(input).toHaveValue('{"owner":"Cedar"}');
    expect(onClose).not.toHaveBeenCalled();
  });
});
