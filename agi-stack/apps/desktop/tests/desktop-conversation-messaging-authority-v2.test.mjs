import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const runtime = require('@agistack/plugin-runtime');
const {
  createDesktopConversationMessagingOperationsV2: createOperations,
  applyDesktopConversationMessagingAuthorityV2: apply,
  desktopConversationMessagingAuthorityDefinitionV2: definition,
  assertLocalMessagingExecutionV2,
} = require(`${ROOT}/src/plugins/desktopConversationMessagingAuthorityModuleV2.js`);
const { acquireDesktopRendererServiceOperationLeaseV2: admit } = require(
  `${ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const config = () => ({
  mode: 'local',
  apiBaseUrl: 'http://localhost:9000',
  apiKey: '',
  localApiToken: 'test-fixture-token',
  deviceAuthorizationBaseUrl: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  workspaceRoot: '',
});
const conversation = (workspace_id = null) => ({
  id: 'conversation-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  user_id: 'user-1',
  workspace_id,
  title: 'title',
  status: 'active',
  message_count: 0,
  created_at: '2026-09-05T00:00:00Z',
});
const message = () => ({ id: 'message-1', workspace_id: 'workspace-1', content: 'hello' });
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function fixture() {
  let service;
  apply(
    {
      provide: (_key, value) => {
        service = value;
      },
    },
    { strategy: 'parent-bound-messaging' },
  );
  const state = {
    roots: 0,
    children: 0,
    releases: 0,
    childReleases: 0,
    calls: [],
    boundConfigs: [],
  };
  const creation = {
    createAgentConversation: async (...args) => {
      state.calls.push(['create', args]);
      return conversation();
    },
    createTaskSession: async () => ({}),
    bindConversationWorkspace: async (...args) => {
      state.calls.push(['bind', args]);
      return conversation('workspace-1');
    },
    runAgentMessage: async (...args) => {
      state.calls.push(['run', args]);
      return { queued: true, created: true, replayed: false, message_id: 'message-1' };
    },
  };
  const taskFlow = Object.fromEntries(
    [
      'approvePlanAndStart',
      'createTaskSession',
      'getConversationMessages',
      'listAgentPlanTasks',
      'listWorkspaces',
      'supportsAgentPlanWorkflow',
      'switchPlanMode',
    ].map((name) => [name, async () => ({})]),
  );
  taskFlow.sendMessage = async (...args) => {
    state.calls.push(['send', args]);
    return message();
  };
  const parent = {
    status: 'accepted',
    digest: 'sha256:fixture',
    acquireChildServiceLease: async (request) => {
      state.children++;
      state.lastChildRequest = request;
      return {
        status: 'accepted',
        digest: 'sha256:fixture',
        useService: (callback) =>
          callback({
            bindOperation: (boundConfig) => {
              state.boundConfig = boundConfig;
              state.boundConfigs.push(boundConfig);
              return request.service.includes('new-thread-creation') ? creation : taskFlow;
            },
          }),
        release: async () => {
          state.childReleases++;
        },
      };
    },
    useService: (callback) => callback(service),
    release: async () => {
      state.releases++;
    },
  };
  const actions = {
    acquireOperationLease() {
      throw new Error('forbidden root fallback');
    },
    acquireServiceOperationLease: async (request) => {
      state.roots++;
      state.request = request;
      return parent;
    },
  };
  return {
    state,
    parent,
    actions,
    service,
    creation,
    taskFlow,
    ops: createOperations(() => actions),
  };
}

test('messaging four facets share frozen parent scope and forward the same cancellation signal', async () => {
  const f = fixture();
  const controller = new AbortController();
  const inputConfig = config();
  const result = await f.ops.withOperation(
    { config: inputConfig, signal: controller.signal },
    async (client) => {
      inputConfig.projectId = 'changed';
      await client.sendMessage('hello');
      const created = await client.createAgentConversation('title', 'project-1', 'user-1');
      const bound = await client.bindConversationWorkspace(created);
      client.assertActive();
      return client.runAgentMessage(bound, 'hello', 'message-1', {
        permissionPreset: 'default',
        mentions: [],
      });
    },
  );
  assert.deepEqual(result, {
    queued: true,
    created: true,
    replayed: false,
    message_id: 'message-1',
  });
  assert.equal(f.state.roots, 1);
  assert.equal(f.state.children, 4);
  assert.deepEqual(
    f.state.boundConfigs.map((value) => value.workspaceId),
    ['workspace-1', '', 'workspace-1', 'workspace-1'],
  );
  assert.equal(f.state.releases, 1);
  assert.equal(f.state.childReleases, 4);
  assert.equal(f.state.boundConfig.projectId, 'project-1');
  assert.ok(Object.isFrozen(f.state.boundConfig));
  assert.deepEqual(f.state.request.scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
  });
  for (const [name, args] of f.state.calls) {
    assert.equal(args[{ send: 4, create: 5, bind: 1, run: 6 }[name]], controller.signal);
  }
});

test('messaging rejects missing fork before callback and releases admission', async () => {
  const f = fixture();
  delete f.parent.acquireChildServiceLease;
  await assert.rejects(
    f.ops.withOperation({ config: config(), signal: new AbortController().signal }, () =>
      assert.fail('callback forbidden'),
    ),
    (error) => error.code === 'desktop_conversation_messaging_parent_lease_required',
  );
  assert.equal(f.state.children, 0);
  assert.equal(f.state.releases, 1);
});

test('messaging abort during delayed admission releases without binding or mutation', async () => {
  const f = fixture();
  const gate = deferred();
  const controller = new AbortController();
  f.actions.acquireServiceOperationLease = async () => {
    await gate.promise;
    return f.parent;
  };
  const pending = f.ops.withOperation({ config: config(), signal: controller.signal }, () =>
    assert.fail('callback forbidden'),
  );
  controller.abort();
  gate.resolve();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(f.state.releases, 1);
  assert.equal(f.state.calls.length, 0);
});

test('messaging abort after child mutation suppresses late result and further work', async () => {
  const f = fixture();
  const gate = deferred();
  const entered = deferred();
  const controller = new AbortController();
  f.taskFlow.sendMessage = async () => {
    entered.resolve();
    await gate.promise;
    return message();
  };
  let escaped;
  const pending = f.ops.withOperation(
    { config: config(), signal: controller.signal },
    async (client) => {
      escaped = client;
      return client.sendMessage('hello');
    },
  );
  await entered.promise;
  controller.abort();
  gate.resolve();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.throws(() => escaped.assertActive());
  assert.equal(f.state.releases, 1);
  assert.equal(f.state.childReleases, 1);
});

test('messaging drains unawaited children before parent release and revokes escaped client', async () => {
  const f = fixture();
  const gate = deferred();
  const entered = deferred();
  let escaped;
  f.taskFlow.sendMessage = async () => {
    entered.resolve();
    await gate.promise;
    return message();
  };
  const pending = f.ops.withOperation(
    { config: config(), signal: new AbortController().signal },
    (client) => {
      escaped = client;
      void client.sendMessage('hello');
      return 'done';
    },
  );
  await entered.promise;
  await Promise.resolve();
  assert.equal(f.state.releases, 0);
  assert.throws(
    () => escaped.sendMessage('second'),
    (error) => error.code === 'desktop_conversation_messaging_operation_released',
  );
  gate.resolve();
  assert.equal(await pending, 'done');
  assert.equal(f.state.releases, 1);
});

test('messaging admission callback is consumed once', async () => {
  const f = fixture();
  let saved;
  f.parent.useService = async (callback) => {
    saved = callback;
    const first = callback(f.service);
    await assert.rejects(
      callback(f.service),
      (error) => error.code === 'desktop_conversation_messaging_operation_released',
    );
    return first;
  };
  let calls = 0;
  await f.ops.withOperation({ config: config(), signal: new AbortController().signal }, () => {
    calls++;
  });
  await assert.rejects(saved(f.service));
  assert.equal(calls, 1);
});

test('messaging preserves primary mutation error when parent release also fails', async () => {
  const f = fixture();
  const primary = new Error('primary');
  f.taskFlow.sendMessage = async () => {
    throw primary;
  };
  f.parent.release = async () => {
    throw new Error('secondary');
  };
  await assert.rejects(
    f.ops.withOperation({ config: config(), signal: new AbortController().signal }, (client) =>
      client.sendMessage('hello'),
    ),
    (error) => error === primary,
  );
});

test('messaging binding rejects request and response identity drift before dispatch continues', async () => {
  const f = fixture();
  await f.ops.withOperation(
    { config: config(), signal: new AbortController().signal },
    async (client) => {
      assert.throws(() =>
        client.bindConversationWorkspace({ ...conversation(), project_id: 'other' }),
      );
    },
  );
  assert.equal(f.state.children, 0);
  f.creation.bindConversationWorkspace = async () => ({
    ...conversation('workspace-1'),
    id: 'other',
  });
  await assert.rejects(
    f.ops.withOperation({ config: config(), signal: new AbortController().signal }, (client) =>
      client.bindConversationWorkspace(conversation()),
    ),
    (error) => error.code === 'desktop_conversation_workspace_binding_response_invalid',
  );
});

test('Local default retains Plan semantics while unsupported explicit permission and context fail', () => {
  assert.doesNotThrow(() =>
    assertLocalMessagingExecutionV2(config(), {
      permissionPreset: 'default',
      message: 'hello',
      mentions: [],
    }),
  );
  for (const execution of [{ permissionPreset: 'relaxed' }, { permissionPreset: 'full' }]) {
    assert.throws(
      () => assertLocalMessagingExecutionV2(config(), execution),
      (error) => error.code === 'local_conversation_message_permission_unsupported',
    );
  }
  for (const execution of [
    { mentions: ['agent'] },
    { fileMetadata: [{}] },
    { appModelContext: {} },
  ]) {
    assert.throws(
      () => assertLocalMessagingExecutionV2(config(), execution),
      (error) => error.code === 'local_conversation_message_context_unsupported',
    );
  }
});

function definitions() {
  return [
    ...runtime.createDesktopRendererDefinitionsV2(),
    ...readdirSync(`${ROOT}/src/plugins`)
      .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
      .flatMap((name) =>
        Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
          (value) => value?.moduleRef && typeof value.apply === 'function',
        ),
      ),
  ];
}
function profile() {
  return JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
}

test('real Loader messaging uses original generation across HMR and disabled outer sends zero HTTP', async () => {
  const manager = new runtime.GenerationManagerV2();
  const originalFetch = globalThis.fetch;
  const wires = [];
  globalThis.fetch = async (url, init) => {
    wires.push([String(url), init]);
    const path = new URL(url).pathname;
    const body = path.endsWith('/mode')
      ? conversation('workspace-1')
      : path.endsWith('/conversations')
        ? conversation()
        : path.includes('/agent/conversations/')
          ? { queued: true, created: true, replayed: false, message_id: 'message-1' }
          : message();
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
  try {
    const loader = new runtime.LoaderV2(definitions(), 'desktop-renderer');
    const initial = profile();
    const old = await loader.stage(initial);
    await manager.publish(old);
    const ops = createOperations(() => ({
      acquireOperationLease() {
        throw new Error('fallback');
      },
      acquireServiceOperationLease: (request) =>
        admit(manager.current, request, (g) => manager.acquire(g)),
    }));
    const signal = new AbortController().signal;
    await ops.withOperation({ config: config(), signal }, async (client) => {
      await client.sendMessage('hello');
      const created = await client.createAgentConversation('title', 'project-1', 'user-1');
      const next = profile();
      next.entries.find((item) => item.module_ref === definition.moduleRef).enabled = false;
      await manager.publish(await loader.stage(next));
      assert.equal(old.disposed, false);
      const bound = await client.bindConversationWorkspace(created);
      await client.runAgentMessage(bound, 'hello', 'message-1');
    });
    assert.equal(wires.length, 4);
    assert.equal(old.disposed, true);
    for (const [, init] of wires) assert.equal(init.signal, signal);
    const bindBody = JSON.parse(wires[2][1].body);
    assert.deepEqual(bindBody, { workspace_id: 'workspace-1' });
    wires.length = 0;
    await assert.rejects(
      ops.withOperation({ config: config(), signal }, () => assert.fail('disabled callback')),
    );
    assert.equal(wires.length, 0);
    assert.equal(manager.current.leaseCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
    await manager.close();
  }
});

test('handled launch failure after saved message preserves the callback partial-success result', async () => {
  const f = fixture();
  const launchFailure = new Error('launch failed');
  f.creation.runAgentMessage = async () => {
    throw launchFailure;
  };
  const result = await f.ops.withOperation(
    { config: config(), signal: new AbortController().signal },
    async (client) => {
      const saved = await client.sendMessage('hello');
      try {
        await client.runAgentMessage(conversation('workspace-1'), 'hello', saved.id);
      } catch (error) {
        assert.equal(error, launchFailure);
        return { saved, launchFailed: true };
      }
      assert.fail('expected launch failure');
    },
  );
  assert.equal(result.launchFailed, true);
  assert.equal(f.state.releases, 1);
});

test('unawaited child failure during drain remains primary over parent release failure', async () => {
  const f = fixture();
  const gate = deferred();
  const entered = deferred();
  const primary = new Error('unawaited child');
  f.taskFlow.sendMessage = async () => {
    entered.resolve();
    await gate.promise;
    throw primary;
  };
  f.parent.release = async () => {
    throw new Error('release failed');
  };
  const pending = f.ops.withOperation(
    { config: config(), signal: new AbortController().signal },
    (client) => {
      void client.sendMessage('hello');
    },
  );
  await entered.promise;
  await Promise.resolve();
  gate.resolve();
  await assert.rejects(pending, (error) => error === primary);
});

test('Local run receipt requires exact message identity and accepts genuine idempotent replay', async () => {
  for (const receipt of [
    { queued: true },
    { queued: true, created: true, replayed: false, message_id: 'wrong' },
  ]) {
    const f = fixture();
    f.creation.runAgentMessage = async () => receipt;
    await assert.rejects(
      f.ops.withOperation({ config: config(), signal: new AbortController().signal }, (client) =>
        client.runAgentMessage(conversation('workspace-1'), 'hello', 'message-1'),
      ),
      (error) => error.code === 'desktop_conversation_messaging_message_receipt_invalid',
    );
  }
  const f = fixture();
  const replay = { queued: false, created: false, replayed: true, message_id: 'message-1' };
  f.creation.runAgentMessage = async () => replay;
  assert.deepEqual(
    await f.ops.withOperation(
      { config: config(), signal: new AbortController().signal },
      (client) => client.runAgentMessage(conversation('workspace-1'), 'hello', 'message-1'),
    ),
    replay,
  );
  assert.equal(f.state.children, 1);
});

test('creation and send clone mutable arguments before delayed child admission', async () => {
  const f = fixture();
  const gate = deferred();
  const original = f.parent.acquireChildServiceLease;
  f.parent.acquireChildServiceLease = async (request) => {
    await gate.promise;
    return original(request);
  };
  const mentions = ['user-1'];
  const pending = f.ops.withOperation(
    { config: config(), signal: new AbortController().signal },
    (client) => {
      const sent = client.sendMessage('hello', undefined, [], mentions);
      mentions[0] = 'changed';
      gate.resolve();
      return sent;
    },
  );
  await pending;
  assert.deepEqual(f.state.calls[0][1][3], ['user-1']);
  assert.ok(Object.isFrozen(f.state.calls[0][1][3]));
});
