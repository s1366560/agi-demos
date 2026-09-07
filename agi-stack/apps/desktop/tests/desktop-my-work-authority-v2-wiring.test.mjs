import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authority = source('src/plugins/desktopMyWorkAuthorityModuleV2.ts');
const generation = desktopProductionRuntimeSource();
const testTypeScriptConfig = source('tsconfig.test.json');

test('App resolves My Work only through the generation-backed operation port', () => {
  assert.match(app, /createDesktopMyWorkOperationsV2/u);
  assert.match(
    app,
    /const desktopMyWorkOperationsV2 = useMemo\([\s\S]*?createDesktopMyWorkOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u
  );
  assert.doesNotMatch(app, /createDesktopMyWorkClientProviderV2/u);
  assert.doesNotMatch(app, /desktopMyWorkClientProviderV2\.publish/u);
  assert.doesNotMatch(app, /desktopMyWorkClientV2\.bindOperation/u);
});

test('the shared My Work helper preserves both callers while moving transport choice behind V2', () => {
  const resolver = callbackSource(app, 'listMyWorkForConfig', 'localRuntimeAuthorityReady');
  const refreshRuntime = callbackSource(app, 'refreshRuntime', null);
  const refreshMyWork = callbackSource(app, 'refreshMyWork', 'selectWorkspace');

  assert.match(
    resolver,
    /desktopMyWorkOperationsV2\.listMyWork\(\{[\s\S]*?config: requestConfig,[\s\S]*?principalId: authRef\.current\.user\?\.user_id[\s\S]*?signal,[\s\S]*?\}\)/u
  );
  assert.doesNotMatch(
    resolver,
    /requestConfig\.mode|desktopAgentAuthorityV2|DesktopApiClient|\.bindOperation\(/u
  );
  assert.match(refreshRuntime, /listMyWorkForConfig\(resolvedConfig\)/u);
  assert.match(refreshMyWork, /listMyWorkForConfig\(requestConfig, controller\.signal\)/u);
  assert.match(refreshMyWork, /controller\.signal\.aborted/u);
  assert.match(refreshMyWork, /myWorkRequestRef\.current !== requestId/u);
  assert.match(refreshMyWork, /myWorkError: formatError\(caught\)/u);
  assert.match(app, /socketEventInvalidatesMyWork/u);
});

test('the My Work V2 module is the only raw transport owner', () => {
  assert.match(authority, /createDesktopAgentAuthorityAdapter/u);
  assert.match(authority, /new DesktopApiClient/u);
  assert.match(
    authority,
    /parseProjectMyWorkResponse|(?:adapter\.client|cloudClient)\s*\.listMyWork/u
  );
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /DESKTOP_MY_WORK_AUTHORITY_SERVICE_V2/u);
  assert.match(generation, /desktopMyWorkAuthorityDefinitionV2/u);
  assert.match(testTypeScriptConfig, /src\/plugins\/desktopMyWorkAuthorityModuleV2\.ts/u);
  assert.doesNotMatch(
    testTypeScriptConfig,
    /src\/features\/my-work\/desktopMyWorkClientProviderV2\.ts/u
  );
  assert.equal(app.match(/\.listMyWork\(/gu)?.length, 1);
  assert.doesNotMatch(app, /(?:adapter\.client|desktopMyWorkClientV2)\.listMyWork/u);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end =
    nextName === null
      ? sourceText.indexOf('\n  useEffect(() => {', start + 1)
      : sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
