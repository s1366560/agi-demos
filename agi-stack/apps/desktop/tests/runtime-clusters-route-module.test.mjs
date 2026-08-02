import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createRuntimeClustersRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime-clusters/runtimeClustersRouteModule.js');

test('Runtime Clusters loader stays lazy and renders a native safe inventory', async () => {
  let bindingCalls = 0;
  const module = await createRuntimeClustersRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return {
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
        controller: controller(),
      };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-clusters');
  assert.equal(module.localPolicy, 'cloud_only');

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
  assert.match(markup, /Runtime clusters/i);
  assert.match(markup, /Primary/);
  assert.match(markup, /runtime_clusters_detail_and_mutations_partial/);
  assert.doesNotMatch(
    markup,
    /credentials_encrypted|provider_config|registration_token|webview|iframe|Open in browser/iu,
  );
});

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      const clusters = [
        {
          id: 'cluster-1',
          name: 'Primary',
          computeProvider: 'kubernetes',
          proxyEndpoint: 'https://cluster.example.test',
          status: 'active',
          healthStatus: 'healthy',
          lastHealthCheck: null,
          createdAt: null,
          updatedAt: null,
        },
      ];
      return {
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
        authority: 'cloud',
        state: 'ready',
        reasonCode: 'runtime_clusters_detail_and_mutations_partial',
        healthState: 'idle',
        healthReasonCode: null,
        selectedClusterId: null,
        retryVisible: false,
        allowedActions: [
          'view',
          'list',
          'refresh',
          'search-current-page',
          'filter-status-current-page',
          'paginate',
          'inspect-health',
        ],
        clusters,
        visibleClusters: clusters,
        health: null,
        total: 1,
        query: { page: 1, pageSize: 20, search: '', status: 'all' },
        lastUpdatedAt: '2026-08-02T00:00:00Z',
      };
    },
    async load() {},
    async retry() {},
    async setQuery() {},
    async setFilters() {},
    async inspectHealth() {},
    closeHealth() {},
    cancel() {},
    stop() {},
  };
}
