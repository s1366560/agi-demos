import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const { takePlatformPluginCredentialEnvironmentsV2: take } = await import(
  '/tmp/agistack-desktop-test-dist/electron/main/platformPluginDataPlaneCredentialPolicy.js'
);
const { sidecarChildEnvironment } = await import(
  '/tmp/agistack-desktop-test-dist/electron/main/sidecarSupervisor.js'
);
const sidecarPrefix = 'AGISTACK_PLUGIN_DATA_PLANE_';
const rendererPrefix = 'AGISTACK_PLUGIN_RENDERER_DATA_PLANE_';
const sidecarSecret = `ms_dp_${'a'.repeat(64)}`;
const rendererSecret = `ms_dp_${'b'.repeat(64)}`;
const grant = (prefix, secret) => ({
  [`${prefix}CREDENTIAL_V2`]: secret,
  [`${prefix}API_BASE_URL_V2`]: 'https://plugins.example.test',
  [`${prefix}ACK_PARTICIPATION_V2`]: 'true',
});

test('both fixed plane grants are consumed independently without changing unrelated environment', () => {
  const environment = {
    ...grant(sidecarPrefix, sidecarSecret),
    ...grant(rendererPrefix, rendererSecret),
    UNRELATED: 'preserved',
  };
  const result = take(environment);
  assert.equal(result.sidecar.data_plane_id, 'desktop-sidecar-v2');
  assert.equal(result.sidecar.credential, sidecarSecret);
  assert.equal(result.renderer.data_plane_id, 'desktop-renderer-v2');
  assert.equal(result.renderer.credential, rendererSecret);
  assert.equal(result.renderer.ack_participation, true);
  assert.ok(Object.isFrozen(result.renderer));
  assert.deepEqual(environment, { UNRELATED: 'preserved' });
});

test('renderer absence never borrows the sidecar grant and renderer ACK defaults to false', () => {
  assert.equal(take(grant(sidecarPrefix, sidecarSecret)).renderer, null);
  const renderer = grant(rendererPrefix, rendererSecret);
  delete renderer[`${rendererPrefix}ACK_PARTICIPATION_V2`];
  const result = take(renderer);
  assert.equal(result.sidecar, null);
  assert.equal(result.renderer.ack_participation, false);
  assert.deepEqual(take({}), { sidecar: null, renderer: null });
});

test('either invalid grant clears all six fields before throwing without revealing credentials', () => {
  for (const prefix of [sidecarPrefix, rendererPrefix]) {
    for (const [field, invalid] of [
      ['CREDENTIAL_V2', 'ms_sk_wrong-kind'],
      ['API_BASE_URL_V2', 'http://remote.example.test'],
      ['API_BASE_URL_V2', 'https://plugins.example.test?token=private'],
      ['ACK_PARTICIPATION_V2', 'yes'],
    ]) {
      const environment = {
        ...grant(sidecarPrefix, sidecarSecret),
        ...grant(rendererPrefix, rendererSecret),
        [`${prefix}${field}`]: invalid,
      };
      assert.throws(() => take(environment), (error) => {
        assert.equal(error.message.includes(sidecarSecret), false);
        assert.equal(error.message.includes(rendererSecret), false);
        assert.equal(error.message.includes(invalid), false);
        return true;
      });
      assert.deepEqual(environment, {});
    }
  }
});

test('sidecar children never inherit either grant including configured overrides', () => {
  const inherited = { ...grant(sidecarPrefix, sidecarSecret), KEEP: 'inherited' };
  const configured = { ...grant(rendererPrefix, rendererSecret), KEEP: 'configured' };
  assert.deepEqual(sidecarChildEnvironment(inherited, configured), { KEEP: 'configured' });
  assert.equal(inherited[`${sidecarPrefix}CREDENTIAL_V2`], sidecarSecret);
  assert.equal(configured[`${rendererPrefix}CREDENTIAL_V2`], rendererSecret);
});

test('renderer credential import is main-only and runs after private sidecar readiness', () => {
  const main = readFileSync(new URL('../electron/main/index.ts', import.meta.url), 'utf8');
  const preload = readFileSync(new URL('../electron/preload/index.ts', import.meta.url), 'utf8');
  const allowed = main.match(/const SIDECAR_COMMANDS = new Set\(\[[\s\S]*?\]\);/u)?.[0];
  assert.ok(allowed);
  assert.doesNotMatch(allowed, /plugin_renderer_data_plane_credential/u);
  assert.doesNotMatch(preload, /plugin_renderer_data_plane_credential/u);
  const bootstrap = main.slice(main.indexOf('async function bootstrapApplication'));
  const consume = bootstrap.indexOf('takePlatformPluginCredentialEnvironmentsV2');
  const spawn = bootstrap.indexOf('createSidecarSupervisor()');
  const ready = bootstrap.indexOf('await sidecarSupervisor.start()');
  const imported = bootstrap.indexOf("invoke('plugin_renderer_data_plane_credential_import_v2'");
  assert.ok(consume >= 0 && consume < spawn && spawn < ready && ready < imported);
});
