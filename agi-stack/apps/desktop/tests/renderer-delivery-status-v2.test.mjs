import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  desktopRendererDeliveryUnavailableV2,
  assertDesktopRendererDeliveryAvailableV2,
  isDesktopRendererCredentialRequiredV2,
} = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererDeliveryStatusV2.js');

test('missing workload authorization remains a typed rejection after IPC serialization', () => {
  const failure = desktopRendererDeliveryUnavailableV2(new Error('renderer_credential_required'));
  assert.deepEqual(failure, { status: 'unavailable', reason_code: 'renderer_credential_required' });
  const transferred = JSON.parse(JSON.stringify(failure));
  assert.throws(() => assertDesktopRendererDeliveryAvailableV2(transferred), (error) => {
    assert.equal(error.code, 'renderer_credential_required');
    assert.equal(isDesktopRendererCredentialRequiredV2(error), true);
    return true;
  });
});

test('transport failures, scope failures and prose containing the code are not relabeled', () => {
  for (const error of [
    new Error('renderer_delivery_superseded'),
    new Error('renderer_transport_unavailable'),
    new Error('unrelated: renderer_credential_required'),
    new Error('renderer_credential_required'),
    { message: 'renderer_credential_required' },
  ]) {
    assert.equal(isDesktopRendererCredentialRequiredV2(error), false);
    if (error.message !== 'renderer_credential_required' || !(error instanceof Error)) {
      assert.equal(desktopRendererDeliveryUnavailableV2(error), null);
    }
  }
  for (const value of [null, { source: 'local', distribution: {} }]) {
    assert.doesNotThrow(() => assertDesktopRendererDeliveryAvailableV2(value));
  }
});

test('only delivery fetch translates the missing grant and renderer rejects before reconciliation', () => {
  const main = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
  const hook = readFileSync(new URL('../src/plugins/useDesktopPluginGenerationV2.ts', import.meta.url), 'utf8');
  const shell = readFileSync(new URL('../src/plugins/DesktopRendererAuthenticatedShellV2.tsx', import.meta.url), 'utf8');
  assert.match(main, /command === 'platform_plugin_renderer_delivery_current_v2'\s*\? desktopRendererDeliveryUnavailableV2\(error\)/u);
  assert.match(main, /if \(!unavailable\) throw error/u);
  assert.match(hook, /assertDesktopRendererDeliveryAvailableV2\(distribution\)/u);
  assert.match(shell, /isDesktopRendererCredentialRequiredV2\(state\.authority\.error\)/u);
  assert.match(shell, /desktopProductionRouter\.credentialRequired\.description/u);
});
