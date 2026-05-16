import { describe, expect, it } from 'vitest';

import { parseDeployProgressSseEvent } from '../../../pages/tenant/deployProgressStream';

describe('parseDeployProgressSseEvent', () => {
  it('parses deploy progress SSE data lines', () => {
    expect(
      parseDeployProgressSseEvent(
        'data: {"type":"status","status":"in_progress","deploy_id":"deploy-1"}\n\n'
      )
    ).toEqual({
      type: 'status',
      status: 'in_progress',
      deploy_id: 'deploy-1',
    });
  });

  it('ignores keepalives and malformed data', () => {
    expect(parseDeployProgressSseEvent(': keepalive\n\n')).toBeNull();
    expect(parseDeployProgressSseEvent('data: not-json\n\n')).toBeNull();
    expect(parseDeployProgressSseEvent('data: {"status":"missing-type"}\n\n')).toBeNull();
  });
});
