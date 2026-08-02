import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const {
  createProjectSupportController,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/project-support/projectSupportController.js'
);

test('Project Support suppresses stale completion after a project scope switch', async () => {
  const pending = new Map();
  const controller = createProjectSupportController({
    authority: 'cloud',
    client: {
      list(scope, _query, options) {
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
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
});

test('Project Support reloads after create and close and maps conflict and forbidden', async () => {
  let listCalls = 0;
  const controller = createProjectSupportController({
    authority: 'cloud',
    client: {
      async list(scopeValue) {
        listCalls += 1;
        return snapshot(scopeValue.projectId);
      },
      async create() {
        return ticket({ id: 'ticket-created' });
      },
      async close() {
        return { id: 'ticket-1', status: 'closed', resolvedAt: '2026-08-02T03:00:00Z' };
      },
    },
    initialScope: scope('project-1'),
  });
  await controller.load(scope('project-1'));
  await controller.create({
    subject: 'Created',
    message: 'Please help',
    priority: 'urgent',
  });
  await controller.close('ticket-1');
  assert.equal(listCalls, 3);

  const forbidden = createProjectSupportController({
    authority: 'cloud',
    client: {
      async list() {
        throw new DesktopApiError('forbidden', 403, {
          reason_code: 'support_tenant_access_forbidden',
        });
      },
    },
    initialScope: scope('project-1'),
  });
  await forbidden.load(scope('project-1'));
  assert.equal(forbidden.getSnapshot().state, 'forbidden');
  assert.equal(forbidden.getSnapshot().reasonCode, 'support_tenant_access_forbidden');

  const conflict = createProjectSupportController({
    authority: 'cloud',
    client: {
      async list() {
        return snapshot('project-1');
      },
      async close() {
        throw new DesktopApiError('conflict', 409, {
          reason_code: 'support_ticket_state_conflict',
        });
      },
    },
    initialScope: scope('project-1'),
  });
  await conflict.load(scope('project-1'));
  await assert.rejects(conflict.close('ticket-1'), /conflict/u);
  assert.equal(conflict.getSnapshot().state, 'conflict');
  assert.equal(conflict.getSnapshot().reasonCode, 'support_ticket_state_conflict');
});

test('Project Support exposes Local not-applicable without mutation affordances', async () => {
  const controller = createProjectSupportController({
    authority: 'local',
    client: {
      async list(scopeValue) {
        return {
          ...snapshot(scopeValue.projectId),
          scope: scopeValue,
          authority: 'local',
          availability: 'not_applicable',
          reasonCode: 'local_support_service_not_applicable',
          allowedActions: [],
          tickets: [],
          total: 0,
        };
      },
    },
    initialScope: { ...scope('project-1'), authority: 'local' },
  });
  await controller.load({ ...scope('project-1'), authority: 'local' });
  assert.equal(controller.getSnapshot().state, 'not_applicable');
  assert.deepEqual(controller.getSnapshot().allowedActions, []);
  await assert.rejects(
    controller.create({
      subject: 'Unavailable',
      message: 'Unavailable',
      priority: 'low',
    }),
    /project_support_action_unavailable:create/u,
  );
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
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'list', 'create', 'close', 'retry'],
    authorityRevision: null,
    tickets: [ticket()],
    total: 1,
    limit: 25,
    offset: 0,
    hasMore: false,
  };
}

function ticket(overrides = {}) {
  return {
    id: 'ticket-1',
    tenantId: 'tenant-1',
    subject: 'Need help',
    message: 'Something failed',
    priority: 'medium',
    status: 'open',
    createdAt: '2026-08-02T00:00:00Z',
    updatedAt: '2026-08-02T01:00:00Z',
    resolvedAt: null,
    allowedActions: ['view', 'close'],
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
