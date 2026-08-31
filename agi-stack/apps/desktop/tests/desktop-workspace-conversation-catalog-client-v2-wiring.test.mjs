import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceConversationCatalogClientProviderV2.ts',
);

test('App publishes one stable V2 workspace conversation catalog Provider', () => {
  assert.match(app, /createDesktopWorkspaceConversationCatalogClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceConversationCatalogClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceConversationCatalogClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceConversationCatalogClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('workspace conversation hydration pins one submitted-scope V2 operation binding', () => {
  const loader = callbackSource(app, 'loadWorkspaceConversations', 'refreshMyWork');
  assert.match(
    loader,
    /desktopWorkspaceConversationCatalogClientV2\.bindOperation\(\{[\s\S]*?\.\.\.requestConfig,[\s\S]*?workspaceId: isUnboundGroup \? '' : workspaceId,[\s\S]*?\}\)/u,
  );
  assert.match(
    loader,
    /client\.listConversations\(projectId, \{[\s\S]*?workspaceId: isUnboundGroup \? null : workspaceId,[\s\S]*?unboundOnly: isUnboundGroup,/u,
  );
  assert.match(
    loader,
    /\[\s*clearMissingConversationSelection,\s*desktopWorkspaceConversationCatalogClientV2,\s*updateDataset,?\s*\]/u,
  );
  assert.doesNotMatch(loader, /new DesktopApiClient\(/u);
});

test('session fallback lookups pin submitted-scope V2 conversation catalog operations', () => {
  const myWorkLoader = functionSource(app, 'openMyWorkSession', 'openAgentSession');
  assert.match(
    myWorkLoader,
    /desktopWorkspaceConversationCatalogClientV2\.bindOperation\(\{[\s\S]*?\.\.\.config,[\s\S]*?projectId: item\.project_id,[\s\S]*?workspaceId,[\s\S]*?\}\)/u,
  );
  assert.match(
    myWorkLoader,
    /client\.listConversations\(\s*item\.project_id,\s*workspaceId \? workspaceId : \{ workspaceId: null, unboundOnly: true \},\s*\)/u,
  );
  assert.match(myWorkLoader, /myWorkConversationMatchesScope/u);
  assert.match(myWorkLoader, /contextRevisionRef\.current/u);
  assert.match(myWorkLoader, /configScopeEpochRef\.current/u);
  assert.doesNotMatch(myWorkLoader, /api\.listConversations/u);

  const agentLoader = functionSource(app, 'openAgentSession', 'createBoardWorkbenchViewV2');
  assert.match(
    agentLoader,
    /desktopWorkspaceConversationCatalogClientV2\.bindOperation\(\{[\s\S]*?\.\.\.config,[\s\S]*?projectId,[\s\S]*?workspaceId,[\s\S]*?\}\)/u,
  );
  assert.match(agentLoader, /client\.listConversations\(projectId, workspaceId\)/u);
  assert.match(agentLoader, /conversation\.tenant_id !== config\.tenantId/u);
  assert.match(agentLoader, /conversation\.workspace_id !== workspaceId/u);
  assert.match(agentLoader, /contextRevisionRef\.current/u);
  assert.match(agentLoader, /configScopeEpochRef\.current/u);
  assert.doesNotMatch(agentLoader, /api\.listConversations/u);
});

test('workspace conversation catalog Provider owns exactly one read method', () => {
  assert.match(provider, /type DesktopWorkspaceConversationCatalogMethod = 'listConversations'/u);
  assert.match(provider, /listConversations:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /loadRuntime|getConversationMessages|createConversation|deleteConversation|refreshRuntime/u,
  );
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
