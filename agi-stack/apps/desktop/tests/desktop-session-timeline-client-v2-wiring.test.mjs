import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const ts = require('typescript');

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const module = source('src/plugins/desktopSessionTimelineAuthorityModuleV2.ts');
const stableOperationsPattern = new RegExp(
  [
    'const desktopSessionTimelineOperationsV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopSessionTimelineOperationsV2\\(',
    '[\\s\\S]*?desktopPluginMarketplaceGenerationActionsRefV2\\.current,',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);
const earlierTimelineRequestPattern = new RegExp(
  [
    'desktopSessionTimelineOperationsV2\\.getConversationMessages\\(\\{',
    '[\\s\\S]*?config: requestConfig,',
    '[\\s\\S]*?conversation,',
    '[\\s\\S]*?beforeTimeUs: cursor\\.timeUs,',
    '[\\s\\S]*?beforeCounter: cursor\\.counter,',
    '[\\s\\S]*?\\}\\)',
  ].join(''),
  'u',
);
const forbiddenAuthorityPolicyPattern = new RegExp(
  [
    'listConversations',
    'sendMessage',
    'runAgentMessage',
    'mergeTimelineItems',
    'resolveEarlierTimelinePage',
    'comparison',
  ].join('|'),
  'u',
);

test('App owns one stable V2 session timeline generation operation port', () => {
  assert.match(app, /createDesktopSessionTimelineOperationsV2/u);
  assert.match(app, stableOperationsPattern);
  assert.doesNotMatch(app, /createDesktopSessionTimelineClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionTimelineClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionTimelineClientV2/u);
});

test('initial session timeline loading shares a scoped input across generation operations', async () => {
  const loader = callbackSource(
    app,
    'loadConversationTimeline',
    'loadEarlierTimeline',
  );
  const conversation = {
    id: 'conversation',
    tenant_id: 'tenant',
    project_id: 'project',
    workspace_id: null,
  };
  const config = {
    mode: 'cloud',
    tenantId: 'tenant',
    projectId: 'old-project',
    apiBaseUrl: 'https://api.invalid',
  };
  const calls = [];
  let state = { items: [] };
  const dependencies = {
    useCallback: (fn) => fn,
    configRef: { current: config },
    timelineRequestRef: { current: 0 },
    configScopeEpochRef: { current: 3 },
    emptyConversationTimeline: { items: [] },
    setConversationTimeline: (update) => {
      state = typeof update === 'function' ? update(state) : update;
    },
    sessionTimelineRequestIsCurrent: (expected, current) =>
      expected.requestId === current.requestId &&
      expected.scopeEpoch === current.scopeEpoch,
    desktopSessionTimelineOperationsV2: {
      async getConversationMessages(input) {
        calls.push(['messages', input]);
        return { timeline: [{ id: 'persisted' }] };
      },
      async getConversationSubagentRuns(input) {
        calls.push(['trace', input]);
        throw new Error('trace offline');
      },
    },
    replayArtifactCanvasEvents: () => ({}),
    artifactCanvasStateRef: { current: null },
    setArtifactCanvasState: () => {},
    mergeTimelineItems: (a, b) => [...a, ...b],
    mergeCloudSubagentTraceItems: (a, b) => [...a, ...b],
    timelineCursorFromFirst: () => null,
    timelineCursorFromLast: () => null,
    formatConnectionError: (error) => error.message,
  };
  const code = ts.transpileModule(
    `${loader}\nreturn loadConversationTimeline;`,
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
      },
    },
  ).outputText;
  const execute = new Function(...Object.keys(dependencies), code)(
    ...Object.values(dependencies),
  );
  await execute(conversation, 'project', config);
  assert.equal(calls.length, 2);
  assert.equal(
    calls[0][1],
    calls[1][1],
    'message and trace use the same captured scoped identity',
  );
  assert.deepEqual(calls[0][1], {
    config: { ...config, projectId: 'project' },
    conversation,
    limit: 50,
  });
  assert.equal(
    config.projectId,
    'old-project',
    'input capture must not mutate caller config',
  );
  assert.deepEqual(state.items, [{ id: 'persisted' }]);
  assert.equal(
    state.error,
    null,
    'trace failure cannot fail parent message history',
  );
  assert.equal(state.subagentTraceError, 'trace offline');
  assert.match(loader, /sessionTimelineRequestIsCurrent/u);
  assert.match(loader, /scopeEpoch: configScopeEpochRef\.current/u);
  assert.match(loader, /replayArtifactCanvasEvents\(responseItems\)/u);
  assert.match(loader, /mergeTimelineItems\(responseItems, current\.items\)/u);
  assert.match(loader, /\[desktopSessionTimelineOperationsV2\]/u);
  assert.doesNotMatch(loader, /bindOperation/u);
  assert.doesNotMatch(loader, /new DesktopApiClient\(/u);
});

test('same-session background history keeps existing HITL, content and pagination visible', async () => {
  const items = [{ id: 'human-message' }, { id: 'pending-permission' }];
  const approvals = [{ id: 'permission' }];
  const harness = timelineHarness({
    conversationId: 'conversation',
    items,
    approvalRequests: approvals,
    loading: false,
    loadingEarlier: true,
    hasMore: true,
    firstCursor: { timeUs: 1, counter: 2 },
    error: 'old error',
  });
  const pending = harness.load('conversation');
  assert.equal(harness.state.items, items);
  assert.equal(harness.state.approvalRequests, approvals);
  assert.equal(harness.state.loading, false);
  assert.equal(harness.state.loadingEarlier, false);
  assert.equal(harness.state.error, null);
  assert.equal(harness.state.hasMore, true);
  assert.deepEqual(harness.state.firstCursor, { timeUs: 1, counter: 2 });
  harness.setState((current) => ({
    ...current,
    items: [...current.items, { id: 'live-event' }],
  }));
  harness.requests[0].resolve({ timeline: [{ id: 'persisted' }] });
  await pending;
  assert.equal(
    harness.state.items.some((item) => item.id === 'live-event'),
    true,
  );
  assert.equal(harness.state.loading, false);
});

test('first load and conversation changes hide prior history and ignore older responses', async () => {
  const harness = timelineHarness();
  const first = harness.load('first');
  assert.equal(harness.state.loading, true);
  assert.deepEqual(harness.state.items, []);
  harness.setState((current) => ({
    ...current,
    items: [{ id: 'first-live' }],
    approvalRequests: [{ id: 'first-approval' }],
  }));
  const second = harness.load('second');
  assert.equal(harness.state.conversationId, 'second');
  assert.equal(harness.state.loading, true);
  assert.deepEqual(harness.state.items, []);
  assert.deepEqual(harness.state.approvalRequests, []);
  harness.requests[0].resolve({ timeline: [{ id: 'late-first' }] });
  await first;
  assert.equal(harness.state.conversationId, 'second');
  assert.deepEqual(harness.state.items, []);
  harness.requests[1].resolve({ timeline: [{ id: 'second-message' }] });
  await second;
  assert.deepEqual(harness.state.items, [{ id: 'second-message' }]);
});

test('background history failure keeps loaded content and exposes an error without skeleton', async () => {
  const items = [{ id: 'loaded-permission' }];
  const harness = timelineHarness({ conversationId: 'conversation', items });
  const pending = harness.load('conversation');
  harness.requests[0].reject(new Error('history unavailable'));
  await pending;
  assert.equal(harness.state.items, items);
  assert.equal(harness.state.loading, false);
  assert.equal(harness.state.error, 'history unavailable');
});

test('an old scope response cannot restore cached history after authority changes', async () => {
  const harness = timelineHarness({
    conversationId: 'conversation',
    items: [{ id: 'old-scope' }],
  });
  const pending = harness.load('conversation');
  harness.scopeEpoch.current++;
  harness.setState({ conversationId: null, items: [], loading: false });
  harness.requests[0].resolve({ timeline: [{ id: 'late-old-scope' }] });
  await pending;
  assert.equal(harness.state.conversationId, null);
  assert.deepEqual(harness.state.items, []);
});

test('earlier-page loading uses an independent generation operation without changing pagination', () => {
  const loader = callbackSource(app, 'loadEarlierTimeline', 'respondToHitl');

  assert.match(loader, /const requestConfig = configRef\.current;/u);
  assert.match(loader, earlierTimelineRequestPattern);
  assert.match(loader, /sessionTimelineRequestIsCurrent/u);
  assert.match(loader, /resolveEarlierTimelinePage\(\{/u);
  assert.match(loader, /pageResolution\.kind === 'stalled'/u);
  assert.match(
    loader,
    /mergeTimelineItems\(response\.timeline \?\? \[\], current\.items\)/u,
  );
  assert.match(
    loader,
    /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u,
  );
  assert.match(loader, /desktopSessionTimelineOperationsV2,/u);
  assert.doesNotMatch(loader, /bindOperation/u);
  assert.doesNotMatch(loader, /api\.getConversationMessages/u);
});

test('session timeline authority owns only transport, identity and lease policy', () => {
  assert.match(module, /DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2/u);
  assert.match(module, /createDesktopSessionTimelineOperationsV2/u);
  assert.match(module, /acquireServiceOperationLease/u);
  const scopeLiterals = [];
  const moduleAst = ts.createSourceFile(
    'authority.ts',
    module,
    ts.ScriptTarget.Latest,
    true,
  );
  const visit = (node) => {
    if (
      ts.isPropertyAssignment(node) &&
      node.name.getText(moduleAst) === 'kind' &&
      ts.isStringLiteral(node.initializer)
    ) {
      scopeLiterals.push(node.initializer.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(moduleAst);
  assert.ok(
    scopeLiterals.includes('session'),
    'lease scope remains a structural session literal',
  );
  assert.match(module, /getConversationMessages:/u);
  assert.doesNotMatch(module, forbiddenAuthorityPolicyPattern);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}

function timelineHarness(initial = {}) {
  const config = {
    mode: 'local',
    tenantId: 'tenant',
    projectId: 'project',
    apiBaseUrl: 'https://api.invalid',
  };
  const empty = {
    conversationId: null,
    items: [],
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: null,
    lastCursor: null,
  };
  let state = { ...empty, ...initial };
  const requests = [];
  const scopeEpoch = { current: 1 };
  const setState = (update) => {
    state = typeof update === 'function' ? update(state) : update;
  };
  const dependencies = {
    useCallback: (fn) => fn,
    configRef: { current: config },
    timelineRequestRef: { current: 0 },
    configScopeEpochRef: scopeEpoch,
    emptyConversationTimeline: empty,
    setConversationTimeline: setState,
    sessionTimelineRequestIsCurrent: (expected, current) =>
      expected.requestId === current.requestId &&
      expected.scopeEpoch === current.scopeEpoch,
    desktopSessionTimelineOperationsV2: {
      getConversationMessages: () =>
        new Promise((resolve, reject) => requests.push({ resolve, reject })),
    },
    replayArtifactCanvasEvents: () => ({}),
    artifactCanvasStateRef: { current: null },
    setArtifactCanvasState() {},
    mergeTimelineItems: (a, b) => [...a, ...b],
    mergeCloudSubagentTraceItems: (a) => a,
    timelineCursorFromFirst: () => null,
    timelineCursorFromLast: () => null,
    formatConnectionError: (error) => error.message,
  };
  const loader = callbackSource(
    app,
    'loadConversationTimeline',
    'loadEarlierTimeline',
  );
  const code = ts.transpileModule(
    `${loader}\nreturn loadConversationTimeline;`,
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
      },
    },
  ).outputText;
  const execute = new Function(...Object.keys(dependencies), code)(
    ...Object.values(dependencies),
  );
  return {
    get state() {
      return state;
    },
    requests,
    scopeEpoch,
    setState,
    load: (id) =>
      execute(
        { id, tenant_id: 'tenant', project_id: 'project', workspace_id: null },
        'project',
        config,
      ),
  };
}
