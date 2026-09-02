import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { test } from "node:test";

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, "utf8") : "";
}

const app = source("src/App.tsx");
const provider = source(
  "src/features/workspace/desktopWorkspaceCatalogClientProviderV2.ts",
);
const authority = source(
  "src/plugins/desktopWorkspaceCatalogAuthorityModuleV2.ts",
);
const generation = source("src/plugins/useDesktopPluginGenerationV2.ts");

test("App creates one stable generation-backed workspace catalog operation port", () => {
  assert.match(app, /createDesktopWorkspaceCatalogOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceCatalogOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceCatalogOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceCatalogClientProviderV2/u);
  assert.doesNotMatch(app, /desktopWorkspaceCatalogClientProviderV2\.publish/u);
  assert.equal(provider, "");
});

test("runtime refresh pins each project workspace catalog read to one generation operation", () => {
  const refresh = refreshRuntimeSource(app);
  const catalogStart = refresh.indexOf(
    "const workspaceResults = await Promise.all",
  );
  const catalogEnd = refresh.indexOf(
    "\n        if (!contextIsCurrent())",
    catalogStart,
  );
  assert.notEqual(catalogStart, -1);
  assert.notEqual(catalogEnd, -1);
  const catalogLoader = refresh.slice(catalogStart, catalogEnd);

  assert.match(
    catalogLoader,
    /desktopWorkspaceCatalogOperationsV2\.listWorkspacesForProject\(\s*\{[\s\S]*?config:\s*\{[\s\S]*?\.\.\.runtimeConfig,[\s\S]*?tenantId: projectTenantId,[\s\S]*?projectId: project\.id,[\s\S]*?workspaceId:\s*["']{2},[\s\S]*?\},[\s\S]*?\}\s*,?\s*\)/u,
  );
  assert.doesNotMatch(catalogLoader, /\.bindOperation\(/u);
  assert.doesNotMatch(catalogLoader, /new DesktopApiClient\(/u);
  assert.match(
    refresh,
    /desktopWorkspaceAutonomyAttentionOperationsV2,[\s\S]*?desktopWorkspaceCatalogOperationsV2,[\s\S]*?desktopWorkspaceConversationCatalogOperationsV2,/u,
  );
});

test("workspace catalog authority owns one project-scoped generated service", () => {
  assert.match(authority, /DESKTOP_WORKSPACE_CATALOG_AUTHORITY_SERVICE_V2/u);
  assert.match(authority, /createDesktopWorkspaceCatalogOperationsV2/u);
  assert.match(authority, /listWorkspacesForProject:/u);
  assert.match(authority, /kind:\s*["']project["']/u);
  assert.match(authority, /workspaceId\s*!==\s*["']/u);
  assert.doesNotMatch(
    authority,
    /listWorkspaces\b|createWorkspace|updateWorkspace|listWorkspaceMembers|listWorkspaceAgents|listConversations/u,
  );
  assert.match(generation, /desktopWorkspaceCatalogAuthorityDefinitionV2/u);
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf("const refreshRuntime = useCallback(");
  assert.notEqual(start, -1);
  const end = sourceText.indexOf("\n  useEffect(() => {", start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
