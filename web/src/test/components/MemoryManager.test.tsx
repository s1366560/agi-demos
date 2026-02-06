import { render, screen, fireEvent } from '@testing-library/react';
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
  MemoryDetailModal: ({ isOpen, onClose: _onClose, memory }: any) =>
    isOpen ? <div data-testid="memory-detail-modal">{memory?.title}</div> : null,
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
    expect(screen.getByText('请先选择项目')).toBeInTheDocument();
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
    fireEvent.click(screen.getByText('新建记忆'));
    expect(screen.getByTestId('memory-create-modal')).toBeInTheDocument();
  });
});
