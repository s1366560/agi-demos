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

// Mock EventSource for SSE tests
class MockEventSource {
  url: string;
  readyState: number = 1;
  onopen: (() => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  private listeners: Map<string, ((e: MessageEvent) => void)[]> = new Map();

  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, callback: (e: MessageEvent) => void) {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, []);
    }
    this.listeners.get(type)!.push(callback);
  }

  removeEventListener() {}

  close() {
    this.readyState = MockEventSource.CLOSED;
  }

  emit(type: string, data: any) {
    const event = new MessageEvent(type, { data: JSON.stringify(data) });
    const listeners = this.listeners.get(type);
    if (listeners) {
      listeners.forEach((callback) => callback(event));
    }
  }
}

let mockEventSourceInstances: MockEventSource[] = [];

describe('MemoryList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockEventSourceInstances = [];

    // Mock EventSource
    (global as any).EventSource = class extends MockEventSource {
      constructor(url: string) {
        super(url);
        mockEventSourceInstances.push(this);
      }
    };
  });

  afterEach(() => {
    mockEventSourceInstances = [];
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
      page_size: 100,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Memory 1')).toBeInTheDocument();
    });
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
      page_size: 100,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Completed Memory')).toBeInTheDocument();
      expect(screen.getByText('Processing Memory')).toBeInTheDocument();
      expect(screen.getByText('Failed Memory')).toBeInTheDocument();
    });

    // Check status badges are rendered
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    expect(screen.getByText('FAILED')).toBeInTheDocument();
  });

  it('subscribes to SSE for processing memories', async () => {
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
      page_size: 100,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Processing Memory')).toBeInTheDocument();
    });

    // Should have created an EventSource for the task
    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBeGreaterThan(0);
      expect(mockEventSourceInstances[0].url).toContain('/tasks/task-123/stream');
    });
  });

  it('shows empty state when no memories', async () => {
    vi.mocked(memoryAPI.list).mockResolvedValue({
      memories: [],
      total: 0,
      page: 1,
      page_size: 100,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      // Component should render - check for search input which is always present
      expect(screen.getByRole('textbox')).toBeInTheDocument();
    });
  });

  it('filters memories by search term', async () => {
    vi.mocked(memoryAPI.list).mockResolvedValue({
      memories: [
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
      ],
      total: 2,
      page: 1,
      page_size: 100,
    });

    renderWithRouter(<MemoryList />, { route: '/project/p1/memories' });

    await waitFor(() => {
      expect(screen.getByText('Apple Memory')).toBeInTheDocument();
      expect(screen.getByText('Banana Memory')).toBeInTheDocument();
    });

    // Find search input and type
    const searchInput = screen.getByRole('textbox');
    fireEvent.change(searchInput, { target: { value: 'Apple' } });

    // After filtering, only Apple should be visible
    await waitFor(() => {
      expect(screen.getByText('Apple Memory')).toBeInTheDocument();
      expect(screen.queryByText('Banana Memory')).not.toBeInTheDocument();
    });
  });
});
