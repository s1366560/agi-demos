import assert from 'node:assert/strict';
import Module, { createRequire } from 'node:module';
import { test } from 'node:test';

process.env.NODE_PATH = new URL('../node_modules', import.meta.url).pathname;
Module._initPaths();

const require = createRequire(import.meta.url);
const compiled = '/tmp/agistack-desktop-test-dist/src/features/project-agent';
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');

const { createProjectAgentDashboardClient, PROJECT_AGENT_DASHBOARD_LOCAL_REASON } = require(
  `${compiled}/projectAgentDashboardClient.js`,
);
const { createProjectAgentLogsClient, PROJECT_AGENT_LOGS_LOCAL_REASON } = require(
  `${compiled}/projectAgentLogsClient.js`,
);
const { createProjectAgentPatternsClient, PROJECT_AGENT_PATTERNS_LOCAL_REASON } = require(
  `${compiled}/projectAgentPatternsClient.js`,
);
const { createProjectAgentLogsController } = require(`${compiled}/projectAgentLogsController.js`);
const { createProjectAgentDashboardController } = require(
  `${compiled}/projectAgentDashboardController.js`,
);
const { createProjectAgentPatternsController } = require(
  `${compiled}/projectAgentPatternsController.js`,
);
const { createProjectAgentDashboardRouteModuleLoader } = require(
  `${compiled}/projectAgentDashboardRouteModule.js`,
);
const { createProjectAgentLogsRouteModuleLoader } = require(
  `${compiled}/projectAgentLogsRouteModule.js`,
);
const { createProjectAgentPatternsRouteModuleLoader } = require(
  `${compiled}/projectAgentPatternsRouteModule.js`,
);

const cloudConfig = Object.freeze({
  apiBaseUrl: 'https://cloud.memstack.test',
  deviceAuthorizationBaseUrl: 'https://cloud.memstack.test',
  apiKey: 'trusted-session',
  localApiToken: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: '',
  mode: 'cloud',
  workspaceRoot: '',
});
const localConfig = Object.freeze({
  ...cloudConfig,
  apiBaseUrl: 'http://127.0.0.1:43117',
  deviceAuthorizationBaseUrl: 'http://127.0.0.1:43117',
  localApiToken: 'private-launch',
  mode: 'local',
});
const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const localScope = Object.freeze({ ...cloudScope, authority: 'local' });

test('Project Agent Cloud clients use trusted-session project authorities and exact scope', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    requests.push({ input: String(input), init });
    const url = new URL(String(input));
    if (url.pathname === '/api/v1/workspace-context') {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 17,
          updated_at: '2026-08-05T00:00:00Z',
        },
        membership_role: 'member',
      });
    }
    if (url.pathname === '/api/v1/agent/trace/runs/project/project-1') {
      return jsonResponse({ project_id: 'project-1', runs: [run()], total: 1 });
    }
    if (url.pathname === '/api/v1/agent/trace/runs/project/project-1/active/count') {
      return jsonResponse({ project_id: 'project-1', active_count: 1 });
    }
    if (url.pathname === '/api/v1/agent/workflows/patterns/project/project-1') {
      return jsonResponse({
        project_id: 'project-1',
        tenant_id: 'tenant-1',
        scope_kind: 'tenant_shared',
        patterns: [pattern()],
        total: 1,
        page: 1,
        page_size: 100,
      });
    }
    throw new Error(`unexpected request: ${String(input)}`);
  };
  try {
    const dashboard = await createProjectAgentDashboardClient(cloudConfig).load(cloudScope);
    const logs = await createProjectAgentLogsClient(cloudConfig).load(cloudScope, {
      status: 'completed',
    });
    const patterns = await createProjectAgentPatternsClient(cloudConfig).load(cloudScope);
    assert.equal(dashboard.activeCount, 1);
    assert.equal(dashboard.scopeRevision, 17);
    assert.equal(logs.runs[0].id, 'run-1');
    assert.equal(patterns.scopeKind, 'tenant_shared');
    assert.equal(patterns.patterns[0].tenantId, 'tenant-1');
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.ok(requests.length >= 7);
  for (const request of requests) {
    const headers = new Headers(request.init.headers);
    assert.equal(headers.get('Authorization'), 'Bearer trusted-session');
    assert.equal(headers.get('X-Agistack-Launch'), null);
    assert.equal(request.init.credentials, 'omit');
  }
});

test('Project Agent Local clients fail closed with stable reasons before network access', async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    throw new Error('Local route must not call Cloud authority');
  };
  try {
    const cases = [
      [createProjectAgentDashboardClient(localConfig), PROJECT_AGENT_DASHBOARD_LOCAL_REASON],
      [createProjectAgentLogsClient(localConfig), PROJECT_AGENT_LOGS_LOCAL_REASON],
      [createProjectAgentPatternsClient(localConfig), PROJECT_AGENT_PATTERNS_LOCAL_REASON],
    ];
    for (const [client, reasonCode] of cases) {
      await assert.rejects(client.load(localScope), (error) => {
        assert.equal(error.status, 501);
        assert.equal(error.payload.reason_code, reasonCode);
        return true;
      });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(fetchCalls, 0);
});

test('Project Agent clients reject mismatched authority responses', async () => {
  const originalFetch = globalThis.fetch;
  let call = 0;
  globalThis.fetch = async () => {
    call += 1;
    if (call === 1) {
      return jsonResponse({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 2,
          updated_at: '2026-08-05T00:00:00Z',
        },
        membership_role: 'member',
      });
    }
    return jsonResponse({ project_id: 'other-project', runs: [], total: 0 });
  };
  try {
    await assert.rejects(
      createProjectAgentLogsClient(cloudConfig).load(cloudScope),
      /project_agent_logs_scope_conflict/u,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Project Agent controller ignores stale completions and maps forbidden state', async () => {
  const first = deferred();
  const second = deferred();
  let call = 0;
  const controller = createProjectAgentLogsController({
    authority: 'cloud',
    client: {
      load() {
        call += 1;
        return call === 1 ? first.promise : second.promise;
      },
    },
    initialScope: cloudScope,
  });
  const projectTwo = Object.freeze({ ...cloudScope, projectId: 'project-2' });
  const firstLoad = controller.load(cloudScope);
  const secondLoad = controller.load(projectTwo);
  second.resolve(logSnapshot(projectTwo, 'second'));
  await secondLoad;
  first.resolve(logSnapshot(cloudScope, 'first'));
  await firstLoad;
  assert.equal(controller.getSnapshot().scope.projectId, 'project-2');
  assert.equal(controller.getSnapshot().items[0].title, 'second');

  const forbidden = createProjectAgentLogsController({
    authority: 'cloud',
    client: {
      async load() {
        const error = new Error('forbidden');
        error.status = 403;
        error.payload = { reason_code: 'project_agent_logs_forbidden' };
        throw error;
      },
    },
    initialScope: cloudScope,
  });
  await forbidden.load(cloudScope);
  assert.equal(forbidden.getSnapshot().state, 'forbidden');
  assert.equal(forbidden.getSnapshot().reasonCode, 'project_agent_logs_forbidden');
});

test('Project Agent controllers map backend-shaped plain 403 responses to stable route reasons', async () => {
  const originalFetch = globalThis.fetch;
  const cases = [
    [
      createProjectAgentDashboardClient,
      createProjectAgentDashboardController,
      'project_agent_dashboard_forbidden',
    ],
    [
      createProjectAgentLogsClient,
      createProjectAgentLogsController,
      'project_agent_logs_forbidden',
    ],
    [
      createProjectAgentPatternsClient,
      createProjectAgentPatternsController,
      'project_agent_patterns_forbidden',
    ],
  ];
  try {
    for (const [createClient, createController, reasonCode] of cases) {
      globalThis.fetch = async (input) => {
        const url = new URL(String(input));
        if (url.pathname === '/api/v1/workspace-context') {
          return jsonResponse({
            context: {
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              revision: 23,
            },
          });
        }
        return jsonResponse({ detail: 'Project access required' }, 403);
      };
      const controller = createController({
        authority: 'cloud',
        client: createClient(cloudConfig),
        initialScope: cloudScope,
      });

      await controller.load(cloudScope);

      assert.equal(controller.getSnapshot().state, 'forbidden');
      assert.equal(controller.getSnapshot().reasonCode, reasonCode);
      assert.doesNotMatch(controller.getSnapshot().reasonCode, /^HTTP /u);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('Project Agent controllers map unstructured outages to stable unavailable reasons', async () => {
  const originalFetch = globalThis.fetch;
  const cases = [
    [
      createProjectAgentDashboardClient,
      createProjectAgentDashboardController,
      'project_agent_dashboard_authority_unavailable',
    ],
    [
      createProjectAgentLogsClient,
      createProjectAgentLogsController,
      'project_agent_logs_authority_unavailable',
    ],
    [
      createProjectAgentPatternsClient,
      createProjectAgentPatternsController,
      'project_agent_patterns_authority_unavailable',
    ],
  ];
  try {
    for (const [createClient, createController, reasonCode] of cases) {
      globalThis.fetch = async () => {
        throw new Error('network unavailable');
      };
      const controller = createController({
        authority: 'cloud',
        client: createClient(cloudConfig),
        initialScope: cloudScope,
      });

      await controller.load(cloudScope);

      assert.equal(controller.getSnapshot().state, 'unavailable');
      assert.equal(controller.getSnapshot().reasonCode, reasonCode);
      assert.equal(controller.getSnapshot().retryVisible, true);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('three Project Agent route modules render native deep links and fail closed on bad scope', async () => {
  const cases = [
    [createProjectAgentDashboardRouteModuleLoader, 'project-agent-dashboard'],
    [createProjectAgentLogsRouteModuleLoader, 'project-agent-logs'],
    [createProjectAgentPatternsRouteModuleLoader, 'project-agent-patterns'],
  ];
  for (const [factory, routeId] of cases) {
    let bindings = 0;
    const module = await factory({
      createBinding(context) {
        bindings += 1;
        const scope = Object.freeze({
          authority: 'cloud',
          tenantId: context.tenantId,
          projectId: context.projectId,
        });
        return Object.freeze({
          controller: readyController(scope, routeId),
          scope,
        });
      },
    })();
    assert.equal(module.routeId, routeId);
    const markup = render(module, {
      tenantId: 'tenant-1',
      projectId: 'project-1',
    });
    assert.equal(bindings, 1);
    assert.match(markup, new RegExp(routeId));
    assert.doesNotMatch(markup, /iframe|webview|open in browser/iu);
    assert.match(render(module, { tenantId: 'tenant-1' }), /route_context_unavailable/u);
    assert.equal(bindings, 1);
  }
});

function run(title = 'Run') {
  return {
    run_id: 'run-1',
    conversation_id: 'conversation-1',
    subagent_name: title,
    task: 'Inspect authority',
    status: 'completed',
    created_at: '2026-08-05T00:00:00Z',
    started_at: null,
    ended_at: null,
    summary: null,
    error: null,
    execution_time_ms: null,
    tokens_used: null,
    metadata: {},
    frozen_result_text: null,
    frozen_at: null,
    trace_id: null,
    parent_span_id: null,
  };
}

function pattern() {
  return {
    id: 'pattern-1',
    tenant_id: 'tenant-1',
    name: 'Review pattern',
    description: 'Shared review workflow',
    steps: [],
    success_rate: 1,
    usage_count: 2,
    created_at: '2026-08-05T00:00:00Z',
    updated_at: '2026-08-05T00:00:00Z',
    metadata: {},
  };
}

function logSnapshot(scope, title) {
  return {
    scope,
    scopeRevision: 1,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    allowedActions: ['view', 'list-runs', 'filter-status'],
    runs: [{ id: 'run-1', title, detail: '', status: 'completed', createdAt: '' }],
    total: 1,
  };
}

function readyController(scope, routeId) {
  return {
    subscribe() {
      return () => {};
    },
    getSnapshot() {
      return {
        routeId,
        state: 'ready',
        scope,
        reasonCode: null,
        retryVisible: false,
        allowedActions: ['view'],
        items: [],
        total: 0,
        metrics: {},
      };
    },
    async load() {},
    async retry() {},
    cancel() {},
    stop() {},
  };
}

function render(module, context) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(module.Surface, { context, module }),
    ),
  );
}

function deferred() {
  let resolve;
  const promise = new Promise((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
