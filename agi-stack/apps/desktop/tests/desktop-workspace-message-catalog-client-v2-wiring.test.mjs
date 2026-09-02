import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authorityModule = source('src/plugins/desktopWorkspaceMessageCatalogAuthorityModuleV2.ts');
const retiredProvider = source(
  'src/features/workspace/desktopWorkspaceMessageCatalogClientProviderV2.ts'
);
const generationHost = source('src/plugins/useDesktopPluginGenerationV2.ts');

test('App constructs one stable generation-backed workspace message catalog operation port', () => {
  assert.match(app, /createDesktopWorkspaceMessageCatalogOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceMessageCatalogOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceMessageCatalogOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u
  );
  assert.doesNotMatch(
    app,
    /createDesktopWorkspaceMessageCatalogClientProviderV2|desktopWorkspaceMessageCatalogClientProviderV2|desktopWorkspaceMessageCatalogClientV2/u
  );
  assert.equal(retiredProvider, '');
  assert.match(generationHost, /desktopWorkspaceMessageCatalogAuthorityDefinitionV2/u);
});

test('runtime refresh pins message hydration to one V2 generation operation lease', () => {
  const refresh = refreshRuntimeSource(app);

  assert.equal(
    refresh.match(/desktopWorkspaceMessageCatalogOperationsV2\.listMessages\(/gu)?.length,
    1
  );
  assert.match(
    refresh,
    /workspaceId\s*\? desktopWorkspaceMessageCatalogOperationsV2\.listMessages\(\{\s*config: resolvedConfig,?\s*\}\)\s*:\s*Promise\.resolve\(\[\]\)/u
  );
  assert.doesNotMatch(
    refresh,
    /workspaceMessageCatalogClient|desktopWorkspaceMessageCatalogClientV2\.bindOperation/u
  );
  assert.match(
    refresh,
    /desktopWorkspaceExecutionSnapshotOperationsV2,[\s\S]*?desktopWorkspaceMessageCatalogOperationsV2,[\s\S]*?desktopWorkspaceRosterOperationsV2,/u
  );
});

test('message catalog migration preserves refresh ordering, failure, commit, and socket policy', () => {
  const refresh = refreshRuntimeSource(app);

  assert.match(
    refresh,
    /const \[\s*messages,\s*tasks,\s*plan,\s*workspaceMembers,\s*workspaceAgents,/u
  );
  assert.match(
    refresh,
    /await Promise\.all\(\[\s*workspaceId\s*\? desktopWorkspaceMessageCatalogOperationsV2\.listMessages\(\{\s*config: resolvedConfig,?\s*\}\)\s*:\s*Promise\.resolve\(\[\]\),\s*workspaceId\s*\? desktopWorkspaceExecutionSnapshotOperationsV2\.listTasks\(\{\s*config: resolvedConfig,?\s*\}\)\s*:\s*Promise\.resolve\(\[\]\),\s*workspaceId\s*\? desktopWorkspaceExecutionSnapshotOperationsV2\s*\.getPlanSnapshot\(\{\s*config: resolvedConfig,?\s*\}\)\s*\.catch\(\(\) => null\)\s*:\s*Promise\.resolve\(null\),/u
  );
  assert.doesNotMatch(
    refresh,
    /desktopWorkspaceMessageCatalogOperationsV2\.listMessages\([\s\S]{0,160}\.catch/u
  );
  assert.match(refresh, /commitRuntimeConfig\(resolvedConfig\);/u);
  assert.match(refresh, /messages,\s*tasks,\s*plan,/u);
  assert.match(
    app,
    /messages = applyWorkspaceMessageStreamEvent\(messages, event, workspaceId\)\.messages;/u
  );
});

test('workspace message catalog module owns only the message read authority', () => {
  assert.match(authorityModule, /service:desktop-renderer\.workspace-message-catalog-authority/u);
  assert.match(authorityModule, /listMessages:/u);
  assert.match(authorityModule, /acquireServiceOperationLease/u);
  assert.match(authorityModule, /kind: ['"]project['"]/u);
  assert.doesNotMatch(
    authorityModule,
    /sendMessage|listTasks|getPlanSnapshot|listConversations|listWorkspaceMembers|listWorkspaceAgents/u
  );
});

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
