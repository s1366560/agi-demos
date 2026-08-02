import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createTenantAnalyticsRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAnalyticsRouteModule.js'
);

test('Tenant Analytics loader stays lazy and renders the exact tenant binding', async () => {
  let bindingCalls = 0;
  const module = await createTenantAnalyticsRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return {
        controller: controller(),
        scope: { authority: 'cloud', tenantId: 'tenant-1', period: '30d' },
        tenantPlan: 'Pro',
      };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-analytics');
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
  assert.match(markup, /tenant-1/);
  assert.match(markup, /Pro/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Tenant Analytics route fails closed without tenant context', async () => {
  let bindingCalls = 0;
  const module = await createTenantAnalyticsRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      throw new Error('must not bind');
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
  assert.match(markup, /tenant_analytics_route_context_unavailable/);
});

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        state: 'ready',
        scope: { authority: 'cloud', tenantId: 'tenant-1', period: '30d' },
        authority: 'cloud',
        reasonCode: null,
        retryVisible: false,
        summary: [
          {
            id: 'projects',
            availability: 'available',
            reasonCode: null,
            value: '1',
          },
        ],
        trend: null,
        memoryGrowth: {
          availability: 'available',
          reasonCode: null,
          points: [],
        },
        projects: [],
      };
    },
    async load() {},
    async retry() {},
    cancel() {},
    stop() {},
  };
}
