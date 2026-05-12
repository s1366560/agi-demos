import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { WorkspaceStatusBar } from '@/components/workspace/WorkspaceStatusBar';

describe('WorkspaceStatusBar', () => {
  it('renders nothing when given no slots', () => {
    const { container } = render(<WorkspaceStatusBar />);
    expect(container.firstChild).toBeNull();
  });

  it('renders supplied slots and skips missing ones', () => {
    render(
      <WorkspaceStatusBar
        subAgent={{ label: 'Agent', value: '@executor', tone: 'running' }}
        hitl={{ label: 'HITL', value: '2 pending', tone: 'warning' }}
      />
    );
    expect(screen.getByTestId('workspace-status-bar')).toBeInTheDocument();
    expect(screen.getByText('@executor')).toBeInTheDocument();
    expect(screen.getByText('2 pending')).toBeInTheDocument();
    expect(screen.queryByText(/sandbox/i)).not.toBeInTheDocument();
  });

  it('renders task progress inline when supplied', () => {
    render(
      <WorkspaceStatusBar
        task={{ label: 'Task', value: '2/7 · 29%', tone: 'running', progressPercent: 29 }}
      />
    );

    expect(screen.getByTestId('workspace-status-bar')).toBeInTheDocument();
    expect(screen.getByText('Task')).toBeInTheDocument();
    expect(screen.getByText('2/7 · 29%')).toBeInTheDocument();
  });
});
