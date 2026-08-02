import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createRuntimeInstancesRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime-instances/runtimeInstancesRouteModule.js');

test('Runtime Instances loader stays lazy and renders a native safe inventory', async () => {
  let bindingCalls = 0;
  const module = await createRuntimeInstancesRouteModuleLoader({
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
  assert.equal(module.routeId, 'tenant-tenant-instances');
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
  assert.match(markup, /Runtime instances/i);
  assert.match(markup, /Primary/);
  assert.match(markup, /runtime_instances_nested_routes_partial/);
  assert.doesNotMatch(markup, /proxy_token|env_vars|webview|iframe|Open in browser/iu);
});

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
        authority: 'cloud',
        state: 'ready',
        reasonCode: 'runtime_instances_nested_routes_partial',
        mutationState: 'idle',
        mutationReasonCode: null,
        busyInstanceId: null,
        retryVisible: false,
        allowedActions: [
          'view',
          'list',
          'refresh',
          'search',
          'filter-status',
          'paginate',
          'restart',
          'delete',
        ],
        instances: [
          {
            id: 'instance-1',
            name: 'Primary',
            status: 'running',
            healthStatus: 'healthy',
            imageVersion: '2026.08',
            replicas: 1,
            availableReplicas: 1,
            clusterId: 'cluster-1',
            createdAt: null,
            updatedAt: null,
            projection: 'cloud',
          },
        ],
        total: 1,
        query: { page: 1, pageSize: 20, search: '', status: 'all' },
        lastUpdatedAt: '2026-08-02T00:00:00Z',
      };
    },
    async load() {},
    async retry() {},
    async setQuery() {},
    async restart() {},
    async delete() {},
    cancel() {},
    stop() {},
  };
}
