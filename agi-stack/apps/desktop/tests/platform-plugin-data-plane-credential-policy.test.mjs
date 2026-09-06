import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const {
  takePlatformPluginDataPlaneCredentialEnvironmentV2,
} = await import(
  '/tmp/agistack-desktop-test-dist/electron/main/platformPluginDataPlaneCredentialPolicy.js'
);

const CREDENTIAL_ENV = 'AGISTACK_PLUGIN_DATA_PLANE_CREDENTIAL_V2';
const BASE_URL_ENV = 'AGISTACK_PLUGIN_DATA_PLANE_API_BASE_URL_V2';
const ACK_PARTICIPATION_ENV = 'AGISTACK_PLUGIN_DATA_PLANE_ACK_PARTICIPATION_V2';
const credential = `ms_dp_${'a'.repeat(64)}`;

test('desktop imports a dedicated plugin data-plane credential and consumes its environment', () => {
  const environment = {
    [CREDENTIAL_ENV]: credential,
    [BASE_URL_ENV]: 'https://plugins.example.test/control',
  };

  const record = takePlatformPluginDataPlaneCredentialEnvironmentV2(environment);

  assert.deepEqual(record, {
    version: 2,
    api_base_url: 'https://plugins.example.test/control',
    data_plane_id: 'desktop-sidecar-v2',
    credential,
    ack_participation: false,
  });
  assert.equal(environment[CREDENTIAL_ENV], undefined);
  assert.equal(environment[BASE_URL_ENV], undefined);
});

test('desktop enables receipt participation only through an explicit managed flag', () => {
  const environment = {
    [CREDENTIAL_ENV]: credential,
    [BASE_URL_ENV]: 'http://127.0.0.1:8000',
    [ACK_PARTICIPATION_ENV]: 'true',
  };

  const record = takePlatformPluginDataPlaneCredentialEnvironmentV2(environment);

  assert.equal(record.ack_participation, true);
  assert.equal(environment[ACK_PARTICIPATION_ENV], undefined);
});

test('desktop leaves the application vault untouched without credential environment', () => {
  assert.equal(takePlatformPluginDataPlaneCredentialEnvironmentV2({}), null);
});

test('desktop rejects incomplete or unsafe credential environment without disclosing the secret', () => {
  for (const environment of [
    { [CREDENTIAL_ENV]: credential },
    {
      [CREDENTIAL_ENV]: credential,
      [BASE_URL_ENV]: 'http://plugins.example.test/control',
    },
    {
      [CREDENTIAL_ENV]: 'ms_sk_user-token',
      [BASE_URL_ENV]: 'https://plugins.example.test/control',
    },
    {
      [CREDENTIAL_ENV]: credential,
      [BASE_URL_ENV]: 'https://plugins.example.test/control',
      [ACK_PARTICIPATION_ENV]: 'yes',
    },
  ]) {
    assert.throws(
      () => takePlatformPluginDataPlaneCredentialEnvironmentV2(environment),
      (error) => error instanceof Error && !error.message.includes(credential),
    );
    assert.equal(environment[CREDENTIAL_ENV], undefined);
    assert.equal(environment[BASE_URL_ENV], undefined);
  }
});

test('workload credential control commands stay outside the renderer command surface', () => {
  const mainSource = readFileSync(join(process.cwd(), 'electron/main/index.ts'), 'utf8');
  const preloadSource = readFileSync(join(process.cwd(), 'electron/preload/index.ts'), 'utf8');
  const mainAllowlist = mainSource.match(/const SIDECAR_COMMANDS = new Set\(\[[\s\S]*?\]\);/u)?.[0];
  const preloadAllowlist = preloadSource.match(
    /const allowedCommands = new Set\(\[[\s\S]*?\]\);/u,
  )?.[0];

  assert.ok(mainAllowlist);
  assert.ok(preloadAllowlist);
  assert.doesNotMatch(mainAllowlist, /plugin_data_plane_credential/u);
  assert.doesNotMatch(preloadAllowlist, /plugin_data_plane_credential/u);
  assert.match(mainSource, /invoke\('plugin_data_plane_credential_import_v2'/u);
});

test('Electron consumes the workload grant before spawn and imports it only after readiness', () => {
  const mainSource = readFileSync(join(process.cwd(), 'electron/main/index.ts'), 'utf8');
  const supervisorSource = readFileSync(
    join(process.cwd(), 'electron/main/sidecarSupervisor.ts'),
    'utf8',
  );
  const bootstrap = mainSource.slice(mainSource.indexOf('async function bootstrapApplication'));
  const consume = bootstrap.indexOf('takePlatformPluginCredentialEnvironmentsV2');
  const create = bootstrap.indexOf('createSidecarSupervisor()');
  const start = bootstrap.indexOf('await sidecarSupervisor.start()');
  const importCredential = bootstrap.indexOf("invoke('plugin_data_plane_credential_import_v2'");
  const readyShape = supervisorSource.match(/type SidecarReady = \{[\s\S]*?\n\};/u)?.[0];

  assert.ok(consume >= 0 && consume < create);
  assert.ok(create < start && start < importCredential);
  assert.match(supervisorSource, /spawn\(this\.#options\.binaryPath, \[\], \{/u);
  assert.ok(readyShape);
  assert.doesNotMatch(readyShape, /data.?plane|credential/iu);
});
