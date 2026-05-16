import { describe, expect, it } from 'vitest';

import { parseTaskSseEvent } from '../../services/taskStream';

describe('parseTaskSseEvent', () => {
  it('parses named SSE events with JSON data', () => {
    expect(parseTaskSseEvent('event: progress\ndata: {"id":"task-1","progress":50}\n\n')).toEqual({
      event: 'progress',
      data: '{"id":"task-1","progress":50}',
    });
  });

  it('ignores keepalive comments and preserves multiline data', () => {
    expect(parseTaskSseEvent(': keepalive\n\n')).toBeNull();
    expect(parseTaskSseEvent('event: progress\ndata: line-1\ndata: line-2\n\n')).toEqual({
      event: 'progress',
      data: 'line-1\nline-2',
    });
  });
});
