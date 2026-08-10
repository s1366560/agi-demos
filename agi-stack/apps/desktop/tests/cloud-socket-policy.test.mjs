import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledModule = '/tmp/agistack-desktop-test-dist/electron/main/cloudSocketPolicy.js';

const trustedSession = Object.freeze({
  version: 1,
  api_base_url: 'https://cloud.memstack.test',
  runtime_mode: 'cloud',
  credential_kind: 'cloud_bearer',
  credential: 'vault-only-cloud-session-secret',
  expires_at: '2099-08-10T00:00:00Z',
});

const scope = Object.freeze({
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  workspace_id: 'workspace-1',
  conversation_id: 'conversation-1',
});

test('main policy binds agent sockets to the vault origin and observed workspace scope', async () => {
  const { authorizeVaultBoundCloudSocket } = require(compiledModule);
  const requests = [];
  const authorized = await authorizeVaultBoundCloudSocket(
    {
      kind: 'agent',
      url: 'wss://cloud.memstack.test/api/v1/agent/ws?session_id=desktop-session-1',
      scope,
    },
    dependencies(requests)
  );

  assert.equal(authorized.kind, 'agent');
  assert.equal(
    authorized.url,
    'wss://cloud.memstack.test/api/v1/agent/ws?session_id=desktop-session-1'
  );
  assert.deepEqual(authorized.protocols, ['memstack.auth', trustedSession.credential]);
  assert.deepEqual(authorized.scope, scope);
  assert.deepEqual(authorized.binary, {
    client_to_server: false,
    server_to_client: false,
  });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'https://cloud.memstack.test/api/v1/workspace-context');
  assert.equal(
    new Headers(requests[0].init.headers).get('Authorization'),
    `Bearer ${trustedSession.credential}`
  );
  assert.equal(requests[0].init.credentials, 'omit');
  assert.equal(requests[0].init.redirect, 'manual');
});

test('main policy supports exact terminal legacy, v2, and voice contracts without query drift', async () => {
  const { authorizeVaultBoundCloudSocket } = require(compiledModule);
  const legacyTerminal = await authorizeVaultBoundCloudSocket(
    {
      kind: 'terminal',
      url: 'wss://cloud.memstack.test/api/v1/projects/project-1/sandbox/terminal/proxy/ws?session_id=terminal-legacy-1',
      scope,
      terminal: {
        session_id: 'terminal-legacy-1',
        resume_token: null,
      },
    },
    dependencies()
  );
  assert.deepEqual(legacyTerminal.protocols, ['memstack.auth', trustedSession.credential]);

  const terminal = await authorizeVaultBoundCloudSocket(
    {
      kind: 'terminal',
      url: 'wss://cloud.memstack.test/api/v1/projects/project-1/sandbox/terminal/sessions/terminal-1/ws?after_sequence=7',
      scope,
      terminal: {
        session_id: 'terminal-1',
        resume_token: 'terminal-resume-token-1',
      },
    },
    dependencies()
  );
  assert.deepEqual(terminal.protocols, [
    'memstack.auth',
    trustedSession.credential,
    'memstack.terminal-v2',
    'terminal-resume-token-1',
  ]);
  assert.deepEqual(terminal.binary, {
    client_to_server: false,
    server_to_client: false,
  });

  const voice = await authorizeVaultBoundCloudSocket(
    {
      kind: 'voice',
      url: 'wss://cloud.memstack.test/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
      scope,
    },
    dependencies()
  );
  assert.deepEqual(voice.protocols, ['memstack.auth', trustedSession.credential]);
  assert.deepEqual(voice.binary, {
    client_to_server: true,
    server_to_client: true,
  });
});

test('main policy rejects origin, path, query, scope, and trusted-session drift', async () => {
  const { authorizeVaultBoundCloudSocket } = require(compiledModule);
  const base = {
    kind: 'voice',
    url: 'wss://cloud.memstack.test/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
    scope,
  };

  await assert.rejects(
    authorizeVaultBoundCloudSocket(
      {
        ...base,
        url: base.url.replace('cloud.memstack.test', 'attacker.test'),
      },
      dependencies()
    ),
    { message: 'cloud socket origin mismatch' }
  );
  await assert.rejects(
    authorizeVaultBoundCloudSocket(
      { ...base, url: `${base.url}&token=query-secret` },
      dependencies()
    ),
    { message: 'cloud voice socket URL is invalid' }
  );
  await assert.rejects(
    authorizeVaultBoundCloudSocket(
      {
        ...base,
        scope: { ...scope, conversation_id: 'conversation-2' },
      },
      dependencies()
    ),
    { message: 'cloud voice socket conversation scope mismatch' }
  );
  await assert.rejects(
    authorizeVaultBoundCloudSocket(
      base,
      dependencies([], {
        ...trustedSession,
        runtime_mode: 'local',
        credential_kind: 'local_session_reference',
      })
    ),
    { message: 'trusted cloud session is unavailable' }
  );
  await assert.rejects(
    authorizeVaultBoundCloudSocket(
      base,
      dependencies([], trustedSession, {
        tenant_id: 'tenant-2',
        project_id: 'project-1',
        workspace_id: 'workspace-1',
      })
    ),
    { message: 'cloud socket tenant scope mismatch' }
  );
});

test('frame policy enforces scope, binary direction, frame size, and secret reflection', async () => {
  const { assertCloudSocketFrame, authorizeVaultBoundCloudSocket } = require(compiledModule);
  const agent = await authorizeVaultBoundCloudSocket(
    {
      kind: 'agent',
      url: 'wss://cloud.memstack.test/api/v1/agent/ws?session_id=desktop-session-1',
      scope,
    },
    dependencies()
  );
  const validText = JSON.stringify({
    type: 'send_message',
    project_id: scope.project_id,
    conversation_id: scope.conversation_id,
    message: 'hello',
  });

  assert.doesNotThrow(() =>
    assertCloudSocketFrame(agent, 'client_to_server', textFrame(validText))
  );
  assert.throws(
    () =>
      assertCloudSocketFrame(
        agent,
        'client_to_server',
        textFrame(
          JSON.stringify({
            type: 'subscribe',
            conversation_id: 'conversation-2',
          })
        )
      ),
    { message: 'cloud socket conversation scope mismatch' }
  );
  const multiplexedAgent = await authorizeVaultBoundCloudSocket(
    {
      kind: 'agent',
      url: 'wss://cloud.memstack.test/api/v1/agent/ws?session_id=desktop-session-2',
      scope: { ...scope, conversation_id: null },
    },
    dependencies()
  );
  assert.doesNotThrow(() =>
    assertCloudSocketFrame(
      multiplexedAgent,
      'client_to_server',
      textFrame(JSON.stringify({ type: 'subscribe', conversation_id: 'conversation-2' }))
    )
  );
  assert.throws(
    () =>
      assertCloudSocketFrame(agent, 'client_to_server', {
        binary: true,
        byteLength: 4,
      }),
    { message: 'cloud socket binary frame is not allowed' }
  );
  assert.throws(
    () =>
      assertCloudSocketFrame(agent, 'server_to_client', {
        ...textFrame(JSON.stringify({ type: 'error', detail: trustedSession.credential })),
      }),
    { message: 'cloud socket frame contains protected credential' }
  );
  assert.throws(
    () =>
      assertCloudSocketFrame(agent, 'server_to_client', {
        binary: false,
        byteLength: agent.limits.max_frame_bytes + 1,
        text: '{}',
      }),
    { message: 'cloud socket frame is too large' }
  );
});

test('registry binds owners, limits connection counts and pending aggregate bytes', async () => {
  const { CloudSocketExecutionRegistry, authorizeVaultBoundCloudSocket } = require(compiledModule);
  const policy = await authorizeVaultBoundCloudSocket(
    {
      kind: 'agent',
      url: 'wss://cloud.memstack.test/api/v1/agent/ws?session_id=desktop-session-1',
      scope,
    },
    dependencies()
  );
  const smallPolicy = {
    ...policy,
    limits: {
      ...policy.limits,
      max_frame_bytes: 8,
      max_aggregate_bytes: 10,
    },
  };
  const scheduler = fakeScheduler();
  const closed = [];
  const registry = new CloudSocketExecutionRegistry({
    perOwnerLimit: 1,
    globalLimit: 2,
    scheduler,
  });
  const lease = registry.begin(7, 'cloud-socket-id-0001', smallPolicy, (event) => {
    closed.push(event);
  });
  assert.equal(lease.signal.aborted, false);
  assert.equal(registry.activeCount, 1);
  assert.equal(registry.markConnected(8, 'cloud-socket-id-0001'), false);
  assert.equal(registry.markConnected(7, 'cloud-socket-id-0001'), true);

  const first = registry.reserveFrame(
    7,
    'cloud-socket-id-0001',
    'server_to_client',
    textFrame('{}')
  );
  const second = registry.reserveFrame(
    7,
    'cloud-socket-id-0001',
    'server_to_client',
    textFrame('{"a":1}')
  );
  assert.equal(registry.pendingBytes(7, 'cloud-socket-id-0001'), 9);
  assert.throws(
    () => registry.reserveFrame(7, 'cloud-socket-id-0001', 'server_to_client', textFrame('{}')),
    { message: 'cloud socket aggregate is too large' }
  );
  assert.equal(lease.signal.aborted, true);
  assert.equal(closed.at(-1).code, 1009);
  first.release();
  second.release();

  const secondOwnerLease = registry.begin(8, 'cloud-socket-id-0002', smallPolicy, (event) =>
    closed.push(event)
  );
  assert.throws(() => registry.begin(8, 'cloud-socket-id-0003', smallPolicy, () => undefined), {
    message: 'cloud socket owner connection limit exceeded',
  });
  assert.equal(registry.close(7, 'cloud-socket-id-0002'), false);
  assert.equal(registry.cancelOwner(8), 1);
  assert.equal(secondOwnerLease.signal.aborted, true);
  assert.equal(registry.activeCount, 0);
});

test('registry enforces connect and idle timeouts and supports global cleanup', async () => {
  const { CloudSocketExecutionRegistry, authorizeVaultBoundCloudSocket } = require(compiledModule);
  const policy = await authorizeVaultBoundCloudSocket(
    {
      kind: 'voice',
      url: 'wss://cloud.memstack.test/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
      scope,
    },
    dependencies()
  );
  const timedPolicy = {
    ...policy,
    limits: {
      ...policy.limits,
      connect_timeout_ms: 11,
      idle_timeout_ms: 22,
    },
  };
  const scheduler = fakeScheduler();
  const closed = [];
  const registry = new CloudSocketExecutionRegistry({
    perOwnerLimit: 2,
    globalLimit: 2,
    scheduler,
  });
  const connecting = registry.begin(1, 'cloud-socket-id-0010', timedPolicy, (event) =>
    closed.push(event)
  );
  scheduler.fireDelay(11);
  assert.equal(connecting.signal.aborted, true);
  assert.equal(closed.at(-1).reason, 'cloud socket connect timed out');

  const open = registry.begin(1, 'cloud-socket-id-0011', timedPolicy, (event) =>
    closed.push(event)
  );
  assert.equal(registry.markConnected(1, 'cloud-socket-id-0011'), true);
  scheduler.fireDelay(22);
  assert.equal(open.signal.aborted, true);
  assert.equal(closed.at(-1).reason, 'cloud socket idle timed out');

  registry.begin(1, 'cloud-socket-id-0012', timedPolicy, (event) => closed.push(event));
  registry.begin(2, 'cloud-socket-id-0013', timedPolicy, (event) => closed.push(event));
  assert.throws(() => registry.begin(3, 'cloud-socket-id-0014', timedPolicy, () => undefined), {
    message: 'cloud socket global connection limit exceeded',
  });
  assert.equal(registry.cancelAll(), 2);
  assert.equal(registry.activeCount, 0);
});

function dependencies(requests = [], session = trustedSession, observedScope = scope) {
  return {
    async loadTrustedSession() {
      return session;
    },
    async fetch(url, init) {
      requests.push({ url, init });
      return new Response(
        JSON.stringify({
          context: {
            tenant_id: observedScope.tenant_id,
            project_id: observedScope.project_id,
            workspace_id: observedScope.workspace_id,
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    },
    now: () => Date.parse('2026-08-10T00:00:00Z'),
  };
}

function textFrame(text) {
  return {
    binary: false,
    byteLength: new TextEncoder().encode(text).byteLength,
    text,
  };
}

function fakeScheduler() {
  let sequence = 0;
  const tasks = new Map();
  return {
    setTimeout(callback, delay) {
      const id = ++sequence;
      tasks.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) {
      tasks.delete(id);
    },
    fireDelay(delay) {
      const matches = [...tasks.entries()].filter(([, task]) => task.delay === delay);
      for (const [id, task] of matches) {
        tasks.delete(id);
        task.callback();
      }
    },
  };
}
