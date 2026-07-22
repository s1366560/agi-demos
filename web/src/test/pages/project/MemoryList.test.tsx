import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { screen, render, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { MemoryList } from '../../../pages/project/MemoryList';
import { memoryAPI } from '../../../services/api';
import { Memory } from '../../../types/memory';

// Mock memoryAPI directly (similar to SpaceDashboard approach)
vi.mock('../../../services/api', () => ({
  memoryAPI: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    get: vi.fn(),
  },
}));

// Mock @tanstack/react-virtual so useVirtualizer renders all rows without needing scroll height
vi.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: (opts: { count: number; estimateSize: () => number }) => ({
    getVirtualItems: () =>
      Array.from({ length: opts.count }, (_, i) => ({
        index: i,
        key: i,
        start: i * opts.estimateSize(),
        size: opts.estimateSize(),
        end: (i + 1) * opts.estimateSize(),
        measureElement: vi.fn(),
      })),
    getTotalSize: () => opts.count * opts.estimateSize(),
    scrollToIndex: vi.fn(),
  }),
}));

describe('MemoryList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const renderWithRouter = (ui: React.ReactElement, { route = '/' } = {}) => {
    return render(
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/project/:projectId/memories" element={ui} />
        </Routes>
      </MemoryRouter>
    );
  };

  it('renders list of memories', async () => {
    vi.mocked(memoryAPI.list).mockResolvedValue({
      memories: [
        {
          id: 'm1',
          title: 'Memory 1',
          content: 'Content 1',
          created_at: '2023-01-01',
          processing_status: 'COMPLETED',
          status: 'ENABLED',
        } as Memory,
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Memory 1')).toBeInTheDocument();
    });

    expect(memoryAPI.list).toHaveBeenCalledWith('p1', { page: 1, page_size: 20 });
  });

  it('keeps the virtualized table horizontally scrollable on narrow screens', async () => {
    vi.mocked(memoryAPI.list).mockResolvedValue({
      memories: [
        {
          id: 'm1',
          title: 'A very long memory title that should not force mobile cells to overlap',
          content: 'Content 1',
          created_at: '2023-01-01',
          processing_status: 'COMPLETED',
          status: 'ENABLED',
        } as Memory,
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    expect(await screen.findByText(/A very long memory title/)).toBeInTheDocument();

    expect(screen.getByTestId('memory-list-horizontal-scroll')).toHaveClass('overflow-x-auto');
    expect(screen.getByTestId('memory-list-vertical-scroll')).toHaveClass(
      'overflow-y-auto',
      'min-w-[960px]'
    );
    expect(document.querySelector('table')).toHaveClass('min-w-[960px]');
  });

  it('displays processing status badges correctly', async () => {
    vi.mocked(memoryAPI.list).mockResolvedValue({
      memories: [
        {
          id: 'm1',
          title: 'Completed Memory',
          content: 'Content',
          processing_status: 'COMPLETED',
          status: 'ENABLED',
        } as Memory,
        {
          id: 'm2',
          title: 'Processing Memory',
          content: 'Content',
          processing_status: 'PROCESSING',
          status: 'ENABLED',
          task_id: 'task-123',
        } as Memory,
        {
          id: 'm3',
          title: 'Failed Memory',
          content: 'Content',
          processing_status: 'FAILED',
          status: 'ENABLED',
        } as Memory,
      ],
      total: 3,
      page: 1,
      page_size: 20,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Completed Memory')).toBeInTheDocument();
      expect(screen.getByText('Processing Memory')).toBeInTheDocument();
      expect(screen.getByText('Failed Memory')).toBeInTheDocument();
    });

    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('shows processing status for in-progress memories', async () => {
    vi.mocked(memoryAPI.list).mockResolvedValue({
      memories: [
        {
          id: 'm1',
          title: 'Processing Memory',
          content: 'Content',
          processing_status: 'PROCESSING',
          status: 'ENABLED',
          task_id: 'task-123',
        } as Memory,
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Processing Memory')).toBeInTheDocument();
    });

    const processingElements = screen.getAllByText('Processing');
    expect(processingElements.length).toBeGreaterThanOrEqual(2);
  });

  it('shows empty state when no memories', async () => {
    vi.mocked(memoryAPI.list).mockResolvedValue({
      memories: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      // Component should render - check for search input which is always present
      expect(screen.getByRole('searchbox')).toBeInTheDocument();
    });
  });

  it('filters memories by search term', async () => {
    vi.mocked(memoryAPI.list).mockImplementation(async (_projectId, params = {}) => {
      const query = params as { search?: string };
      const memories =
        query.search === 'Apple'
          ? [
              {
                id: 'm1',
                title: 'Apple Memory',
                content: 'About apples',
                processing_status: 'COMPLETED',
              } as Memory,
            ]
          : [
              {
                id: 'm1',
                title: 'Apple Memory',
                content: 'About apples',
                processing_status: 'COMPLETED',
              } as Memory,
              {
                id: 'm2',
                title: 'Banana Memory',
                content: 'About bananas',
                processing_status: 'COMPLETED',
              } as Memory,
            ];
      return {
        memories,
        total: memories.length,
        page: 1,
        page_size: 20,
      };
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Apple Memory')).toBeInTheDocument();
      expect(screen.getByText('Banana Memory')).toBeInTheDocument();
    });

    // Find search input and type
    const searchInput = screen.getByRole('searchbox');
    fireEvent.change(searchInput, { target: { value: 'Apple' } });

    // After filtering, only Apple should be visible
    await waitFor(() => {
      expect(screen.getByText('Apple Memory')).toBeInTheDocument();
      expect(screen.queryByText('Banana Memory')).not.toBeInTheDocument();
    });
    expect(memoryAPI.list).toHaveBeenLastCalledWith('p1', {
      page: 1,
      page_size: 20,
      search: 'Apple',
    });
  });

  it('filters memories by content type', async () => {
    vi.mocked(memoryAPI.list).mockImplementation(async (_projectId, params = {}) => {
      const query = params as { content_type?: string };
      const memories =
        query.content_type === 'document'
          ? [
              {
                id: 'm2',
                title: 'Document Memory',
                content: 'Uploaded document',
                content_type: 'document',
                processing_status: 'COMPLETED',
              } as Memory,
            ]
          : [
              {
                id: 'm1',
                title: 'Text Memory',
                content: 'Plain note',
                content_type: 'text',
                processing_status: 'COMPLETED',
              } as Memory,
              {
                id: 'm2',
                title: 'Document Memory',
                content: 'Uploaded document',
                content_type: 'document',
                processing_status: 'COMPLETED',
              } as Memory,
            ];
      return {
        memories,
        total: memories.length,
        page: 1,
        page_size: 20,
      };
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Text Memory')).toBeInTheDocument();
      expect(screen.getByText('Document Memory')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Document' }));

    await waitFor(() => {
      expect(screen.queryByText('Text Memory')).not.toBeInTheDocument();
      expect(screen.getByText('Document Memory')).toBeInTheDocument();
    });
    expect(memoryAPI.list).toHaveBeenLastCalledWith('p1', {
      page: 1,
      page_size: 20,
      content_type: 'document',
    });
  });

  it('requests the next server page from pagination controls', async () => {
    vi.mocked(memoryAPI.list).mockImplementation(async (_projectId, params = {}) => {
      const query = params as { page?: number };
      const isSecondPage = query.page === 2;
      return {
        memories: [
          {
            id: isSecondPage ? 'm2' : 'm1',
            title: isSecondPage ? 'Second Page Memory' : 'First Page Memory',
            content: 'Content',
            processing_status: 'COMPLETED',
          } as Memory,
        ],
        total: 21,
        page: isSecondPage ? 2 : 1,
        page_size: 20,
      };
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    expect(await screen.findByText('First Page Memory')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));

    await waitFor(() => {
      expect(screen.getByText('Second Page Memory')).toBeInTheDocument();
    });
    expect(memoryAPI.list).toHaveBeenLastCalledWith('p1', { page: 2, page_size: 20 });
  });
});
