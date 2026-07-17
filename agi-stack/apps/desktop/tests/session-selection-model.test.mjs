import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { sessionSelectionRequiresRuntimeRefresh, sessionTimelineRequestIsCurrent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/session/sessionSelectionModel.js'
);

const current = {
  mode: 'local',
  apiBaseUrl: 'http://127.0.0.1:45123',
  apiKey: 'local-session',
  localApiToken: 'local-runtime',
  tenantId: 'northstar',
  projectId: 'desktop-client',
  workspaceId: 'desktop-client-main',
  workspaceRoot: '/workspace',
};

test('same-workspace session selection preserves workspace authority and live transport', () => {
  assert.equal(sessionSelectionRequiresRuntimeRefresh(current, { ...current }), false);
});

test('cross-workspace session selection refreshes the exact workspace authority', () => {
  assert.equal(
    sessionSelectionRequiresRuntimeRefresh(current, {
      ...current,
      workspaceId: 'release-reliability',
    }),
    true,
  );
});

test('runtime transport or tenant changes cannot reuse the previous session authority', () => {
  assert.equal(
    sessionSelectionRequiresRuntimeRefresh(current, {
      ...current,
      apiBaseUrl: 'https://api.memstack.example',
    }),
    true,
  );
  assert.equal(
    sessionSelectionRequiresRuntimeRefresh(current, {
      ...current,
      tenantId: 'orbital',
    }),
    true,
  );
});

test('timeline response remains current only within the same request generation and scope epoch', () => {
  const expected = { requestId: 8, scopeEpoch: 3 };

  assert.equal(sessionTimelineRequestIsCurrent(expected, { ...expected }), true);
  assert.equal(
    sessionTimelineRequestIsCurrent(expected, { requestId: 9, scopeEpoch: 3 }),
    false,
  );
  assert.equal(
    sessionTimelineRequestIsCurrent(expected, { requestId: 8, scopeEpoch: 4 }),
    false,
  );
});

test('a deferred timeline response fails closed after a tenant or workspace scope switch', () => {
  const deferredRequest = { requestId: 12, scopeEpoch: 5 };
  const switchedScope = { requestId: 12, scopeEpoch: 6 };

  assert.equal(sessionTimelineRequestIsCurrent(deferredRequest, switchedScope), false);
});
