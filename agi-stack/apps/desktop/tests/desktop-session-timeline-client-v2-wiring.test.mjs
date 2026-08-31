import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source('src/features/session/desktopSessionTimelineClientProviderV2.ts');
const stableProviderPattern = new RegExp(
  [
    'const desktopSessionTimelineClientProviderV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopSessionTimelineClientProviderV2\\(\\)',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);
const earlierTimelineRequestPattern = new RegExp(
  [
    'client\\.getConversationMessages\\(',
    '[\\s\\S]*?conversation\\.id,',
    '[\\s\\S]*?requestConfig\\.projectId,',
    '[\\s\\S]*?beforeTimeUs: cursor\\.timeUs,',
    '[\\s\\S]*?beforeCounter: cursor\\.counter,',
  ].join(''),
  'u',
);
const forbiddenProviderPolicyPattern = new RegExp(
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

test('App publishes one stable V2 session timeline client Provider', () => {
  assert.match(app, /createDesktopSessionTimelineClientProviderV2/u);
  assert.match(app, stableProviderPattern);
  assert.match(app, /desktopSessionTimelineClientProviderV2\.publish\(\{ config \}\)/u);
});

test('initial session timeline loading uses one submitted-scope V2 operation binding', () => {
  const loader = callbackSource(app, 'loadConversationTimeline', 'loadEarlierTimeline');

  assert.match(
    loader,
    /const client = desktopSessionTimelineClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.match(
    loader,
    /client\.getConversationMessages\(conversation\.id, projectId, \{[\s\S]*?limit: 50,/u,
  );
  assert.match(loader, /sessionTimelineRequestIsCurrent/u);
  assert.match(loader, /scopeEpoch: configScopeEpochRef\.current/u);
  assert.match(loader, /replayArtifactCanvasEvents\(responseItems\)/u);
  assert.match(loader, /mergeTimelineItems\(responseItems, current\.items\)/u);
  assert.match(loader, /\[desktopSessionTimelineClientV2\]/u);
  assert.doesNotMatch(loader, /new DesktopApiClient\(/u);
});

test('earlier-page loading snapshots one V2 operation binding without changing pagination', () => {
  const loader = callbackSource(app, 'loadEarlierTimeline', 'respondToHitl');

  assert.match(loader, /const requestConfig = configRef\.current;/u);
  assert.match(
    loader,
    /const client = desktopSessionTimelineClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.match(
    loader,
    earlierTimelineRequestPattern,
  );
  assert.match(loader, /sessionTimelineRequestIsCurrent/u);
  assert.match(loader, /resolveEarlierTimelinePage\(\{/u);
  assert.match(loader, /pageResolution\.kind === 'stalled'/u);
  assert.match(loader, /mergeTimelineItems\(response\.timeline \?\? \[\], current\.items\)/u);
  assert.match(loader, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(loader, /desktopSessionTimelineClientV2,/u);
  assert.doesNotMatch(loader, /api\.getConversationMessages/u);
});

test('session timeline Provider owns only the transport read and no semantic policy', () => {
  assert.match(provider, /type DesktopSessionTimelineMethod = 'getConversationMessages'/u);
  assert.match(provider, /getConversationMessages:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(provider, forbiddenProviderPolicyPattern);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
