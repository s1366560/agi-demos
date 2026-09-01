import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source('src/features/workspace/desktopWorkspaceCatalogClientProviderV2.ts');

test('App publishes one stable V2 workspace catalog Provider', () => {
  assert.match(app, /createDesktopWorkspaceCatalogClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceCatalogClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceCatalogClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(app, /desktopWorkspaceCatalogClientProviderV2\.publish\(\{ config \}\)/u);
});

test('runtime refresh pins each project workspace catalog read to one V2 operation binding', () => {
  const refresh = refreshRuntimeSource(app);
  const catalogStart = refresh.indexOf('const workspaceResults = await Promise.all');
  const catalogEnd = refresh.indexOf('\n        if (!contextIsCurrent())', catalogStart);
  assert.notEqual(catalogStart, -1);
  assert.notEqual(catalogEnd, -1);
  const catalogLoader = refresh.slice(catalogStart, catalogEnd);

  assert.match(
    catalogLoader,
    /desktopWorkspaceCatalogClientV2\.bindOperation\(\{[\s\S]*?\.\.\.runtimeConfig,[\s\S]*?tenantId: projectTenantId,[\s\S]*?projectId: project\.id,[\s\S]*?workspaceId: '',[\s\S]*?\}\)/u,
  );
  assert.match(
    catalogLoader,
    /client\.listWorkspacesForProject\(project\.id, projectTenantId\)/u,
  );
  assert.doesNotMatch(catalogLoader, /new DesktopApiClient\(/u);
  assert.match(
    refresh,
    /desktopWorkspaceAutonomyAttentionClientV2,[\s\S]*?desktopWorkspaceCatalogClientV2,[\s\S]*?desktopWorkspaceConversationCatalogClientV2,/u,
  );
});

test('workspace catalog Provider owns exactly one read method', () => {
  assert.match(provider, /type DesktopWorkspaceCatalogMethod = 'listWorkspacesForProject'/u);
  assert.match(provider, /listWorkspacesForProject:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /listWorkspaces\b|createWorkspace|updateWorkspace|listWorkspaceMembers|listWorkspaceAgents|listConversations/u,
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
