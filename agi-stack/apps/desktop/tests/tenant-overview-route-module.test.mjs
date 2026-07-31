import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createDesktopProductionRouteRegistry,
  PROJECT_CRON_JOBS_ROUTE_ID,
  PROJECT_OVERVIEW_ROUTE_ID,
  PROJECT_SEARCH_ROUTE_ID,
  TENANT_OVERVIEW_ROUTE_ID,
  TENANT_PROJECTS_ROUTE_ID,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js'
);
const {
  createTenantOverviewRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantOverviewRouteModule.js'
);

test('Tenant Overview loader stays lazy and renders the exact tenant binding', async () => {
  let bindingCalls = 0;
  const tenantLoader = createTenantOverviewRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return {
        controller: controller(),
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
      };
    },
  });
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders: {
      [TENANT_OVERVIEW_ROUTE_ID]: tenantLoader,
      [PROJECT_OVERVIEW_ROUTE_ID]: fakeLoader(PROJECT_OVERVIEW_ROUTE_ID),
      [PROJECT_SEARCH_ROUTE_ID]: fakeLoader(PROJECT_SEARCH_ROUTE_ID),
      [PROJECT_CRON_JOBS_ROUTE_ID]: fakeLoader(PROJECT_CRON_JOBS_ROUTE_ID),
      [TENANT_PROJECTS_ROUTE_ID]: fakeLoader(TENANT_PROJECTS_ROUTE_ID),
    },
  });
  assert.equal(bindingCalls, 0);
  const module = await registry.byId.get(TENANT_OVERVIEW_ROUTE_ID).loader();
  assert.equal(module.routeId, TENANT_OVERVIEW_ROUTE_ID);
  assert.equal(module.disposition, 'implemented');
  assert.equal(module.availability, 'available');
  assert.equal(bindingCalls, 0);

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
  assert.match(markup, /#TEN-ABC/);
  assert.match(markup, /tenant-1/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Tenant Overview route fails closed without a tenant context', async () => {
  let bindingCalls = 0;
  const module = await createTenantOverviewRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return {
        controller: controller(),
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
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
  assert.match(markup, /tenant_overview_route_context_unavailable/);
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
        tenant: {
          organizationId: '#TEN-ABC',
          plan: 'Pro',
          region: null,
          nextBillingDate: null,
        },
        summary: [
          {
            id: 'projects',
            availability: 'available',
            reasonCode: null,
            value: 1,
          },
        ],
        projects: [],
        memoryHistory: {
          availability: 'available',
          reasonCode: null,
          value: [],
        },
      };
    },
    async load() {},
    async retry() {},
    cancel() {},
    stop() {},
  };
}

function fakeLoader(routeId) {
  return async () => ({
    routeId,
    capability: routeId,
    localPolicy: 'native_equivalent',
    disposition: 'implemented',
    availability: 'available',
    reasonCode: null,
    Surface() {
      return null;
    },
  });
}
