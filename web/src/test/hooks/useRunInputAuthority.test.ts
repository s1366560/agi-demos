import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/runInputService', () => ({
  runInputService: {
    getActiveRun: vi.fn(),
    getLatestRun: vi.fn(),
    create: vi.fn(),
    list: vi.fn(),
    promote: vi.fn(),
  },
}));

import { useRunInputAuthority } from '@/hooks/useRunInputAuthority';
import { runInputService } from '@/services/runInputService';

describe('useRunInputAuthority', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (runInputService.list as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_id: 'run-1',
      run_revision: 4,
      inputs: [],
      total_count: 0,
    });
  });

  it('loads latest-run review authority before streaming and active-run authority while streaming', async () => {
    (runInputService.getLatestRun as ReturnType<typeof vi.fn>).mockResolvedValue(null);
    (runInputService.getActiveRun as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      run_revision: 4,
      status: 'running',
      allowed_actions: ['steer_now', 'queue_next'],
      authority_revision: 2,
    });

    const { result, rerender } = renderHook(
      ({ streaming }) => useRunInputAuthority('conversation-1', streaming),
      { initialProps: { streaming: false } }
    );

    await waitFor(() => {
      expect(runInputService.getLatestRun).toHaveBeenCalledWith('conversation-1');
    });
    expect(result.current.activeRun).toBeNull();

    rerender({ streaming: true });

    await waitFor(() => {
      expect(result.current.activeRun?.run_id).toBe('run-1');
    });
    expect(runInputService.getActiveRun).toHaveBeenCalledWith('conversation-1');
  });

  it('retains the draft when the authoritative request is rejected', async () => {
    (runInputService.getActiveRun as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      run_revision: 4,
      status: 'running',
      allowed_actions: ['queue_next'],
      authority_revision: 2,
    });
    (runInputService.create as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('revision conflict')
    );

    const { result } = renderHook(() => useRunInputAuthority('conversation-1', true));
    await waitFor(() => {
      expect(result.current.activeRun).not.toBeNull();
    });

    let accepted = true;
    await act(async () => {
      accepted = await result.current.submit('Keep this draft', 'queue_next');
    });

    expect(accepted).toBe(false);
    expect(result.current.error).toBe('revision conflict');
  });

  it('reuses command identity when an identical failed submission is retried', async () => {
    (runInputService.getActiveRun as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      turn_id: 'message-4',
      run_revision: 4,
      status: 'running',
      allowed_actions: ['steer_now'],
      authority_revision: 2,
    });
    (runInputService.create as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('control dispatch unavailable')
    );

    const { result } = renderHook(() => useRunInputAuthority('conversation-1', true));
    await waitFor(() => {
      expect(result.current.activeRun).not.toBeNull();
    });

    await act(async () => {
      await result.current.submit('Keep this identity', 'steer_now');
      await result.current.submit('Keep this identity', 'steer_now');
    });

    const [first, second] = (runInputService.create as ReturnType<typeof vi.fn>).mock.calls;
    expect(second?.[1].message_id).toBe(first?.[1].message_id);
    expect(second?.[1].idempotency_key).toBe(first?.[1].idempotency_key);
  });

  it('submits a revisioned, idempotent input and exposes its receipt', async () => {
    (runInputService.getActiveRun as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      run_revision: 4,
      status: 'running',
      allowed_actions: ['steer_now'],
      authority_revision: 2,
    });
    (runInputService.create as ReturnType<typeof vi.fn>).mockResolvedValue({
      accepted: true,
      created: true,
      action: 'send_message',
      conversation_id: 'conversation-1',
      message_id: 'message-1',
      delivery_mode: 'steer_now',
      run_id: 'run-1',
      run_revision: 4,
      input: { id: 'input-1', status: 'pending_boundary' },
    });

    const { result } = renderHook(() => useRunInputAuthority('conversation-1', true));
    await waitFor(() => {
      expect(result.current.activeRun).not.toBeNull();
    });

    await act(async () => {
      await result.current.submit('Change direction', 'steer_now', {
        contextItems: [
          {
            kind: 'skill',
            resource_id: 'focused-tests',
            label: 'Focused tests',
          },
        ],
      });
    });

    expect(runInputService.create).toHaveBeenCalledWith(
      'run-1',
      expect.objectContaining({
        expected_run_revision: 4,
        message: 'Change direction',
        delivery: 'steer_now',
        context_items: [
          {
            kind: 'skill',
            resource_id: 'focused-tests',
            label: 'Focused tests',
          },
        ],
      })
    );
    expect(result.current.lastReceipt?.input.id).toBe('input-1');
  });

  it('lists ready queued inputs and promotes only after an explicit command', async () => {
    (runInputService.getLatestRun as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'conversation-1',
      run_id: 'run-1',
      run_revision: 5,
      status: 'ready_review',
      allowed_actions: [],
      authority_revision: 5,
    });
    (runInputService.list as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_id: 'run-1',
      run_revision: 5,
      inputs: [{ id: 'input-ready', status: 'ready', content: 'Plan this next' }],
      total_count: 1,
    });
    (runInputService.promote as ReturnType<typeof vi.fn>).mockResolvedValue({
      accepted: true,
      created: true,
      action: 'start_plan_turn',
    });

    const { result } = renderHook(() => useRunInputAuthority('conversation-1', false));
    await waitFor(() => {
      expect(result.current.inputs[0]?.status).toBe('ready');
    });
    expect(runInputService.promote).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.promote('input-ready');
    });

    expect(runInputService.promote).toHaveBeenCalledWith('run-1', 'input-ready', {
      expected_source_run_revision: 5,
      idempotency_key: expect.stringMatching(/^run-input-promote-/),
    });
  });
});
