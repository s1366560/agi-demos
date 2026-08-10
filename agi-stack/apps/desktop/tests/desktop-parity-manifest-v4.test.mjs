import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';

const contractRoot = new URL('../contracts/desktop-web-parity/', import.meta.url);
const repositoryRoot = fileURLToPath(new URL('../../../../', import.meta.url));
const generatorFixtureFiles = [
  'generate-parity-manifest-v4.mjs',
  'parity-authority-overrides.v4.json',
  'parity-judgment-ledger.mjs',
  'parity-manifest.v2.json',
  'parity-manifest.v3.json',
  'parity-manifest.v3.schema.json',
  'parity-manifest.v4.json',
  'parity-manifest.v4.schema.json',
  'parity-structural-closure.mjs',
  'schema-validator.mjs',
];

function readJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), 'utf8'));
}

function createGeneratorFixture(t, { mutateOverrides = null, mutateV3 = null } = {}) {
  const fixtureRoot = mkdtempSync(resolve(tmpdir(), 'memstack-parity-v4-generator-'));
  const fixtureContractRoot = resolve(
    fixtureRoot,
    'agi-stack/apps/desktop/contracts/desktop-web-parity',
  );
  mkdirSync(fixtureContractRoot, { recursive: true });
  for (const fileName of generatorFixtureFiles) {
    copyFileSync(
      resolve(repositoryRoot, 'agi-stack/apps/desktop/contracts/desktop-web-parity', fileName),
      resolve(fixtureContractRoot, fileName),
    );
  }
  if (mutateOverrides) {
    const overridePath = resolve(fixtureContractRoot, 'parity-authority-overrides.v4.json');
    const catalog = JSON.parse(readFileSync(overridePath, 'utf8'));
    mutateOverrides(catalog);
    writeFileSync(overridePath, `${JSON.stringify(catalog, null, 2)}\n`);
  }
  if (mutateV3) {
    const v3Path = resolve(fixtureContractRoot, 'parity-manifest.v3.json');
    const manifest = JSON.parse(readFileSync(v3Path, 'utf8'));
    mutateV3(manifest);
    writeFileSync(v3Path, `${JSON.stringify(manifest)}\n`);
  }
  t.after(() => rmSync(fixtureRoot, { recursive: true, force: true }));
  return {
    fixtureRoot,
    generatorPath: resolve(fixtureContractRoot, 'generate-parity-manifest-v4.mjs'),
    manifestPath: resolve(fixtureContractRoot, 'parity-manifest.v4.json'),
  };
}

function runGenerator(fixture, args = ['--check']) {
  return spawnSync(process.execPath, [fixture.generatorPath, ...args], {
    cwd: fixture.fixtureRoot,
    encoding: 'utf8',
  });
}

function output(result) {
  return `${result.stderr}\n${result.stdout}`;
}

test('parity manifest v4 adds explicit primary and supporting authority roles', () => {
  const schema = readJson('parity-manifest.v4.schema.json');
  const manifest = readJson('parity-manifest.v4.json');
  const v3Manifest = readJson('parity-manifest.v3.json');

  assert.deepEqual(validateJsonSchema(schema, manifest), []);
  assert.equal(manifest.schema_version, '4.0.0');
  assert.equal(manifest.capabilities.length, v3Manifest.capabilities.length + 1);
  assert.deepEqual(Object.keys(manifest.capabilities[0].surfaces), [
    'web',
    'desktop_cloud',
    'local_online',
    'local_offline',
    'native_only',
  ]);
  assert.equal(JSON.stringify(manifest).includes('"desktop_local"'), false);
  assert.equal(JSON.stringify(schema).includes('"desktop_local"'), false);
  for (const capability of manifest.capabilities) {
    for (const surface of Object.values(capability.surfaces)) {
      assert.equal(Array.isArray(surface.supporting_authorities), true);
    }
    for (const contract of [
      ...capability.api_contracts,
      ...capability.journeys.flatMap((journey) => journey.api_contracts),
    ]) {
      assert.equal(['primary', 'supporting'].includes(contract.authority_role), true);
    }
  }
});

test('Agent Workspace declares Electron support without replacing service authority', () => {
  const manifest = readJson('parity-manifest.v4.json');
  const capability = manifest.capabilities.find(
    ({ id }) => id === 'agent-workspace-tenant-agent-workspace',
  );
  const content = capability.journeys.find(({ id }) => id === 'content-and-export');
  const localRuntime = capability.journeys.find(({ id }) => id === 'local-runtime');

  assert.equal(capability.surfaces.desktop_cloud.authority, 'cloud_service');
  assert.equal(capability.surfaces.local_online.authority, 'sidecar');
  assert.equal(capability.surfaces.local_offline.authority, 'sidecar');
  assert.deepEqual(capability.surfaces.desktop_cloud.supporting_authorities, ['electron']);
  assert.deepEqual(capability.surfaces.local_online.supporting_authorities, ['electron']);
  assert.deepEqual(capability.surfaces.local_offline.supporting_authorities, ['electron']);
  assert.equal(
    content.api_contracts
      .filter(({ method }) => method === 'IPC')
      .every(
        ({ authority, authority_role }) =>
          authority === 'electron' && authority_role === 'supporting',
      ),
    true,
  );
  assert.equal(
    localRuntime.api_contracts
      .filter(({ surface }) => ['local_online', 'local_offline'].includes(surface))
      .every(
        ({ authority, authority_role }) => authority === 'sidecar' && authority_role === 'primary',
      ),
    true,
  );
});

test('Browser Bridge is the 67th native-only compound-authority capability', () => {
  const manifest = readJson('parity-manifest.v4.json');
  const capability = manifest.capabilities.at(-1);

  assert.equal(manifest.capabilities.length, 67);
  assert.equal(capability.id, 'browser-integration-browser-bridge');
  assert.deepEqual(capability.journeys[0].mode_policy, {
    web: 'not_applicable',
    desktop_cloud: 'not_applicable',
    local_online: 'not_applicable',
    local_offline: 'not_applicable',
    native_only: 'required',
  });
  assert.equal(capability.surfaces.native_only.authority, 'sidecar');
  assert.deepEqual(capability.surfaces.native_only.supporting_authorities, [
    'browser_extension',
    'electron',
  ]);
  assert.equal(capability.surfaces.native_only.implementation_status, 'partial');
  assert.equal(capability.surfaces.native_only.availability, 'degraded');
  assert.equal(
    capability.surfaces.native_only.reason_code,
    'browser_bridge_release_and_registration_evidence_incomplete',
  );
  for (const surfaceName of ['web', 'desktop_cloud', 'local_online', 'local_offline']) {
    assert.equal(capability.journeys[0].mode_policy[surfaceName], 'not_applicable');
    assert.equal(capability.surfaces[surfaceName].availability, 'not_applicable');
  }
  const paths = capability.production_entries.native_only.map(({ path }) => path);
  for (const path of [
    'agi-stack/apps/browser-extension/entrypoints/background.ts',
    'agi-stack/apps/browser-extension/src/handlers.ts',
    'agi-stack/apps/browser-extension/src/protocol.ts',
    'agi-stack/crates/adapters-browser/src/lib.rs',
    'agi-stack/apps/desktop/sidecar/src/local_runtime/browser_bridge.rs',
    'agi-stack/apps/desktop/sidecar/src/native_host.rs',
    'agi-stack/apps/desktop/src/features/settings/BrowserIntegrationSettingsPage.tsx',
  ]) {
    assert.equal(paths.includes(path), true, path);
  }
});

test('v4 check fails closed when the checked-in v3 artifact is invalid', (t) => {
  const fixture = createGeneratorFixture(t, {
    mutateV3(manifest) {
      manifest.schema_version = '3.0.0-invalid';
    },
  });
  const result = runGenerator(fixture);

  assert.notEqual(result.status, 0, result.stdout);
  assert.match(output(result), /v3 artifact preflight failed/iu);
  assert.match(output(result), /schema_version/iu);
});

test('v4 authority overrides reject unknown and duplicate contract keys', (t) => {
  const unknown = createGeneratorFixture(t, {
    mutateOverrides(catalog) {
      catalog.contracts[0].path = 'electron://dialog/unknown';
    },
  });
  assert.match(output(runGenerator(unknown, [])), /did not match a v3 contract/iu);

  const duplicate = createGeneratorFixture(t, {
    mutateOverrides(catalog) {
      catalog.contracts.push({ ...catalog.contracts[0] });
    },
  });
  assert.match(output(runGenerator(duplicate, [])), /duplicate authority override/iu);
});

test('v4 generation validates before replacing the checked-in artifact', (t) => {
  const fixture = createGeneratorFixture(t, {
    mutateOverrides(catalog) {
      catalog.contracts[0].authority_role = 'invalid';
    },
  });
  const original = readFileSync(fixture.manifestPath, 'utf8');
  const result = runGenerator(fixture, []);

  assert.notEqual(result.status, 0, result.stdout);
  assert.equal(readFileSync(fixture.manifestPath, 'utf8'), original);
});
