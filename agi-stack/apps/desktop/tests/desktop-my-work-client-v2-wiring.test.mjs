import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source('src/features/my-work/desktopMyWorkClientProviderV2.ts');
const testTypeScriptConfig = source('tsconfig.test.json');

test('App publishes one stable Local V2 My Work Provider', () => {
  assert.match(app, /createDesktopMyWorkClientProviderV2/u);
  assert.match(
    app,
    /const desktopMyWorkClientProviderV2 = useMemo\([\s\S]*?createDesktopMyWorkClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(app, /desktopMyWorkClientProviderV2\.publish\(\{ config \}\)/u);
});

test('one scope-pinned resolver keeps Cloud and Local My Work authorities disjoint', () => {
  const resolver = callbackSource(app, 'listMyWorkForConfig', 'localRuntimeAuthorityReady');

  assert.match(resolver, /requestConfig\.mode === 'cloud'/u);
  assert.match(
    resolver,
    /desktopAgentAuthorityV2\.bindOperation\(\{[\s\S]*?config: requestConfig,[\s\S]*?principalId:[\s\S]*?\}\)/u,
  );
  assert.match(resolver, /operation\.adapter\.client\.listMyWork\(/u);
  assert.match(resolver, /operation\.cloudScope/u);
  assert.match(
    resolver,
    /desktopMyWorkClientV2\.bindOperation\(requestConfig\)\.listMyWork\(/u,
  );
  assert.doesNotMatch(resolver, /api\.listMyWork|scopedClient\.listMyWork/u);
});

test('initial runtime load and refresh use the same submitted-scope My Work resolver', () => {
  const refreshRuntime = callbackSource(app, 'refreshRuntime', 'refreshMyWork');
  const refreshMyWork = callbackSource(app, 'refreshMyWork', 'selectWorkspace');

  assert.match(refreshRuntime, /listMyWorkForConfig\(resolvedConfig\)/u);
  assert.doesNotMatch(refreshRuntime, /scopedClient\.listMyWork/u);
  assert.match(refreshMyWork, /const requestConfig = configRef\.current/u);
  assert.match(
    refreshMyWork,
    /listMyWorkForConfig\(requestConfig, controller\.signal\)/u,
  );
  assert.doesNotMatch(refreshMyWork, /api\.listMyWork/u);
});

test('Local My Work Provider owns exactly one read method', () => {
  assert.match(
    testTypeScriptConfig,
    /src\/features\/my-work\/desktopMyWorkClientProviderV2\.ts/u,
  );
  assert.match(provider, /type DesktopMyWorkMethod = 'listMyWork'/u);
  assert.match(provider, /listMyWork:/u);
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /getActivityReadState|putActivityReadState|getRunSummary|getRunChanges|listRunInputs|startTerminal/u,
  );
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
