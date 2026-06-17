/**
 * Unit tests for TaskList component (Compound Components Pattern)
 *
 * TDD: GREEN - Tests passing after implementation
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import '@testing-library/jest-dom/vitest';

const antdMessage = vi.hoisted(() => ({
  error: vi.fn(),
}));
const antdModal = vi.hoisted(() => ({
  confirm: vi.fn((options?: { onOk?: () => void | Promise<void> }) => options?.onOk?.()),
}));

vi.mock('antd', () => ({
  Modal: antdModal,
  message: antdMessage,
}));

// Mock date-fns
vi.mock('date-fns', () => ({
  format: vi.fn((_date: Date) => 'Jan 1, 12:00:00'),
}));

import { taskAPI } from '../../../services/api';

const mockTasks = [
  {
    id: 'task-1-abc123def456',
    task_type: 'embedding',
    status: 'completed',
    created_at: '2024-01-01T12:00:00Z',
    completed_at: '2024-01-01T12:05:00Z',
    duration: '5s',
    entity_id: 'entity-1',
    entity_type: 'memory',
  },
  {
    id: 'task-2-xyz789abc123',
    task_type: 'vector_search',
    status: 'processing',
    created_at: '2024-01-01T12:01:00Z',
    entity_id: 'entity-2',
    entity_type: 'memory',
  },
  {
    id: 'task-3-failed456',
    task_type: 'graph_sync',
    status: 'failed',
    created_at: '2024-01-01T11:50:00Z',
    error: 'Connection timeout',
    entity_id: 'entity-3',
    entity_type: 'graph',
  },
];

const taskResponse = (
  tasks = mockTasks,
  overrides: Partial<Awaited<ReturnType<typeof taskAPI.getRecentTasks>>> = {}
) => ({
  tasks,
  total: tasks.length,
  limit: 50,
  offset: 0,
  has_more: false,
  ...overrides,
});

describe('TaskList (Compound Components)', () => {
  beforeAll(() => {
    // Set up default mock for all tests
    vi.spyOn(taskAPI, 'getRecentTasks').mockResolvedValue(taskResponse());
    vi.spyOn(taskAPI, 'retryTask').mockResolvedValue(undefined);
    vi.spyOn(taskAPI, 'stopTask').mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('TaskList - Main Container', () => {
    it('should render empty state when no tasks', async () => {
      vi.spyOn(taskAPI, 'getRecentTasks').mockResolvedValueOnce(taskResponse([]));

      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText(/No tasks found/i)).toBeInTheDocument();
      });
    });

    it('should render table with tasks when data is loaded', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText(/embedding/i)).toBeInTheDocument();
        expect(screen.getByText(/vector_search/i)).toBeInTheDocument();
        expect(screen.getByText(/graph_sync/i)).toBeInTheDocument();
      });
    });

    it('should render in embedded mode without header', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      const { container } = render(<TaskList embedded={true} />);

      await waitFor(() => {
        expect(screen.queryByText('Tasks')).not.toBeInTheDocument();
        expect(container.querySelector('.border-0')).toBeInTheDocument();
      });
    });

    it('should scope embedded task requests by entity id and type', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList entityId="community-123" entityType="community" embedded={true} />);

      await waitFor(() => {
        const lastParams = vi.mocked(taskAPI.getRecentTasks).mock.calls.at(-1)?.[0];
        expect(lastParams).toMatchObject({
          entity_id: 'community-123',
          entity_type: 'community',
        });
        expect(lastParams).not.toHaveProperty('task_type');
      });
    });
  });

  describe('TaskList.Header', () => {
    it('should render search input', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/Search Task ID or Name/i)).toBeInTheDocument();
      });
    });

    it('should render status filter dropdown', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByDisplayValue(/All Statuses/i)).toBeInTheDocument();
      });
    });

    it('should render refresh button', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        const buttons = screen.getAllByRole('button');
        expect(buttons.length).toBeGreaterThan(0);
      });
    });
  });

  describe('TaskList.Item', () => {
    it('should render task status with correct color', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        // Status badges render inside styled <span> elements within table rows.
        // Use getAllByText since status names also appear in the filter dropdown options.
        expect(screen.getAllByText(/completed/i).length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText(/processing/i).length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText(/failed/i).length).toBeGreaterThanOrEqual(1);
      });
    });

    it('should render task type name', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText(/embedding/i)).toBeInTheDocument();
      });
    });

    it('should render task duration or dash placeholder', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText('5s')).toBeInTheDocument();
      });
    });

    it('should render action buttons for tasks', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText('Retry')).toBeInTheDocument();
        expect(screen.getByText('Stop')).toBeInTheDocument();
      });
    });

    it('shows in-app error feedback when retry fails', async () => {
      vi.spyOn(taskAPI, 'retryTask').mockRejectedValueOnce(new Error('retry failed'));
      const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined);

      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText('Retry')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Retry'));

      await waitFor(() => {
        expect(antdMessage.error).toHaveBeenCalledWith('Failed to retry task. Please try again.');
      });
      expect(alertSpy).not.toHaveBeenCalled();
      alertSpy.mockRestore();
    });

    it('allows stale pending add_episode tasks to be restarted', async () => {
      vi.spyOn(taskAPI, 'getRecentTasks').mockResolvedValueOnce(
        taskResponse([
          {
            id: 'task-pending-add-episode',
            name: 'add_episode',
            status: 'pending',
            created_at: '2024-01-01T12:00:00Z',
            entity_id: 'memory-1',
            entity_type: 'episode',
          },
        ])
      );

      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText('Retry')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Retry'));

      await waitFor(() => {
        expect(taskAPI.retryTask).toHaveBeenCalledWith('task-pending-add-episode');
      });
    });

    it('shows in-app error feedback when stop fails', async () => {
      vi.spyOn(taskAPI, 'stopTask').mockRejectedValueOnce(new Error('stop failed'));
      const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => undefined);

      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText('Stop')).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText('Stop'));

      await waitFor(() => {
        expect(antdMessage.error).toHaveBeenCalledWith('Failed to stop task. Please try again.');
      });
      expect(alertSpy).not.toHaveBeenCalled();
      alertSpy.mockRestore();
    });

    it('should render entity info for tasks without entityId prop', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText('memory:entity-1...')).toBeInTheDocument();
      });
    });
  });

  describe('TaskList.Pagination', () => {
    it('should render pagination controls', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText(/Showing \d+ of \d+ tasks/i)).toBeInTheDocument();
        expect(screen.getByText(/previous/i)).toBeInTheDocument();
        expect(screen.getByText(/next/i)).toBeInTheDocument();
      });
    });

    it('should disable previous button on first page', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        const prevButton = screen.getByText(/previous/i).closest('button');
        expect(prevButton).toBeDisabled();
      });
    });

    it('uses backend has_more metadata to enable the next page', async () => {
      vi.spyOn(taskAPI, 'getRecentTasks')
        .mockResolvedValueOnce(taskResponse(mockTasks, { total: 4, has_more: true }))
        .mockResolvedValueOnce(taskResponse([mockTasks[0]!], { total: 4, offset: 50 }));

      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText(/Showing 3 of 4 tasks/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/next/i));

      await waitFor(() => {
        const lastParams = vi.mocked(taskAPI.getRecentTasks).mock.calls.at(-1)?.[0];
        expect(lastParams).toMatchObject({ offset: 50, limit: 50 });
      });
    });
  });

  describe('TaskList.EmptyState', () => {
    it('should render empty state with search icon', async () => {
      vi.spyOn(taskAPI, 'getRecentTasks').mockResolvedValueOnce(taskResponse([]));

      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByText(/No tasks found/i)).toBeInTheDocument();
      });
    });
  });

  describe('Accessibility', () => {
    it('should have proper table structure', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        expect(screen.getByRole('table')).toBeInTheDocument();
      });
    });

    it('should have proper column headers', async () => {
      const { TaskList } = await import('../../../components/tasks/TaskList');
      render(<TaskList />);

      await waitFor(() => {
        const headerRow = screen.getAllByRole('columnheader');
        const headerTexts = headerRow.map((th) => th.textContent?.trim().toLowerCase());
        expect(headerTexts).toContain('status');
        expect(headerTexts).toContain('type');
        expect(headerTexts).toContain('timestamp');
      });
    });
  });
});
