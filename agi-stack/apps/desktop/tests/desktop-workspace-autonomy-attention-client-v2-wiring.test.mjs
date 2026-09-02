import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authorityModule = source(
  'src/plugins/desktopWorkspaceAutonomyAttentionAuthorityModuleV2.ts',
);
const lifecycleProvider = source(
  'src/features/workspace/desktopWorkspaceLifecycleClientProviderV2.ts',
);
const legacyProviderPath = new URL(
  '../src/features/workspace/desktopWorkspaceAutonomyAttentionClientProviderV2.ts',
  import.meta.url,
);
const testTypeScriptConfig = source('tsconfig.test.json');

test('App owns one stable generation-bound autonomy-attention operation set', () => {
  assert.match(app, /createDesktopWorkspaceAutonomyAttentionOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceAutonomyAttentionOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceAutonomyAttentionOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceAutonomyAttentionClientProviderV2/u);
  assert.doesNotMatch(app, /desktopWorkspaceAutonomyAttentionClientProviderV2\.publish/u);
  assert.equal(existsSync(legacyProviderPath), false);
});

test('runtime refresh resolves the initial attention read through the immutable generation', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /desktopWorkspaceAutonomyAttentionOperationsV2\.listWorkspaceAutonomyAttentions\(\{[\s\S]*?config: resolvedConfig,[\s\S]*?workspaceId,/u,
  );
  assert.doesNotMatch(
    refresh,
    /workspaceAutonomyAttentionClient|desktopWorkspaceAutonomyAttention\w*\.bindOperation/u,
  );
});

test('retry pins mutation and canonical reread inside one V2 operation boundary', () => {
  const retry = asyncArrowFunctionSource(app, 'retryWorkspaceAutonomyAttention');

  assert.match(retry, /const requestConfig = configRef\.current;/u);
  assert.match(
    retry,
    /desktopWorkspaceAutonomyAttentionOperationsV2\.withRetryWorkspaceAutonomyAttention\(/u,
  );
  assert.match(retry, /config: requestConfig,/u);
  assert.match(retry, /workspaceId: requestConfig\.workspaceId,/u);
  assert.match(retry, /attentionId,/u);
  assert.match(retry, /await client\.retryWorkspaceAutonomyAttention\(attentionId\);/u);
  assert.match(retry, /return client\.listWorkspaceAutonomyAttentions\(\);/u);
  assert.match(retry, /isSameDesktopRequestScope\(requestConfig, configRef\.current\)/u);
  assert.doesNotMatch(retry, /new DesktopApiClient\(|bindOperation/u);
});

test('resolve keeps revision, idempotency, recovery and rereads on one pinned generation', () => {
  const resolve = asyncArrowFunctionSource(app, 'resolveWorkspaceAutonomyAttention');

  assert.match(resolve, /const persistedAttempt = currentWorkspaceAutonomyAttentionResolveAttempt/u);
  assert.match(
    resolve,
    /desktop-autonomy-attention-resolve:\$\{globalThis\.crypto\.randomUUID\(\)\}/u,
  );
  assert.match(
    resolve,
    /desktopWorkspaceAutonomyAttentionOperationsV2\.withResolveWorkspaceAutonomyAttention\(/u,
  );
  for (const input of [
    /config: requestConfig,/u,
    /workspaceId: requestConfig\.workspaceId,/u,
    /actorId: requestActorId,/u,
    /attentionId,/u,
    /expectedRevision: persistedAttempt\?\.expectedRevision \?\? null,/u,
    /idempotencyKey: operationIdempotencyKey,/u,
  ]) {
    assert.match(resolve, input);
  }
  assert.match(resolve, /await client\.getWorkspaceAuthorityRevision\(\);/u);
  assert.match(resolve, /idempotencyKey: prepared\.idempotencyKey,/u);
  assert.match(resolve, /await client\.resolveWorkspaceAutonomyAttention\(/u);
  assert.equal(
    countMatches(resolve, /await client\.listWorkspaceAutonomyAttentions\(\);/gu),
    2,
  );
  assert.match(resolve, /caught instanceof DesktopApiError && caught\.status === 409/u);
  assert.match(resolve, /discardWorkspaceAutonomyAttentionResolveAttempt/u);
  assert.match(resolve, /operationErrorHandled = true;/u);
  assert.doesNotMatch(resolve, /new DesktopApiClient\(|bindOperation/u);
});

test('authority module owns four transports, project lease and no App state policy', () => {
  assert.match(
    testTypeScriptConfig,
    /src\/plugins\/desktopWorkspaceAutonomyAttentionAuthorityModuleV2\.ts/u,
  );
  assert.match(
    testTypeScriptConfig,
    /src\/plugins\/desktopWorkspaceAutonomyAttentionContractV2\.ts/u,
  );
  assert.doesNotMatch(
    testTypeScriptConfig,
    /src\/features\/workspace\/desktopWorkspaceAutonomyAttentionClientProviderV2\.ts/u,
  );
  for (const method of [
    'listWorkspaceAutonomyAttentions',
    'getWorkspaceAuthorityRevision',
    'retryWorkspaceAutonomyAttention',
    'resolveWorkspaceAutonomyAttention',
  ]) {
    assert.match(authorityModule, new RegExp(method));
  }
  assert.match(authorityModule, /acquireServiceOperationLease/u);
  assert.match(authorityModule, /kind: 'project'/u);
  assert.match(authorityModule, /new DesktopApiClient\(operationConfig\)/u);
  assert.doesNotMatch(
    authorityModule,
    /resolveWorkspaceAutonomyAttentionAttempt|retainOpenWorkspaceAutonomyAttentionResolveAttempts|discardWorkspaceAutonomyAttentionResolveAttempt|randomUUID|setWorkspaceAutonomyAttentionState/u,
  );
  assert.doesNotMatch(
    lifecycleProvider,
    /listWorkspaceAutonomyAttentions|getWorkspaceAuthorityRevision|retryWorkspaceAutonomyAttention|resolveWorkspaceAutonomyAttention/u,
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  const end = sourceText.indexOf('\n  useEffect(() => {', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}

function asyncArrowFunctionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = useCallback(async`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  const ', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}

function countMatches(sourceText, pattern) {
  return [...sourceText.matchAll(pattern)].length;
}
