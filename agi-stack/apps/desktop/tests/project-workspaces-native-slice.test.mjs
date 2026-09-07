import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { DesktopApiError } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');
const {
  createProjectWorkspacesController,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-workspaces/projectWorkspacesController.js');
const {
  createProjectWorkspacesRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/project-workspaces/projectWorkspacesRouteModule.js');

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

test('Project Workspaces controller hides stale scopes and maps forbidden authority responses', async () => {
  const deferred = Promise.withResolvers();
  const client = {
    list(scope) {
      return scope.projectId === 'project-1'
        ? deferred.promise
        : Promise.reject(
            new DesktopApiError('forbidden', 403, {
              reason_code: 'project_workspaces_forbidden',
            }),
          );
    },
  };
  const controller = createProjectWorkspacesController({
    authority: 'cloud',
    client,
    initialScope: cloudScope,
  });
  const first = controller.load(cloudScope);
  const nextScope = Object.freeze({ ...cloudScope, projectId: 'project-2' });
  await controller.load(nextScope);
  assert.equal(controller.getSnapshot().state, 'forbidden');
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
  deferred.resolve(snapshot(cloudScope));
  await first;
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
});

test('Project Workspaces route is native, scope-bound and opens the canonical Blackboard target', async () => {
  const opened = [];
  let renderedBinding = null;
  const module = await createProjectWorkspacesRouteModuleLoader({
    createBinding(context) {
      renderedBinding = {
        controller: readyController(cloudScope),
        scope: cloudScope,
        openBlackboard(workspaceId) {
          opened.push({ ...context, workspaceId });
        },
      };
      return renderedBinding;
    },
  })();
  assert.equal(module.routeId, 'project-project-workspaces');
  assert.equal(module.disposition, 'implemented');
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, {
        context: { tenantId: 'tenant-1', projectId: 'project-1' },
        module,
      }),
    ),
  );
  assert.match(markup, /Alpha workspace/);
  assert.match(markup, /Collaboration canvas/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
  renderedBinding.openBlackboard('workspace-1');
  assert.deepEqual(opened, [
    { tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1' },
  ]);
});

function readyController(scope) {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        state: 'ready',
        scope,
        authority: scope.authority,
        reasonCode: null,
        retryVisible: false,
        busyAction: null,
        allowedActions: ['view', 'list', 'create', 'open-blackboard'],
        workspaces: [workspaceRecord()],
      };
    },
    async load() {},
    async retry() {},
    async create() {},
    cancel() {},
    stop() {},
  };
}

function snapshot(scope) {
  return {
    scope,
    authority: scope.authority,
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '1.0.0',
    authorityRevision: null,
    allowedActions: ['view', 'list', 'create', 'open-blackboard'],
    workspaces: [workspaceRecord()],
  };
}

function workspaceRecord(overrides = {}) {
  return {
    id: 'workspace-1',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    name: 'Alpha workspace',
    description: 'Native workspace',
    archived: false,
    createdAt: '2026-08-05T00:00:00Z',
    updatedAt: null,
    ...overrides,
  };
}
