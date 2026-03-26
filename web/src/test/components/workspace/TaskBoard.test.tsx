import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TaskBoard } from '@/components/workspace/TaskBoard';
import { render, screen, fireEvent } from '@/test/utils';

vi.mock('@/stores/workspace', () => ({
  useWorkspaceTasks: vi.fn(),
  useWorkspaceActions: vi.fn(),
}));

describe('TaskBoard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders tasks and triggers create action', async () => {
    const createTask = vi.fn().mockResolvedValue(undefined);
    const setTaskStatus = vi.fn().mockResolvedValue(undefined);
    const { useWorkspaceTasks, useWorkspaceActions } = await import('@/stores/workspace');

    vi.mocked(useWorkspaceTasks).mockReturnValue([
      { id: 'task-1', title: 'Define scope', status: 'todo', workspace_id: 'ws-1' },
    ] as any);
    vi.mocked(useWorkspaceActions).mockReturnValue({
      createTask,
      setTaskStatus,
    } as any);

    render(<TaskBoard workspaceId="ws-1" />);

    expect(screen.getByText('Define scope')).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('Add task title'), {
      target: { value: 'Build MVP' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add task' }));

    expect(createTask).toHaveBeenCalledWith('ws-1', { title: 'Build MVP' });
  });
});
