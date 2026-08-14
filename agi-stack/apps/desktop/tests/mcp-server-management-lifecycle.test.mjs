import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const managementSource = readFileSync(
  new URL('../src/features/settings/useMCPServerManagement.ts', import.meta.url),
  'utf8',
);
const dialogSource = readFileSync(
  new URL('../src/features/settings/MCPServerDialog.tsx', import.meta.url),
  'utf8',
);

function callbackSource(name, nextName) {
  const start = managementSource.indexOf(`const ${name} = useCallback`);
  const end = managementSource.indexOf(`const ${nextName} = useCallback`, start + 1);
  assert.notEqual(start, -1, `${name} callback should exist`);
  assert.notEqual(end, -1, `${nextName} callback should follow ${name}`);
  return managementSource.slice(start, end);
}

test('MCP request completions stay bound to their client and project context', () => {
  assert.match(managementSource, /const mountedRef = useRef\(true\)/);
  assert.match(
    managementSource,
    /const client = useMemo\(\(\) => new DesktopApiClient\(config\), \[config\]\)/,
  );
  assert.match(managementSource, /const clientRef = useRef\(client\)/);
  assert.match(managementSource, /const requestContextIsCurrent = useCallback/);
  assert.match(
    managementSource,
    new RegExp(
      'mountedRef\\.current[\\s\\S]*clientRef\\.current === requestContext\\.client' +
        '[\\s\\S]*contextKeyRef\\.current === requestContext\\.contextKey',
    ),
  );

  const callbackPairs = [
    ['create', 'update'],
    ['update', 'toggleServer'],
    ['toggleServer', 'remove'],
    ['remove', 'testServer'],
  ];
  for (const [name, nextName] of callbackPairs) {
    const source = callbackSource(name, nextName);
    assert.match(source, /const requestContext = captureRequestContext\(\)/);
    assert.match(source, /requestContextIsCurrent\(requestContext\)/);
  }
  const testServerStart = managementSource.indexOf('const testServer = useCallback');
  const returnStart = managementSource.indexOf('\n  return {', testServerStart);
  const testServerSource = managementSource.slice(testServerStart, returnStart);
  assert.match(testServerSource, /const requestContext = captureRequestContext\(\)/);
  assert.match(testServerSource, /requestContextIsCurrent\(requestContext\)/);
});

test('MCP create retries reuse an attempt key only for the same canonical submission', () => {
  const createSource = callbackSource('create', 'update');
  assert.match(createSource, /dialog\?\.kind !== 'create'/);
  assert.match(createSource, /resolveSubmissionAttemptKey\(dialog\.key, input\)/);
  assert.match(createSource, /const mutationIdempotencyKey = `mcp-server:\$\{attemptKey\}`/);
  assert.match(createSource, /idempotencyKey: attemptKey/);
  assert.match(createSource, /mutationIdempotencyKey,/);
  assert.match(createSource, /idempotency_key: mutationIdempotencyKey/);

  const submitStart = dialogSource.indexOf('const submit = () => {');
  const renderStart = dialogSource.indexOf('\n  return (', submitStart);
  const submitSource = dialogSource.slice(submitStart, renderStart);
  assert.doesNotMatch(submitSource, /setSecret\(''\)/);
});

test('MCP changed submissions rotate attempt keys while exact retries reuse them', () => {
  assert.match(managementSource, /async function mcpSubmissionFingerprint/);
  assert.match(managementSource, /canonicalizeSubmissionValue\(input\)/);
  assert.match(managementSource, /crypto\.subtle\.digest\('SHA-256'/);
  assert.match(managementSource, /const submissionAttemptRef = useRef/);
  assert.match(
    managementSource,
    /current\?\.dialogKey === dialogKey && current\.fingerprint === fingerprint/,
  );
  assert.match(managementSource, /return current\.key/);
  assert.match(managementSource, /const key = crypto\.randomUUID\(\)/);
  assert.match(managementSource, /submissionAttemptRef\.current = \{ dialogKey, fingerprint, key \}/);
});

test('MCP update rotates by submission while delete retries keep the dialog key', () => {
  const updateSource = callbackSource('update', 'toggleServer');
  assert.match(updateSource, /resolveSubmissionAttemptKey\(dialog\.key, input\)/);
  assert.match(
    updateSource,
    /const mutationIdempotencyKey = `mcp-server-update:\$\{attemptKey\}`/,
  );
  assert.match(updateSource, /idempotencyKey: attemptKey/);
  assert.match(updateSource, /mutationIdempotencyKey,/);
  assert.match(updateSource, /idempotency_key: mutationIdempotencyKey/);

  const removeSource = callbackSource('remove', 'testServer');
  assert.match(removeSource, /idempotency_key: `mcp-server-delete:\$\{dialog\.key\}`/);
  assert.doesNotMatch(removeSource, /mcp-server-delete:\$\{crypto\.randomUUID\(\)\}/);
});

test('MCP toggle retries retain one key until canonical server state advances', () => {
  const toggleSource = callbackSource('toggleServer', 'remove');
  assert.match(managementSource, /const toggleAttemptKeysRef = useRef\(new Map/);
  assert.match(toggleSource, /mcpToggleAttemptIdentity\(contextKey, server\)/);
  assert.match(toggleSource, /resolveMCPMutationAttemptKey\(/);
  assert.match(toggleSource, /idempotency_key: `mcp-server-toggle:\$\{attemptKey\}`/);
  assert.doesNotMatch(toggleSource, /mcp-server-toggle:\$\{crypto\.randomUUID\(\)\}/);
  assert.match(managementSource, /retainCurrentMCPToggleAttempts\(/);
  assert.match(managementSource, /toggleAttemptKeysRef\.current\.clear\(\)/);
});

test('MCP edit hydration preserves separately represented stdio args', () => {
  assert.match(dialogSource, /formatMCPStdioCommand\(mcpStdioCommandArgv\(/);
  assert.match(managementSource, /mcpStdioCommandArgv\(transportConfig\?\.command/);
});

test('busy MCP dialogs reject backdrop, close-button, and Escape dismissal', () => {
  assert.match(managementSource, /const dialogBusyRef = useRef\(false\)/);
  assert.match(
    managementSource,
    /const closeDialog = useCallback\(\(\) => \{[\s\S]*if \(dialogBusyRef\.current\) return;/,
  );
  assert.match(
    dialogSource,
    /const requestClose = \(\) => \{[\s\S]*if \(!busy\) onClose\(\);[\s\S]*\};/,
  );
  assert.match(dialogSource, /useModalDialog\(\{[\s\S]*onClose: requestClose/);
  assert.match(
    dialogSource,
    /className="plugin-management-backdrop" onMouseDown=\{requestClose\}/,
  );
  assert.match(
    dialogSource,
    /aria-label=\{t\('common\.close'\)\}[\s\S]*disabled=\{busy\}[\s\S]*onClick=\{requestClose\}/,
  );
});
