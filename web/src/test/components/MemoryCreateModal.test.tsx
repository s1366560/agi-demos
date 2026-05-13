import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { MemoryCreateModal } from '../../components/MemoryCreateModal';
import { useMemoryStore } from '../../stores/memory';
import { useProjectStore } from '../../stores/project';

vi.mock('../../stores/memory', () => ({
  useMemoryStore: vi.fn(),
}));

vi.mock('../../stores/project', () => ({
  useProjectStore: vi.fn(),
}));

describe('MemoryCreateModal', () => {
  const mockCreateMemory = vi.fn();
  const mockExtractEntities = vi.fn();
  const mockExtractRelationships = vi.fn();
  const mockOnClose = vi.fn();
  const mockOnSuccess = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    (useProjectStore as any).mockReturnValue({
      currentProject: { id: 'project-1', name: 'Project 1' },
    });
    (useMemoryStore as any).mockReturnValue({
      createMemory: mockCreateMemory,
      extractEntities: mockExtractEntities,
      extractRelationships: mockExtractRelationships,
      isLoading: false,
      error: null,
    });
  });

  it('renders nothing if not open', () => {
    const { container } = render(<MemoryCreateModal isOpen={false} onClose={mockOnClose} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders modal when open', () => {
    render(<MemoryCreateModal isOpen={true} onClose={mockOnClose} />);
    expect(screen.getByRole('heading', { name: 'Create Memory' })).toBeInTheDocument();
  });

  it('handles form input', () => {
    render(<MemoryCreateModal isOpen={true} onClose={mockOnClose} />);

    const titleInput = screen.getByPlaceholderText('Enter memory title');
    const contentInput = screen.getByPlaceholderText('Enter memory content');

    fireEvent.change(titleInput, { target: { value: 'New Memory' } });
    fireEvent.change(contentInput, { target: { value: 'Memory Content' } });

    expect(titleInput).toHaveValue('New Memory');
    expect(contentInput).toHaveValue('Memory Content');
  });

  it('submits form', async () => {
    render(<MemoryCreateModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />);

    fireEvent.change(screen.getByPlaceholderText('Enter memory title'), { target: { value: 'Title' } });
    fireEvent.change(screen.getByPlaceholderText('Enter memory content'), { target: { value: 'Content' } });

    fireEvent.click(screen.getByRole('button', { name: 'Create Memory' }));

    await waitFor(() => {
      expect(mockCreateMemory).toHaveBeenCalledWith(
        'project-1',
        expect.objectContaining({
          title: 'Title',
          content: 'Content',
          project_id: 'project-1',
        })
      );
      expect(mockOnSuccess).toHaveBeenCalled();
      expect(mockOnClose).toHaveBeenCalled();
    });
  });

  it('handles extraction', async () => {
    mockExtractEntities.mockResolvedValue([{ name: 'Entity1', type: 'Person' }]);
    mockExtractRelationships.mockResolvedValue([
      { source_id: 'E1', target_id: 'E2', type: 'related' },
    ]);

    render(<MemoryCreateModal isOpen={true} onClose={mockOnClose} />);

    // Fill content
    fireEvent.change(screen.getByPlaceholderText('Enter memory content'), { target: { value: 'Content' } });

    // Switch to extraction tab - need to find tab button
    fireEvent.click(screen.getByText('Entity Extraction'));

    // Click extract buttons
    fireEvent.click(screen.getByText('Extract Entities'));

    await waitFor(() => {
      expect(mockExtractEntities).toHaveBeenCalled();
      expect(screen.getByText('Entity1')).toBeInTheDocument();
    });
  });
});
