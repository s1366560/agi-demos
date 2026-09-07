import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source('src/features/workspace/desktopWorkspaceRosterClientProviderV2.ts');
const authority = source('src/plugins/desktopWorkspaceRosterAuthorityModuleV2.ts');
const routePermissionClient = source('src/features/navigation/desktopRoutePermissionHttpClient.ts');
const routeAuthorityProvider = source(
  'src/features/navigation/desktopProductionRouteAuthorityProviderV2.ts'
);
const policyHook = source('src/features/settings/useWorkspaceAgentPolicy.ts');
const composerCatalogProvider = source(
  'src/features/task/desktopNewThreadComposerCatalogClientProviderV2.ts'
);

test('App resolves one stable V2 workspace roster operation facade', () => {
  assert.match(
    app,
    /const desktopWorkspaceRosterOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceRosterOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceRosterClientProviderV2/u);
  assert.equal(provider, '');
});

test('runtime refresh resolves both roster reads through project generation leases', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /desktopWorkspaceRosterOperationsV2\.listWorkspaceMembers\(\{[\s\S]*?config: resolvedConfig[\s\S]*?\}\)/u
  );
  assert.match(
    refresh,
    /desktopWorkspaceRosterOperationsV2\.listWorkspaceAgents\(\{[\s\S]*?config: resolvedConfig[\s\S]*?\}\)/u
  );
  assert.doesNotMatch(refresh, /workspaceRosterClient|\.bindOperation\(resolvedConfig\)/u);
  assert.match(
    refresh,
    /desktopWorkspaceConversationCatalogOperationsV2,[\s\S]*?desktopWorkspaceRosterOperationsV2,/u
  );
});

test('workspace roster module owns exactly two read operations', () => {
  assert.match(
    authority,
    /DESKTOP_WORKSPACE_ROSTER_AUTHORITY_SERVICE_V2 =[\s\S]*?'service:desktop-renderer\.workspace-roster-authority'/u
  );
  assert.match(authority, /listWorkspaceMembers/u);
  assert.match(authority, /listWorkspaceAgents/u);
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.doesNotMatch(
    authority,
    /addWorkspaceMember|removeWorkspaceMember|updateWorkspaceMemberRole|bindWorkspaceAgent|unbindWorkspaceAgent|listWorkspacesForProject|listConversations/u
  );
});

test('route permissions, policy and New Thread delegate roster reads to the same V2 seam', () => {
  assert.match(routePermissionClient, /workspaceRosterOperationsV2\.listWorkspaceMembers/u);
  assert.doesNotMatch(routePermissionClient, /scoped\.listWorkspaceMembers/u);
  assert.match(routeAuthorityProvider, /workspaceRosterOperationsV2/u);
  assert.match(policyHook, /workspaceRosterOperationsV2\.listWorkspaceMembers/u);
  assert.doesNotMatch(policyHook, /client\.listWorkspaceMembers/u);
  assert.match(composerCatalogProvider, /workspaceRosterOperationsV2\.listWorkspaceAgents/u);
  assert.doesNotMatch(composerCatalogProvider, /authority\.listWorkspaceAgents/u);
  assert.match(app, /workspaceRosterOperationsV2:\s*desktopWorkspaceRosterOperationsV2/u);
  assert.match(
    app,
    /useWorkspaceAgentPolicy\([\s\S]*?newThreadRuntimeConfig,[\s\S]*?desktopWorkspaceRosterOperationsV2/u
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
