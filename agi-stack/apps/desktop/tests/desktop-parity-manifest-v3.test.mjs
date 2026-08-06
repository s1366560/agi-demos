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
  'generate-parity-manifest-v3.mjs',
  'parity-judgment-ledger.mjs',
  'parity-journey-overrides.v3.json',
  'parity-manifest.v2.json',
  'parity-manifest.v2.schema.json',
  'parity-manifest.v3.json',
  'parity-manifest.v3.schema.json',
  'parity-structural-closure.mjs',
  'schema-validator.mjs',
];

function readJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), 'utf8'));
}

function createGeneratorFixture(t, { mutateOverride = null, v2Status = 0, webStatus = 0 } = {}) {
  const fixtureRoot = mkdtempSync(resolve(tmpdir(), 'memstack-parity-v3-generator-'));
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

  const overridePath = resolve(fixtureContractRoot, 'parity-journey-overrides.v3.json');
  if (mutateOverride) {
    const catalog = JSON.parse(readFileSync(overridePath, 'utf8'));
    mutateOverride(catalog);
    writeFileSync(overridePath, `${JSON.stringify(catalog, null, 2)}\n`);
  }

  const webCheckerPath = resolve(fixtureRoot, 'web/scripts/web-route-inventory.mjs');
  mkdirSync(resolve(webCheckerPath, '..'), { recursive: true });
  writeFileSync(
    webCheckerPath,
    `process.stderr.write('fixture web inventory stale\\n');\nprocess.exitCode = ${webStatus};\n`,
  );
  writeFileSync(
    resolve(fixtureContractRoot, 'generate-parity-manifest-v2.mjs'),
    `process.stderr.write('fixture v2 production source stale\\n');\nprocess.exitCode = ${v2Status};\n`,
  );

  t.after(() => rmSync(fixtureRoot, { recursive: true, force: true }));
  return {
    fixtureRoot,
    generatorPath: resolve(fixtureContractRoot, 'generate-parity-manifest-v3.mjs'),
    manifestPath: resolve(fixtureContractRoot, 'parity-manifest.v3.json'),
  };
}

function runGenerator(fixture, args = ['--check']) {
  return spawnSync(process.execPath, [fixture.generatorPath, ...args], {
    cwd: fixture.fixtureRoot,
    encoding: 'utf8',
  });
}

function generatorOutput(result) {
  return `${result.stderr}\n${result.stdout}`;
}

test('parity manifest v3 adds journey-level acceptance contracts without weakening v2', () => {
  const schema = readJson('parity-manifest.v3.schema.json');
  const manifest = readJson('parity-manifest.v3.json');
  const legacyManifest = readJson('parity-manifest.v2.json');

  assert.deepEqual(validateJsonSchema(schema, manifest), []);
  assert.equal(manifest.schema_version, '3.0.0');
  assert.equal(manifest.references.audit_revision, legacyManifest.references.audit_revision);
  assert.equal(manifest.capabilities.length, legacyManifest.capabilities.length);

  for (const capability of manifest.capabilities) {
    assert.equal(capability.journeys.length > 0, true, capability.id);
    assert.deepEqual(
      Object.keys(capability.surfaces),
      Object.keys(
        legacyManifest.capabilities.find((candidate) => candidate.id === capability.id)
          .surfaces,
      ),
      capability.id,
    );
  }
});

test('every journey declares mode policy, desired actions, authority contracts, states and evidence', () => {
  const manifest = readJson('parity-manifest.v3.json');
  const journeyIds = new Set();

  for (const capability of manifest.capabilities) {
    for (const journey of capability.journeys) {
      const globalId = `${capability.id}:${journey.id}`;
      assert.equal(journeyIds.has(globalId), false, globalId);
      journeyIds.add(globalId);
      assert.equal(journey.title.length > 0, true, globalId);
      assert.deepEqual(
        Object.keys(journey.mode_policy).sort(),
        ['desktop_cloud', 'desktop_local', 'native_only', 'web'],
        globalId,
      );
      assert.deepEqual(
        Object.keys(journey.actions).sort(),
        ['desktop_cloud', 'desktop_local', 'native_only', 'web'],
        globalId,
      );
      assert.equal(journey.api_contracts.length > 0, true, globalId);
      assert.equal(journey.data_states.length > 0, true, globalId);
      assert.equal(journey.interaction_states.length > 0, true, globalId);
      assert.equal(journey.evidence_requirements.length > 0, true, globalId);
      assert.equal(journey.expected_observable_result.length > 0, true, globalId);
    }
  }
});

test('Agent Workspace is governed by independent user-journey acceptance rows', () => {
  const manifest = readJson('parity-manifest.v3.json');
  const capability = manifest.capabilities.find(
    (candidate) => candidate.id === 'agent-workspace-tenant-agent-workspace',
  );

  assert.deepEqual(
    capability.journeys.map((journey) => journey.id),
    [
      'bootstrap-and-scope',
      'conversation-lifecycle',
      'stream-and-run-control',
      'hitl-and-a2ui',
      'roster-and-subagents',
      'work-review',
      'content-and-export',
      'local-runtime',
    ],
  );
  for (const journey of capability.journeys) {
    assert.equal(
      journey.evidence_requirements.includes('native_electron'),
      true,
      journey.id,
    );
  }
});

test('v3 check fails closed when the Web production inventory preflight fails', (t) => {
  const fixture = createGeneratorFixture(t, { webStatus: 1 });
  const result = runGenerator(fixture);

  assert.notEqual(result.status, 0, result.stdout);
  assert.match(generatorOutput(result), /Web production inventory preflight failed/iu);
  assert.match(generatorOutput(result), /fixture web inventory stale/iu);
});

test('v3 check fails closed when the v2 production-source preflight fails', (t) => {
  const fixture = createGeneratorFixture(t, { v2Status: 1 });
  const result = runGenerator(fixture);

  assert.notEqual(result.status, 0, result.stdout);
  assert.match(generatorOutput(result), /v2 production source preflight failed/iu);
  assert.match(generatorOutput(result), /fixture v2 production source stale/iu);
});

test('v3 generation validates the schema before replacing the checked-in artifact', (t) => {
  const fixture = createGeneratorFixture(t, {
    mutateOverride(catalog) {
      catalog.capabilities[0].journeys[0].data_states = [];
    },
  });
  const originalManifest = readFileSync(fixture.manifestPath, 'utf8');
  const result = runGenerator(fixture, []);

  assert.notEqual(result.status, 0, result.stdout);
  assert.match(generatorOutput(result), /parity manifest v3 schema validation failed/iu);
  assert.equal(readFileSync(fixture.manifestPath, 'utf8'), originalManifest);
});

test('Electron dialog IPC contracts retain native runtime authority in every Desktop mode', (t) => {
  const fixture = createGeneratorFixture(t);
  const result = runGenerator(fixture, []);

  assert.equal(result.status, 0, generatorOutput(result));
  const manifest = JSON.parse(readFileSync(fixture.manifestPath, 'utf8'));
  const capability = manifest.capabilities.find(
    (candidate) => candidate.id === 'agent-workspace-tenant-agent-workspace',
  );
  const journey = capability.journeys.find(
    (candidate) => candidate.id === 'content-and-export',
  );
  const dialogContracts = journey.api_contracts.filter(
    (contract) => contract.method === 'IPC' && contract.path.startsWith('electron://dialog/'),
  );

  assert.equal(dialogContracts.length, 4);
  assert.deepEqual(
    [...new Set(dialogContracts.map((contract) => contract.authority))],
    ['electron'],
  );
});
