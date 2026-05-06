/**
 * Unit tests for `deriveTaskProgress` (taskProgressDerivation).
 */
import { describe, expect, it } from 'vitest';

import { deriveTaskProgress } from '../../../../components/agent/tasks/taskProgressDerivation';

import type { AgentTask, TaskStatus } from '../../../../types/agent';

const makeTask = (
  id: string,
  status: TaskStatus,
  order_index: number,
  content = `Task ${id}`,
): AgentTask => ({
  id,
  conversation_id: 'c1',
  content,
  status,
  priority: 'medium',
  order_index,
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
});

describe('deriveTaskProgress', () => {
  it('returns hasTasks=false when tasks list is empty and not streaming', () => {
    const result = deriveTaskProgress([], false);
    expect(result.hasTasks).toBe(false);
    expect(result.status).toBe('completed');
  });

  it('returns thinking when streaming with no tasks', () => {
    const result = deriveTaskProgress([], true);
    expect(result.hasTasks).toBe(false);
    expect(result.status).toBe('thinking');
  });

  it('marks step_executing for in_progress task and surfaces label', () => {
    const tasks = [
      makeTask('a', 'completed', 0),
      makeTask('b', 'in_progress', 1, 'Run integration tests'),
      makeTask('c', 'pending', 2),
    ];
    const result = deriveTaskProgress(tasks, true);
    expect(result.status).toBe('step_executing');
    expect(result.current).toBe(2);
    expect(result.total).toBe(3);
    expect(result.label).toBe('Run integration tests');
  });

  it('falls back to next pending when nothing is in_progress', () => {
    const tasks = [
      makeTask('a', 'completed', 0),
      makeTask('b', 'pending', 1, 'Plan migration'),
      makeTask('c', 'pending', 2),
    ];
    const result = deriveTaskProgress(tasks, true);
    expect(result.status).toBe('thinking');
    expect(result.current).toBe(2);
    expect(result.label).toBe('Plan migration');
  });

  it('returns failed when there are failed tasks and not all completed', () => {
    const tasks = [
      makeTask('a', 'completed', 0),
      makeTask('b', 'failed', 1, 'Deploy to staging'),
    ];
    const result = deriveTaskProgress(tasks, false);
    expect(result.status).toBe('failed');
    expect(result.label).toBe('Deploy to staging');
  });

  it('returns completed when all tasks are done', () => {
    const tasks = [
      makeTask('a', 'completed', 0),
      makeTask('b', 'completed', 1),
    ];
    const result = deriveTaskProgress(tasks, false);
    expect(result.status).toBe('completed');
    expect(result.current).toBe(2);
    expect(result.total).toBe(2);
  });

  it('orders tasks by order_index regardless of input order', () => {
    const tasks = [
      makeTask('c', 'pending', 2, 'Third'),
      makeTask('a', 'completed', 0, 'First'),
      makeTask('b', 'in_progress', 1, 'Second'),
    ];
    const result = deriveTaskProgress(tasks, true);
    expect(result.label).toBe('Second');
    expect(result.current).toBe(2);
  });
});
