import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import '@testing-library/jest-dom/vitest';

import { ToolExecutionDetail } from '../../../../components/agent/execution/ToolExecutionDetail';

import type { ToolExecution } from '../../../../types/agent';

const baseExecution: ToolExecution = {
  id: 'tool-1',
  toolName: 'web_search',
  input: { query: 'memstack' },
  status: 'success',
  result: 'Search complete',
  startTime: '2024-01-01T00:00:00Z',
  endTime: '2024-01-01T00:00:01Z',
  duration: 1000,
};

describe('ToolExecutionDetail', () => {
  it('renders one status badge in the full header', () => {
    render(<ToolExecutionDetail execution={baseExecution} />);

    expect(screen.getAllByText('Success')).toHaveLength(1);
  });

  it('renders the running state without duplicating the status badge', () => {
    render(
      <ToolExecutionDetail
        execution={{
          ...baseExecution,
          status: 'running',
          result: undefined,
          endTime: undefined,
          duration: undefined,
        }}
      />
    );

    expect(screen.getAllByText('Running')).toHaveLength(1);
    expect(screen.getByText('Executing...')).toBeInTheDocument();
  });
});
