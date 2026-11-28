import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  authorizeDesktopLocalRun,
} = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const session = {
  version: 1,
  api_base_url: 'https://cloud.example',
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'test-vault-credential',
  expires_at: null,
};
const common = {
  user_id: 'user-1',
  tenant_id: 'tenant-1',
  device_id: 'device-1',
  conversation_id: 'conv-1',
  idempotency_key: 'local-key-1',
};
const start = {
  ...common,
  message: 'hello',
  local_root: '/tmp/local-demo',
  local_root_label: 'local-demo',
  execution_target: 'local',
};
const stop = { ...common, run_id: 'run-1', expected_revision: 2 };

function policy({ responses = {}, onRequest = () => {}, loadSession = () => session } = {}) {
  const defaults = {
    '/api/v1/workspace-context': {
      context: { tenant_id: 'tenant-1', project_id: 'project-1' },
    },
    '/api/v1/auth/me': { user_id: 'user-1' },
    '/api/v1/agent/conversations/conv-1': {
      id: 'conv-1',
      project_id: 'project-1',
      tenant_id: 'tenant-1',
    },
    '/api/v1/agent/runs/run-1/summary': {
      run_id: 'run-1',
      conversation_id: 'conv-1',
      project_id: 'project-1',
      tenant_id: 'tenant-1',
    },
  };
  return {
    loadTrustedSession: async () => loadSession(),
    fetch: async (url, init) => {
      const target = new URL(url);
      assert.equal(target.origin, session.api_base_url);
      onRequest(target, init);
      const body = responses[target.pathname] ?? defaults[target.pathname];
      assert.ok(body, 'expected a supported cloud observation');
      return Response.json(body);
    },
  };
}

test('only the current vault and the observed user, tenant and conversation authorize local runs', async () => {
  for (const [command, input] of [
    ['local_run_execute', start],
    ['local_run_stop', stop],
  ]) {
    const args = await authorizeDesktopLocalRun(command, input, policy());
    assert.equal(args.api_base_url, session.api_base_url);
    assert.equal(args.authorization, 'Bearer ' + session.credential);
    assert.equal(args.idempotency_key, common.idempotency_key);
    for (const extra of [
      { user_id: 'other' },
      { tenant_id: 'other' },
      { api_base_url: 'https://other.example' },
      { authorization: 'untrusted' },
      { origin: 'untrusted' },
    ]) {
      await assert.rejects(() =>
        authorizeDesktopLocalRun(command, { ...input, ...extra }, policy()),
      );
    }
  }
  for (const responses of [
    {
      '/api/v1/agent/conversations/conv-1': {
        id: 'conv-1',
        tenant_id: 'other',
        project_id: 'project-1',
      },
    },
    {
      '/api/v1/agent/runs/run-1/summary': {
        run_id: 'run-1',
        conversation_id: 'other',
        project_id: 'project-1',
        tenant_id: 'tenant-1',
      },
    },
  ]) {
    await assert.rejects(() =>
      authorizeDesktopLocalRun('local_run_stop', stop, policy({ responses })),
    );
  }
  for (const extra of [{ local_root: 'relative/work' }, { local_root_label: 'other-directory' }]) {
    await assert.rejects(() =>
      authorizeDesktopLocalRun('local_run_execute', { ...start, ...extra }, policy()),
    );
  }
  let loaded = 0;
  await assert.rejects(() =>
    authorizeDesktopLocalRun(
      'local_run_execute',
      start,
      policy({
        loadSession: () =>
          ++loaded === 1 ? session : { ...session, credential: 'different-account' },
      }),
    ),
  );
  await assert.rejects(() =>
    authorizeDesktopLocalRun('local_run_stop', { ...stop, run_id: '../invalid' }, policy()),
  );
});

test('a rotated token is used for every accepted observation and actual sidecar admission', async () => {
  let stored = session;
  const observed = [];
  const state = policy({
    loadSession: () => stored,
    onRequest: (url, init) => {
      observed.push([url.pathname, new Headers(init.headers).get('authorization')]);
    },
  });
  const observe = state.fetch;
  state.fetch = async (url, init) => {
    if (url.endsWith('/auth/me') && stored === session) return Response.json({}, { status: 401 });
    return observe(url, init);
  };
  state.refreshTrustedSession = async () => {
    stored = { ...session, credential: 'rotated-test-credential' };
    return { status: 'refreshed', record: stored };
  };
  const args = await authorizeDesktopLocalRun('local_run_execute', start, state);
  assert.equal(args.authorization, 'Bearer ' + stored.credential);
  for (const path of [
    '/api/v1/auth/me',
    '/api/v1/workspace-context',
    '/api/v1/agent/conversations/conv-1',
  ]) {
    assert.ok(observed.some(([url, bearer]) => url === path && bearer === args.authorization));
  }
});

test('local-run admission rejects a refresh that moves to another cloud origin', async () => {
  const observed = [];
  const state = policy();
  state.fetch = async (url, init) => {
    observed.push([new URL(url).origin, new Headers(init.headers).get('authorization')]);
    return Response.json({}, { status: 401 });
  };
  state.refreshTrustedSession = async () => ({
    status: 'refreshed',
    record: {
      ...session,
      api_base_url: 'https://other.example',
      credential: 'other-origin',
    },
  });
  await assert.rejects(
    () => authorizeDesktopLocalRun('local_run_execute', start, state),
    /origin changed/,
  );
  assert.deepEqual(observed, [[session.api_base_url, 'Bearer ' + session.credential]]);
});
