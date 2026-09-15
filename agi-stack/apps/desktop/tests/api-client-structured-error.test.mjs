import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const { DesktopApiClient, DesktopApiError } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

for (const transport of ['vault', 'fetch']) {
  test(`${transport} task-session errors preserve readable structured details`, async () => {
    const oldWindow = globalThis.window;
    const oldFetch = globalThis.fetch;
    let body;
    let requests = 0;
    globalThis.window = transport === 'vault' ? {
      __MEMSTACK_DESKTOP__: { core: { invoke: async () => { requests++; return { status: 503, body }; } } },
    } : {};
    globalThis.fetch = async () => { requests++; return new Response(JSON.stringify(body), { status: 503, headers: { 'content-type': 'application/json' } }); };
    try {
      const client = new DesktopApiClient({ ...DEFAULT_CONFIG, mode: 'cloud', apiKey: transport === 'fetch' ? 'test-session' : '', tenantId: 'tenant', projectId: 'project' });
      for (const [detail, message] of [
        [{ code: 'WORKSPACE_CORE_UNAVAILABLE', reason: 'workspace_core_unavailable', detail: 'Workspace Core is unavailable' }, 'Workspace Core is unavailable'],
        [{ code: 'TASK_SESSION_SAGA_RETRYABLE', reason: 'task_session_platform_commit_failed' }, 'TASK_SESSION_SAGA_RETRYABLE'],
        [{ message: 'Select a valid model', code: 'INVALID_MODEL' }, 'Select a valid model'],
        ['Plain server error', 'Plain server error'],
        [{ unrecognized: { value: 'do not stringify arbitrary data' } }, 'HTTP 503'],
      ]) {
        body = { detail };
        const before = requests;
        await assert.rejects(client.createTaskSession({}), (error) => {
          assert.ok(error instanceof DesktopApiError);
          assert.equal(error.message, message);
          assert.equal(error.status, 503);
          assert.deepEqual(error.payload, body);
          return true;
        });
        assert.equal(requests, before + 1, 'structured HTTP failure must not retry creation');
      }
    } finally {
      globalThis.fetch = oldFetch;
      if (oldWindow === undefined) delete globalThis.window;
      else globalThis.window = oldWindow;
    }
  });
}
