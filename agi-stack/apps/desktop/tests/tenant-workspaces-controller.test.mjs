import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import('/tmp/agistack-desktop-test-dist/src/api/client.js');
const { createTenantWorkspacesController } =
  await import('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantWorkspacesController.js');

test('Tenant Workspaces suppresses stale completion after a project scope switch', async () => {
  const pending = new Map();
  const controller = createTenantWorkspacesController({
    authority: 'cloud',
    client: {
      list(scope, options) {
        const request = deferred();
        pending.set(scope.projectId, { ...request, signal: options.signal });
        return request.promise;
      },
    },
    initialScope: scope('project-1'),
  });

  const first = controller.load(scope('project-1'));
  const second = controller.load(scope('project-2'));
  assert.equal(pending.get('project-1').signal.aborted, true);
  assert.equal(controller.getSnapshot().state, 'scope_switch');

  pending.get('project-1').resolve(snapshot('project-1'));
  await first;
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');

  pending.get('project-2').resolve(snapshot('project-2'));
  await second;
  assert.equal(controller.getSnapshot().state, 'degraded');
  assert.equal(controller.getSnapshot().workspaces[0].projectId, 'project-2');
});

test('Tenant Workspaces creates once, reloads and retains structured conflict state', async () => {
  let listCalls = 0;
  const controller = createTenantWorkspacesController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        listCalls += 1;
        return snapshot(scopeValue.projectId);
      },
      async create(_scopeValue, input) {
        return workspace('project-1', { id: 'created', name: input.name });
      },
    },
    initialScope: scope('project-1'),
  });

  await controller.load(scope('project-1'));
  await controller.create({ name: 'Created', description: 'Native' });
  assert.equal(listCalls, 2);

  const conflict = createTenantWorkspacesController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        return snapshot(scopeValue.projectId);
      },
      async create() {
        throw new DesktopApiError('conflict', 409, {
          reason_code: 'workspace_create_conflict',
        });
      },
    },
    initialScope: scope('project-1'),
  });
  await conflict.load(scope('project-1'));
  await assert.rejects(conflict.create({ name: 'Duplicate', description: '' }), /conflict/u);
  assert.equal(conflict.getSnapshot().state, 'conflict');
  assert.equal(conflict.getSnapshot().reasonCode, 'workspace_create_conflict');
});

function scope(projectId) {
  return {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId,
  };
}

function snapshot(projectId) {
  return {
    scope: scope(projectId),
    authority: 'cloud',
    availability: 'degraded',
    reasonCode: 'desktop_tenant_workspaces_advanced_management_partial',
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'list', 'create'],
    authorityRevision: null,
    workspaces: [workspace(projectId)],
  };
}

function workspace(projectId, overrides = {}) {
  return {
    id: 'workspace-1',
    tenantId: 'tenant-1',
    projectId,
    name: 'Alpha workspace',
    description: '',
    status: 'active',
    archived: false,
    createdAt: '2026-07-31T00:00:00Z',
    updatedAt: null,
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
