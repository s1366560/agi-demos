import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source('src/features/workspace/desktopWorkspaceRosterClientProviderV2.ts');

test('App publishes one stable V2 workspace roster Provider', () => {
  assert.match(app, /createDesktopWorkspaceRosterClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceRosterClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceRosterClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(app, /desktopWorkspaceRosterClientProviderV2\.publish\(\{ config \}\)/u);
});

test('runtime refresh pins workspace roster hydration to one V2 operation binding', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /const workspaceRosterClient =\s*desktopWorkspaceRosterClientV2\.bindOperation\(resolvedConfig\);/u,
  );
  assert.match(
    refresh,
    /resolveWorkspaceAuthority\(workspaceRosterClient\.listWorkspaceMembers\(\)\)/u,
  );
  assert.match(
    refresh,
    /resolveWorkspaceAuthority\(workspaceRosterClient\.listWorkspaceAgents\(\)\)/u,
  );
  assert.doesNotMatch(
    refresh,
    /scopedClient\.listWorkspace(?:Members|Agents)\(\)/u,
  );
  assert.match(
    refresh,
    /desktopWorkspaceConversationCatalogClientV2,[\s\S]*?desktopWorkspaceRosterClientV2,/u,
  );
});

test('workspace roster Provider owns only read authority', () => {
  assert.match(
    provider,
    /type DesktopWorkspaceRosterMethod =[\s\S]*?'listWorkspaceMembers'[\s\S]*?'listWorkspaceAgents'/u,
  );
  assert.match(provider, /listWorkspaceMembers:/u);
  assert.match(provider, /listWorkspaceAgents:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /addWorkspaceMember|removeWorkspaceMember|updateWorkspaceMemberRole|bindWorkspaceAgent|unbindWorkspaceAgent|listWorkspacesForProject|listConversations/u,
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
