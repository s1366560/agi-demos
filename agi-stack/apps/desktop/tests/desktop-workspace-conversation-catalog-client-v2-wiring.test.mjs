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
