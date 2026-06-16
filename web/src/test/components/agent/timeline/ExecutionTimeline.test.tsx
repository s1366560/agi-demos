import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import '@testing-library/jest-dom/vitest';

import { ExecutionTimeline } from '../../../../components/agent/timeline/ExecutionTimeline';

vi.mock('../../../../components/agent/results/MultiSourceResultsCard', () => ({
  MultiSourceResultsCard: () => null,
}));

vi.mock('../../../../components/agent/timeline/useMCPAppOpen', () => ({
  useMCPAppOpen: () => () => undefined,
}));

describe('ExecutionTimeline summary formatting', () => {
  it('uses locale-neutral separators for todo summaries', () => {
    render(
      <ExecutionTimeline
        steps={[
          {
            id: 'todo-1',
            toolName: 'todo_write',
            status: 'success',
            input: {
              action: 'update',
              todos: [
                { status: 'completed', content: 'Ship definition' },
                { status: 'in_progress', content: 'Verify workspace' },
                { status: 'pending', content: 'Audit evolution' },
              ],
            },
          },
        ]}
      />
    );

    const summary = screen.getAllByText(/Update 3 todos:/)[0]?.textContent ?? '';
    expect(summary).toContain(
      '1 completed, 1 in progress, 1 pending: Ship definition, Verify workspace and 1 more'
    );
    expect(summary).not.toMatch(/[，、：]/);
  });
});
