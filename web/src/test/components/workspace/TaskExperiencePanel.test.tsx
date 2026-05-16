import { describe, expect, it, vi } from 'vitest';

import { TaskExperiencePanel } from '@/components/workspace/TaskExperiencePanel';
import type { WorkspaceTask } from '@/types/workspace';

import { render, screen } from '../../utils';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: string | ({ defaultValue?: string } & Record<string, unknown>)) => {
      const fallback = typeof options === 'string' ? options : (options?.defaultValue ?? _key);
      if (typeof options === 'string') {
        return fallback;
      }
      return fallback.replace(/\{\{(\w+)\}\}/g, (_match, token: string) =>
        String(options?.[token] ?? '')
      );
    },
    i18n: { language: 'en-US', changeLanguage: vi.fn() },
  }),
}));

describe('TaskExperiencePanel', () => {
  const task: WorkspaceTask = {
    id: 'task-1',
    workspace_id: 'workspace-1',
    title: 'Investigate execution gap',
    status: 'todo',
    metadata: {},
    created_at: '2024-01-01T00:00:00Z',
  };

  it('renders localized overview copy without execution session data', () => {
    render(
      <TaskExperiencePanel
        task={task}
        agents={[]}
        experience={null}
        executionSession={null}
        loading={false}
        recoveryActionLoading={false}
        error={null}
        onRecoveryAction={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByRole('complementary', { name: 'Task experience' })).toBeInTheDocument();
    expect(screen.getByLabelText('Close task details')).toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Goal Contract')).toBeInTheDocument();
    expect(screen.getByText('Execution')).toBeInTheDocument();
    expect(screen.getByText('Execution session')).toBeInTheDocument();
    expect(screen.getByText('No session data')).toBeInTheDocument();
    expect(screen.getByText('Workspace task')).toBeInTheDocument();
    expect(screen.getByText('Unassigned')).toBeInTheDocument();
    expect(screen.getByText('Evidence signal')).toBeInTheDocument();
    expect(screen.getAllByText('None').length).toBeGreaterThan(0);
  });
});
