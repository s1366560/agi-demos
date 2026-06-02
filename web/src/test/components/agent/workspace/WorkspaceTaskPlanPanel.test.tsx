import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { WorkspaceTaskPlanPanel } from '@/components/agent/workspace/WorkspaceTaskPlanPanel';

import type { WorkspacePlanSnapshot } from '@/types/workspace';
import type { WorkspaceTaskPlanRow } from '@/components/agent/workspace/WorkspaceTaskPlanPanelModel';

function row(overrides: Partial<WorkspaceTaskPlanRow>): WorkspaceTaskPlanRow {
  return {
    id: 'row-1',
    entityId: 'node-1',
    title: 'Task',
    status: 'todo',
    source: 'plan',
    isCurrent: false,
    iterationIndex: 1,
    order: 1,
    ...overrides,
  };
}

function snapshot(currentIteration: number): WorkspacePlanSnapshot {
  return {
    workspace_id: 'ws-1',
    plan: {
      id: 'plan-1',
      workspace_id: 'ws-1',
      goal_id: 'goal-1',
      status: 'active',
      created_at: '2026-06-02T00:00:00Z',
      nodes: [],
      counts: {},
    },
    iteration: {
      current_iteration: currentIteration,
      loop_label: 'Loop',
      cadence: 'manual',
      loop_status: 'active',
      max_iterations: 3,
      completed_iterations: [],
      current_sprint_goal: '',
      review_summary: '',
      stop_reason: '',
      active_phase: '',
      active_phase_label: '',
      next_action: '',
      task_count: 2,
      task_budget: 2,
      phases: [],
      deliverables: [],
      feedback_items: [],
      history: [],
      actions: {},
    },
    blackboard: [],
    outbox: [],
    events: [],
  };
}

function snapshotWithoutCurrentIteration(): WorkspacePlanSnapshot {
  const value = snapshot(1);
  return {
    ...value,
    iteration: undefined,
  };
}

describe('WorkspaceTaskPlanPanel', () => {
  it('collapses iteration groups by default and only expands the current iteration', () => {
    render(
      <WorkspaceTaskPlanPanel
        rows={[
          row({
            id: 'iteration-1-row',
            entityId: 'iteration-1-node',
            title: 'Older iteration task',
            iterationIndex: 1,
          }),
          row({
            id: 'iteration-2-row',
            entityId: 'iteration-2-node',
            title: 'Current iteration task',
            status: 'in_progress',
            iterationIndex: 2,
          }),
        ]}
        snapshot={snapshot(2)}
        loading={false}
        error={null}
        view="lanes"
      />
    );

    expect(screen.getByRole('button', { name: /Iteration 1/ })).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    expect(screen.getByRole('button', { name: /Iteration 2/ })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.queryByText('Older iteration task')).not.toBeInTheDocument();
    expect(screen.getByText('Current iteration task')).toBeInTheDocument();
    expect(screen.queryByText('Empty.')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Iteration 1/ }));

    expect(screen.getByRole('button', { name: /Iteration 1/ })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getByText('Older iteration task')).toBeInTheDocument();
  });

  it('expands the first iteration when the snapshot has no current iteration signal', () => {
    render(
      <WorkspaceTaskPlanPanel
        rows={[
          row({
            id: 'iteration-1-row',
            entityId: 'iteration-1-node',
            title: 'First iteration task',
            iterationIndex: 1,
          }),
          row({
            id: 'iteration-2-row',
            entityId: 'iteration-2-node',
            title: 'Second iteration task',
            iterationIndex: 2,
          }),
        ]}
        snapshot={snapshotWithoutCurrentIteration()}
        loading={false}
        error={null}
        view="lanes"
      />
    );

    expect(screen.getByRole('button', { name: /Iteration 1/ })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getByRole('button', { name: /Iteration 2/ })).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    expect(screen.getByText('First iteration task')).toBeInTheDocument();
    expect(screen.queryByText('Second iteration task')).not.toBeInTheDocument();
  });
});
