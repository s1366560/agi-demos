import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const registry = source('src/features/navigation/appRouteRegistry.ts');
const provider = source('src/features/tenant/desktopTenantCatalogClientProviderV2.ts');
const cloudAuth = source('src/hooks/useCloudSessionAuth.ts');
const localAuth = source('src/hooks/useLocalCredentialAuth.ts');

test('App publishes one stable tenant catalog Provider into renderer route composition', () => {
  assert.match(app, /createDesktopTenantCatalogClientProviderV2/u);
  assert.match(
    app,
    /const desktopTenantCatalogClientProviderV2 = useMemo\([\s\S]*?createDesktopTenantCatalogClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopTenantCatalogClientProviderV2\.publish\(\{ config \}\)/u,
  );
  const routeRefs = sourceBetween(
    app,
    'const desktopRendererRouteRefsV2 = useMemo(',
    'const desktopRendererCompositionV2 = useMemo(',
  );
  assert.match(routeRefs, /desktopTenantCatalogClientProviderV2/u);
  assert.doesNotMatch(routeRefs, /\n\s*api,?\s*\n/u);
});

test('invitation and tenant creation route loaders use operation-bound tenant catalogs', () => {
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
    /desktopTenantCatalogClientProviderV2[\s\S]*?\.resolve\(\)[\s\S]*?\.bindOperation\(configRef\.current\)/u,
  );
  assert.match(invitation, /await tenantCatalogClient\.listTenants\(signal\)/u);
  assert.match(invitation, /if \(signal\.aborted\) return/u);
  assert.match(
    invitation,
    /authoritativeTenants\.some\(\(tenant\) => tenant\.id === invitation\.tenant_id\)[\s\S]*?tenantId:\s*invitation\.tenant_id,[\s\S]*?projectId:\s*'',[\s\S]*?workspaceId:\s*''/u,
  );
  assert.match(invitation, /Acceptance remains authoritative even if catalog refresh is stale/u);

  assert.match(
    tenantCreation,
    /desktopTenantCatalogClientProviderV2[\s\S]*?\.resolve\(\)[\s\S]*?\.bindOperation\(currentConfig\)/u,
  );
  assert.match(tenantCreation, /tenants:\s*\[\.\.\.upsertCreatedTenant/u);
  assert.match(tenantCreation, /await tenantCatalogClient\.listTenants\(signal\)/u);
  assert.match(
    tenantCreation,
    /if \(signal\.aborted\)[\s\S]*?catalogRefreshed:\s*false[\s\S]*?tenants:\s*authoritativeTenants[\s\S]*?catalogRefreshed:\s*true/u,
  );
  assert.doesNotMatch(registry, /new DesktopApiClient/u);
  assert.doesNotMatch(registry, /import \{ DesktopApiClient \}/u);
  assert.doesNotMatch(registry, /\n\s*api:\s*DesktopApiClient;/u);
});

test('tenant catalog Provider owns transport only and leaves authentication catalog reads intact', () => {
  assert.match(provider, /type DesktopTenantCatalogMethod = 'listTenants'/u);
  assert.match(provider, /listTenants:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /setAuth|commitRuntimeConfig|upsertCreatedTenant|invitation|catalogRefreshed/u,
  );
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
