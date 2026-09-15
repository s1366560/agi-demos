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
  'u'
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
  'u'
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
  'u'
);

test('App owns one stable V2 session timeline generation operation port', () => {
  assert.match(app, /createDesktopSessionTimelineOperationsV2/u);
  assert.match(app, stableOperationsPattern);
  assert.doesNotMatch(app, /createDesktopSessionTimelineClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionTimelineClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionTimelineClientV2/u);
});

test('initial session timeline loading shares a scoped input across generation operations', async () => {
  const loader = callbackSource(app, 'loadConversationTimeline', 'loadEarlierTimeline');
  const conversation = { id: 'conversation', tenant_id: 'tenant', project_id: 'project', workspace_id: null };
  const config = { mode: 'cloud', tenantId: 'tenant', projectId: 'old-project', apiBaseUrl: 'https://api.invalid' };
  const calls = [];
  let state = { items: [] };
  const dependencies = {
    useCallback: (fn) => fn,
    configRef: { current: config }, timelineRequestRef: { current: 0 }, configScopeEpochRef: { current: 3 },
    emptyConversationTimeline: { items: [] },
    setConversationTimeline: (update) => { state = typeof update === 'function' ? update(state) : update; },
    sessionTimelineRequestIsCurrent: (expected, current) => expected.requestId === current.requestId && expected.scopeEpoch === current.scopeEpoch,
    desktopSessionTimelineOperationsV2: {
      async getConversationMessages(input) { calls.push(['messages', input]); return { timeline: [{ id: 'persisted' }] }; },
      async getConversationSubagentRuns(input) { calls.push(['trace', input]); throw new Error('trace offline'); },
    },
    replayArtifactCanvasEvents: () => ({}), artifactCanvasStateRef: { current: null }, setArtifactCanvasState: () => {},
    mergeTimelineItems: (a, b) => [...a, ...b], mergeCloudSubagentTraceItems: (a, b) => [...a, ...b],
    timelineCursorFromFirst: () => null, timelineCursorFromLast: () => null,
    formatConnectionError: (error) => error.message,
  };
  const code = ts.transpileModule(`${loader}\nreturn loadConversationTimeline;`, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  const execute = new Function(...Object.keys(dependencies), code)(...Object.values(dependencies));
  await execute(conversation, 'project', config);
  assert.equal(calls.length, 2);
  assert.equal(calls[0][1], calls[1][1], 'message and trace use the same captured scoped identity');
  assert.deepEqual(calls[0][1], { config: { ...config, projectId: 'project' }, conversation, limit: 50 });
  assert.equal(config.projectId, 'old-project', 'input capture must not mutate caller config');
  assert.deepEqual(state.items, [{ id: 'persisted' }]);
  assert.equal(state.error, null, 'trace failure cannot fail parent message history');
  assert.equal(state.subagentTraceError, 'trace offline');
  assert.match(loader, /sessionTimelineRequestIsCurrent/u);
  assert.match(loader, /scopeEpoch: configScopeEpochRef\.current/u);
  assert.match(loader, /replayArtifactCanvasEvents\(responseItems\)/u);
  assert.match(loader, /mergeTimelineItems\(responseItems, current\.items\)/u);
  assert.match(loader, /\[desktopSessionTimelineOperationsV2\]/u);
  assert.doesNotMatch(loader, /bindOperation/u);
  assert.doesNotMatch(loader, /new DesktopApiClient\(/u);
});

test('earlier-page loading uses an independent generation operation without changing pagination', () => {
  const loader = callbackSource(app, 'loadEarlierTimeline', 'respondToHitl');

  assert.match(loader, /const requestConfig = configRef\.current;/u);
  assert.match(loader, earlierTimelineRequestPattern);
  assert.match(loader, /sessionTimelineRequestIsCurrent/u);
  assert.match(loader, /resolveEarlierTimelinePage\(\{/u);
  assert.match(loader, /pageResolution\.kind === 'stalled'/u);
  assert.match(loader, /mergeTimelineItems\(response\.timeline \?\? \[\], current\.items\)/u);
  assert.match(loader, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(loader, /desktopSessionTimelineOperationsV2,/u);
  assert.doesNotMatch(loader, /bindOperation/u);
  assert.doesNotMatch(loader, /api\.getConversationMessages/u);
});

test('session timeline authority owns only transport, identity and lease policy', () => {
  assert.match(module, /DESKTOP_SESSION_TIMELINE_AUTHORITY_SERVICE_V2/u);
  assert.match(module, /createDesktopSessionTimelineOperationsV2/u);
  assert.match(module, /acquireServiceOperationLease/u);
  const scopeLiterals = [];
  const moduleAst = ts.createSourceFile('authority.ts', module, ts.ScriptTarget.Latest, true);
  const visit = (node) => {
    if (ts.isPropertyAssignment(node) && node.name.getText(moduleAst) === 'kind' && ts.isStringLiteral(node.initializer)) {
      scopeLiterals.push(node.initializer.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(moduleAst);
  assert.ok(scopeLiterals.includes('session'), 'lease scope remains a structural session literal');
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
