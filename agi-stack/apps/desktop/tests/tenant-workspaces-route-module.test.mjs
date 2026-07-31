import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createTenantWorkspacesRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantWorkspacesRouteModule.js');

test('Tenant Workspaces loader stays lazy and renders a native list/create surface', async () => {
  let bindingCalls = 0;
  const module = await createTenantWorkspacesRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return {
        controller: controller(),
        scope: {
          authority: 'cloud',
          tenantId: 'tenant-1',
          projectId: 'project-1',
        },
      };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-workspaces');
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
  assert.match(markup, /Alpha workspace/);
  assert.match(markup, /Create workspace/);
  assert.match(markup, /project-1/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Tenant Workspaces route fails closed without tenant context', async () => {
  let bindingCalls = 0;
  const module = await createTenantWorkspacesRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return {
        controller: controller(),
        scope: {
          authority: 'cloud',
          tenantId: 'tenant-1',
          projectId: 'project-1',
        },
      };
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
  assert.match(markup, /tenant_workspaces_route_context_unavailable/);
});

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        state: 'degraded',
        scope: {
          authority: 'cloud',
          tenantId: 'tenant-1',
          projectId: 'project-1',
        },
        authority: 'cloud',
        reasonCode: 'desktop_tenant_workspaces_advanced_management_partial',
        retryVisible: false,
        busyAction: null,
        allowedActions: ['view', 'list', 'create'],
        workspaces: [
          {
            id: 'workspace-1',
            tenantId: 'tenant-1',
            projectId: 'project-1',
            name: 'Alpha workspace',
            description: 'Native workspace',
            status: 'active',
            archived: false,
            createdAt: '2026-07-31T00:00:00Z',
            updatedAt: null,
          },
        ],
      };
    },
    async load() {},
    async retry() {},
    async create() {},
    cancel() {},
    stop() {},
  };
}
