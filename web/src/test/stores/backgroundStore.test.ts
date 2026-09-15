import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useBackgroundStore } from '../../stores/backgroundStore';
import { subagentAPI } from '../../services/subagentService';
vi.mock('../../services/subagentService', () => ({ subagentAPI: { cancelExecution: vi.fn() } }));

beforeEach(() => {
  useBackgroundStore.getState().clearAll();
  vi.clearAllMocks();
});

function launch() {
  useBackgroundStore.getState().launch('run-1', 'worker', 'task', 'conversation-1');
}
const entry = () => useBackgroundStore.getState().executions.get('run-1')!;

describe('background cancellation owner acknowledgement', () => {
  it('passes owner conversation and waits for terminal after accepted request', async () => {
    launch();
    vi.mocked(subagentAPI.cancelExecution).mockResolvedValue({
      execution_id: 'run-1',
      cancelled: false,
      cancel_requested: true,
      message: 'accepted',
    });
    await useBackgroundStore.getState().kill('run-1', 'requested reason');
    expect(subagentAPI.cancelExecution).toHaveBeenCalledWith(
      'run-1',
      'conversation-1',
      'requested reason'
    );
    expect(entry().status).toBe('running');
    expect(entry().completedAt).toBeUndefined();
    expect(entry().cancellation?.status).toBe('pending');
    await useBackgroundStore.getState().kill('run-1');
    expect(subagentAPI.cancelExecution).toHaveBeenCalledTimes(1);
    useBackgroundStore.getState().cancel('run-1');
    expect(entry().status).toBe('cancelled');
    expect(entry().cancellation).toBeUndefined();
  });

  it('keeps running with a visible retryable request error', async () => {
    launch();
    vi.mocked(subagentAPI.cancelExecution).mockRejectedValue(new Error('delivery unavailable'));
    await useBackgroundStore.getState().kill('run-1');
    expect(entry().status).toBe('running');
    expect(entry().completedAt).toBeUndefined();
    expect(entry().cancellation).toEqual({ status: 'failed', error: 'delivery unavailable' });
  });

  it('does not override a completion that races with a rejected cancellation', async () => {
    launch();
    let reject!: (error: Error) => void;
    vi.mocked(subagentAPI.cancelExecution).mockReturnValue(
      new Promise((_, no) => {
        reject = no;
      })
    );
    const request = useBackgroundStore.getState().kill('run-1');
    useBackgroundStore.getState().complete('run-1', 'finished');
    reject(new Error('too late'));
    await request;
    expect(entry().status).toBe('completed');
    expect(entry().cancellation).toBeUndefined();
  });

  it('accepts only matching execution owner terminal receipt', async () => {
    launch();
    vi.mocked(subagentAPI.cancelExecution).mockResolvedValue({
      execution_id: 'other-run',
      cancelled: true,
      message: 'terminal',
    });
    await useBackgroundStore.getState().kill('run-1');
    expect(entry().status).toBe('running');
    expect(entry().cancellation?.status).toBe('failed');
  });
});

it('uses an already-cancelled matching owner receipt as terminal evidence', async () => {
  launch();
  vi.mocked(subagentAPI.cancelExecution).mockResolvedValue({
    execution_id: 'run-1',
    cancelled: true,
    message: 'already cancelled',
  });
  await useBackgroundStore.getState().kill('run-1');
  expect(entry().status).toBe('cancelled');
  expect(entry().cancellation).toBeUndefined();
});

it('does not send a cancellation for an old record without conversation ownership', async () => {
  launch();
  useBackgroundStore.setState({
    executions: new Map([['run-1', { ...entry(), conversationId: '' }]]),
  });
  await useBackgroundStore.getState().kill('run-1');
  expect(subagentAPI.cancelExecution).not.toHaveBeenCalled();
  expect(entry().status).toBe('running');
  expect(entry().cancellation?.status).toBe('failed');
});

it('ignores replayed launches without overwriting owner or terminal state', () => {
  launch();
  useBackgroundStore.getState().cancel('run-1');
  useBackgroundStore.getState().launch('run-1', 'worker', 'replay', 'other-conversation');
  expect(entry().conversationId).toBe('conversation-1');
  expect(entry().status).toBe('cancelled');
});

it('keeps a confirmed terminal state when delayed terminal events arrive', () => {
  launch();
  useBackgroundStore.getState().cancel('run-1');
  useBackgroundStore.getState().complete('run-1', 'delayed completion');
  useBackgroundStore.getState().fail('run-1', 'delayed failure');
  expect(entry().status).toBe('cancelled');
});
