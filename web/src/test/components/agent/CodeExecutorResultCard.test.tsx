import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CodeExecutorResultCard } from '@/components/agent/CodeExecutorResultCard';

describe('CodeExecutorResultCard', () => {
  it('uses semantic success styling for successful executions', () => {
    const { container } = render(
      <CodeExecutorResultCard
        result={{
          success: true,
          stdout: 'done',
          exit_code: 0,
          execution_time_ms: 42,
        }}
      />
    );

    expect(screen.getByText('Code Execution')).toBeInTheDocument();
    expect(screen.getByText('Success')).toBeInTheDocument();
    expect(container.querySelector('.code-executor-result-card')).toHaveClass('bg-green-50');
  });

  it('uses semantic error styling for failed executions', () => {
    const { container } = render(
      <CodeExecutorResultCard
        result={{
          success: false,
          stderr: 'traceback',
          exit_code: 1,
          execution_time_ms: 7,
          error: 'Execution failed',
        }}
      />
    );

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Execution failed')).toBeInTheDocument();
    expect(container.querySelector('.code-executor-result-card')).toHaveClass('bg-red-50');
  });
});
