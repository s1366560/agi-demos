import { describe, expect, it } from 'vitest';

import {
  activityEntryIsRead,
  buildReadReceipt,
  countUnreadProjectWork,
  reconcilePendingActivityReceipts,
} from '@/components/agent/activity/projectActivityModel';

const item = {
  id: 'workspace_attempt:1',
  authority_kind: 'workspace_attempt' as const,
  authority_id: 'attempt-1',
  conversation_id: 'conversation-1',
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  title: 'Run tests',
  group: 'running' as const,
  status: 'running' as const,
  required_action: 'observe' as const,
  revision: 3,
  created_at: '2026-08-04T00:00:00Z',
  updated_at: '2026-08-04T00:01:00Z',
};

describe('projectActivityModel', () => {
  it('uses authority revisions instead of timestamps or content guesses', () => {
    expect(
      activityEntryIsRead(item, {
        entry_id: item.id,
        entry_revision: 2,
        read_at: '2026-08-04T00:02:00Z',
      })
    ).toBe(false);
    expect(
      activityEntryIsRead(item, {
        entry_id: item.id,
        entry_revision: 3,
        read_at: '2026-08-04T00:00:01Z',
      })
    ).toBe(true);
  });

  it('builds an idempotent receipt from the work-item authority revision', () => {
    expect(buildReadReceipt(item, '2026-08-04T00:03:00Z')).toEqual({
      entry_id: item.id,
      entry_revision: 3,
      read_at: '2026-08-04T00:03:00Z',
    });
  });

  it('counts only items without a matching authoritative receipt', () => {
    expect(
      countUnreadProjectWork(
        [item, { ...item, id: 'hitl_request:2', revision: 1 }],
        [
          {
            entry_id: item.id,
            entry_revision: 3,
            read_at: '2026-08-04T00:02:00Z',
          },
        ]
      )
    ).toBe(1);
  });

  it('migrates only known scoped entry IDs at their current authority revision', () => {
    expect(
      reconcilePendingActivityReceipts([item], [
        {
          entry_id: item.id,
          entry_revision: 99,
          read_at: '2026-08-04T00:02:00Z',
        },
        {
          entry_id: 'agent_run:outside-scope',
          entry_revision: 1,
          read_at: '2026-08-04T00:03:00Z',
        },
      ])
    ).toEqual([
      {
        entry_id: item.id,
        entry_revision: 3,
        read_at: '2026-08-04T00:02:00Z',
      },
    ]);
  });
});
