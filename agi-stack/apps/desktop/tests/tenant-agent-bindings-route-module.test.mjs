import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { Theme } = require('@radix-ui/themes');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createTenantAgentBindingsRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAgentBindingsRouteModule.js'
);

test('Agent Bindings loader stays lazy and renders the exact native tenant binding', async () => {
  let bindingCalls = 0;
  const module = await createTenantAgentBindingsRouteModuleLoader({
    createBinding(context) {
      bindingCalls += 1;
      assert.equal(context.tenantId, 'tenant-1');
      return {
        controller: controller(),
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
      };
    },
  })();
  assert.equal(bindingCalls, 0);
  assert.equal(module.routeId, 'tenant-tenant-agent-bindings');
  assert.equal(module.disposition, 'implemented');

  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(
        Theme,
        null,
        React.createElement(module.Surface, {
          context: { tenantId: 'tenant-1' },
          module,
        }),
      ),
    ),
  );
  assert.equal(bindingCalls, 1);
  assert.match(markup, /Agent Bindings/);
  assert.match(markup, /Support/);
  assert.match(markup, /Create binding/);
  assert.match(markup, /Test routing/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

test('Agent Bindings route fails closed without tenant context', async () => {
  let bindingCalls = 0;
  const module = await createTenantAgentBindingsRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      throw new Error('must not bind');
    },
  })();
  const markup = renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(
        Theme,
        null,
        React.createElement(module.Surface, { context: {}, module }),
      ),
    ),
  );
  assert.equal(bindingCalls, 0);
  assert.match(markup, /tenant_agent_bindings_route_context_unavailable/);
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
        busyAction: null,
        allowedActions: [
          'view',
          'list',
          'create',
          'delete',
          'set-enabled',
          'test',
        ],
        bindings: [
          {
            id: 'binding-1',
            tenantId: 'tenant-1',
            agentId: 'agent-1',
            agentName: 'Support',
            channelType: 'slack',
            channelId: 'channel-1',
            accountId: null,
            peerId: null,
            groupId: null,
            priority: 0,
            enabled: true,
            createdAt: '2026-08-03T00:00:00Z',
            specificityScore: 3,
          },
        ],
        visibleBindings: [
          {
            id: 'binding-1',
            tenantId: 'tenant-1',
            agentId: 'agent-1',
            agentName: 'Support',
            channelType: 'slack',
            channelId: 'channel-1',
            accountId: null,
            peerId: null,
            groupId: null,
            priority: 0,
            enabled: true,
            createdAt: '2026-08-03T00:00:00Z',
            specificityScore: 3,
          },
        ],
        definitions: [
          { id: 'agent-1', name: 'support', displayName: 'Support' },
        ],
        filters: { search: '', channelType: null, enabled: null },
        emptyReason: null,
        testResult: null,
      };
    },
    async load() {},
    async retry() {},
    setFilters() {},
    async create() {},
    async delete() {},
    async setEnabled() {},
    async test() {},
    cancel() {},
    stop() {},
  };
}
