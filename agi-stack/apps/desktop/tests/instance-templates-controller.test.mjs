import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createInstanceTemplatesController } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/instance-templates/instanceTemplatesController.js'
);
const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
});
const localScope = Object.freeze({
  authority: 'local',
  tenantId: 'tenant-1',
});

function template(overrides = {}) {
  return {
    id: 'template-1',
    name: 'Starter',
    slug: 'starter',
    tenantId: 'tenant-1',
    description: 'Safe starter',
    icon: null,
    imageVersion: 'v1',
    defaultConfig: { cpu: 2 },
    isPublished: false,
    isFeatured: false,
    installCount: 3,
    createdAt: '2026-08-02T08:00:00Z',
    updatedAt: null,
    ...overrides,
  };
}

function page() {
  return {
    templates: [template()],
    total: 1,
    page: 1,
    pageSize: 20,
  };
}

test('Instance Templates loads, inspects, mutates, and preserves stale rows', async () => {
  let failList = false;
  let listCalls = 0;
  const controller = createInstanceTemplatesController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async () => {
        listCalls += 1;
        if (failList) throw new Error('offline');
        return page();
      },
      get: async () => template(),
      listItems: async () => [
        {
          id: 'item-1',
          templateId: 'template-1',
          itemType: 'gene',
          itemSlug: 'gene.safe',
          displayOrder: 1,
          createdAt: '2026-08-02T08:01:00Z',
        },
      ],
      create: async () => template({ id: 'template-2' }),
      delete: async () => {},
      publish: async () => template({ isPublished: true }),
      clone: async () => template({ id: 'template-3' }),
    },
  });
  await controller.load(cloudScope);
  await controller.inspect('template-1');
  assert.equal(controller.getSnapshot().selectedTemplate?.id, 'template-1');
  assert.equal(controller.getSnapshot().items.length, 1);
  await controller.create({
    name: 'New Template',
    slug: 'new-template',
    description: null,
    defaultConfig: {},
  });
  await controller.publish('template-1');
  await controller.clone('template-1', 'Starter Copy');
  await controller.delete('template-1');
  assert.equal(listCalls, 5);

  failList = true;
  await controller.retry();
  assert.equal(controller.getSnapshot().state, 'stale');
  assert.equal(controller.getSnapshot().templates.length, 1);
});

test('Instance Templates keeps Local unavailable and maps Cloud forbidden errors', async () => {
  let calls = 0;
  const local = createInstanceTemplatesController({
    authority: 'local',
    initialScope: localScope,
    client: unavailableClient(() => {
      calls += 1;
    }),
  });
  await local.load(localScope);
  assert.equal(local.getSnapshot().state, 'unavailable');
  assert.equal(
    local.getSnapshot().reasonCode,
    'local_instance_template_authority_unavailable',
  );
  assert.deepEqual(local.getSnapshot().allowedActions, []);
  assert.equal(calls, 0);

  const forbidden = createInstanceTemplatesController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      ...unavailableClient(),
      list: async () => {
        throw new DesktopApiError('forbidden', 403, null);
      },
    },
  });
  await forbidden.load(cloudScope);
  assert.equal(forbidden.getSnapshot().state, 'forbidden');
});

function unavailableClient(onCall = () => {}) {
  return {
    list: async () => {
      onCall();
      throw new Error('must not run');
    },
    get: async () => {
      onCall();
      throw new Error('must not run');
    },
    listItems: async () => {
      onCall();
      throw new Error('must not run');
    },
    create: async () => {
      onCall();
      throw new Error('must not run');
    },
    delete: async () => {
      onCall();
      throw new Error('must not run');
    },
    publish: async () => {
      onCall();
      throw new Error('must not run');
    },
    clone: async () => {
      onCall();
      throw new Error('must not run');
    },
  };
}
