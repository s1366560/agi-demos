import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createProjectSupportRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/project-support/projectSupportRouteModule.js'
);

test('Project Support loader stays lazy and renders native ticket authority', async () => {
  let bindingCalls = 0;
  const module = await createProjectSupportRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      assert.equal(context.projectId, 'project-1');
      return {
        controller: controller(),
        scope: scope(),
      };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'project-support');
  assert.equal(module.localPolicy, 'cloud_only');
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
  assert.equal(bindingCalls, 1);
  assert.match(markup, /Need help/);
  assert.match(markup, /Create ticket/);
  assert.match(markup, /Close ticket/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Project Support route fails closed without complete project context', async () => {
  let bindingCalls = 0;
  const module = await createProjectSupportRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return { controller: controller(), scope: scope() };
    },
  })();
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
  assert.equal(bindingCalls, 0);
  assert.match(markup, /project_support_route_context_unavailable/);
});

function scope() {
  return {
    authority: 'cloud',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
}

function controller() {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        state: 'ready',
        scope: scope(),
        authority: 'cloud',
        reasonCode: null,
        retryVisible: false,
        busyAction: null,
        allowedActions: ['view', 'list', 'create', 'close', 'retry'],
        tickets: [
          {
            id: 'ticket-1',
            tenantId: 'tenant-1',
            subject: 'Need help',
            message: 'Something failed',
            priority: 'medium',
            status: 'open',
            createdAt: '2026-08-02T00:00:00Z',
            updatedAt: '2026-08-02T01:00:00Z',
            resolvedAt: null,
            allowedActions: ['view', 'close'],
          },
        ],
        total: 1,
        limit: 25,
        offset: 0,
        hasMore: false,
      };
    },
    async load() {},
    async retry() {},
    async create() {},
    async close() {},
    cancel() {},
    stop() {},
  };
}
