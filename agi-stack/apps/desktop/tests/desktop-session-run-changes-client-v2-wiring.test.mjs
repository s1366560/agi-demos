import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const retiredProvider = source('src/features/session/desktopSessionRunChangesClientProviderV2.ts');
const authorityModule = source('src/plugins/desktopSessionRunChangesAuthorityModuleV2.ts');
const generationHook = source('src/plugins/useDesktopPluginGenerationV2.ts');

test('App creates one generation-backed session run-changes operation port', () => {
  assert.match(app, /createDesktopSessionRunChangesOperationsV2/u);
  assert.match(
    app,
    /const desktopSessionRunChangesOperationsV2 = useMemo\([\s\S]*?createDesktopSessionRunChangesOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopSessionRunChangesClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionRunChangesClientProviderV2/u);
  assert.doesNotMatch(app, /desktopSessionRunChangesClientV2/u);
  assert.equal(retiredProvider, '');
});

test('Local run changes use a session-scoped generation service without changing Cloud authority', () => {
  const callback = callbackSource(app, 'loadRunChanges');

  assert.match(callback, /const requestConfig = configRef\.current/u);
  assert.match(callback, /requestConfig\.mode === 'cloud'/u);
  assert.match(callback, /activityAuthorityAdapter\.client\.getRunChanges/u);
  assert.match(callback, /desktopChangeSnapshotFromCloud/u);
  assert.match(callback, /scope: changeScope/u);
  assert.match(callback, /changeScope === 'turn' \? \{ turn_id:/u);
  assert.match(
    callback,
    /changeScope === 'run' && scopedConversation[\s\S]*?desktopSessionRunChangesOperationsV2\.getRunChanges\(\{[\s\S]*?config: requestConfig,[\s\S]*?conversation: scopedConversation,[\s\S]*?runId: currentArtifactRun\.id,[\s\S]*?expectedRevision: currentArtifactRun\.revision,[\s\S]*?signal,[\s\S]*?\}\)/u,
  );
  assert.match(callback, /local_run_changes_scope_unavailable/u);
  assert.match(callback, /cloud_run_changes_authority_scope_unavailable/u);
  assert.match(callback, /reference\.snapshot_id === snapshot\.id/u);
  assert.match(callback, /reference\.environment_id === snapshot\.environment_id/u);
  assert.match(callback, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(callback, /setChangeSnapshotLoading\(false\)/u);
  assert.match(callback, /desktopSessionRunChangesOperationsV2,/u);
  assert.match(callback, /scopedConversation,/u);
  assert.doesNotMatch(callback, /api\.getRunChanges/u);
  assert.doesNotMatch(callback, /\.bindOperation\(/u);
});

test('run-changes authority is registered as an exact one-method generation service', () => {
  assert.match(generationHook, /desktopSessionRunChangesAuthorityDefinitionV2/u);
  assert.match(authorityModule, /service:desktop-renderer\.session-run-changes-authority/u);
  assert.match(authorityModule, /getRunChanges/u);
  assert.match(authorityModule, /acquireServiceOperationLease/u);
  assert.doesNotMatch(
    authorityModule,
    /pauseRun:|resumeRun:|forkRecoveryRun:|cancelRun:|reviewRun:|listRunInputs:/u,
  );
  assert.doesNotMatch(authorityModule, /DesktopSessionRunChangesClientProvider/u);
});

test('automatic run-changes refresh aborts the operation boundary on cleanup', () => {
  assert.match(
    app,
    /useEffect\(\(\) => \{[\s\S]*?const controller = new AbortController\(\);[\s\S]*?void loadRunChanges\(controller\.signal\);[\s\S]*?return \(\) => controller\.abort\(\);[\s\S]*?\}, \[loadRunChanges\]\);/u,
  );
});

function callbackSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  const availableChangeScopes', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
