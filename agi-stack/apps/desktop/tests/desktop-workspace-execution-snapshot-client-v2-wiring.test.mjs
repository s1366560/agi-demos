import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceExecutionSnapshotClientProviderV2.ts',
);

test('App publishes one stable V2 workspace execution snapshot Provider', () => {
  assert.match(app, /createDesktopWorkspaceExecutionSnapshotClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceExecutionSnapshotClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceExecutionSnapshotClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceExecutionSnapshotClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('runtime refresh pins task and plan hydration to one V2 operation binding', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /const workspaceExecutionSnapshotClient =\s*desktopWorkspaceExecutionSnapshotClientV2\.bindOperation\(resolvedConfig\);/u,
  );
  assert.equal(
    refresh.match(
      /desktopWorkspaceExecutionSnapshotClientV2\.bindOperation\(resolvedConfig\)/gu,
    )?.length,
    1,
  );
  assert.match(
    refresh,
    /workspaceId \? workspaceExecutionSnapshotClient\.listTasks\(\) : Promise\.resolve\(\[\]\)/u,
  );
  assert.match(
    refresh,
    /workspaceId\s*\? workspaceExecutionSnapshotClient\.getPlanSnapshot\(\)\.catch\(\(\) => null\)\s*:\s*Promise\.resolve\(null\)/u,
  );
  assert.doesNotMatch(refresh, /scopedClient\.(?:listTasks|getPlanSnapshot)\(\)/u);
  assert.doesNotMatch(refresh, /const scopedClient = new DesktopApiClient\(resolvedConfig\);/u);
  assert.match(
    refresh,
    /desktopWorkspaceConversationCatalogClientV2,[\s\S]*?desktopWorkspaceExecutionSnapshotClientV2,[\s\S]*?desktopWorkspaceMessageCatalogClientV2,/u,
  );
});

test('execution snapshot migration preserves refresh ordering, failure, and commit policy', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /const \[\s*messages,\s*tasks,\s*plan,\s*workspaceMembers,\s*workspaceAgents,/u,
  );
  assert.match(
    refresh,
    /await Promise\.all\(\[\s*workspaceId \? workspaceMessageCatalogClient\.listMessages\(\) : Promise\.resolve\(\[\]\),\s*workspaceId \? workspaceExecutionSnapshotClient\.listTasks\(\) : Promise\.resolve\(\[\]\),\s*workspaceId\s*\? workspaceExecutionSnapshotClient\.getPlanSnapshot\(\)\.catch\(\(\) => null\)\s*:\s*Promise\.resolve\(null\),/u,
  );
  assert.doesNotMatch(
    refresh,
    /workspaceExecutionSnapshotClient\.listTasks\(\)\.catch/u,
  );
  assert.match(refresh, /commitRuntimeConfig\(resolvedConfig\);/u);
  assert.match(refresh, /messages,\s*tasks,\s*plan,/u);
});

test('workspace execution snapshot Provider owns only task and plan reads', () => {
  assert.match(
    provider,
    /type DesktopWorkspaceExecutionSnapshotMethod =[\s\S]*?'listTasks'[\s\S]*?'getPlanSnapshot'/u,
  );
  assert.match(provider, /listTasks:/u);
  assert.match(provider, /getPlanSnapshot:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /listMessages|sendMessage|createTask|updateTask|deleteTask|approvePlan|listWorkspaceMembers|listWorkspaceAgents/u,
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
