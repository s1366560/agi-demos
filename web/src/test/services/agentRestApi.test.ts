import { beforeEach, describe, expect, it, vi } from 'vitest';

import { httpClient } from '../../services/client/httpClient';
import { restApi } from '../../services/agent/restApi';

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    patch: vi.fn(),
  },
}));

describe('agent restApi', () => {
  const mockHttpClient = httpClient as unknown as {
    get: ReturnType<typeof vi.fn>;
    patch: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses backend recovery cursor parameter names for execution status', async () => {
    mockHttpClient.get.mockResolvedValue({
      is_running: false,
      last_event_time_us: 456,
      last_event_counter: 7,
      current_message_id: null,
      conversation_id: 'conv-1',
      recovery: {
        can_recover: true,
        stream_exists: false,
        recovery_source: 'database',
        missed_events_count: 3,
      },
    });

    const result = await restApi.getExecutionStatus('conv-1', true, 123, 4);

    expect(mockHttpClient.get).toHaveBeenCalledWith(
      '/agent/conversations/conv-1/execution-status',
      {
        params: {
          include_recovery: true,
          from_time_us: 123,
          from_counter: 4,
        },
      }
    );
    expect(result.recovery?.can_recover).toBe(true);
  });

  it('updates conversation titles through the dedicated backend title route', async () => {
    mockHttpClient.patch.mockResolvedValue({ id: 'conv-1', title: 'Updated title' });

    await restApi.updateConversationTitle('conv-1', 'project-1', 'Updated title');

    expect(mockHttpClient.patch).toHaveBeenCalledWith(
      '/agent/conversations/conv-1/title',
      { title: 'Updated title' },
      { params: { project_id: 'project-1' } }
    );
  });
});
