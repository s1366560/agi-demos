import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/session/desktopSessionProjectionClientProviderV2.ts',
);
const testTypeScriptConfig = source('tsconfig.test.json');

test('App publishes one stable V2 session projection client Provider', () => {
  assert.match(app, /createDesktopSessionProjectionClientProviderV2/u);
  assert.match(
    app,
    /const desktopSessionProjectionClientProviderV2 = useMemo\([\s\S]*?createDesktopSessionProjectionClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopSessionProjectionClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('session projection loading binds one immutable submitted-scope operation client', () => {
  const loader = sessionProjectionLoader(app);

  assert.match(loader, /const requestConfig = configRef\.current;/u);
  assert.match(
    loader,
    /const client = desktopSessionProjectionClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.match(loader, /void client\s*\.getConversationSession\(/u);
  assert.match(loader, /tenantId: requestConfig\.tenantId/u);
  assert.match(loader, /projectId: requestConfig\.projectId/u);
  assert.match(loader, /workspaceId: requestConfig\.workspaceId \|\| null/u);
  assert.match(loader, /new AbortController\(\)/u);
  assert.match(loader, /sessionProjectionRequestRef\.current !== requestId/u);
  assert.match(loader, /signedSessionSnapshotRevision\(payload\)/u);
  assert.match(loader, /decodeConversationSessionProjection\(payload/u);
  assert.match(loader, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(loader, /desktopSessionProjectionClientV2,/u);
  assert.doesNotMatch(loader, /api\.getConversationSession/u);
});

test('session projection Provider owns one transport read and no projection policy', () => {
  assert.match(
    testTypeScriptConfig,
    /src\/features\/session\/desktopSessionProjectionClientProviderV2\.ts/u,
  );
  assert.match(
    provider,
    /type DesktopSessionProjectionMethod = 'getConversationSession'/u,
  );
  assert.match(provider, /getConversationSession:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /decodeConversationSessionProjection|signedSessionSnapshotRevision|sessionProjectionRequestRef|snapshotRevision|setSessionProjectionState/u,
  );
});

function sessionProjectionLoader(sourceText) {
  const anchor = sourceText.indexOf(
    'const requestId = sessionProjectionRequestRef.current + 1;',
  );
  assert.notEqual(anchor, -1);
  const start = sourceText.lastIndexOf('useEffect(() => {', anchor);
  const end = sourceText.indexOf('\n  const sessionProjection =', anchor);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
