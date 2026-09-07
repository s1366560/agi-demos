import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authority = source(
  'src/plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2.ts',
);
const generation = desktopProductionRuntimeSource();
const legacyProviderUrl = new URL(
  '../src/features/workspace/desktopWorkspaceConversationCatalogClientProviderV2.ts',
  import.meta.url,
);

test('App owns one stable generation-bound workspace conversation catalog operations facade', () => {
  assert.match(app, /createDesktopWorkspaceConversationCatalogOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceConversationCatalogOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceConversationCatalogOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceConversationCatalogClientProviderV2/u);
  assert.doesNotMatch(app, /desktopWorkspaceConversationCatalogClientProviderV2/u);
  assert.equal(existsSync(legacyProviderUrl), false);
  assert.match(generation, /desktopWorkspaceConversationCatalogAuthorityDefinitionV2/u);
  assert.match(
    authority,
    /service:desktop-renderer\.workspace-conversation-catalog-authority/u,
  );
  assert.match(authority, /acquireServiceOperationLease/u);
});

test('workspace conversation hydration pins immutable filters to one project generation lease', () => {
  const loader = callbackSource(app, 'loadWorkspaceConversations', 'refreshMyWork');
  assert.match(
    loader,
    /desktopWorkspaceConversationCatalogOperationsV2\.listConversations\(\{[\s\S]*?config: requestConfig,[\s\S]*?workspaceId: isUnboundGroup \? null : workspaceId,[\s\S]*?unboundOnly: isUnboundGroup,[\s\S]*?\}\)/u,
  );
  assert.match(
    loader,
    /\[\s*clearMissingConversationSelection,\s*desktopWorkspaceConversationCatalogOperationsV2,\s*updateDataset,?\s*\]/u,
  );
  assert.doesNotMatch(loader, /new DesktopApiClient\(/u);
});

test('runtime refresh pins each catalog target to one submitted project generation', () => {
  const refresh = refreshRuntimeSource(app);
  const conversationLoaderStart = refresh.indexOf('const conversationResultsPromise');
  const conversationLoaderEnd = refresh.indexOf('\n        const [', conversationLoaderStart);
  assert.notEqual(conversationLoaderStart, -1);
  assert.notEqual(conversationLoaderEnd, -1);
  const conversationLoader = refresh.slice(conversationLoaderStart, conversationLoaderEnd);

  assert.match(
    conversationLoader,
    /desktopWorkspaceConversationCatalogOperationsV2\.listConversations\(\{[\s\S]*?config: resolvedConfig,[\s\S]*?workspaceId: isUnboundGroup \? null : targetWorkspaceId,[\s\S]*?unboundOnly: isUnboundGroup,[\s\S]*?\}\)/u,
  );
  assert.doesNotMatch(conversationLoader, /new DesktopApiClient\(/u);
  assert.match(
    refresh,
    /desktopWorkspaceAutonomyAttentionOperationsV2,[\s\S]*?desktopWorkspaceConversationCatalogOperationsV2,[\s\S]*?listMyWorkForConfig/u,
  );
});

test('session fallback lookups use submitted-scope generation operations', () => {
  const myWorkLoader = functionSource(app, 'openMyWorkSession', 'openAgentSession');
  assert.match(
    myWorkLoader,
    /desktopWorkspaceConversationCatalogOperationsV2\.listConversations\(\{[\s\S]*?config: \{[\s\S]*?\.\.\.config,[\s\S]*?projectId: item\.project_id,[\s\S]*?workspaceId,[\s\S]*?\},[\s\S]*?workspaceId: workspaceId \|\| null,[\s\S]*?unboundOnly: !workspaceId,[\s\S]*?\}\)/u,
  );
  assert.match(myWorkLoader, /myWorkConversationMatchesScope/u);
  assert.match(myWorkLoader, /contextRevisionRef\.current/u);
  assert.match(myWorkLoader, /configScopeEpochRef\.current/u);
  assert.doesNotMatch(myWorkLoader, /api\.listConversations/u);

  const agentLoader = functionSource(app, 'openAgentSession', 'createBoardWorkbenchViewV2');
  assert.match(
    agentLoader,
    /desktopWorkspaceConversationCatalogOperationsV2\.listConversations\(\{[\s\S]*?config: \{[\s\S]*?\.\.\.config,[\s\S]*?projectId,[\s\S]*?workspaceId,[\s\S]*?\},[\s\S]*?workspaceId,[\s\S]*?unboundOnly: false,[\s\S]*?\}\)/u,
  );
  assert.match(agentLoader, /conversation\.tenant_id !== config\.tenantId/u);
  assert.match(agentLoader, /conversation\.workspace_id !== workspaceId/u);
  assert.match(agentLoader, /contextRevisionRef\.current/u);
  assert.match(agentLoader, /configScopeEpochRef\.current/u);
  assert.doesNotMatch(agentLoader, /api\.listConversations/u);
});

test('workspace conversation catalog authority owns exactly one read operation', () => {
  assert.match(authority, /listConversations:/u);
  assert.match(authority, /bindOperation/u);
  assert.doesNotMatch(
    authority,
    /loadRuntime|getConversationMessages|createConversation|deleteConversation|refreshRuntime/u,
  );
});

test('every App conversation catalog read is covered by one generation operation', () => {
  assert.equal(
    app.match(/desktopWorkspaceConversationCatalogOperationsV2\.listConversations\(/gu)
      ?.length,
    4,
  );
  assert.doesNotMatch(app, /(?:api|scopedClient|client)\.listConversations\(/u);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}

function functionSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = async`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}

function refreshRuntimeSource(sourceText) {
  const start = sourceText.indexOf('const refreshRuntime = useCallback(');
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  useEffect(() => {', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
