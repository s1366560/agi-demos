import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import {
  chmodSync,
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

import {
  finalizeParityJudgmentClosure,
} from '../contracts/desktop-web-parity/parity-judgment-closure.mjs';
import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';

const contractRoot = new URL('../contracts/desktop-web-parity/', import.meta.url);
const repositoryRoot = fileURLToPath(new URL('../../../../', import.meta.url));
const generatorFixtureFiles = [
  'generate-parity-manifest-v4.mjs',
  'parity-authority-overrides.v4.json',
  'parity-judgment-closure.mjs',
  'parity-judgment-ledger.mjs',
  'parity-manifest.v2.json',
  'parity-manifest.v3.json',
  'parity-manifest.v3.schema.json',
  'parity-manifest.v4.json',
  'parity-manifest.v4.schema.json',
  'parity-structural-closure.mjs',
  'production-entry-integrity.mjs',
  'schema-validator.mjs',
];
const browserSourcePaths = [
  'agi-stack/apps/browser-extension/entrypoints/background.ts',
  'agi-stack/apps/browser-extension/src/handlers.ts',
  'agi-stack/apps/browser-extension/src/protocol.ts',
  'agi-stack/crates/adapters-browser/src/lib.rs',
  'agi-stack/apps/desktop/sidecar/src/local_runtime/browser_bridge.rs',
  'agi-stack/apps/desktop/sidecar/src/native_host.rs',
  'agi-stack/apps/desktop/src/features/settings/BrowserIntegrationSettingsPage.tsx',
    'agi-stack/apps/desktop/src/features/settings/useBrowserIntegrationManagementV2.ts',
  'agi-stack/apps/desktop/src/App.tsx',
  'agi-stack/apps/desktop/src/features/settings/SettingsWindow.tsx',
  'agi-stack/apps/desktop/src/plugins/useDesktopPluginGenerationV2.ts',
  'agi-stack/apps/desktop/src/plugins/desktopBrowserIntegrationAuthorityModuleV2.ts',
  'agi-stack/apps/desktop/src/plugins/desktopBrowserIntegrationOperationContractV2.ts',
  'agi-stack/apps/desktop/src/plugins/desktopBrowserIntegrationResponseContractV2.ts',
  'agi-stack/apps/desktop/src/plugins/desktopBrowserIntegrationHttpProjectionV2.ts',
  'agi-stack/apps/desktop/src/plugins/desktopBrowserBridgeManagementAuthorityModuleV2.ts',
  'agi-stack/apps/desktop/src/plugins/desktopBrowserBridgeManagementOperationContractV2.ts',
  'agi-stack/apps/desktop/src/plugins/desktopBrowserBridgeManagementNativeProjectionV2.ts',
  'agi-stack/apps/desktop/src/features/settings/useBrowserBridgeManagementV2.ts',
  'agi-stack/apps/desktop/tests/desktop-browser-bridge-management-authority-v2.test.mjs',
  'agi-stack/apps/desktop/tests/browser-bridge-management-lifecycle.test.mjs',
  'agi-stack/apps/desktop/tests/desktop-browser-bridge-management-loader-v2.test.mjs',
  'agi-stack/apps/desktop/sidecar/src/local_runtime/mod.rs',
  'agi-stack/apps/desktop/sidecar/src/local_runtime/session_store.rs',
  'agi-stack/apps/desktop/sidecar/src/local_runtime/browser_run_tool_host.rs',
];

function readJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), 'utf8'));
}

function createGeneratorFixture(t, { mutateOverrides = null, mutateV3 = null } = {}) {
  const fixtureRoot = mkdtempSync(resolve(tmpdir(), 'memstack-parity-v4-generator-'));
  const externalRoot = mkdtempSync(resolve(tmpdir(), 'memstack-parity-v4-review-'));
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
  t.after(() => rmSync(externalRoot, { recursive: true, force: true }));
  return {
    emitInputsPath: resolve(externalRoot, 'browser-bridge-inputs.jsonl'),
    fixtureRoot,
    generatorPath: resolve(fixtureContractRoot, 'generate-parity-manifest-v4.mjs'),
    judgmentPath: resolve(externalRoot, 'browser-bridge-judgment.jsonl'),
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

function git(repositoryRoot, args) {
  const result = spawnSync('git', args, {
    cwd: repositoryRoot,
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, output(result));
  return result.stdout.trim();
}

function setAuditedRevision(path, revision) {
  const manifest = JSON.parse(readFileSync(path, 'utf8'));
  manifest.references = {
    ...manifest.references,
    audit_revision: revision,
    web_revision: revision,
    desktop_revision: revision,
  };
  writeFileSync(path, `${JSON.stringify(manifest)}\n`);
}

function surfaceSummary(surface) {
  return {
    disposition: surface.disposition,
    implementation_status: surface.implementation_status,
    availability: surface.availability,
    reason_code: surface.reason_code,
    authority: surface.authority,
    supporting_authorities: [...surface.supporting_authorities],
  };
}

function prepareBrowserBridgeJudgment(fixture, mutate = null) {
  const emitted = runGenerator(fixture, ['--emit-inputs', fixture.emitInputsPath]);
  assert.equal(emitted.status, 0, output(emitted));
  const records = readFileSync(fixture.emitInputsPath, 'utf8')
    .trim()
    .split(/\r?\n/u)
    .map((line) => JSON.parse(line));
  assert.equal(records.length, 1);
  const [{ input, input_digest: inputDigest }] = records;
  const judgment = {
    agent_id: 'desktop-parity-v4-test-reviewer',
    tool_name: 'structured_parity_judgment',
    input,
    input_digest: inputDigest,
    output: {
      verdict: 'accepted',
      ...Object.fromEntries(
        Object.entries(input.surfaces).map(([surfaceName, surface]) => [
          surfaceName,
          surfaceSummary(surface),
        ]),
      ),
    },
    rationale:
      'Fixture reviewer confirms the exact Browser Bridge input remains native-only and degraded.',
    latency_ms: 5,
    recorded_at: '2026-08-30T00:00:00.000Z',
  };
  mutate?.(judgment);
  writeFileSync(fixture.judgmentPath, `${JSON.stringify(judgment)}\n`);
  chmodSync(fixture.judgmentPath, 0o600);
  return judgment;
}

function createGitBackedSourceFixture(t) {
  const fixture = createGeneratorFixture(t);
  for (const sourcePath of browserSourcePaths) {
    const target = resolve(fixture.fixtureRoot, sourcePath);
    mkdirSync(resolve(target, '..'), { recursive: true });
    copyFileSync(resolve(repositoryRoot, sourcePath), target);
  }
  git(fixture.fixtureRoot, ['init', '--quiet']);
  git(fixture.fixtureRoot, ['config', 'user.name', 'MemStack Parity Test']);
  git(fixture.fixtureRoot, ['config', 'user.email', 'parity-test@memstack.invalid']);
  git(fixture.fixtureRoot, ['add', '.']);
  git(fixture.fixtureRoot, ['commit', '--quiet', '-m', 'source baseline']);
  const auditedRevision = git(fixture.fixtureRoot, ['rev-parse', 'HEAD']);
  setAuditedRevision(
    resolve(
      fixture.fixtureRoot,
      'agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v2.json',
    ),
    auditedRevision,
  );
  setAuditedRevision(
    resolve(
      fixture.fixtureRoot,
      'agi-stack/apps/desktop/contracts/desktop-web-parity/parity-manifest.v3.json',
    ),
    auditedRevision,
  );
  return { ...fixture, auditedRevision };
}

function createGitBackedGeneratorFixture(t) {
  const fixture = createGitBackedSourceFixture(t);
  rmSync(fixture.manifestPath, { force: true });
  prepareBrowserBridgeJudgment(fixture);
  const generated = runGenerator(fixture, ['--judgments', fixture.judgmentPath]);
  assert.equal(generated.status, 0, output(generated));
  git(fixture.fixtureRoot, ['add', '.']);
  git(fixture.fixtureRoot, ['commit', '--quiet', '-m', 'generated contract']);
  return fixture;
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

test('every v4 judgment binds the final structurally closed input and output', () => {
  const manifest = readJson('parity-manifest.v4.json');

  for (const capability of manifest.capabilities) {
    const expectedDigest = `sha256:${createHash('sha256')
      .update(JSON.stringify(capability.judgment.input))
      .digest('hex')}`;
    assert.equal(capability.judgment.input_digest, expectedDigest, capability.id);
    assert.deepEqual(
      capability.judgment.input.surfaces,
      capability.surfaces,
      capability.id,
    );
    assert.deepEqual(
      capability.judgment.output,
      {
        verdict: 'accepted',
        ...Object.fromEntries(
          Object.entries(capability.surfaces).map(([surfaceName, surface]) => [
            surfaceName,
            surfaceSummary(surface),
          ]),
        ),
      },
      capability.id,
    );
  }
});

test('v4 fails closed when structural closure changes an external Agent judgment', () => {
  const beforeStructuralClosure = readJson('parity-manifest.v4.json');
  const afterStructuralClosure = structuredClone(beforeStructuralClosure);
  const browserBridge = afterStructuralClosure.capabilities.find(
    ({ id }) => id === 'browser-integration-browser-bridge',
  );
  browserBridge.surfaces.native_only.availability = 'unavailable';
  browserBridge.judgment.input.surfaces.native_only.availability = 'unavailable';

  assert.throws(
    () =>
      finalizeParityJudgmentClosure({
        beforeStructuralClosure,
        afterStructuralClosure,
        externalJudgmentCapabilityIds: ['browser-integration-browser-bridge'],
      }),
    /changed external structured Agent judgment/iu,
  );
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

test('Cloud OAuth keeps service authority with Electron and vault support', () => {
  const manifest = readJson('parity-manifest.v4.json');
  const auth = manifest.capabilities.find(
    ({ id }) => id === 'authentication-and-account-entry',
  );
  const oauth = manifest.capabilities.find(({ id }) => id === 'oauth-callback');

  assert.ok(auth);
  assert.ok(oauth);
  assert.equal(auth.surfaces.desktop_cloud.authority, 'cloud_service');
  assert.deepEqual(auth.surfaces.desktop_cloud.supporting_authorities, [
    'electron',
    'sidecar',
  ]);
  for (const surfaceName of ['desktop_cloud', 'local_online']) {
    assert.equal(oauth.surfaces[surfaceName].authority, 'cloud_service');
    assert.deepEqual(oauth.surfaces[surfaceName].supporting_authorities, [
      'electron',
      'sidecar',
    ]);
  }
  assert.equal(oauth.surfaces.local_offline.availability, 'not_applicable');
  assert.equal(
    oauth.api_contracts
      .filter(({ method }) => method === 'IPC')
      .every(({ authority_role }) => authority_role === 'supporting'),
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

test('v4 emits one protected Browser Bridge review input before fresh generation', (t) => {
  const fixture = createGitBackedSourceFixture(t);
  const original = readFileSync(fixture.manifestPath, 'utf8');
  const result = runGenerator(fixture, ['--emit-inputs', fixture.emitInputsPath]);

  assert.equal(result.status, 0, output(result));
  assert.equal(readFileSync(fixture.manifestPath, 'utf8'), original);
  const records = readFileSync(fixture.emitInputsPath, 'utf8')
    .trim()
    .split(/\r?\n/u)
    .map((line) => JSON.parse(line));
  assert.equal(records.length, 1);
  assert.equal(records[0].input.capability_id, 'browser-integration-browser-bridge');
  assert.deepEqual(
    records[0].input.production_entries.native_only.map(({ path }) => path),
    browserSourcePaths,
  );
  assert.match(records[0].input_digest, /^sha256:[0-9a-f]{64}$/u);
});

test('v4 fresh generation requires an exact external structured Agent judgment', (t) => {
  const fixture = createGitBackedSourceFixture(t);
  const original = readFileSync(fixture.manifestPath, 'utf8');

  const missing = runGenerator(fixture, []);
  assert.notEqual(missing.status, 0, missing.stdout);
  assert.match(output(missing), /exactly one of --check, --judgments, or --emit-inputs/iu);

  prepareBrowserBridgeJudgment(fixture, (judgment) => {
    judgment.output.native_only.availability = 'available';
  });
  const drifted = runGenerator(fixture, ['--judgments', fixture.judgmentPath]);
  assert.notEqual(drifted.status, 0, drifted.stdout);
  assert.match(output(drifted), /judgment output drifted/iu);
  assert.equal(readFileSync(fixture.manifestPath, 'utf8'), original);
});

test('v4 remains stable after its generated artifact is committed', (t) => {
  const fixture = createGitBackedGeneratorFixture(t);
  const artifactHead = git(fixture.fixtureRoot, ['rev-parse', 'HEAD']);
  assert.notEqual(artifactHead, fixture.auditedRevision);

  const result = runGenerator(fixture);
  assert.equal(result.status, 0, output(result));
  const manifest = JSON.parse(readFileSync(fixture.manifestPath, 'utf8'));
  assert.equal(manifest.references.audit_revision, fixture.auditedRevision);
  assert.equal(manifest.references.desktop_revision, fixture.auditedRevision);
  const browserBridge = manifest.capabilities.find(
    ({ id }) => id === 'browser-integration-browser-bridge',
  );
  assert.equal(browserBridge.source_revision, fixture.auditedRevision);
  assert.equal(browserBridge.judgment.input.audited_revision, fixture.auditedRevision);
});

test('v4 rejects divergent historical revisions and Browser Bridge source drift', (t) => {
  const divergent = createGeneratorFixture(t, {
    mutateV3(manifest) {
      manifest.references.desktop_revision = '0'.repeat(40);
    },
  });
  assert.match(
    output(runGenerator(divergent)),
    /requires identical v2 and v3 references/iu,
  );

  const drifted = createGitBackedGeneratorFixture(t);
  const driftedSource = resolve(drifted.fixtureRoot, browserSourcePaths[0]);
  writeFileSync(
    driftedSource,
    `${readFileSync(driftedSource, 'utf8')}\n// fixture drift\n`,
  );
  const result = runGenerator(drifted);
  assert.notEqual(result.status, 0, result.stdout);
  assert.match(
    output(result),
    /current HEAD blob differs from live regular-file bytes/iu,
  );
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
  assert.match(output(runGenerator(unknown)), /did not match a v3 contract/iu);

  const duplicate = createGeneratorFixture(t, {
    mutateOverrides(catalog) {
      catalog.contracts.push({ ...catalog.contracts[0] });
    },
  });
  assert.match(output(runGenerator(duplicate)), /duplicate authority override/iu);
});

test('v4 generation validates before replacing the checked-in artifact', (t) => {
  const fixture = createGeneratorFixture(t, {
    mutateOverrides(catalog) {
      catalog.contracts[0].authority_role = 'invalid';
    },
  });
  const original = readFileSync(fixture.manifestPath, 'utf8');
  const result = runGenerator(fixture);

  assert.notEqual(result.status, 0, result.stdout);
  assert.equal(readFileSync(fixture.manifestPath, 'utf8'), original);
});
