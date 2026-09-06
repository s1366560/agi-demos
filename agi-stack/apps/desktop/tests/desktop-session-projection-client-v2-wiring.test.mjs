import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const generationHook = desktopProductionRuntimeSource();
const authorityModule = source('src/plugins/desktopSessionProjectionAuthorityModuleV2.ts');
const legacyProviderPath = new URL(
  '../src/features/session/desktopSessionProjectionClientProviderV2.ts',
  import.meta.url,
);
const forbiddenAuthorityPolicyPattern = new RegExp(
  [
    'decodeConversationSessionProjection',
    'signedSessionSnapshotRevision',
    'sessionProjectionRequestRef',
    'snapshotRevision',
    'setSessionProjectionState',
    'formatConnectionError',
  ].join('|'),
  'u',
);

test('App creates one stable generation-backed session projection operation port', () => {
  assert.match(app, /createDesktopSessionProjectionOperationsV2/u);
  assert.match(
    app,
    /const desktopSessionProjectionOperationsV2 = useMemo\([\s\S]*?createDesktopSessionProjectionOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopSessionProjectionClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionProjectionClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionProjectionClientV2/u);
  assert.equal(existsSync(legacyProviderPath), false);
});

test('session projection loading enters one session-scoped V2 read operation', () => {
  const loader = sessionProjectionLoader(app);

  assert.match(loader, /const requestConfig = configRef\.current;/u);
  assert.match(loader, /const controller = new AbortController\(\)/u);
  assert.match(
    loader,
    /void desktopSessionProjectionOperationsV2\.getConversationSession\(\{[\s\S]*?config: requestConfig,[\s\S]*?conversation: scopedConversation,[\s\S]*?signal: controller\.signal,[\s\S]*?\}\)/u,
  );
  assert.match(loader, /sessionProjectionRequestRef\.current !== requestId/u);
  assert.match(loader, /signedSessionSnapshotRevision\(payload\)/u);
  assert.match(loader, /decodeConversationSessionProjection\(payload/u);
  assert.match(loader, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(loader, /return \(\) => controller\.abort\(\)/u);
  assert.match(loader, /desktopSessionProjectionOperationsV2,/u);
  assert.doesNotMatch(loader, /api\.getConversationSession/u);
  assert.doesNotMatch(loader, /bindOperation/u);
});

test('renderer runtime registers one generated session projection authority definition', () => {
  assert.match(generationHook, /desktopSessionProjectionAuthorityDefinitionV2/u);
  assert.match(authorityModule, /service:desktop-renderer\.session-projection-authority/u);
  assert.match(authorityModule, /acquireServiceOperationLease/u);
  assert.match(authorityModule, /kind: 'session'/u);
  assert.match(authorityModule, /new DesktopApiClient/u);
  assert.doesNotMatch(authorityModule, forbiddenAuthorityPolicyPattern);
  assert.doesNotMatch(generationHook, /desktopSessionProjectionClientProviderV2/u);
});

function sessionProjectionLoader(sourceText) {
  const anchor = sourceText.indexOf('const requestId = sessionProjectionRequestRef.current + 1;');
  assert.notEqual(anchor, -1);
  const start = sourceText.lastIndexOf('useEffect(() => {', anchor);
  const end = sourceText.indexOf('\n  const sessionProjection =', anchor);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
