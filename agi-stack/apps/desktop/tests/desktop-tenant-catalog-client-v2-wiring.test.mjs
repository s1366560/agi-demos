import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL('../' + relativePath, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const registry = source('src/features/navigation/appRouteRegistry.ts');
const authority = source('src/plugins/desktopTenantCatalogAuthorityModuleV2.ts');
const oldProvider = source('src/features/tenant/desktopTenantCatalogClientProviderV2.ts');
const cloudAuth = source('src/hooks/useCloudSessionAuth.ts');
const localAuth = source('src/hooks/useLocalCredentialAuth.ts');

test('App injects stable V2 tenant catalog operations backed by the generation actions ref', () => {
  assert.match(app, /createDesktopTenantCatalogOperationsV2/u);
  assert.match(
    app,
    /const desktopTenantCatalogOperationsV2 = useMemo\([\s\S]*?createDesktopTenantCatalogOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  const routeRefs = sourceBetween(
    app,
    'const desktopRendererRouteRefsV2 = useMemo(',
    'const desktopRendererCompositionV2 = useMemo(',
  );
  assert.match(routeRefs, /tenantCatalogOperationsV2:\s*desktopTenantCatalogOperationsV2/u);
  assert.doesNotMatch(routeRefs, /desktopTenantCatalogClientProviderV2/u);
  assert.doesNotMatch(app, /createDesktopTenantCatalogClientProviderV2/u);
  assert.doesNotMatch(app, /desktopTenantCatalogClientProviderV2\.publish/u);
});

test('invitation and tenant creation refresh only inside callbacks with exact V2 operations', () => {
  const invitation = sourceBetween(
    registry,
    'function createInvitationAcceptanceRouteLoader',
    'export function createAppAuthenticationRouteRegistry',
  );
  const tenantCreationStart = registry.indexOf(
    'export function createAppTenantCreationRouteRegistry',
  );
  assert.notEqual(tenantCreationStart, -1);
  const tenantCreation = registry.slice(tenantCreationStart);

  assert.match(
    invitation,
    /tenantCatalogOperationsV2\.listTenants\(\s*configRef\.current,\s*signal,?\s*\)/u,
  );
  assert.match(invitation, /if \(signal\.aborted\) return/u);
  assert.match(
    invitation,
    /authoritativeTenants\.some\(\(tenant\) => tenant\.id === invitation\.tenant_id\)[\s\S]*?tenantId:\s*invitation\.tenant_id,[\s\S]*?projectId:\s*'',[\s\S]*?workspaceId:\s*''/u,
  );
  assert.match(invitation, /Acceptance remains authoritative even if catalog refresh is stale/u);
  assert.doesNotMatch(invitation, /\.resolve\(\)|\.bindOperation\(/u);

  const createBinding = sourceBetween(
    tenantCreation,
    'createBinding: () => {',
    'onCreated: async',
  );
  assert.doesNotMatch(createBinding, /tenantCatalog|bindOperation|acquireServiceOperationLease/u);
  assert.match(
    tenantCreation,
    /tenants:\s*\[\.\.\.upsertCreatedTenant/u,
  );
  assert.match(
    tenantCreation,
    /tenantCatalogOperationsV2\.listTenants\(\s*currentConfig,\s*signal,?\s*\)/u,
  );
  assert.match(
    tenantCreation,
    /if \(signal\.aborted\)[\s\S]*?catalogRefreshed:\s*false[\s\S]*?tenants:\s*authoritativeTenants[\s\S]*?catalogRefreshed:\s*true/u,
  );
  assert.doesNotMatch(registry, /desktopTenantCatalogClientProviderV2/u);
  assert.doesNotMatch(registry, /new DesktopApiClient/u);
  assert.doesNotMatch(registry, /import \{ DesktopApiClient \}/u);
});

test('tenant catalog V2 owns transport only and leaves authentication reads in the kernel', () => {
  assert.match(authority, /interface DesktopTenantCatalogAuthorityV2/u);
  assert.match(authority, /listTenants:/u);
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /scope:\s*Object\.freeze\(\{\s*kind:\s*'root'\s*\}\)/u);
  assert.doesNotMatch(
    authority,
    /setAuth|commitRuntimeConfig|upsertCreatedTenant|invitation|catalogRefreshed/u,
  );
  assert.equal(oldProvider, '');
  assert.match(cloudAuth, /identityClient\.listTenants\(\)/u);
  assert.match(localAuth, /identityClient\.listTenants\(\)/u);
});

function sourceBetween(sourceText, startMarker, endMarker) {
  const start = sourceText.indexOf(startMarker);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
