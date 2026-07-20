import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { MemoryDetailModal } from '@/components/project/MemoryDetailModal';
import { memoryService } from '@/services/memoryService';

vi.mock('@/services/memoryService', () => ({
  memoryService: {
    updateMemory: vi.fn(),
  },
}));

describe('MemoryDetailModal', () => {
  const mockOnClose = vi.fn();
  const mockMemory: any = {
    id: '1',
    title: 'Test Memory',
    content: 'Test Content',
    content_type: 'text',
    author_id: 'user1',
    version: 1,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    project_id: 'p1',
    tags: [],
    entities: [
      { id: 'e1', name: 'Entity1', type: 'Person', properties: { role: 'Admin' }, confidence: 0.9 },
    ],
    relationships: [
      {
        id: 'r1',
        source_id: 'Entity1',
        target_id: 'Entity2',
        type: 'Knows',
        properties: {},
        confidence: 0.8,
      },
    ],
    collaborators: [],
    is_public: false,
    metadata: { key: 'value' },
  };

  it('renders nothing if not open', () => {
    const { container } = render(
      <MemoryDetailModal isOpen={false} onClose={mockOnClose} memory={mockMemory} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders memory details', () => {
    render(<MemoryDetailModal isOpen={true} onClose={mockOnClose} memory={mockMemory} />);

    expect(screen.getByText('Memory Details')).toBeInTheDocument();
    expect(screen.getByText('Test Memory')).toBeInTheDocument();
    expect(screen.getByText('Test Content')).toBeInTheDocument();
    expect(screen.getByText('text')).toBeInTheDocument();
    expect(screen.getByText('User: user1')).toBeInTheDocument();
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    render(<MemoryDetailModal isOpen={true} onClose={onClose} memory={mockMemory} />);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders entities and relationships', () => {
    render(<MemoryDetailModal isOpen={true} onClose={mockOnClose} memory={mockMemory} />);

    expect(screen.getAllByText('Entity1').length).toBeGreaterThan(0);
    expect(screen.getByText('Person')).toBeInTheDocument();
    // Selectors might need adjustment depending on exact rendering
    // Just checking text presence is usually enough if unique
    expect(screen.getByText('Knows')).toBeInTheDocument();
  });

  it('handles download', () => {
    // Mock URL.createObjectURL
    window.URL.createObjectURL = vi.fn();
    window.URL.revokeObjectURL = vi.fn();

    render(<MemoryDetailModal isOpen={true} onClose={mockOnClose} memory={mockMemory} />);

    const downloadButton = screen.getByTitle('Download');
    fireEvent.click(downloadButton);

    expect(window.URL.createObjectURL).toHaveBeenCalled();
  });

  it('copies the provided canonical memory link', async () => {
    const writeText = vi.mocked(navigator.clipboard.writeText);
    writeText.mockResolvedValueOnce(undefined);

    render(
      <MemoryDetailModal
        isOpen={true}
        onClose={mockOnClose}
        memory={mockMemory}
        shareUrl="https://example.test/tenant/t1/project/p1/memory/1"
      />
    );

    fireEvent.click(screen.getByTitle('Share'));

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith('https://example.test/tenant/t1/project/p1/memory/1');
    });
  });

  it('updates the open modal without reloading the page after save', async () => {
    const updatedMemory = {
      ...mockMemory,
      title: 'Updated Memory',
      content: 'Updated Content',
      version: 2,
      updated_at: '2024-01-02T00:00:00Z',
    };
    const onUpdated = vi.fn();
    vi.mocked(memoryService.updateMemory).mockResolvedValueOnce(updatedMemory);

    render(
      <MemoryDetailModal
        isOpen={true}
        onClose={mockOnClose}
        memory={mockMemory}
        onUpdated={onUpdated}
      />
    );

    fireEvent.click(screen.getByTitle('Edit'));
    fireEvent.change(screen.getByLabelText('Edit memory title'), {
      target: { value: 'Updated Memory' },
    });
    fireEvent.change(screen.getByLabelText('Edit memory content'), {
      target: { value: 'Updated Content' },
    });
    fireEvent.click(screen.getByTitle('Save'));

    await waitFor(() => {
      expect(memoryService.updateMemory).toHaveBeenCalledWith('1', {
        title: 'Updated Memory',
        content: 'Updated Content',
        version: 1,
      });
      expect(onUpdated).toHaveBeenCalledWith(updatedMemory);
    });
    expect(screen.getByText('Updated Memory')).toBeInTheDocument();
    expect(screen.getByText('Updated Content')).toBeInTheDocument();
  });
});
