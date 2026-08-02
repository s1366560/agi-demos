import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createInstanceTemplatesRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/instance-templates/instanceTemplatesRouteModule.js');

test('Instance Templates loader stays lazy and renders the native lifecycle surface', async () => {
  let bindingCalls = 0;
  const module = await createInstanceTemplatesRouteModuleLoader({
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
  assert.equal(module.routeId, 'tenant-tenant-instance-templates');
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
  assert.match(markup, /Instance templates/i);
  assert.match(markup, /Starter/);
  assert.match(markup, /instance_templates_nested_deep_link_and_deploy_partial/);
  assert.doesNotMatch(markup, /webview|iframe|Open in browser/iu);
});

function controller() {
  const templates = [
    {
      id: 'template-1',
      name: 'Starter',
      slug: 'starter',
      tenantId: 'tenant-1',
      description: 'Safe starter',
      icon: null,
      imageVersion: 'v1',
      defaultConfig: { cpu: 2 },
      isPublished: false,
      isFeatured: false,
      installCount: 3,
      createdAt: '2026-08-02T08:00:00Z',
      updatedAt: null,
    },
  ];
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        scope: { authority: 'cloud', tenantId: 'tenant-1' },
        authority: 'cloud',
        state: 'ready',
        reasonCode: 'instance_templates_nested_deep_link_and_deploy_partial',
        retryVisible: false,
        allowedActions: [
          'view',
          'list',
          'list-items',
          'create',
          'delete',
          'publish',
          'clone',
          'refresh',
          'paginate',
          'search-current-page',
          'filter-status',
        ],
        templates,
        visibleTemplates: templates,
        total: 1,
        query: { page: 1, pageSize: 20, search: '', status: 'all' },
        selectedTemplate: null,
        detailState: 'idle',
        detailReasonCode: null,
        items: [],
        mutationState: 'idle',
        mutationReasonCode: null,
        lastUpdatedAt: '2026-08-02T08:00:00Z',
      };
    },
    async load() {},
    async retry() {},
    async setQuery() {},
    async setFilters() {},
    async inspect() {},
    closeDetail() {},
    async create() {},
    async delete() {},
    async publish() {},
    async clone() {},
    cancel() {},
    stop() {},
  };
}
