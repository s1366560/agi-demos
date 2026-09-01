import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authority = source('src/plugins/desktopWorkspaceExecutionSnapshotAuthorityModuleV2.ts');

test('App owns one stable workspace execution snapshot generation operation port', () => {
  assert.match(app, /createDesktopWorkspaceExecutionSnapshotOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceExecutionSnapshotOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceExecutionSnapshotOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceExecutionSnapshotClientProviderV2/u);
  assert.doesNotMatch(app, /desktopWorkspaceExecutionSnapshotClientV2/u);
});

test('runtime refresh keeps task and plan reads in their original slots', () => {
  const refresh = refreshRuntimeSource(app);

  assert.doesNotMatch(refresh, /workspaceExecutionSnapshotClient/u);
  assert.match(
    refresh,
    /workspaceId\s*\?\s*desktopWorkspaceExecutionSnapshotOperationsV2\.listTasks\(\{\s*config: resolvedConfig,?\s*\}\)\s*:\s*Promise\.resolve\(\[\]\)/u
  );
  assert.match(
    refresh,
    /workspaceId\s*\?\s*desktopWorkspaceExecutionSnapshotOperationsV2\s*\.getPlanSnapshot\(\{\s*config: resolvedConfig,?\s*\}\)\s*\.catch\(\(\) => null\)\s*:\s*Promise\.resolve\(null\)/u
  );
  assert.match(
    refresh,
    /const \[\s*messages,\s*tasks,\s*plan,\s*workspaceMembers,\s*workspaceAgents,/u
  );
  assert.doesNotMatch(
    refresh,
    /desktopWorkspaceExecutionSnapshotOperationsV2\.listTasks\([\s\S]{0,120}?\.catch/u
  );
  assert.match(refresh, /commitRuntimeConfig\(resolvedConfig\);/u);
  assert.match(refresh, /messages,\s*tasks,\s*plan,/u);
  assert.match(
    refresh,
    /desktopWorkspaceConversationCatalogClientV2,[\s\S]*?desktopWorkspaceExecutionSnapshotOperationsV2,[\s\S]*?desktopWorkspaceMessageCatalogOperationsV2,/u
  );
});

test('authority module owns only task and plan transport, identity and lease policy', () => {
  assert.match(authority, /DESKTOP_WORKSPACE_EXECUTION_SNAPSHOT_AUTHORITY_SERVICE_V2/u);
  assert.match(authority, /listTasks/u);
  assert.match(authority, /getPlanSnapshot/u);
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /kind: ['"]project['"]/u);
  assert.match(authority, /new DesktopApiClient/u);
  assert.doesNotMatch(
    authority,
    /listMessages|sendMessage|createTask|updateTask|deleteTask|approvePlan|listWorkspaceMembers|listWorkspaceAgents/u
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
