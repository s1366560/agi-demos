import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceAutonomyAttentionClientProviderV2.ts',
);
const lifecycleProvider = source(
  'src/features/workspace/desktopWorkspaceLifecycleClientProviderV2.ts',
);
const testTypeScriptConfig = source('tsconfig.test.json');

test('App publishes one stable V2 Workspace Autonomy Attention client Provider', () => {
  assert.match(app, /createDesktopWorkspaceAutonomyAttentionClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceAutonomyAttentionClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceAutonomyAttentionClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceAutonomyAttentionClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('runtime refresh binds the initial attention read to the resolved immutable scope', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /const workspaceAutonomyAttentionClient =\s*desktopWorkspaceAutonomyAttentionClientV2\.bindOperation\(resolvedConfig\);/u,
  );
  assert.match(
    refresh,
    /resolveWorkspaceAuthority\(\s*workspaceAutonomyAttentionClient\.listWorkspaceAutonomyAttentions\(\),?\s*\)/u,
  );
  assert.doesNotMatch(refresh, /scopedClient\.listWorkspaceAutonomyAttentions/u);
});

test('retry binds mutation and canonical reread to one submitted-scope operation client', () => {
  const retry = asyncArrowFunctionSource(app, 'retryWorkspaceAutonomyAttention');

  assert.match(retry, /const requestConfig = configRef\.current;/u);
  assert.match(
    retry,
    /const client = desktopWorkspaceAutonomyAttentionClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.match(retry, /await client\.retryWorkspaceAutonomyAttention\(attentionId\);/u);
  assert.match(retry, /await client\.listWorkspaceAutonomyAttentions\(\);/u);
  assert.match(retry, /isSameDesktopRequestScope\(requestConfig, configRef\.current\)/u);
  assert.doesNotMatch(retry, /new DesktopApiClient\(/u);
});

test('resolve keeps revision, idempotency, 409 recovery and reread on one operation client', () => {
  const resolve = asyncArrowFunctionSource(app, 'resolveWorkspaceAutonomyAttention');

  assert.match(resolve, /const requestConfig = configRef\.current;/u);
  assert.match(
    resolve,
    /const client = desktopWorkspaceAutonomyAttentionClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.equal(
    countMatches(
      resolve,
      /desktopWorkspaceAutonomyAttentionClientV2\.bindOperation\(requestConfig\)/gu,
    ),
    1,
  );
  assert.match(resolve, /await client\.getWorkspaceAuthorityRevision\(\);/u);
  assert.match(resolve, /desktop-autonomy-attention-resolve:\$\{globalThis\.crypto\.randomUUID\(\)\}/u);
  assert.match(resolve, /await client\.resolveWorkspaceAutonomyAttention\(/u);
  assert.equal(
    countMatches(resolve, /await client\.listWorkspaceAutonomyAttentions\(\);/gu),
    2,
  );
  assert.match(resolve, /caught instanceof DesktopApiError && caught\.status === 409/u);
  assert.match(resolve, /discardWorkspaceAutonomyAttentionResolveAttempt/u);
  assert.match(resolve, /applyCanonicalAttentions\(attentions, resolveError\)/u);
  assert.doesNotMatch(resolve, /new DesktopApiClient\(/u);
});

test('attention Provider owns exactly four transport methods and no App policy', () => {
  assert.match(
    testTypeScriptConfig,
    /src\/features\/workspace\/desktopWorkspaceAutonomyAttentionClientProviderV2\.ts/u,
  );
  for (const method of [
    'listWorkspaceAutonomyAttentions',
    'getWorkspaceAuthorityRevision',
    'retryWorkspaceAutonomyAttention',
    'resolveWorkspaceAutonomyAttention',
  ]) {
    assert.match(provider, new RegExp(`${method}:`));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /resolveWorkspaceAutonomyAttentionAttempt|retainOpenWorkspaceAutonomyAttentionResolveAttempts|discardWorkspaceAutonomyAttentionResolveAttempt|randomUUID|DesktopApiError|setWorkspaceAutonomyAttentionState/u,
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
