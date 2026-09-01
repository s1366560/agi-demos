import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceMessageCatalogClientProviderV2.ts',
);

test('App publishes one stable V2 workspace message catalog Provider', () => {
  assert.match(app, /createDesktopWorkspaceMessageCatalogClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceMessageCatalogClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceMessageCatalogClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceMessageCatalogClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('runtime refresh pins message hydration to one V2 operation binding', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /const workspaceMessageCatalogClient =\s*desktopWorkspaceMessageCatalogClientV2\.bindOperation\(resolvedConfig\);/u,
  );
  assert.equal(
    refresh.match(/desktopWorkspaceMessageCatalogClientV2\.bindOperation\(resolvedConfig\)/gu)
      ?.length,
    1,
  );
  assert.match(
    refresh,
    /workspaceId \? workspaceMessageCatalogClient\.listMessages\(\) : Promise\.resolve\(\[\]\)/u,
  );
  assert.doesNotMatch(refresh, /scopedClient\.listMessages\(\)/u);
  assert.match(
    refresh,
    /desktopWorkspaceExecutionSnapshotClientV2,[\s\S]*?desktopWorkspaceMessageCatalogClientV2,[\s\S]*?desktopWorkspaceRosterClientV2,/u,
  );
});

test('message catalog migration preserves refresh ordering, failure, commit, and socket policy', () => {
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
    /workspaceMessageCatalogClient\.listMessages\(\)\.catch/u,
  );
  assert.match(refresh, /commitRuntimeConfig\(resolvedConfig\);/u);
  assert.match(refresh, /messages,\s*tasks,\s*plan,/u);
  assert.match(
    app,
    /messages = applyWorkspaceMessageStreamEvent\(messages, event, workspaceId\)\.messages;/u,
  );
});

test('workspace message catalog Provider owns only the message read authority', () => {
  assert.match(
    provider,
    /type DesktopWorkspaceMessageCatalogMethod = 'listMessages';/u,
  );
  assert.match(provider, /listMessages:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /sendMessage|listTasks|getPlanSnapshot|listConversations|listWorkspaceMembers|listWorkspaceAgents/u,
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
