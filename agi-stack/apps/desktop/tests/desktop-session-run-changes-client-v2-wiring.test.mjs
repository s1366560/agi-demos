import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/session/desktopSessionRunChangesClientProviderV2.ts',
);

test('App publishes one stable V2 session run-changes Provider', () => {
  assert.match(app, /createDesktopSessionRunChangesClientProviderV2/u);
  assert.match(
    app,
    /const desktopSessionRunChangesClientProviderV2 = useMemo\([\s\S]*?createDesktopSessionRunChangesClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopSessionRunChangesClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('Local run changes use a submitted-scope V2 client without changing Cloud authority', () => {
  const callback = callbackSource(app, 'loadRunChanges');

  assert.match(callback, /const requestConfig = configRef\.current/u);
  assert.match(callback, /requestConfig\.mode === 'cloud'/u);
  assert.match(callback, /activityAuthorityAdapter\.client\.getRunChanges/u);
  assert.match(callback, /desktopChangeSnapshotFromCloud/u);
  assert.match(callback, /scope: changeScope/u);
  assert.match(callback, /changeScope === 'turn' \? \{ turn_id:/u);
  assert.match(
    callback,
    /changeScope === 'run'[\s\S]*?desktopSessionRunChangesClientV2[\s\S]*?\.bindOperation\(requestConfig\)[\s\S]*?\.getRunChanges\(currentArtifactRun\.id, currentArtifactRun\.revision\)/u,
  );
  assert.match(callback, /local_run_changes_scope_unavailable/u);
  assert.match(callback, /cloud_run_changes_authority_scope_unavailable/u);
  assert.match(callback, /reference\.snapshot_id === snapshot\.id/u);
  assert.match(callback, /reference\.environment_id === snapshot\.environment_id/u);
  assert.match(callback, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(callback, /setChangeSnapshotLoading\(false\)/u);
  assert.match(callback, /desktopSessionRunChangesClientV2,/u);
  assert.doesNotMatch(callback, /api\.getRunChanges/u);
  assert.doesNotMatch(callback, /\[\s*activityAuthorityAdapter,[\s\S]*?\n\s*api,/u);
});

test('session run-changes Provider owns exactly one read method', () => {
  assert.match(provider, /type DesktopSessionRunChangesMethod = 'getRunChanges'/u);
  assert.match(provider, /getRunChanges:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /pauseRun:|resumeRun:|forkRecoveryRun:|cancelRun:|reviewRun:|listRunInputs:/u,
  );
});

function callbackSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  const availableChangeScopes', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
