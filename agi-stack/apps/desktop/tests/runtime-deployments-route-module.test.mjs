import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createRuntimeDeploymentsRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime-deployments/runtimeDeploymentsRouteModule.js');

test('Runtime Deployments loader stays lazy and renders a native read-only history', async () => {
  let bindingCalls = 0;
  const module = await createRuntimeDeploymentsRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      assert.equal(context.instanceId, 'instance-1');
      return {
        scope: {
          authority: 'cloud',
          tenantId: 'tenant-1',
          instanceId: 'instance-1',
        },
        controller: controller(),
      };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-deploy');
  assert.equal(module.localPolicy, 'cloud_only');

  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, {
        context: { tenantId: 'tenant-1', instanceId: 'instance-1' },
        module,
      }),
    ),
  );
  assert.equal(bindingCalls, 1);
  assert.match(markup, /Deployment history/i);
  assert.match(markup, /deploy-1/);
  assert.match(
    markup,
    /runtime_deployments_mutations_and_instance_discovery_partial/,
  );
  assert.doesNotMatch(
    markup,
    /create deployment|cancel deployment|mark success|mark failed|webview|iframe|Open in browser/iu,
  );
});

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      const deployments = [
        {
          id: 'deploy-1',
          instanceId: 'instance-1',
          action: 'update',
          revision: 7,
          status: 'running',
          imageVersion: 'v1.2.3',
          replicas: 3,
          startedAt: '2026-08-02T08:00:00Z',
          finishedAt: null,
          createdAt: '2026-08-02T07:59:00Z',
        },
      ];
      return {
        scope: {
          authority: 'cloud',
          tenantId: 'tenant-1',
          instanceId: 'instance-1',
        },
        authority: 'cloud',
        state: 'ready',
        reasonCode:
          'runtime_deployments_mutations_and_instance_discovery_partial',
        retryVisible: false,
        allowedActions: [
          'view',
          'list',
          'refresh',
          'paginate',
          'inspect-progress',
          'reconnect-progress',
        ],
        deployments,
        total: 1,
        query: { page: 1, pageSize: 10 },
        selectedDeployment: null,
        detailState: 'idle',
        detailReasonCode: null,
        progressState: 'idle',
        progressReasonCode: null,
        progressRetryVisible: false,
        lastUpdatedAt: '2026-08-02T08:00:00Z',
      };
    },
    async load() {},
    async retry() {},
    async setQuery() {},
    async inspect() {},
    closeDetail() {},
    async reconnectProgress() {},
    cancel() {},
    stop() {},
  };
}
