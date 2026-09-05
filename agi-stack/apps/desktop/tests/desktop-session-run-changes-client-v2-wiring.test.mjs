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
const reviewHook = source('src/features/session/useRunReviewAuthorityV2.ts');

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

test('Cloud summary and both runtime changes use required session-scoped operations', () => {
  assert.match(app, /const loadRunChanges = useRunReviewAuthorityV2\(\{/u);
  assert.match(app, /projectionOperations: desktopSessionProjectionOperationsV2/u);
  assert.match(app, /changesOperations: desktopSessionRunChangesOperationsV2/u);
  assert.match(reviewHook, /projectionOperations\s*\.getRunSummary\(/u);
  assert.match(reviewHook, /scope === 'turn' \? \{ turnId: run\.message_id/u);
  assert.match(
    reviewHook,
    /changesOperations\.getRunChanges\(\{[\s\S]*?config,\s*conversation,\s*runId: run\.id,\s*expectedRevision: run\.revision,\s*scope,[\s\S]*?signal: request\.signal/u,
  );
  assert.match(reviewHook, /local_run_changes_scope_unavailable/u);
  assert.match(reviewHook, /reference\.snapshot_id === snapshot\.id/u);
  assert.match(reviewHook, /reference\.environment_id === snapshot\.environment_id/u);
  assert.match(reviewHook, /formatConnectionError\(error, config\.apiBaseUrl\)/u);
  assert.match(reviewHook, /if \(ownsRequest\(\)\) setLoading\(false\)/u);
  assert.doesNotMatch(
    app + reviewHook,
    /activityAuthorityAdapter\.client\.getRun(?:Changes|Summary)/u,
  );
  assert.doesNotMatch(reviewHook, /api\.getRunChanges|\.bindOperation\(/u);
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
    reviewHook,
    /useEffect\(\(\) => \{[\s\S]*?void loadRunChanges\(\);[\s\S]*?return \(\) => \{\s*lifetime\.controller\.abort\(\);\s*lifetime\.request\?\.abort\(\);\s*\};/u,
  );
});
