import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createTenantProjectsRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantProjectsRouteModule.js'
);

test('Tenant Projects loader stays lazy and renders a native CRUD surface', async () => {
  let bindingCalls = 0;
  const module = await createTenantProjectsRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return {
        controller: controller(),
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
      };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-projects');
  assert.equal(module.disposition, 'implemented');

  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, {
        context: { tenantId: 'tenant-1' },
        module,
      }),
    ),
  );
  assert.equal(bindingCalls, 1);
  assert.match(markup, /Alpha/);
  assert.match(markup, /Create project/);
  assert.match(markup, /Edit Alpha/);
  assert.match(markup, /Delete Alpha/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Tenant Projects route fails closed without tenant context', async () => {
  let bindingCalls = 0;
  const module = await createTenantProjectsRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return { controller: controller(), scope: { authority: 'cloud', tenantId: 'tenant-1' } };
    },
  })();
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { context: {}, module }),
    ),
  );
  assert.equal(bindingCalls, 0);
  assert.match(markup, /tenant_projects_route_context_unavailable/);
});

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        state: 'ready',
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
        authority: 'cloud',
        reasonCode: null,
        retryVisible: false,
        busyAction: null,
        allowedActions: ['view', 'list', 'create', 'update', 'delete'],
        projects: [
          {
            id: 'project-1',
            tenantId: 'tenant-1',
            name: 'Alpha',
            description: 'Project Alpha',
            ownerId: 'user-1',
            memberIds: ['user-1'],
            isPublic: false,
            allowedActions: ['view', 'update', 'delete'],
            createdAt: '2026-07-31T00:00:00Z',
            updatedAt: null,
            stats: {},
          },
        ],
        total: 1,
        page: 1,
        pageSize: 20,
        ownerIds: ['user-1'],
      };
    },
    async load() {},
    async retry() {},
    async create() {},
    async update() {},
    async delete() {},
    cancel() {},
    stop() {},
  };
}
