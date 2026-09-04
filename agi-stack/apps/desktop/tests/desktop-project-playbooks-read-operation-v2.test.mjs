import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const { RuntimeV2Error } = require('@agistack/plugin-runtime');
const {
  createDesktopProjectPlaybooksReadOperationsV2,
  DesktopProjectPlaybooksReadAuthorityUnavailableErrorV2,
} = require(`${ROOT}/src/plugins/desktopProjectPlaybooksReadAuthorityModuleV2.js`);
const config = () => ({
  apiBaseUrl: 'https://api.test',
  deviceAuthorizationBaseUrl: '',
  apiKey: '',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
});
const scope = () => ({ authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' });
const snapshot = (scopeRevision = 7) => ({
  scope: scope(),
  scopeRevision,
  authority: 'cloud',
  availability: 'available',
  reasonCode: null,
  allowedActions: ['view', 'list', 'refresh', 'review-verdicts'],
  playbooks: [],
  verdicts: [],
});

test('Project Playbooks read freezes input and acquires one exact project lease', async () => {
  const lifecycle = [];
  const received = [];
  const operations = createDesktopProjectPlaybooksReadOperationsV2(() => ({
    async acquireServiceOperationLease(request) {
      lifecycle.push(['acquire', request]);
      return {
        status: 'accepted',
        digest: 'playbooks',
        useService(operation) {
          return operation(
            Object.freeze({
              bindOperation(boundConfig) {
                received.push(boundConfig);
                return Object.freeze({
                  async load(boundScope, options) {
                    received.push(boundScope, options);
                    return snapshot();
                  },
                });
              },
            }),
          );
        },
        async release() {
          lifecycle.push(['release']);
        },
      };
    },
  }));
  const runtime = config();
  const operationScope = scope();
  const controller = new AbortController();
  await operations.loadProjectPlaybooks({
    config: runtime,
    scope: operationScope,
    signal: controller.signal,
  });
  runtime.tenantId = 'changed';
  operationScope.projectId = 'changed';
  assert.deepEqual(lifecycle, [
    [
      'acquire',
      {
        service: 'service:desktop-renderer.project-playbooks-read-authority',
        version: '1.0.0',
        scope: { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
      },
    ],
    ['release'],
  ]);
  assert.equal(Object.isFrozen(received[0]), true);
  assert.equal(Object.isFrozen(received[1]), true);
  assert.equal(received[2].signal, controller.signal);
});

test('Project Playbooks read rejects scope mismatch and missing generation before service use', async () => {
  let acquired = 0;
  const operations = createDesktopProjectPlaybooksReadOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquired += 1;
      assert.fail();
    },
  }));
  assert.throws(
    () =>
      operations.loadProjectPlaybooks({
        config: config(),
        scope: { ...scope(), projectId: 'other' },
      }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_playbooks_read_operation_input_invalid',
  );
  assert.equal(acquired, 0);
  assert.throws(
    () =>
      createDesktopProjectPlaybooksReadOperationsV2(() => null).loadProjectPlaybooks({
        config: config(),
        scope: scope(),
      }),
    (error) => error instanceof DesktopProjectPlaybooksReadAuthorityUnavailableErrorV2,
  );
});

test('Project Playbooks read keeps the primary error when release also fails', async () => {
  const primary = new Error('primary');
  const operations = createDesktopProjectPlaybooksReadOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        digest: 'playbooks',
        useService(operation) {
          return operation({
            bindOperation: () => ({
              load: async () => {
                throw primary;
              },
            }),
          });
        },
        async release() {
          throw new Error('release');
        },
      };
    },
  }));
  await assert.rejects(
    operations.loadProjectPlaybooks({ config: config(), scope: scope() }),
    primary,
  );
});

test('Project Playbooks read keeps an old request pinned while a later request uses replacement', async () => {
  let resolveOld;
  let generation = 'old';
  const oldResult = new Promise((resolve) => {
    resolveOld = resolve;
  });
  const operations = createDesktopProjectPlaybooksReadOperationsV2(() => ({
    async acquireServiceOperationLease() {
      const pinned = generation;
      return {
        status: 'accepted',
        digest: pinned,
        useService(operation) {
          return operation({
            bindOperation: () => ({ load: () => (pinned === 'old' ? oldResult : snapshot(8)) }),
          });
        },
        async release() {},
      };
    },
  }));
  const oldRequest = operations.loadProjectPlaybooks({ config: config(), scope: scope() });
  generation = 'new';
  const newResult = await operations.loadProjectPlaybooks({ config: config(), scope: scope() });
  resolveOld(snapshot());
  const pinnedResult = await oldRequest;
  assert.equal(newResult.scopeRevision, 8);
  assert.equal(pinnedResult.scopeRevision, 7);
});

test('Project Playbooks read rejects malformed service and response shapes', async () => {
  const actions = (service) => ({
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        digest: 'bad',
        useService(operation) {
          return operation(service);
        },
        async release() {},
      };
    },
  });
  await assert.rejects(
    createDesktopProjectPlaybooksReadOperationsV2(() => actions({})).loadProjectPlaybooks({
      config: config(),
      scope: scope(),
    }),
    (error) =>
      error instanceof RuntimeV2Error &&
      error.code === 'desktop_project_playbooks_read_service_invalid',
  );
  await assert.rejects(
    createDesktopProjectPlaybooksReadOperationsV2(() =>
      actions({ bindOperation: () => ({ load: async () => ({}) }) }),
    ).loadProjectPlaybooks({ config: config(), scope: scope() }),
    /desktop_project_playbooks_read_service_contract_invalid/u,
  );
});
