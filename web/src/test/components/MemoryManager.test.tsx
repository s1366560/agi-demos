import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { MemoryManager } from '@/components/project/MemoryManager';

import { useMemoryStore } from '../../stores/memory';
import { useProjectStore } from '../../stores/project';

vi.mock('../../stores/memory', () => ({
  useMemoryStore: vi.fn(),
}));

vi.mock('../../stores/project', () => ({
  useProjectStore: vi.fn(),
}));

// Mock modals
vi.mock('../../components/MemoryCreateModal', () => ({
  MemoryCreateModal: ({ isOpen, onClose, onSuccess }: any) =>
    isOpen ? (
      <div data-testid="memory-create-modal">
        <button onClick={onClose}>Close</button>
        <button onClick={onSuccess}>Create</button>
      </div>
    ) : null,
}));

vi.mock('../../components/MemoryDetailModal', () => ({
  MemoryDetailModal: ({ isOpen, onClose: _onClose, memory, shareUrl }: any) =>
    isOpen ? (
      <div data-testid="memory-detail-modal" data-share-url={shareUrl}>
        {memory?.title}
      </div>
    ) : null,
}));

describe('MemoryManager', () => {
  const mockListMemories = vi.fn();
  const mockDeleteMemory = vi.fn();
  const mockSetCurrentMemory = vi.fn();
  const mockOnMemorySelect = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    (useProjectStore as any).mockReturnValue({
      currentProject: { id: 'project-1', name: 'Project 1' },
    });
    (useMemoryStore as any).mockReturnValue({
      memories: [],
      currentMemory: null,
      listMemories: mockListMemories,
      deleteMemory: mockDeleteMemory,
      setCurrentMemory: mockSetCurrentMemory,
      isLoading: false,
      error: null,
    });
  });

  it('renders loading state', () => {
    (useMemoryStore as any).mockReturnValue({
      isLoading: true,
      listMemories: mockListMemories,
    });
    const { container } = render(<MemoryManager />);
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('renders empty state when no project selected', () => {
    (useProjectStore as any).mockReturnValue({ currentProject: null });
    render(<MemoryManager />);
    expect(screen.getByText('Select a Project First')).toBeInTheDocument();
  });

  it('renders list of memories', () => {
    const memories = [
      {
        id: '1',
        title: 'Memory 1',
        content: 'Content 1',
        content_type: 'text',
        status: 'ENABLED',
        processing_status: 'COMPLETED',
        created_at: '2024-01-01',
      },
      {
        id: '2',
        title: 'Memory 2',
        content: 'Content 2',
        content_type: 'document',
        status: 'ENABLED',
        processing_status: 'PENDING',
        created_at: '2024-01-02',
      },
    ];
    (useMemoryStore as any).mockReturnValue({
      memories,
      currentMemory: memories[0],
      listMemories: mockListMemories,
      setCurrentMemory: mockSetCurrentMemory,
      deleteMemory: mockDeleteMemory,
      isLoading: false,
    });

    render(<MemoryManager onMemorySelect={mockOnMemorySelect} />);

    expect(screen.getByText('Memory 1')).toBeInTheDocument();
    expect(screen.getByText('Memory 2')).toBeInTheDocument();

    // Select memory
    fireEvent.click(screen.getByText('Memory 2'));
    expect(mockSetCurrentMemory).toHaveBeenCalledWith(memories[1]);
    expect(mockOnMemorySelect).toHaveBeenCalledWith(memories[1]);
  });

  it('opens create modal', () => {
    render(<MemoryManager />);
    fireEvent.click(screen.getByText('New Memory'));
    expect(screen.getByTestId('memory-create-modal')).toBeInTheDocument();
  });

  it('passes the canonical project memory URL to the detail modal', async () => {
    const writeText = vi.mocked(navigator.clipboard.writeText);
    writeText.mockResolvedValueOnce(undefined);
    const memories = [
      {
        id: '1',
        title: 'Memory 1',
        content: 'Content 1',
        content_type: 'text',
        author_id: 'user-1',
        project_id: 'project-1',
        tags: [],
        entities: [],
        relationships: [],
        collaborators: [],
        is_public: false,
        metadata: {},
        version: 1,
        status: 'ENABLED',
        processing_status: 'COMPLETED',
        created_at: '2024-01-01',
      },
    ];
    (useMemoryStore as any).mockReturnValue({
      memories,
      currentMemory: memories[0],
      listMemories: mockListMemories,
      setCurrentMemory: mockSetCurrentMemory,
      deleteMemory: mockDeleteMemory,
      isLoading: false,
    });

    render(<MemoryManager />);
    fireEvent.click(screen.getByLabelText('View Memory 1'));
    fireEvent.click(screen.getByTitle('Share'));

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        'http://localhost:3000/tenant/project/project-1/memory/1'
      );
    });
  });
});
