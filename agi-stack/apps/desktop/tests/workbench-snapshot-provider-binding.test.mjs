import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');

function load(path) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output)(require, module, module.exports);
  return module.exports;
}

const {
  createDesktopWorkbenchCapabilityClientProviderV2,
} = load('../src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts');

const config = Object.freeze({
  mode: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

test('snapshot loading passes the frozen config and the caller signal', async () => {
  const calls = [];
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const binding = provider.publish({
    config,
    snapshotOperationsV2: {
      async loadSnapshot(input) {
        calls.push(input);
        return { ok: true };
      },
    },
  });
  const controller = new AbortController();
  const result = await binding.client.loadSnapshot(controller.signal);
  assert.deepEqual(result, { ok: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].config.tenantId, 'tenant-1');
  assert.equal(calls[0].config.projectId, 'project-1');
  assert.notEqual(calls[0].config, config);
  assert.equal(Object.isFrozen(calls[0].config), true);
  assert.equal(calls[0].signal, controller.signal);
});

test('an aborted snapshot signal is forwarded and the operation error propagates', async () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const binding = provider.publish({
    config,
    snapshotOperationsV2: {
      async loadSnapshot(input) {
        if (input.signal.aborted) {
          throw new DOMException('Aborted', 'AbortError');
        }
        return { ok: true };
      },
    },
  });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    () => binding.client.loadSnapshot(controller.signal),
    (error) => error instanceof DOMException && error.name === 'AbortError',
  );
});
