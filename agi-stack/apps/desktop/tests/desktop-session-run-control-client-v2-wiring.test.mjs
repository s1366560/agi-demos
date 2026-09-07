import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authority = source('src/plugins/desktopSessionRunControlAuthorityModuleV2.ts');
const contract = source('src/plugins/desktopSessionRunControlContractV2.ts');
const generation = desktopProductionRuntimeSource();
const stableOperationsPattern = new RegExp(
  [
    'const desktopSessionRunControlOperationsV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopSessionRunControlOperationsV2\\(',
    '[\\s\\S]*?desktopPluginMarketplaceGenerationActionsRefV2\\.current',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);
const forbiddenAuthorityPolicyPattern = new RegExp(
  [
    'sessionDetailViewModel',
    'runActions',
    'setSessionRunActionPending',
    'applyAuthoritativeRun',
    'invalidateSessionAuthority',
    'showToast',
    'desktop-recovery-fork',
  ].join('|'),
  'u',
);

test('App owns one stable generation-bound session run-control facade', () => {
  assert.match(app, /createDesktopSessionRunControlOperationsV2/u);
  assert.match(app, stableOperationsPattern);
  assert.doesNotMatch(app, /createDesktopSessionRunControlClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionRunControlClientProviderV2\.publish/u);
});

test('session run actions bind one exact authoritative-session V2 authority', () => {
  const action = callbackSource(app, 'handleSessionRunAction', 'handleArtifactAction');

  assert.match(action, /const authoritativeRun = sessionProjection\?\.currentRun;/u);
  assert.match(action, /const requestConfig = configRef\.current;/u);
  assert.match(
    action,
    /desktopSessionRunControlOperationsV2\.bindOperation\([\s\S]*?requestConfig,[\s\S]*?authoritativeRun\.conversation_id,[\s\S]*?\);/u,
  );
  for (const method of [
    'pauseRun',
    'resumeRun',
    'forkRecoveryRun',
    'cancelRun',
    'reviewRun',
  ]) {
    assert.match(action, new RegExp(`await client\\.${method}\\(`, 'u'));
  }
  assert.match(action, /authoritativeRun\.id !== runId/u);
  assert.match(action, /authoritativeRun\.revision !== revision/u);
  assert.match(action, /!sessionDetailViewModel\.runActions\.includes\(action\)/u);
  assert.match(action, /`desktop-recovery-fork:\$\{runId\}:\$\{revision\}`/u);
  assert.match(action, /applyAuthoritativeRun\(outcome\.run\)/u);
  assert.match(action, /invalidateSessionAuthority\(\)/u);
  assert.doesNotMatch(
    action,
    /api\.(?:pauseRun|resumeRun|forkRecoveryRun|cancelRun|reviewRun)/u,
  );
});

test('session run-control authority is cataloged and owns no UI policy', () => {
  assert.match(authority, /service:desktop-renderer\.session-run-control-authority/u);
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /kind: 'session'/u);
  assert.match(authority, /pauseRun/u);
  assert.match(authority, /resumeRun/u);
  assert.match(authority, /forkRecoveryRun/u);
  assert.match(authority, /cancelRun/u);
  assert.match(authority, /reviewRun/u);
  assert.match(contract, /assertRunControlOutcomeV2/u);
  assert.match(contract, /assertForkRecoveryOutcomeV2/u);
  assert.match(generation, /desktopSessionRunControlAuthorityDefinitionV2/u);
  assert.doesNotMatch(authority, forbiddenAuthorityPolicyPattern);
  assert.doesNotMatch(contract, forbiddenAuthorityPolicyPattern);
  assert.equal(
    existsSync(
      new URL('../src/features/session/desktopSessionRunControlClientProviderV2.ts', import.meta.url),
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
