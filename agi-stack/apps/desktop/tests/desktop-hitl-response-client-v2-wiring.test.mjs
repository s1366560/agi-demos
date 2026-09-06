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
const authorityModule = source('src/plugins/desktopHitlResponseAuthorityModuleV2.ts');
const socket = source('src/hooks/useAgentSocket.ts');
const legacyProviderPath = new URL(
  '../src/features/session/desktopHitlResponseClientProviderV2.ts',
  import.meta.url,
);
const forbiddenProviderOwnershipPattern = new RegExp(
  [
    'respondableHitlRequestIdSet',
    'classifyHitlAuthorityRecovery',
    'invalidateSessionAuthority',
    'loadConversationTimeline',
    'sessionProjection',
  ].join('|'),
  'u',
);

test('App creates one stable generation-backed HITL response operation port', () => {
  assert.match(app, /createDesktopHitlResponseOperationsV2/u);
  assert.match(
    app,
    /const desktopHitlResponseOperationsV2 = useMemo\([\s\S]*?createDesktopHitlResponseOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopHitlResponseClientProviderV2/u);
  assert.doesNotMatch(app, /desktopHitlResponseClientProviderV2/u);
  assert.doesNotMatch(app, /desktopHitlResponseClientV2/u);
  assert.equal(existsSync(legacyProviderPath), false);
});

test('HITL responses enter one submitted session-scoped V2 authority', () => {
  const response = callbackSource(app, 'respondToHitl', 'presetAutoApprovalAttemptsRef');

  assert.match(response, /const requestConfig = configRef\.current;/u);
  assert.match(
    response,
    /await desktopHitlResponseOperationsV2\.respond\(\{[\s\S]*?config: requestConfig,[\s\S]*?conversation: scopedConversation,[\s\S]*?submission,[\s\S]*?\}\);/u,
  );
  assert.match(response, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(response, /if \(!scopedConversation\)/u);
  assert.match(response, /request\.status !== 'pending'/u);
  assert.match(response, /request\.kind !== submission\.hitlType/u);
  assert.match(response, /request\.authority_revision !== submission\.expectedRevision/u);
  assert.match(response, /respondableHitlRequestIdSet\.has\(submission\.requestId\)/u);
  assert.match(response, /classifyHitlAuthorityRecovery\(caught\)/u);
  assert.doesNotMatch(response, /api\.respondToHitl/u);
  assert.doesNotMatch(response, /bindOperation/u);
});

test('manual and preset approval paths share the V2 response coordinator', () => {
  assert.match(app, /void respondToHitl\(submission\)/u);
  assert.match(app, /await respondToHitl\(submission\);/u);
});

test('renderer runtime registers one generated HITL response authority definition', () => {
  assert.match(generationHook, /desktopHitlResponseAuthorityDefinitionV2/u);
  assert.match(authorityModule, /service:desktop-renderer\.hitl-response-authority/u);
  assert.match(authorityModule, /acquireServiceOperationLease/u);
  assert.match(authorityModule, /kind: 'session'/u);
  assert.doesNotMatch(authorityModule, forbiddenProviderOwnershipPattern);
  assert.doesNotMatch(generationHook, /desktopHitlResponseClientProviderV2/u);
});

test('Desktop socket no longer exposes a second HITL response authority', () => {
  assert.doesNotMatch(socket, /respondToHitl/u);
  assert.doesNotMatch(socket, /buildHitlSocketMessage/u);
  assert.doesNotMatch(socket, /HitlResponseSubmission/u);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
