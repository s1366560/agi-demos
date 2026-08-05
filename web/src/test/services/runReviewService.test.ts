import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
  },
}));

import { httpClient } from '@/services/client/httpClient';
import { runReviewService } from '@/services/runReviewService';

describe('runReviewService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads the authoritative run summary', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      run_id: 'run-1',
      revision: 9,
      status: 'completed',
      summary_state: 'recorded',
      reason_code: null,
      input_tokens: 100,
      output_tokens: 50,
      cost_usd: 0.02,
      completion_summary: 'Finished',
      files_changed: 2,
      lines_added: 8,
      lines_deleted: 3,
      artifact_count: 1,
      checks_passed: 4,
      checks_failed: 0,
      evidence_references: [],
    });

    const summary = await runReviewService.getSummary('run/1');

    expect(httpClient.get).toHaveBeenCalledWith('/agent/runs/run%2F1/summary');
    expect(summary).toEqual(
      expect.objectContaining({
        revision: 9,
        summary_state: 'recorded',
        completion_summary: 'Finished',
        input_tokens: 100,
        output_tokens: 50,
        files_changed: 2,
        lines_added: 8,
        lines_deleted: 3,
        checks_passed: 4,
        checks_failed: 0,
      })
    );
  });

  it('requests explicitly scoped changes with revision and turn attribution', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'snapshot-1',
      run_id: 'run-1',
      conversation_id: 'conversation-1',
      run_revision: 9,
      scope: 'turn',
      turn_id: 'turn-1',
      status: 'ready',
      additions: 3,
      deletions: 1,
      files_changed: 1,
      truncated: false,
      captured_at: '2026-08-04T00:00:00Z',
      files: [],
    });

    await runReviewService.getChanges('run-1', {
      scope: 'turn',
      turn_id: 'turn/1',
      expected_revision: 9,
    });

    expect(httpClient.get).toHaveBeenCalledWith('/agent/runs/run-1/changes', {
      params: {
        scope: 'turn',
        turn_id: 'turn/1',
        expected_revision: 9,
      },
    });
  });
});
