import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

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

test('initial session timeline loading uses one session-scoped generation operation', () => {
  const loader = callbackSource(app, 'loadConversationTimeline', 'loadEarlierTimeline');

  assert.match(
    loader,
    /desktopSessionTimelineOperationsV2\.getConversationMessages\(\{[\s\S]*?config: \{[\s\S]*?\.\.\.requestConfig,[\s\S]*?projectId,[\s\S]*?\},[\s\S]*?conversation,[\s\S]*?limit: 50,[\s\S]*?\}\)/u
  );
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
  assert.match(module, /kind: 'session'/u);
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
