import { describe, expect, it } from 'vitest';

import { StatusTab } from '@/components/blackboard/tabs/StatusTab';
import { render, screen } from '@/test/utils';

describe('StatusTab', () => {
  it('renders binding-aware worker label for pending adjudication tasks', () => {
    render(
      <StatusTab
        stats={{
          completionRatio: 50,
          discussions: 1,
          activeAgents: 1,
          pendingAdjudicationTasks: 1,
        }}
        topologyEdges={[]}
        agents={[
          {
            id: 'binding-1',
            workspace_id: 'ws-1',
            agent_id: 'worker-a',
            display_name: 'Worker A',
            is_active: true,
            created_at: '2026-04-23T00:00:00Z',
          },
        ]}
        tasks={[
          {
            id: 'task-1',
            workspace_id: 'ws-1',
            title: 'Draft checklist',
            status: 'in_progress',
            created_at: '2026-04-23T00:00:00Z',
            metadata: {
              pending_leader_adjudication: true,
              last_worker_report_type: 'completed',
              last_worker_report_summary: 'Checklist drafted',
              current_attempt_worker_binding_id: 'binding-1',
            },
          },
        ]}
        workspaceId="ws-1"
        projectId="p-1"
        tenantId="t-1"
        statusBadgeTone={() => 'bg-green-500'}
      />
    );

    expect(
      screen.getAllByText((content, node) => {
        const text = node?.textContent ?? content;
        return text.includes('Worker A') && text.includes('blackboard.pendingAdjudicationWorker');
      })[0]
    ).toBeInTheDocument();
    const boundaryBadge = screen.getByText('blackboard.pendingAdjudicationSurfaceHint').closest('div');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-boundary', 'hosted');
    expect(boundaryBadge).toHaveAttribute('data-blackboard-authority', 'non-authoritative');
  });
});
