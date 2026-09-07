import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const conversationHook = source('src/hooks/useConversationMessaging.ts');
const conversationFacade = source('src/hooks/useAgentConversation.ts');
const generationHook = desktopProductionRuntimeSource();
const authorityModule = source('src/plugins/desktopSessionRunInputAuthorityModuleV2.ts');
const cloudClient = source('src/features/agent-authority/cloudAgentAuthorityClient.ts');
const cloudTypes = source('src/features/agent-authority/agentAuthorityTypes.ts');
const cloudContract = source('src/features/agent-authority/agentAuthorityContract.ts');
const cloudProjection = source('src/features/agent-authority/agentAuthorityProjection.ts');
const testTypeScriptConfig = source('tsconfig.test.json');
const retiredProviderPath = new URL(
  '../src/features/session/desktopSessionRunInputClientProviderV2.ts',
  import.meta.url,
);

test('App binds one stable generation-backed session run-input operation facade', () => {
  assert.match(app, /createDesktopSessionRunInputOperationsV2/u);
  assert.match(
    app,
    /const desktopSessionRunInputOperationsV2 = useMemo\([\s\S]*?createDesktopSessionRunInputOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /sessionRunInputOperationsV2: desktopSessionRunInputOperationsV2/u,
  );
  assert.doesNotMatch(app, /desktopSessionRunInputClientProviderV2/u);
});

test('run-input listing and promotion use one V2 operation path in both runtime modes', () => {
  const effect = sourceSlice(
    app,
    'useEffect(() => {\n    let active = true;\n    const controller = new AbortController();',
    'useEffect(() => {\n    setRunInputDelivery',
  );
  const callback = sourceSlice(
    app,
    'const promoteQueuedRunInput = useCallback(',
    '\n  const titlebarRunState',
  );

  assert.match(effect, /desktopSessionRunInputOperationsV2\.listRunInputs\(\{/u);
  assert.match(effect, /conversation: scopedConversation/u);
  assert.match(callback, /desktopSessionRunInputOperationsV2\.promoteRunInput\(\{/u);
  assert.match(callback, /conversation: selectedConversation/u);
  for (const sourceText of [effect, callback]) {
    assert.doesNotMatch(sourceText, /requestConfig\.mode === 'cloud'/u);
    assert.doesNotMatch(sourceText, /activityAuthorityAdapter\.client/u);
    assert.doesNotMatch(sourceText, /desktopSessionRunInputClientV2/u);
  }
});

test('composer creation uses the same V2 session operation without authority branching', () => {
  assert.match(
    conversationFacade,
    /sessionRunInputOperationsV2: DesktopSessionRunInputOperationsV2/u,
  );
  assert.match(
    conversationHook,
    /sessionRunInputOperationsV2\.createRunInput\(\{/u,
  );
  assert.match(conversationHook, /conversation: selectedConversation/u);
  assert.doesNotMatch(conversationHook, /activityAuthorityAdapter\.client\.createRunInput/u);
  assert.doesNotMatch(conversationHook, /sessionRunInputClientV2/u);
  assert.doesNotMatch(conversationHook, /desktopRunInputFromCloud/u);
});

test('generation runtime owns the exact V2 module and retired authorities have no run-input API', () => {
  assert.match(generationHook, /desktopSessionRunInputAuthorityDefinitionV2/u);
  assert.match(
    authorityModule,
    /service:desktop-renderer\.session-run-input-authority/u,
  );
  assert.match(
    testTypeScriptConfig,
    /src\/plugins\/desktopSessionRunInputAuthorityModuleV2\.ts/u,
  );
  assert.equal(existsSync(retiredProviderPath), false);
  for (const sourceText of [cloudClient, cloudTypes]) {
    assert.doesNotMatch(sourceText, /createRunInput|listRunInputs|promoteRunInput/u);
    assert.doesNotMatch(sourceText, /create_run_input|list_run_inputs|promote_run_input/u);
  }
  assert.doesNotMatch(
    cloudContract,
    /requireCreateRunInputRequest|parseRunInputAck|parseRunInputListResponse|parsePromoteRunInputResponse/u,
  );
  assert.doesNotMatch(cloudProjection, /desktopRunInputFromCloud/u);
});

function sourceSlice(sourceText, startNeedle, endNeedle) {
  const start = sourceText.indexOf(startNeedle);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(endNeedle, start + startNeedle.length);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
