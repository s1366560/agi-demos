import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(),
    put: vi.fn(),
  },
}));

import { httpClient } from '@/services/client/httpClient';
import { projectWorkService } from '@/services/projectWorkService';

describe('projectWorkService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads the authoritative project My Work projection', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      items: [
        {
          id: 'agent_run:run-1',
          authority_kind: 'agent_run',
          authority_id: 'run-1',
          run_id: 'run-1',
          conversation_id: 'conversation-1',
          workspace_id: 'workspace-1',
          project_id: 'project-1',
          title: 'Run 1',
          group: 'ready_review',
          status: 'ready_review',
          required_action: 'review_approval',
          revision: 2,
          created_at: '2026-08-04T00:00:00Z',
          updated_at: '2026-08-04T00:01:00Z',
          run_summary: {
            run_id: 'run-1',
            tenant_id: 'tenant-1',
            project_id: 'project-1',
            conversation_id: 'conversation-1',
            status: 'ready_review',
            revision: 2,
            summary_state: 'recorded',
            reason_code: null,
            model_breakdown: [],
            completion_summary: 'Finished',
            evidence_references: [],
          },
        },
      ],
      total: 1,
    });

    const response = await projectWorkService.list('project/1');

    expect(httpClient.get).toHaveBeenCalledWith('/projects/project%2F1/my-work');
    expect(response.items[0]).toEqual(
      expect.objectContaining({
        authority_kind: 'agent_run',
        status: 'ready_review',
        run_summary: expect.objectContaining({ completion_summary: 'Finished' }),
      })
    );
  });

  it('loads and updates activity read receipts', async () => {
    (httpClient.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      authority_revision: 1,
      entries: [],
    });
    (httpClient.put as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: 'project-1',
      authority_revision: 2,
      entries: [
        {
          entry_id: 'workspace_attempt:1',
          entry_revision: 3,
          read_at: '2026-08-04T00:00:00Z',
        },
      ],
    });

    await projectWorkService.getReadState('project-1');
    await projectWorkService.updateReadState('project-1', {
      expected_authority_revision: 1,
      entries: [
        {
          entry_id: 'workspace_attempt:1',
          entry_revision: 3,
          read_at: '2026-08-04T00:00:00Z',
        },
      ],
    });

    expect(httpClient.get).toHaveBeenCalledWith('/projects/project-1/activity/read-state');
    expect(httpClient.put).toHaveBeenCalledWith('/projects/project-1/activity/read-state', {
      expected_authority_revision: 1,
      entries: [
        {
          entry_id: 'workspace_attempt:1',
          entry_revision: 3,
          read_at: '2026-08-04T00:00:00Z',
        },
      ],
    });
  });
});
