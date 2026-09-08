import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { nativeScope, projectScope, config } from './nativeKnowledgeProcessingFixtures.mjs';
const require = createRequire(import.meta.url);
const root = process.env.NATIVE_INPUTS_DIST ?? '/tmp/agistack-desktop-test-dist';
const { createDesktopNativeKnowledgeInputsClientV2: create } = require(
  `${root}/src/plugins/desktopNativeKnowledgeInputsClientV2.js`,
);
const provider = {
  id: 'provider',
  tenant_id: projectScope.tenantId,
  name: 'Provider',
  is_active: true,
  revision: 3,
  api_key_masked: 'DO_NOT_FORWARD',
};
const workspace = {
  id: 'workspace',
  tenant_id: projectScope.tenantId,
  project_id: projectScope.projectId,
  name: 'Workspace',
  is_archived: false,
};
function fixture({
  providerRows = [provider],
  catalog = {
    providerId: 'provider',
    availability: 'available',
    models: [
      { id: 'embed', capability: 'embedding' },
      { id: 'chat', capability: 'chat' },
    ],
  },
  workspaceRows = [workspace],
  isCurrent = () => true,
  observe = async () => ({ scope: nativeScope }),
} = {}) {
  const calls = [];
  const client = create(config, {
    processing: { query: observe },
    providers: {
      async listLlmProviders() {
        calls.push('providers');
        return providerRows;
      },
      async discoverLlmProviderModels(id, revision) {
        calls.push(['models', id, revision]);
        return typeof catalog === 'function' ? await catalog() : catalog;
      },
    },
    workspaces: {
      async listWorkspacesForProject() {
        calls.push('workspaces');
        return workspaceRows;
      },
    },
    isCurrent,
  });
  return { client, calls };
}
const opts = (operation) => ({ operation, expectedScope: nativeScope });
test('embedding choices use exact provider revision and structured capability only', async () => {
  const f = fixture();
  const got = await f.client.load(projectScope, opts('configure_embedding'));
  assert.deepEqual(got.embeddingModels, {
    availability: 'available',
    items: [
      { providerId: 'provider', providerRevision: 3, providerName: 'Provider', modelId: 'embed' },
    ],
  });
  assert.equal(got.workspaces.availability, 'unavailable');
  assert.ok(!JSON.stringify(got).includes('DO_NOT_FORWARD'));
  assert.ok(Object.isFrozen(got.embeddingModels.items[0]));
  assert.deepEqual(f.calls, ['providers', ['models', 'provider', 3]]);
});
test('workspace choices never query unrelated providers and exclude archived', async () => {
  const f = fixture({
    workspaceRows: [workspace, { ...workspace, id: 'archived', is_archived: true }],
  });
  const got = await f.client.load(projectScope, opts('process_one'));
  assert.deepEqual(got.workspaces.items, [{ id: 'workspace', name: 'Workspace' }]);
  assert.equal(got.embeddingModels.availability, 'unavailable');
  assert.deepEqual(f.calls, ['workspaces']);
});
test('inactive providers and unavailable catalogs never become selectable', async () => {
  let f = fixture({ providerRows: [{ ...provider, is_active: false }] });
  assert.deepEqual(
    (await f.client.load(projectScope, opts('configure_embedding'))).embeddingModels.items,
    [],
  );
  assert.deepEqual(f.calls, ['providers']);
  f = fixture({ catalog: { providerId: 'provider', availability: 'unavailable', models: [] } });
  assert.equal(
    (await f.client.load(projectScope, opts('configure_embedding'))).embeddingModels.availability,
    'unavailable',
  );
});
test('catalog identity mismatch and cross-project workspace fail closed', async () => {
  for (const [f, operation] of [
    [
      fixture({ catalog: { providerId: 'other', availability: 'available', models: [] } }),
      'configure_embedding',
    ],
    [fixture({ workspaceRows: [{ ...workspace, project_id: 'other' }] }), 'process_one'],
  ])
    await assert.rejects(f.client.load(projectScope, opts(operation)), /scope/);
});
test('live identity loss at async boundary rejects catalog result', async () => {
  let current = true;
  const f = fixture({
    isCurrent: () => current,
    observe: async () => {
      current = false;
      return { scope: nativeScope };
    },
  });
  await assert.rejects(f.client.load(projectScope, opts('process_one')), /scope/);
  assert.deepEqual(f.calls, []);
});
test('native scope drift after discovery rejects complete selection', async () => {
  let observed = 0;
  const f = fixture({
    observe: async () => ({
      scope: {
        ...nativeScope,
        context_revision: ++observed === 1 ? nativeScope.context_revision : 99,
      },
    }),
  });
  await assert.rejects(f.client.load(projectScope, opts('configure_embedding')), /scope/);
});
test('invalid operation or expected scope rejected before reads', async () => {
  let count = 0;
  const f = fixture({
    observe: async () => {
      count++;
      return { scope: nativeScope };
    },
  });
  for (const options of [
    { operation: 'other', expectedScope: nativeScope },
    { operation: 'process_one', expectedScope: { ...nativeScope, project_id: 'other' } },
  ])
    await assert.rejects(f.client.load(projectScope, options));
  assert.equal(count, 0);
});

test('authentication errors remain fatal while an unavailable directory stays independent', async () => {
  const { DesktopApiError } = require(`${root}/src/api/client.js`);
  for (const status of [401, 503]) {
    const f = fixture({
      catalog: async () => {
        throw new DesktopApiError('catalog', status, null);
      },
    });
    if (status === 401)
      await assert.rejects(
        f.client.load(projectScope, opts('configure_embedding')),
        (error) => error.status === 401,
      );
    else
      assert.equal(
        (await f.client.load(projectScope, opts('configure_embedding'))).embeddingModels
          .availability,
        'unavailable',
      );
  }
});
test('permission loss during model discovery discards otherwise valid choices', async () => {
  let current = true;
  const f = fixture({
    isCurrent: () => current,
    catalog: async () => {
      current = false;
      return {
        providerId: 'provider',
        availability: 'available',
        models: [{ id: 'embed', capability: 'embedding' }],
      };
    },
  });
  await assert.rejects(f.client.load(projectScope, opts('configure_embedding')), /scope/);
});

test('production catalog adapters hold their scoped leases and clear selected workspace for project listing', async () => {
  const {
    createDesktopTenantProvidersOperationsV2,
    createDesktopTenantProvidersClientV2,
  } = require(`${root}/src/plugins/desktopTenantProvidersAuthorityModuleV2.js`);
  const { createDesktopWorkspaceCatalogOperationsV2 } = require(
    `${root}/src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.js`,
  );
  const events = [];
  const actions = {
    async acquireServiceOperationLease(input) {
      events.push(['acquire', input.scope]);
      const service = input.service.includes('tenant-providers')
        ? {
            bindOperation: () => ({
              execute: async (method, p) => {
                if (method === 'listLlmProviders')
                  return [{ ...provider, provider_type: 'openai' }];
                assert.equal(method, 'discoverLlmProviderModels');
                assert.deepEqual(p.args, ['provider', 3]);
                return {
                  provider_id: 'provider',
                  provider_type: 'openai',
                  availability: 'available',
                  source: 'fixture',
                  models: { embedding: ['embed'], chat: ['chat'] },
                };
              },
            }),
          }
        : {
            bindOperation: (c) => {
              assert.equal(c.workspaceId, '');
              return { listWorkspacesForProject: async () => [workspace] };
            },
          };
      return {
        status: 'accepted',
        useService: (fn) => fn(service),
        async release() {
          events.push(['release']);
        },
      };
    },
  };
  const runtime = { ...config, workspaceId: 'selected' };
  const client = create(runtime, {
    processing: { query: async () => ({ scope: nativeScope }) },
    providers: createDesktopTenantProvidersClientV2(
      createDesktopTenantProvidersOperationsV2(() => actions),
      runtime,
    ),
    workspaces: createDesktopWorkspaceCatalogOperationsV2(() => actions),
    isCurrent: () => true,
  });
  assert.equal(
    (await client.load(projectScope, opts('configure_embedding'))).embeddingModels.items[0]
      .providerRevision,
    3,
  );
  assert.deepEqual((await client.load(projectScope, opts('process_one'))).workspaces.items, [
    { id: 'workspace', name: 'Workspace' },
  ]);
  assert.equal(events.filter((e) => e[0] === 'acquire').length, 3);
  assert.equal(events.filter((e) => e[0] === 'release').length, 3);
  assert.equal(events[0][1].kind, 'tenant');
  assert.equal(events[4][1].kind, 'project');
});
