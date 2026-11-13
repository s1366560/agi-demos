import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const cache = new Map();

function load(url) {
  if (cache.has(url.href)) return cache.get(url.href);
  const module = { exports: {} };
  cache.set(url.href, module.exports);
  const code = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  new Function('require', 'module', 'exports', code)(
    (name) => (name.startsWith('.') ? load(new URL(`${name}.ts`, url)) : require(name)),
    module,
    module.exports,
  );
  return module.exports;
}

const { isIntentionalCloudCancel, settleCloudRequest } = load(
  new URL('../electron/main/cloudRequestPolicy.ts', import.meta.url),
);

test('user cancel is not a failed cloud request', () => {
  assert.equal(isIntentionalCloudCancel(new Error('cloud request was cancelled')), true);
  assert.equal(
    isIntentionalCloudCancel(new DOMException('MCP App request cancelled', 'AbortError')),
    true,
  );
});

test('settled cloud requests keep cancel, timeout, and success apart', async () => {
  assert.deepEqual(
    await settleCloudRequest(async () => {
      throw new Error('cloud request was cancelled');
    }),
    { cancelled: true, kind: 'cancelled' },
  );
  assert.deepEqual(await settleCloudRequest(async () => ({ status: 200 })), { status: 200 });
  await assert.rejects(
    () => settleCloudRequest(async () => {
      throw new Error('cloud request timed out');
    }),
    /cloud request timed out/u,
  );
  await assert.rejects(
    () => settleCloudRequest(async () => {
      throw new Error('vendor_balance');
    }),
    /vendor_balance/u,
  );
});

test('timeout and provider failures stay failures', () => {
  assert.equal(isIntentionalCloudCancel(new Error('cloud request timed out')), false);
  assert.equal(isIntentionalCloudCancel(new Error('vendor_rate_limit')), false);
  assert.equal(isIntentionalCloudCancel('cloud request was cancelled'), false);
});
