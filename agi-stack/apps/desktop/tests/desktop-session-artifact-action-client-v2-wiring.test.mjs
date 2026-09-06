import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authority = source('src/plugins/desktopSessionArtifactActionAuthorityModuleV2.ts');
const contract = source('src/plugins/desktopSessionArtifactActionContractV2.ts');
const generation = desktopProductionRuntimeSource();
const stableOperationsPattern = new RegExp(
  [
    'const desktopSessionArtifactActionOperationsV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopSessionArtifactActionOperationsV2\\(',
    '[\\s\\S]*?desktopPluginMarketplaceGenerationActionsRefV2\\.current',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);
const forbiddenAuthorityPolicyPattern = new RegExp(
  [
    'artifactVersionActions',
    'setArtifactActionPending',
    'invalidateSessionAuthority',
    'allowedActions',
    'canDeliverArtifacts',
    'canReviewArtifacts',
  ].join('|'),
  'u',
);

test('App owns one stable generation-bound session artifact action facade', () => {
  assert.match(app, /createDesktopSessionArtifactActionOperationsV2/u);
  assert.match(app, stableOperationsPattern);
  assert.doesNotMatch(app, /createDesktopSessionArtifactActionClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionArtifactActionClientProviderV2\.publish/u);
});

test('artifact actions bind one exact submitted-session V2 authority', () => {
  const action = callbackSource(app, 'handleArtifactAction', 'hasWorkspaceScope');

  assert.match(action, /const requestConfig = configRef\.current;/u);
  assert.match(
    action,
    /desktopSessionArtifactActionOperationsV2\.bindOperation\([\s\S]*?requestConfig,[\s\S]*?authoritativeVersion\.conversation_id,[\s\S]*?\);/u,
  );
  assert.match(action, /await client\.deliverArtifactVersion\(/u);
  assert.match(action, /await client\.reviewArtifactVersion\(/u);
  assert.match(action, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(action, /desktopSessionArtifactActionOperationsV2/u);
  assert.doesNotMatch(action, /api\.(?:deliver|review)ArtifactVersion/u);
});

test('session artifact action authority is cataloged and owns no UI policy', () => {
  assert.match(authority, /service:desktop-renderer\.session-artifact-action-authority/u);
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /kind: 'session'/u);
  assert.match(authority, /reviewArtifactVersion/u);
  assert.match(authority, /deliverArtifactVersion/u);
  assert.match(contract, /assertArtifactReviewOutcomeV2/u);
  assert.match(contract, /assertArtifactDeliveryOutcomeV2/u);
  assert.match(generation, /desktopSessionArtifactActionAuthorityDefinitionV2/u);
  assert.doesNotMatch(authority, forbiddenAuthorityPolicyPattern);
  assert.doesNotMatch(contract, forbiddenAuthorityPolicyPattern);
  assert.equal(
    existsSync(
      new URL(
        '../src/features/session/desktopSessionArtifactActionClientProviderV2.ts',
        import.meta.url,
      ),
    ),
    false,
  );
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
