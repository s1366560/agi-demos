import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import {
  cases,
  envelope,
  nativeScope,
  projectScope,
  cloudResolution,
} from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const root = '/tmp/agistack-desktop-test-dist/src';
const {
  createDesktopProjectMemoriesOperationsV2,
  createDesktopNativeKnowledgeClientV2,
  withDesktopProjectMemoriesAuthorityOperationV2,
} = require(root + '/plugins/desktopProjectMemoriesAuthorityModuleV2.js');
const config = {
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'https://cloud.test',
  apiKey: 'identity',
  localApiToken: 'launch',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  workspaceRoot: '',
  mode: 'local',
};
function actions(events, executeSync) {
  return {
    async acquireServiceOperationLease(request) {
      events.push(['acquire', request]);
      return {
        status: 'accepted',
        digest: 'renderer-digest',
        useService(fn) {
          return fn({
            bindOperation() {
              return {
                load: async () => {
                  throw Error('unexpected load');
                },
                executeSync,
              };
            },
          });
        },
        async release() {
          events.push(['release']);
        },
      };
    },
  };
}

test('typed sync authority uses the existing project lease and immutable command client', async () => {
  const events = [];
  const execute = async (command) => {
    events.push(['execute', command]);
    const [, result] = cases.find(([c]) => c.operation === command.operation);
    return envelope(command, result);
  };
  const ops = createDesktopProjectMemoriesOperationsV2(() => actions(events, execute));
  const client = createDesktopNativeKnowledgeClientV2(ops, config);
  const command = { operation: 'sync_status' };
  const pending = client.execute(projectScope, command);
  command.operation = 'sync_push';
  const result = await pending;
  assert.equal(result.operation, 'sync_status');
  assert(Object.isFrozen(result));
  assert(Object.isFrozen(result.result.status));
  assert.deepEqual(
    events.map(([name]) => name),
    ['acquire', 'execute', 'release'],
  );
  assert.equal(events[0][1].service, 'service:desktop-renderer.project-memories-authority');
  assert.deepEqual(events[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
  });
});

test('invalid native sync commands and cloud mode fail before leasing a service', async () => {
  const events = [];
  const ops = createDesktopProjectMemoriesOperationsV2(() =>
    actions(events, async () => {
      throw Error('unexpected');
    }),
  );
  for (const input of [
    { config, scope: projectScope, command: { operation: 'sync_push', remote: {} } },
    {
      config: { ...config, mode: 'cloud', apiBaseUrl: 'https://cloud.test' },
      scope: { ...projectScope, authority: 'cloud' },
      command: { operation: 'sync_push' },
    },
    {
      config: { ...config, apiBaseUrl: 'https://cloud.test' },
      scope: projectScope,
      command: { operation: 'sync_push' },
    },
  ]) {
    await assert.rejects(async () => ops.executeKnowledgeSync(input));
  }
  assert.equal(events.length, 0);
});

test('native sync refuses escaped released capabilities and aborts before returning results', async () => {
  const command = { operation: 'sync_status' };
  const events = [];
  const service = actions(events, async (command) => envelope(command, cases[0][1]));
  const escaped = await withDesktopProjectMemoriesAuthorityOperationV2(
    service,
    { kind: 'sync', config, scope: projectScope, command },
    (authority) => authority,
  );
  await assert.rejects(escaped.executeSync(command), /released/);
  const abort = new AbortController();
  const ops = createDesktopProjectMemoriesOperationsV2(() =>
    actions(events, async (command) => {
      abort.abort();
      return envelope(command, cases[0][1]);
    }),
  );
  await assert.rejects(
    ops.executeKnowledgeSync({ config, scope: projectScope, command, signal: abort.signal }),
    { name: 'AbortError' },
  );
  assert.deepEqual(events.at(-1), ['release']);
});

test('native sync wrapper rejects context-stale resolutions from an authority', async () => {
  const events = [];
  const [command, result] = cases.find(([c]) => c.operation === 'resolve_push');
  const ops = createDesktopProjectMemoriesOperationsV2(() =>
    actions(events, async () =>
      envelope(command, result, {
        ...nativeScope,
        context_revision: nativeScope.context_revision + 1,
      }),
    ),
  );
  await assert.rejects(
    ops.executeKnowledgeSync({ config, scope: projectScope, command, expectedScope: nativeScope }),
    (error) => error.status === 409,
  );
  assert.deepEqual(events.at(-1), ['release']);
});

test('selected-state commands without observed scope fail before service lease admission', async () => {
  const events = [];
  const ops = createDesktopProjectMemoriesOperationsV2(() =>
    actions(events, async () => {
      throw Error('unexpected');
    }),
  );
  for (const [command] of cases.filter(([c]) =>
    [
      'sync_link',
      'resolve_pull',
      'resolve_push',
      'resume_resolution',
      'reconcile_resolution',
    ].includes(c.operation),
  )) {
    await assert.rejects(
      async () => ops.executeKnowledgeSync({ config, scope: projectScope, command }),
      (error) =>
        error.message === 'native_knowledge_expected_scope_required' && error.status === 422,
    );
  }
  assert.equal(events.length, 0);
});
