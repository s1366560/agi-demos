import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source('src/features/session/desktopConversationConfigClientProviderV2.ts');
const stableProviderPattern = new RegExp(
  [
    'const desktopConversationConfigClientProviderV2 = useMemo\\(',
    '[\\s\\S]*?createDesktopConversationConfigClientProviderV2\\(\\)',
    '[\\s\\S]*?\\[\\],[\\s\\S]*?\\);',
  ].join(''),
  'u',
);

test('App publishes one stable V2 conversation config client Provider', () => {
  assert.match(app, /createDesktopConversationConfigClientProviderV2/u);
  assert.match(app, stableProviderPattern);
  assert.match(app, /desktopConversationConfigClientProviderV2\.publish\(\{ config \}\)/u);
});

test('conversation model mutations bind one submitted-scope V2 client', () => {
  const mutation = callbackSource(
    app,
    'persistChatRuntimeModelOverride',
    'selectChatRuntimeModel',
  );

  assert.match(mutation, /const requestConfig = configRef\.current;/u);
  assert.match(
    mutation,
    /const client = desktopConversationConfigClientV2\.bindOperation\(requestConfig\);/u,
  );
  assert.match(
    mutation,
    /await client\.updateAgentConversationConfig\([\s\S]*?conversation\.id,[\s\S]*?llm_model_override: overrideModel,[\s\S]*?requestConfig\.mode === 'local'[\s\S]*?llm_route_override: routeOverride \?\? null[\s\S]*?conversation\.project_id \|\| requestConfig\.projectId,/u,
  );
  assert.match(mutation, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.match(mutation, /desktopConversationConfigClientV2/u);
  assert.doesNotMatch(mutation, /api\.updateAgentConversationConfig/u);
});

test('conversation model mutation responses fail closed after request or scope drift', () => {
  const mutation = callbackSource(
    app,
    'persistChatRuntimeModelOverride',
    'selectChatRuntimeModel',
  );

  assert.match(
    mutation,
    /conversationModelMutationRequestRef\.current !== requestId/u,
  );
  assert.match(
    mutation,
    /activeSession\?\.scopeKey !== agentConversationScopeKey\(configRef\.current\)/u,
  );
  assert.match(mutation, /activeSession\.conversation\.id !== conversation\.id/u);
  assert.match(
    mutation,
    /current\?\.scopeKey !== activeSession\.scopeKey[\s\S]*?current\.conversation\.id !== conversation\.id/u,
  );
});

test('conversation config Provider owns only the transport mutation', () => {
  assert.match(
    provider,
    /type DesktopConversationConfigMethod = 'updateAgentConversationConfig'/u,
  );
  assert.match(provider, /updateAgentConversationConfig:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /conversationModelMutationRequestRef|agentConversationScopeKey|setConversationModelMutation|conversationRuntimeModelSelection/u,
  );
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
