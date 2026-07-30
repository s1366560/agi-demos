import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const {
  createProjectCronJobsRouteModuleLoader,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/automations/projectCronJobsRouteModule.js'
);

const factorySource = readFileSync(
  new URL(
    '../src/features/automations/projectCronJobsRouteModule.tsx',
    import.meta.url,
  ),
  'utf8',
);
const appSource = readFileSync(
  new URL('../src/App.tsx', import.meta.url),
  'utf8',
);

const routeContext = Object.freeze({
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

test('factory stays lazy and publishes the exact Project Cron Jobs route contract', async () => {
  let bindingCalls = 0;
  const loader = createProjectCronJobsRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return binding();
    },
  });

  assert.equal(bindingCalls, 0);
  const module = await loader();
  assert.equal(bindingCalls, 0);
  assert.deepEqual(
    {
      routeId: module.routeId,
      capability: module.capability,
      localPolicy: module.localPolicy,
      disposition: module.disposition,
      availability: module.availability,
      reasonCode: module.reasonCode,
      surfaceType: typeof module.Surface,
    },
    {
      routeId: 'project-project-cron-jobs',
      capability: 'project-project-cron-jobs',
      localPolicy: 'native_equivalent',
      disposition: 'implemented',
      availability: 'available',
      reasonCode: null,
      surfaceType: 'function',
    },
  );
});

test('surface reuses AutomationsPage and binds only exact tenant and project context', async () => {
  const receivedContexts = [];
  const module = await createProjectCronJobsRouteModuleLoader({
    createBinding(context) {
      receivedContexts.push(context);
      return binding();
    },
  })();

  const markup = renderRoute(module, routeContext);

  assert.deepEqual(receivedContexts, [routeContext]);
  assert.match(markup, /class="automations-page"/u);
  assert.match(markup, /Project One/u);
  assert.match(factorySource, /import\('\.\/AutomationsPage'\)/u);
  assert.match(factorySource, /<AutomationsPage/u);
  assert.doesNotMatch(
    factorySource,
    /window\.location|document\.location|new URL\(|URLSearchParams|RegExp\(|\.match\(/u,
  );
});

test('missing tenant or project context fails closed without creating a binding', async () => {
  let bindingCalls = 0;
  const module = await createProjectCronJobsRouteModuleLoader({
    createBinding() {
      bindingCalls += 1;
      return binding();
    },
  })();

  for (const context of [
    { projectId: 'project-1' },
    { tenantId: 'tenant-1' },
    { tenantId: ' ', projectId: 'project-1' },
    { tenantId: 'tenant-1', projectId: '\n' },
  ]) {
    const markup = renderRoute(module, context);
    assert.match(
      markup,
      /data-reason-code="project_cron_jobs_route_context_unavailable"/u,
    );
  }
  assert.equal(bindingCalls, 0);
});

test('binding scope drift fails closed before exposing automation authority', async () => {
  const calls = [];
  const module = await createProjectCronJobsRouteModuleLoader({
    createBinding() {
      return binding({
        scope: {
          tenantId: 'tenant-1',
          projectId: 'project-other',
        },
        api: automationApi({
          async listAutomations() {
            calls.push('list');
            throw new Error('automation authority must stay unreachable');
          },
        }),
      });
    },
  })();

  const markup = renderRoute(module, routeContext);

  assert.match(
    markup,
    /data-reason-code="project_cron_jobs_route_binding_scope_mismatch"/u,
  );
  assert.deepEqual(calls, []);
});

test('AutomationsPage code loads only behind the production route loader boundary', () => {
  assert.match(factorySource, /import\('\.\/AutomationsPage'\)/u);
  assert.match(
    factorySource,
    /key=\{`\$\{context\.tenantId\}:\$\{context\.projectId\}`\}/u,
  );
  assert.match(factorySource, /const binding = createBinding\(context\)/u);
  assert.doesNotMatch(factorySource, /useMemo/u);
  assert.doesNotMatch(
    factorySource,
    /import\s+\{\s*AutomationsPage\s*\}\s+from/u,
  );
  assert.doesNotMatch(
    appSource,
    /import\s+\{\s*AutomationsPage\s*\}\s+from/u,
  );
});

function renderRoute(module, context) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { module, context }),
    ),
  );
}

function binding(overrides = {}) {
  return {
    api: automationApi(),
    scope: routeContext,
    projectName: 'Project One',
    runCapability: availableCapability(),
    onOpenProjectSettings() {},
    onOpenConnection() {},
    ...overrides,
  };
}

function automationApi(overrides = {}) {
  return {
    async createAutomation() {
      throw new Error('not used');
    },
    async deleteAutomation() {
      throw new Error('not used');
    },
    async getAutomationCapabilities() {
      return automationCapabilities();
    },
    async listAutomations() {
      return { items: [], total: 0 };
    },
    async listAutomationRuns() {
      return { items: [], total: 0 };
    },
    async runAutomation() {
      throw new Error('not used');
    },
    async toggleAutomation() {
      throw new Error('not used');
    },
    async updateAutomation() {
      throw new Error('not used');
    },
    ...overrides,
  };
}

function automationCapabilities() {
  return {
    schema_version: 2,
    read: true,
    revision_guarded: true,
    idempotency_guarded: true,
    durable_execution: true,
    supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
    create: { allowed: true },
    edit: { allowed: true },
    toggle: { allowed: true },
    run_now: { allowed: true },
    delete: { allowed: true },
  };
}

function availableCapability() {
  return Object.freeze({
    availability: 'available',
    status: 'available',
    available: true,
    reason_code: null,
    service_version: '3.0.0',
    contract_version: '3.0.0',
    allowed_actions: Object.freeze(['run_now']),
    scope: Object.freeze({
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: 7,
  });
}
