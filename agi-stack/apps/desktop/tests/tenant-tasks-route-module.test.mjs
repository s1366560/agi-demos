import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createTenantTasksRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantTasksRouteModule.js');
const {
  TENANT_TASKS_REFRESH_INTERVAL_MS,
  tenantTasksAutoRefreshAllowed,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant/useTenantTasksController.js');

test('Tenant Tasks refreshes every five seconds only while visible and settled', () => {
  assert.equal(TENANT_TASKS_REFRESH_INTERVAL_MS, 5_000);
  assert.equal(tenantTasksAutoRefreshAllowed('visible', 'ready', null), true);
  assert.equal(tenantTasksAutoRefreshAllowed('visible', 'degraded', null), true);
  assert.equal(tenantTasksAutoRefreshAllowed('hidden', 'ready', null), false);
  assert.equal(tenantTasksAutoRefreshAllowed('visible', 'loading', null), false);
  assert.equal(
    tenantTasksAutoRefreshAllowed('visible', 'ready', 'retry-task:task-1'),
    false,
  );
});

test('Tenant Tasks loader stays lazy and renders the complete native dashboard shell', async () => {
  let bindingCalls = 0;
  const module = await createTenantTasksRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return { controller: controller(), scope: scope() };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-tasks');
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
  assert.match(markup, /Task Dashboard/);
  assert.match(markup, /Process episode/);
  assert.match(markup, /Resume pending/);
  assert.match(markup, /Dead letter queue/);
  assert.match(markup, /#\/tenant\/tenant-1\/dead-letter-queue/);
  assert.match(markup, /Search tasks/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Tenant Tasks route fails closed without tenant context', async () => {
  let bindingCalls = 0;
  const module = await createTenantTasksRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return { controller: controller(), scope: scope() };
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
  assert.match(markup, /tenant_tasks_route_context_unavailable/);
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
        allowedActions: [
          'view',
          'list',
          'search',
          'filter',
          'paginate',
          'refresh',
          'retry-task',
          'stop-task',
          'retry-pending',
          'navigate-dead-letter-queue',
        ],
        stats: {
          total: 1,
          pending: 1,
          processing: 0,
          completed: 0,
          failed: 0,
          throughputPerMinute: 0,
          errorRate: 0,
        },
        queue: { current: 1, history: [{ timestamp: '12:00', depth: 1 }] },
        tasks: [
          {
            id: 'task-1',
            projectId: null,
            workspaceId: null,
            conversationId: null,
            taskType: 'add_episode',
            name: 'Process episode',
            status: 'pending',
            createdAt: '2026-07-31T00:00:00Z',
            completedAt: null,
            error: null,
            duration: null,
            entityId: 'episode-1',
            entityType: 'episode',
            revision: null,
            canRetry: true,
            canStop: true,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
        hasMore: false,
        query: { search: '', status: 'all', limit: 50, offset: 0 },
        lastUpdatedAt: '2026-07-31T00:00:00Z',
      };
    },
    async load() {},
    async retry() {},
    async setQuery() {},
    async retryTask() {},
    async stopTask() {},
    async retryPending() {},
    cancel() {},
    stop() {},
  };
}
