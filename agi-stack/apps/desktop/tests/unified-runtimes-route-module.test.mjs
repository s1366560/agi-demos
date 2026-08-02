import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createUnifiedRuntimesRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/unified-runtimes/unifiedRuntimesRouteModule.js');
const {
  UNIFIED_RUNTIMES_REFRESH_INTERVAL_MS,
  unifiedRuntimesAutoRefreshAllowed,
} = require('/tmp/agistack-desktop-test-dist/src/features/unified-runtimes/useUnifiedRuntimesController.js');

test('Unified Runtimes refreshes only while the native route is visible', () => {
  assert.equal(UNIFIED_RUNTIMES_REFRESH_INTERVAL_MS, 15_000);
  assert.equal(unifiedRuntimesAutoRefreshAllowed('visible'), true);
  assert.equal(unifiedRuntimesAutoRefreshAllowed('hidden'), false);
  assert.equal(unifiedRuntimesAutoRefreshAllowed('prerender'), false);
});

test('Unified Runtimes loader stays lazy and renders the native authority inventory', async () => {
  let bindingCalls = 0;
  const module = await createUnifiedRuntimesRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return { controller: controller(), scope: scope() };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-runtimes');
  assert.equal(module.disposition, 'implemented');
  assert.equal(module.localPolicy, 'native_equivalent');

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
  assert.match(markup, /Unified runtimes/i);
  assert.match(markup, /pool-instance-1/);
  assert.match(markup, /sandbox-1/);
  assert.match(markup, /cloud_runtime_inventory_native_projection/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return model();
    },
    async load() {},
    async retry() {},
    cancel() {},
    stop() {},
  };
}

function scope() {
  return {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
}

function model() {
  return {
    scope: scope(),
    authority: 'cloud',
    availability: 'available',
    reasonCode: 'cloud_runtime_inventory_native_projection',
    poolState: 'ready',
    sandboxState: 'ready',
    sidecarState: 'not_applicable',
    capabilitiesState: 'not_applicable',
    poolReasonCode: null,
    sandboxReasonCode: null,
    sidecarReasonCode: 'cloud_sidecar_not_applicable',
    capabilitiesReasonCode: 'cloud_sidecar_capabilities_not_applicable',
    retryPoolVisible: false,
    retrySandboxVisible: false,
    retrySidecarVisible: false,
    retryCapabilitiesVisible: false,
    allowedActions: ['view', 'refresh', 'filter', 'toggle-auto-refresh'],
    poolStatus: {
      enabled: true,
      status: 'running',
      totalInstances: 1,
      hotInstances: 1,
      warmInstances: 0,
      coldInstances: 0,
      readyInstances: 1,
      executingInstances: 0,
      unhealthyInstances: 0,
      prewarmPool: null,
      resourceUsage: null,
      reasonCode: null,
    },
    rows: [
      {
        key: 'pool:pool-instance-1',
        kind: 'pool_actor',
        identifier: 'pool-instance-1',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        status: 'ready',
        health: 'healthy',
        tier: 'hot',
        loadLabel: '0 active',
        memoryMb: 128,
        lastActivity: '2026-08-01T00:00:00Z',
      },
      {
        key: 'sandbox:sandbox-1',
        kind: 'sandbox',
        identifier: 'sandbox-1',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        status: 'running',
        health: 'healthy',
        tier: null,
        loadLabel: null,
        memoryMb: null,
        lastActivity: '2026-08-01T00:01:00Z',
      },
    ],
    lastUpdatedAt: '2026-08-01T00:02:00Z',
  };
}
