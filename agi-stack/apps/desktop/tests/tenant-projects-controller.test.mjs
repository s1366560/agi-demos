import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const {
  createTenantProjectsController,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantProjectsController.js'
);

test('Projects controller suppresses stale list completion after a tenant scope switch', async () => {
  const pending = new Map();
  const client = {
    list(scope, _query, options) {
      const request = deferred();
      pending.set(scope.tenantId, { ...request, signal: options.signal });
      return request.promise;
    },
  };
  const controller = createTenantProjectsController({
    authority: 'cloud',
    client,
    initialScope: scope('tenant-1'),
  });

  const first = controller.load(scope('tenant-1'));
  const second = controller.load(scope('tenant-2'));
  assert.equal(pending.get('tenant-1').signal.aborted, true);
  assert.equal(controller.getSnapshot().state, 'scope_switch');
  assert.deepEqual(controller.getSnapshot().projects, []);

  pending.get('tenant-1').resolve(listSnapshot('tenant-1'));
  await first;
  assert.equal(controller.getSnapshot().scope.tenantId, 'tenant-2');

  pending.get('tenant-2').resolve(listSnapshot('tenant-2'));
  await second;
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.equal(controller.getSnapshot().projects[0].tenantId, 'tenant-2');
});

test('Projects controller reloads after mutations and maps forbidden and conflict states', async () => {
  let listCalls = 0;
  const client = {
    async list(scopeValue) {
      listCalls += 1;
      return listSnapshot(scopeValue.tenantId);
    },
    async create(_scopeValue, input) {
      return project('tenant-1', { id: 'created', name: input.name });
    },
    async update(_scopeValue, projectId, input) {
      return project('tenant-1', { id: projectId, name: input.name });
    },
    async delete() {},
  };
  const controller = createTenantProjectsController({
    authority: 'cloud',
    client,
    initialScope: scope('tenant-1'),
  });

  await controller.load(scope('tenant-1'));
  await controller.create({ name: 'Created', description: '' });
  await controller.update('project-1', { name: 'Updated', description: '' });
  await controller.delete('project-1');
  assert.equal(listCalls, 4);

  const forbidden = createTenantProjectsController({
    authority: 'cloud',
    client: {
      async list() {
        throw new DesktopApiError('forbidden', 403, {
          reason_code: 'tenant_projects_forbidden',
        });
      },
    },
    initialScope: scope('tenant-1'),
  });
  await forbidden.load(scope('tenant-1'));
  assert.equal(forbidden.getSnapshot().state, 'forbidden');

  const conflict = createTenantProjectsController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        return listSnapshot(scopeValue.tenantId);
      },
      async update() {
        throw new DesktopApiError('conflict', 409, {
          reason_code: 'project_revision_conflict',
        });
      },
    },
    initialScope: scope('tenant-1'),
  });
  await conflict.load(scope('tenant-1'));
  await assert.rejects(
    conflict.update('project-1', { name: 'Updated', description: '' }),
    /conflict/u,
  );
  assert.equal(conflict.getSnapshot().state, 'conflict');
  assert.equal(conflict.getSnapshot().reasonCode, 'project_revision_conflict');
});

test('Projects controller rejects overlapping mutations without aborting or redispatching', async () => {
  const createRequest = deferred();
  let createCalls = 0;
  const controller = createTenantProjectsController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        return listSnapshot(scopeValue.tenantId);
      },
      create() {
        createCalls += 1;
        return createRequest.promise;
      },
    },
    initialScope: scope('tenant-1'),
  });
  await controller.load(scope('tenant-1'));

  const first = controller.create({ name: 'Created', description: '' });
  await assert.rejects(
    controller.create({ name: 'Duplicate', description: '' }),
    /tenant_projects_mutation_in_progress/u,
  );
  assert.equal(createCalls, 1);
  assert.equal(controller.getSnapshot().busyAction, 'create');

  createRequest.resolve(project('tenant-1', { id: 'created', name: 'Created' }));
  await first;
  assert.equal(controller.getSnapshot().busyAction, null);
});

test('Projects controller forwards the editor-owned idempotency key', async () => {
  let receivedOptions = null;
  const controller = createTenantProjectsController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        return listSnapshot(scopeValue.tenantId);
      },
      async create(_scopeValue, _input, options) {
        receivedOptions = options;
        return project('tenant-1', { id: 'created' });
      },
    },
    initialScope: scope('tenant-1'),
  });
  await controller.load(scope('tenant-1'));

  await controller.create(
    { name: 'Created', description: '' },
    'desktop-project-create-stable-retry',
  );

  assert.equal(
    receivedOptions.idempotencyKey,
    'desktop-project-create-stable-retry',
  );
});

function scope(tenantId) {
  return { authority: 'cloud', tenantId };
}

function listSnapshot(tenantId) {
  return {
    scope: scope(tenantId),
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'list', 'create', 'update', 'delete'],
    authorityRevision: null,
    projects: [project(tenantId)],
    total: 1,
    page: 1,
    pageSize: 20,
    ownerIds: ['user-1'],
  };
}

function project(tenantId, overrides = {}) {
  return {
    id: 'project-1',
    tenantId,
    name: 'Alpha',
    description: '',
    ownerId: 'user-1',
    memberIds: ['user-1'],
    isPublic: false,
    createdAt: '2026-07-31T00:00:00Z',
    updatedAt: null,
    stats: {},
    ...overrides,
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}
