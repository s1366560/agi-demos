import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createRuntimePoolRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime-pool/runtimePoolRouteModule.js');
const {
  RUNTIME_POOL_REFRESH_INTERVAL_MS,
  runtimePoolAutoRefreshAllowed,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime-pool/useRuntimePoolController.js');

test('Runtime Pool refreshes only while visible and no mutation is active', () => {
  assert.equal(RUNTIME_POOL_REFRESH_INTERVAL_MS, 15_000);
  assert.equal(runtimePoolAutoRefreshAllowed('visible', null), true);
  assert.equal(runtimePoolAutoRefreshAllowed('hidden', null), false);
  assert.equal(runtimePoolAutoRefreshAllowed('visible', 'instance-1'), false);
});

test('Cloud Runtime Pool loader stays lazy and renders native lifecycle controls', async () => {
  let bindingCalls = 0;
  const module = await createRuntimePoolRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return { controller: controller(), scope: scope() };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-pool');
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
  assert.match(markup, /Runtime pool/i);
  assert.match(markup, /instance-1/);
  assert.match(markup, /Pause/);
  assert.match(markup, /Terminate/);
  assert.match(markup, /global_pool_capacity_not_available_in_tenant_scope/);
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
    async setQuery() {},
    async pauseInstance() {},
    async resumeInstance() {},
    async terminateInstance() {},
    cancel() {},
    stop() {},
  };
}

function scope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function model() {
  return {
    scope: scope(),
    authority: 'cloud',
    statusState: 'ready',
    instancesState: 'ready',
    metricsState: 'ready',
    statusReasonCode: null,
    instancesReasonCode: null,
    metricsReasonCode: null,
    mutationState: 'idle',
    mutationReasonCode: null,
    retryStatusVisible: false,
    retryInstancesVisible: false,
    retryMetricsVisible: false,
    busyInstanceKey: null,
    allowedActions: [
      'view',
      'refresh',
      'filter',
      'paginate',
      'pause',
      'resume',
      'terminate',
    ],
    status: {
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
      reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
    },
    instances: [
      {
        instanceKey: 'instance-1',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        agentMode: 'chat',
        tier: 'hot',
        status: 'ready',
        createdAt: '2026-08-01T00:00:00Z',
        lastRequestAt: '2026-08-01T00:01:00Z',
        activeRequests: 0,
        totalRequests: 3,
        memoryUsedMb: 128,
        healthStatus: 'healthy',
      },
    ],
    metrics: {
      instances: {
        total: 1,
        byTier: { hot: 1, warm: 0, cold: 0 },
        byStatus: { ready: 1, executing: 0, unhealthy: 0 },
      },
      unhealthyCount: 0,
      prewarm: null,
      reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
    },
    total: 1,
    query: { tier: 'all', status: 'all', page: 1, pageSize: 20 },
    lastUpdatedAt: '2026-08-01T00:02:00Z',
  };
}
