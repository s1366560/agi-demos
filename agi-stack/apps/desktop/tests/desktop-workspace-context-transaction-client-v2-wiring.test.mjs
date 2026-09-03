import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceContextTransactionClientProviderV2.ts',
);
const settingsCorePages = source('src/features/settings/SettingsCorePages.tsx');
const settingsWindow = source('src/features/settings/SettingsWindow.tsx');

test('App publishes one stable V2 workspace-context transaction Provider', () => {
  assert.match(app, /createDesktopWorkspaceContextTransactionClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceContextTransactionClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceContextTransactionClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceContextTransactionClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('route scope transaction resolves its narrow authority inside the existing route lease', () => {
  const routeTransaction = section(
    app,
    'const productionRouteScopeTransaction = useMemo(',
    '\n  const switchProductionRouteScope',
  );

  assert.match(
    routeTransaction,
    /createAuthority: \(authorityConfig\) =>[\s\S]*?desktopWorkspaceContextTransactionClientProviderV2[\s\S]*?\.resolve\(\)[\s\S]*?\.bindOperation\(authorityConfig\)/u,
  );
  assert.doesNotMatch(routeTransaction, /new DesktopApiClient/u);
  assert.match(routeTransaction, /commitRuntimeConfig\(nextConfig\)/u);
  assert.match(routeTransaction, /await productionRouteRefreshRef\.current/u);
});

test('Settings project loading uses an abortable V2 operation instead of a general API client', () => {
  const workspacePage = section(
    settingsCorePages,
    'export function WorkspaceSettingsPage(',
    '\nexport function GeneralSettingsPage',
  );

  assert.doesNotMatch(settingsCorePages, /import \{ DesktopApiClient \}/u);
  assert.doesNotMatch(workspacePage, /new DesktopApiClient/u);
  assert.match(workspacePage, /listWorkspaceContextProjects/u);
  assert.match(workspacePage, /const controller = new AbortController\(\)/u);
  assert.match(
    workspacePage,
    /listWorkspaceContextProjects\(tenantId, controller\.signal\)/u,
  );
  assert.match(workspacePage, /return \(\) => controller\.abort\(\)/u);
  assert.match(settingsWindow, /listWorkspaceContextProjects/u);
  assert.match(
    settingsWindow,
    /<WorkspaceSettingsPage[\s\S]*?listWorkspaceContextProjects=\{listWorkspaceContextProjects\}/u,
  );
});

test('Settings list and apply operations hold one generation lease across each transaction', () => {
  const listProjects = section(
    app,
    'const listSettingsWorkspaceContextProjects = useCallback(',
    '\n  const sandboxRuntime',
  );
  const applyContext = section(
    app,
    'const applySettingsContext = async',
    '\n\n  const goBackSection',
  );

  for (const operation of [listProjects, applyContext]) {
    assert.match(operation, /runDesktopWorkspaceContextOperationV2/u);
    assert.match(
      operation,
      /desktopRendererGenerationV2\.actions\.acquireOperationLease/u,
    );
    assert.match(
      operation,
      /desktopWorkspaceContextTransactionClientProviderV2[\s\S]*?\.resolve\(\)[\s\S]*?\.bindOperation/u,
    );
    assert.doesNotMatch(operation, /new DesktopApiClient/u);
  }
  assert.match(app, /listWorkspaceContextProjects: listSettingsWorkspaceContextProjects/u);
});

test('Settings context migration preserves stale checks, validation, commit, and refresh ordering', () => {
  const applyContext = section(
    app,
    'const applySettingsContext = async',
    '\n\n  const goBackSection',
  );

  assert.match(applyContext, /authAttemptRevisionRef\.current === authAttemptRevision/u);
  assert.match(applyContext, /isSameDesktopRequestScope\(requestConfig, configRef\.current\)/u);
  assert.match(applyContext, /auth\.tenants\.some/u);
  assert.match(applyContext, /const listedProjects = await contextClient\.listProjects/u);
  assert.match(applyContext, /let currentContext = auth\.context/u);
  assert.match(applyContext, /await contextClient\.getWorkspaceContext/u);
  assert.match(applyContext, /await contextClient\.switchWorkspaceContext/u);
  assert.match(applyContext, /workspaceContextMatchesSelection/u);
  assert.match(
    applyContext,
    /resetProjectScopedState\(\);[\s\S]*?commitRuntimeConfig\(nextConfig\);[\s\S]*?setAuth\([\s\S]*?applySectionSideEffects\('workspace'\);[\s\S]*?await refreshRuntime/u,
  );
});

test('workspace-context Provider owns exactly the three transaction methods', () => {
  assert.match(
    provider,
    /type DesktopWorkspaceContextTransactionMethod =[\s\S]*?'listProjects'[\s\S]*?'getWorkspaceContext'[\s\S]*?'switchWorkspaceContext'/u,
  );
  assert.match(provider, /listProjects:/u);
  assert.match(provider, /getWorkspaceContext:/u);
  assert.match(provider, /switchWorkspaceContext:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /listTenants:|currentUser:|listWorkspaces:|createWorkspaceForProject:/u,
  );
});

function section(sourceText, startMarker, endMarker) {
  const start = sourceText.indexOf(startMarker);
  assert.notEqual(start, -1, `missing start marker: ${startMarker}`);
  const end = sourceText.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(end, -1, `missing end marker: ${endMarker}`);
  return sourceText.slice(start, end);
}
