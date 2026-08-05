import { describe, expect, it } from 'vitest';

import { latestSubagentRunRevision } from '@/components/agent/timeline/subagentControlModel';

describe('latestSubagentRunRevision', () => {
  it('reads only structured revision fields from the latest lifecycle event', () => {
    const events = [
      { data: { run_revision: 2 } },
      { metadata: { authority_revision: 4 } },
    ];

    expect(latestSubagentRunRevision(events)).toBe(4);
  });

  it('supports persisted camel-case authority metadata', () => {
    expect(latestSubagentRunRevision([{ metadata: { runRevision: 7 } }])).toBe(7);
  });

  it('does not infer a revision from message text or timestamps', () => {
    expect(
      latestSubagentRunRevision([
        {
          content: 'run revision 99',
          timestamp: '2026-08-04T00:00:00Z',
          data: {},
        },
      ])
    ).toBeNull();
  });

  it('rejects missing, fractional, and non-positive revisions', () => {
    expect(
      latestSubagentRunRevision([
        { metadata: { run_revision: 0 } },
        { metadata: { authority_revision: 1.5 } },
      ])
    ).toBeNull();
  });
});
