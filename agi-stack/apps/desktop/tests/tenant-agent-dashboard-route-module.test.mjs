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
  createTenantAgentDashboardRouteModuleLoader,
} = require('/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAgentDashboardRouteModule.js');

test('Agent Dashboard loader renders the native config and trace surface', async () => {
  const module = await createTenantAgentDashboardRouteModuleLoader({
    createBinding() {
      return { controller: controller(), scope: scope() };
    },
  })();
  assert.equal(module.routeId, 'tenant-tenant-agent-configuration');
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
  assert.match(markup, /Agent Dashboard/);
  assert.match(markup, /gpt-5.6/);
  assert.match(markup, /Researcher/);
  assert.match(markup, /Edit configuration/);
  assert.match(markup, /Agent runtime/);
  assert.match(markup, /ray/);
  assert.match(markup, /120 tokens/);
  assert.match(markup, /conversation-1/);
  assert.match(markup, /trace-1/);
  assert.doesNotMatch(markup, /iframe|webview|Open in browser/iu);
});

function scope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
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
        configConflict: null,
        retryVisible: false,
        busyAction: null,
        allowedActions: [
          'view-config',
          'update-config',
          'view-hook-catalog',
          'list-runs',
          'filter-runs',
          'inspect-run',
          'inspect-trace',
          'refresh',
          'retry',
        ],
        authorityRevision: 7,
        canModify: true,
        config: {
          id: 'config-1',
          tenantId: 'tenant-1',
          configType: 'tenant',
          llmModel: 'gpt-5.6',
          llmTemperature: 0.2,
          patternLearningEnabled: true,
          multiLevelThinkingEnabled: false,
          maxWorkPlanSteps: 10,
          toolTimeoutSeconds: 60,
          enabledTools: ['read_file'],
          disabledTools: [],
          runtimeHooks: [],
          runtimeHookSettingsRedacted: false,
          multiAgentEnabled: true,
          authorityRevision: 7,
          createdAt: '2026-08-03T00:00:00Z',
          updatedAt: '2026-08-03T00:00:00Z',
        },
        hookCatalog: [],
        runtimeInfo: {
          edition: 'enterprise',
          features: [],
          agentRuntimeMode: 'ray',
          memoryRuntimeMode: 'dual',
          toolProviderMode: 'plugin',
          failurePersistenceEnabled: true,
        },
        runs: [
          {
            runId: 'run-1',
            conversationId: 'conversation-1',
            subagentName: 'Researcher',
            task: 'Audit runtime',
            status: 'running',
            createdAt: '2026-08-03T00:00:00Z',
            startedAt: '2026-08-03T00:00:01Z',
            endedAt: null,
            summary: null,
            error: null,
            executionTimeMs: null,
            tokensUsed: 120,
            traceId: 'trace-1',
            parentSpanId: null,
          },
        ],
        visibleRuns: [
          {
            runId: 'run-1',
            conversationId: 'conversation-1',
            subagentName: 'Researcher',
            task: 'Audit runtime',
            status: 'running',
            createdAt: '2026-08-03T00:00:00Z',
            startedAt: '2026-08-03T00:00:01Z',
            endedAt: null,
            summary: null,
            error: null,
            executionTimeMs: null,
            tokensUsed: 120,
            traceId: 'trace-1',
            parentSpanId: null,
          },
        ],
        activeRunCount: 1,
        filters: { status: null, search: '' },
        selectedRunId: 'run-1',
        selectedTrace: {
          traceId: 'trace-1',
          conversationId: 'conversation-1',
          runs: [
            {
              runId: 'run-1',
              conversationId: 'conversation-1',
              subagentName: 'Researcher',
              task: 'Audit runtime',
              status: 'running',
              createdAt: '2026-08-03T00:00:00Z',
              startedAt: '2026-08-03T00:00:01Z',
              endedAt: null,
              summary: null,
              error: null,
              executionTimeMs: null,
              tokensUsed: 120,
              traceId: 'trace-1',
              parentSpanId: null,
            },
          ],
          total: 1,
        },
      };
    },
    async load() {},
    async retry() {},
    setFilters() {},
    async inspectRun() {},
    clearSelection() {},
    async updateConfig() {},
    cancel() {},
    stop() {},
  };
}
