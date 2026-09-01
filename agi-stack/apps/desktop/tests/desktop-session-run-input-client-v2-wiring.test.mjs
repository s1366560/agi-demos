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
const testTypeScriptConfig = source('tsconfig.test.json');
const provider = source(
  'src/features/session/desktopSessionRunInputClientProviderV2.ts',
);

test('App publishes one stable V2 session run-input Provider', () => {
  assert.match(app, /createDesktopSessionRunInputClientProviderV2/u);
  assert.match(
    app,
    /const desktopSessionRunInputClientProviderV2 = useMemo\([\s\S]*?createDesktopSessionRunInputClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopSessionRunInputClientProviderV2\.publish\(\{ config \}\)/u,
  );
  assert.match(
    app,
    /sessionRunInputClientV2: desktopSessionRunInputClientV2/u,
  );
});

test('Local run-input listing binds the submitted config while Cloud keeps Agent authority', () => {
  const effect = sourceSlice(
    app,
    'useEffect(() => {\n    let active = true;\n    const requestConfig = configRef.current;',
    'useEffect(() => {\n    setRunInputDelivery',
  );

  assert.match(effect, /const requestConfig = configRef\.current/u);
  assert.match(effect, /requestConfig\.mode === 'cloud'/u);
  assert.match(effect, /activityAuthorityAdapter\.client\.listRunInputs/u);
  assert.match(
    effect,
    /desktopSessionRunInputClientV2[\s\S]*?\.bindOperation\(requestConfig\)[\s\S]*?\.listRunInputs\(currentArtifactRun\.id\)/u,
  );
  assert.match(effect, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.doesNotMatch(effect, /api\.listRunInputs/u);
});

test('Local run-input promotion binds the submitted config without changing Cloud authority', () => {
  const callback = sourceSlice(
    app,
    'const promoteQueuedRunInput = useCallback(',
    '\n  const titlebarRunState',
  );

  assert.match(callback, /const requestConfig = configRef\.current/u);
  assert.match(callback, /requestConfig\.mode === 'cloud'/u);
  assert.match(callback, /activityAuthorityAdapter\.client\.promoteRunInput/u);
  assert.match(
    callback,
    /desktopSessionRunInputClientV2[\s\S]*?\.bindOperation\(requestConfig\)[\s\S]*?\.promoteRunInput\(/u,
  );
  assert.match(callback, /formatConnectionError\(caught, requestConfig\.apiBaseUrl\)/u);
  assert.doesNotMatch(callback, /api\.promoteRunInput/u);
});

test('Local run-input creation uses the same V2 binding while Cloud stays adapter-only', () => {
  assert.match(conversationFacade, /sessionRunInputClientV2: DesktopSessionRunInputClientBindingV2/u);
  assert.match(conversationHook, /sessionRunInputClientV2/u);
  assert.match(conversationHook, /const requestConfig = configRef\.current/u);
  assert.match(conversationHook, /requestConfig\.mode === 'cloud'/u);
  assert.match(conversationHook, /activityAuthorityAdapter\.client\.createRunInput/u);
  assert.match(
    conversationHook,
    /sessionRunInputClientV2[\s\S]*?\.bindOperation\(requestConfig\)[\s\S]*?\.createRunInput\(/u,
  );
  assert.doesNotMatch(conversationHook, /api\.createRunInput/u);
});

test('session run-input Provider owns exactly the three shared transport methods', () => {
  assert.match(
    testTypeScriptConfig,
    /src\/features\/session\/desktopSessionRunInputClientProviderV2\.ts/u,
  );
  assert.match(
    provider,
    /type DesktopSessionRunInputMethod =[\s\S]*?'createRunInput'[\s\S]*?'listRunInputs'[\s\S]*?'promoteRunInput'/u,
  );
  for (const method of ['createRunInput', 'listRunInputs', 'promoteRunInput']) {
    assert.match(provider, new RegExp(`${method}:`, 'u'));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /getRunChanges:|pauseRun:|resumeRun:|forkRecoveryRun:|cancelRun:|reviewRun:/u,
  );
});

function sourceSlice(sourceText, startNeedle, endNeedle) {
  const start = sourceText.indexOf(startNeedle);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(endNeedle, start + startNeedle.length);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
