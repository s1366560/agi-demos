import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const generationHook = desktopProductionRuntimeSource();
const authorityModule = source('src/plugins/desktopConversationConfigAuthorityModuleV2.ts');
const legacyProviderPath = new URL(
  '../src/features/session/desktopConversationConfigClientProviderV2.ts',
  import.meta.url,
);

test('App creates one stable generation-backed conversation config operation port', () => {
  assert.match(app, /createDesktopConversationConfigOperationsV2/u);
  assert.match(
    app,
    /const desktopConversationConfigOperationsV2 = useMemo\([\s\S]*?createDesktopConversationConfigOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopConversationConfigClientProviderV2/u);
  assert.doesNotMatch(app, /desktopConversationConfigClientProviderV2/u);
  assert.doesNotMatch(app, /desktopConversationConfigClientV2/u);
  assert.equal(existsSync(legacyProviderPath), false);
});

test('conversation model mutations enter the session-scoped V2 authority once', () => {
  const mutation = callbackSource(
    app,
    'persistChatRuntimeModelOverride',
    'selectChatRuntimeModel',
  );

  assert.match(mutation, /const requestConfig = configRef\.current;/u);
  assert.match(
    mutation,
    /await desktopConversationConfigOperationsV2\.updateModelOverride\(\{[\s\S]*?config: requestConfig,[\s\S]*?conversation,[\s\S]*?llmModelOverride: overrideModel,[\s\S]*?llmRouteOverride: routeOverride \?\? null,[\s\S]*?\}\);/u,
  );
  assert.match(mutation, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.doesNotMatch(mutation, /updateAgentConversationConfig/u);
  assert.doesNotMatch(mutation, /new DesktopApiClient/u);
});

test('response freshness guards remain outside the transport authority', () => {
  const mutation = callbackSource(
    app,
    'persistChatRuntimeModelOverride',
    'selectChatRuntimeModel',
  );

  assert.match(mutation, /conversationModelMutationRequestRef\.current !== requestId/u);
  assert.match(
    mutation,
    /activeSession\?\.scopeKey !== agentConversationScopeKey\(configRef\.current\)/u,
  );
  assert.match(mutation, /activeSession\.conversation\.id !== conversation\.id/u);
  assert.match(
    mutation,
    /current\?\.scopeKey !== activeSession\.scopeKey[\s\S]*?current\.conversation\.id !== conversation\.id/u,
  );
  assert.doesNotMatch(
    authorityModule,
    /conversationModelMutationRequestRef|agentConversationScopeKey|setConversationModelMutation|conversationRuntimeModelSelection/u,
  );
});

test('desktop renderer runtime registers only the generated V2 authority definition', () => {
  assert.match(generationHook, /desktopConversationConfigAuthorityDefinitionV2/u);
  assert.match(
    generationHook,
    /desktopConversationConfigAuthorityDefinitionV2,[\s\S]*desktopTerminalLifecycleAuthorityDefinitionV2/u,
  );
  assert.match(
    authorityModule,
    /service:desktop-renderer\.conversation-config-authority/u,
  );
  assert.doesNotMatch(generationHook, /desktopConversationConfigClientProviderV2/u);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
