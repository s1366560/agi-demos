import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { httpClient } from '@/services/client/httpClient';
import { runInputService } from '@/services/runInputService';

describe('runInputService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads the authoritative active run for a conversation', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'conversation-1',
      active_run: {
        id: 'run-1',
        turn_id: 'message-7',
        conversation_id: 'conversation-1',
        revision: 7,
        status: 'running',
        allowed_actions: ['steer_now', 'queue_next'],
        authority_revision: 3,
      },
      availability: 'available',
      reason_code: null,
      authority_revision: 3,
    });

    const result = await runInputService.getActiveRun('conversation/1');

    expect(httpClient.get).toHaveBeenCalledWith(
      '/agent/conversations/conversation%2F1/active-run'
    );
    expect(result?.run_id).toBe('run-1');
    expect(result?.turn_id).toBe('message-7');
  });

  it('normalizes the latest run for reload-safe review', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      conversation_id: 'conversation-1',
      latest_run: {
        id: 'run-9',
        turn_id: 'message-12',
        conversation_id: 'conversation-1',
        revision: 12,
        status: 'completed',
        allowed_actions: [],
        authority_revision: 12,
      },
      availability: 'available',
      reason_code: null,
      authority_revision: 12,
    });

    const result = await runInputService.getLatestRun('conversation-1');

    expect(httpClient.get).toHaveBeenCalledWith(
      '/agent/conversations/conversation-1/latest-run'
    );
    expect(result?.status).toBe('completed');
    expect(result?.turn_id).toBe('message-12');
  });

  it('creates a run input with the canonical contract', async () => {
    (httpClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      accepted: true,
      created: true,
      action: 'send_message',
      conversation_id: 'conversation-1',
      message_id: 'message-1',
      delivery_mode: 'steer_now',
      run_id: 'run-1',
      run_revision: 7,
      input: {
        id: 'input-1',
        conversation_id: 'conversation-1',
        run_id: 'run-1',
        expected_run_revision: 7,
        message_id: 'message-1',
        idempotency_key: 'idempotency-1',
        delivery: 'steer_now',
        status: 'pending_boundary',
        sequence: 1,
        content: 'Use the new constraint',
        references: [],
        context_items: [],
        created_at: '2026-08-04T00:00:00Z',
        updated_at: '2026-08-04T00:00:00Z',
      },
    });

    const receipt = await runInputService.create('run/1', {
      expected_run_revision: 7,
      message: 'Use the new constraint',
      message_id: 'message-1',
      idempotency_key: 'idempotency-1',
      delivery: 'steer_now',
      references: [],
      context_items: [],
    });

    expect(httpClient.post).toHaveBeenCalledWith('/agent/runs/run%2F1/inputs', {
      expected_run_revision: 7,
      message: 'Use the new constraint',
      message_id: 'message-1',
      idempotency_key: 'idempotency-1',
      delivery: 'steer_now',
      references: [],
      context_items: [],
    });
    expect(receipt.input.status).toBe('pending_boundary');
  });

  it('lists and promotes inputs through nested canonical routes', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_id: 'run-1',
      run_revision: 8,
      inputs: [],
      total_count: 0,
    });
    (httpClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      accepted: true,
      created: true,
      action: 'start_plan_turn',
    });

    await runInputService.list('run-1');
    await runInputService.promote('run-1', 'input/1', {
      expected_source_run_revision: 8,
      idempotency_key: 'promote-1',
    });

    expect(httpClient.get).toHaveBeenCalledWith('/agent/runs/run-1/inputs');
    expect(httpClient.post).toHaveBeenCalledWith(
      '/agent/runs/run-1/inputs/input%2F1/promote',
      {
        expected_source_run_revision: 8,
        idempotency_key: 'promote-1',
      }
    );
  });
});
