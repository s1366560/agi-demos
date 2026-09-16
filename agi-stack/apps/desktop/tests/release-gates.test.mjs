import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { deflateRawSync } from 'node:zlib';
import { stringify } from 'yaml';

import {
  findSpawnedSidecar,
  isDescendantOf,
  launchArgumentsFor,
  parseUnixProcessTable,
  parseWindowsProcessTable,
} from '../scripts/install-launch-smoke.mjs';
import {
  BLOCKMAP_VERIFICATION_SCOPE,
  EVIDENCE_SCOPE,
  INSTALL_LAUNCH_SMOKE_SCHEMA,
  RELEASE_DISPOSITION,
  RELEASE_EVIDENCE_SCHEMA,
  RELEASE_EVIDENCE_SUPERSEDES,
  UPDATE_DRILL_SCHEMA,
  assertInstallLaunchEvidence,
  assertUpdateDrillEvidence,
  composeReleaseEvidence,
  verifyTagEvidence,
  writeEvidenceFragment,
} from '../scripts/release-evidence.mjs';
import { probeSidecarHealth } from '../scripts/sidecar-health-probe.mjs';
import { drillVersions, runUpdateDrill } from '../scripts/smoke-update-drill.mjs';

const VERSION = '0.1.0';
const TAG = `v${VERSION}`;

function fakeSidecarSource() {
    return `import { createHmac } from 'node:crypto';
import { createInterface } from 'node:readline';

const mode = process.argv[2] ?? 'ok';
const reader = createInterface({ input: process.stdin, crlfDelay: Infinity });
let initialized = false;
for await (const line of reader) {
  const message = JSON.parse(line);
  if (!initialized) {
    initialized = true;
    if (mode === 'exit-after-ready') process.exit(3);
    const apiBaseUrl = 'http://127.0.0.1:41234';
    const apiToken = 'probe-test-token-0123456789abcdef';
    const proofMessage = [
      message.protocolVersion,
      message.nonce,
      process.pid,
      apiBaseUrl,
      apiToken,
    ].join('\\n');
    const secret = Buffer.from(message.secret, 'base64url');
    const proof =
      mode === 'bad-proof'
        ? createHmac('sha256', Buffer.alloc(32, 9)).update(proofMessage).digest('base64url')
        : createHmac('sha256', secret).update(proofMessage).digest('base64url');
    process.stdout.write(
      JSON.stringify({
        type: 'ready',
        protocolVersion: message.protocolVersion,
        nonce: message.nonce,
        pid: process.pid,
        apiBaseUrl,
        apiToken,
        proof,
      }) + '\\n',
    );
    continue;
  }
  process.stdout.write(
    JSON.stringify({
      type: 'response',
      id: message.id,
      ok: true,
      result: { api_base_url: 'http://127.0.0.1:41234' },
    }) + '\\n',
  );
}
`;
}

function withFakeSidecar(mode, run) {
  const root = mkdtempSync(join(tmpdir(), 'agistack-fake-sidecar-'));
  const scriptPath = join(root, 'fake-sidecar.mjs');
  writeFileSync(scriptPath, fakeSidecarSource(), 'utf8');
  const spawnImpl = (_binary, args, options) =>
    spawn(process.execPath, [scriptPath, mode, ...args], options);
  const workspaceCore = join(root, 'workspace-core');
  writeFileSync(workspaceCore, 'not a real binary', 'utf8');
  chmodSync(workspaceCore, 0o700);
  const sidecar = join(root, 'agistack-desktop-sidecar');
  writeFileSync(sidecar, 'probe spawns via injected spawnImpl', 'utf8');
  chmodSync(sidecar, 0o700);
  return Promise.resolve(run({ sidecarPath: sidecar, workspaceCorePath: workspaceCore, spawnImpl })).finally(
    () => rmSync(root, { recursive: true, force: true }),
  );
}

test('sidecar health probe completes the real handshake contract and clean exit', async () => {
  await withFakeSidecar('ok', async ({ sidecarPath, workspaceCorePath, spawnImpl }) => {
    const evidence = await probeSidecarHealth({
      sidecarPath,
      workspaceCorePath,
      spawnImpl,
      handshakeTimeoutMs: 15_000,
    });
    assert.equal(evidence.handshake, 'initialize_hmac_proof_verified');
    assert.equal(evidence.protocol_version, 1);
    assert.equal(evidence.api_bind_host, '127.0.0.1');
    assert.equal(evidence.local_runtime_status, 'ok');
    assert.equal(evidence.clean_exit, true);
    assert.ok(Number.isSafeInteger(evidence.sidecar_pid));
    const serialized = JSON.stringify(evidence);
    assert.ok(!serialized.includes('probe-test-token'), 'evidence must not leak the API token');
  });
});

test('sidecar health probe rejects a forged handshake proof', async () => {
  await withFakeSidecar('bad-proof', async ({ sidecarPath, workspaceCorePath, spawnImpl }) => {
    await assert.rejects(
      probeSidecarHealth({ sidecarPath, workspaceCorePath, spawnImpl, handshakeTimeoutMs: 15_000 }),
      /handshake proof is invalid/u,
    );
  });
});

test('sidecar health probe rejects a sidecar that dies before answering', async () => {
  await withFakeSidecar(
    'exit-after-ready',
    async ({ sidecarPath, workspaceCorePath, spawnImpl }) => {
      await assert.rejects(
        probeSidecarHealth({
          sidecarPath,
          workspaceCorePath,
          spawnImpl,
          handshakeTimeoutMs: 15_000,
        }),
        /sidecar/u,
      );
    },
  );
});

test('unix process tables parse pid, ppid, and command', () => {
  const table = parseUnixProcessTable(
    ['  100     1 /sbin/launchd', '  220   100 /opt/agi stack/app --no-sandbox', 'bad line'].join(
      '\n',
    ),
  );
  assert.deepEqual(table, [
    { pid: 100, ppid: 1, command: '/sbin/launchd' },
    { pid: 220, ppid: 100, command: '/opt/agi stack/app --no-sandbox' },
  ]);
});

test('windows process tables accept both array and single-object JSON', () => {
  const arrayTable = parseWindowsProcessTable(
    JSON.stringify([
      { ProcessId: 10, ParentProcessId: 4, ExecutablePath: 'C:\\App\\app.exe' },
      { ProcessId: 11, ParentProcessId: 10, ExecutablePath: 'C:\\App\\resources\\sidecar\\s.exe' },
    ]),
  );
  assert.equal(arrayTable.length, 2);
  const singleTable = parseWindowsProcessTable(
    JSON.stringify({ ProcessId: 9, ParentProcessId: 4, ExecutablePath: null }),
  );
  assert.deepEqual(singleTable, [{ pid: 9, ppid: 4, command: '' }]);
});

test('spawned sidecar detection requires descendant parentage', () => {
  const processes = [
    { pid: 500, ppid: 1, command: '/tmp/installed/app' },
    { pid: 640, ppid: 500, command: '/tmp/installed/resources/sidecar/agistack-desktop-sidecar' },
    { pid: 777, ppid: 1, command: '/other/resources/sidecar/agistack-desktop-sidecar' },
  ];
  const sidecarPath = '/tmp/installed/resources/sidecar/agistack-desktop-sidecar';
  assert.equal(isDescendantOf(processes, 640, 500), true);
  assert.equal(isDescendantOf(processes, 777, 500), false);
  assert.equal(findSpawnedSidecar(processes, 500, sidecarPath)?.pid, 640);
  assert.equal(findSpawnedSidecar(processes, 999, sidecarPath), undefined);
});

test('launch flags disable the Chromium sandbox only on headless Linux', () => {
  assert.deepEqual(launchArgumentsFor('linux'), ['--no-sandbox']);
  assert.deepEqual(launchArgumentsFor('darwin'), []);
  assert.deepEqual(launchArgumentsFor('win32'), []);
});

test('drill versions bump the patch marker from the package version', () => {
  assert.deepEqual(drillVersions('0.1.0'), {
    base: '0.1.0',
    candidate: '0.1.1',
    rollbackProbe: '0.1.2',
  });
  assert.throws(() => drillVersions('0.1'), /semver/u);
});

function drillFixture(run) {
  const root = mkdtempSync(join(tmpdir(), 'agistack-update-drill-test-'));
  const sidecarSource = join(root, 'staged-sidecar');
  const workspaceCoreSource = join(root, 'staged-workspace-core');
  writeFileSync(sidecarSource, 'genuine-staged-sidecar', 'utf8');
  writeFileSync(workspaceCoreSource, 'genuine-staged-workspace-core', 'utf8');
  chmodSync(sidecarSource, 0o700);
  chmodSync(workspaceCoreSource, 0o700);
  const evidenceDir = join(root, 'evidence');
  return Promise.resolve(
    run({
      rootDirectory: join(root, 'drill'),
      sidecarSourcePath: sidecarSource,
      workspaceCoreSourcePath: workspaceCoreSource,
      evidenceDir,
    }),
  ).finally(() => rmSync(root, { recursive: true, force: true }));
}

test('update drill applies N+1, asserts the version, and rolls back both failure modes', async () => {
  await drillFixture(async (overrides) => {
    const probedPaths = [];
    const probe = async ({ sidecarPath }) => {
      if (readFileSync(sidecarPath, 'utf8') !== 'genuine-staged-sidecar') {
        throw new Error('candidate sidecar binary failed the health probe');
      }
      probedPaths.push(sidecarPath);
      return { handshake: 'initialize_hmac_proof_verified', clean_exit: true };
    };
    const prepareSnapshot = () => ({
      prepared: true,
      manifest_sha512_bytes: 64,
      manifest_size: 128,
    });
    const fragment = await runUpdateDrill({
      platform: 'linux',
      version: VERSION,
      tag: TAG,
      probe,
      prepareSnapshot,
      ...overrides,
    });

    assert.equal(fragment.schema, UPDATE_DRILL_SCHEMA);
    assert.equal(fragment.base_version, '0.1.0');
    assert.equal(fragment.candidate_version, '0.1.1');
    assert.equal(fragment.apply.applied, true);
    assert.equal(fragment.apply.version_reported, '0.1.1');
    assert.deepEqual(
      fragment.rollback_drills.map((drill) => drill.mode),
      ['version_marker_mismatch', 'corrupt_sidecar_binary'],
    );
    for (const drill of fragment.rollback_drills) {
      assert.equal(drill.update_rejected, true);
      assert.equal(drill.restored_version, '0.1.1');
      assert.equal(drill.sidecar_probe_after_restore, 'passed');
    }
    assert.equal(fragment.coverage.electron_updater_feed_apply, false);
    assert.equal(fragment.coverage.failed_update_rollback, true);
    assert.ok(probedPaths.length >= 4, 'probe must validate apply and both restores');
    assert.equal(fragment.snapshot.prepared, true);
    assertUpdateDrillEvidence(fragment);
  });
});

test('update drill fails closed when the candidate sidecar probe rejects the apply', async () => {
  await drillFixture(async (overrides) => {
    const probe = async () => {
      throw new Error('sidecar handshake failed');
    };
    const prepareSnapshot = () => ({
      prepared: true,
      manifest_sha512_bytes: 64,
      manifest_size: 128,
    });
    await assert.rejects(
      runUpdateDrill({
        platform: 'linux',
        version: VERSION,
        tag: TAG,
        probe,
        prepareSnapshot,
        ...overrides,
      }),
      /update validation failed/u,
    );
  });
});

function sha512(content) {
  return createHash('sha512').update(content).digest('base64');
}

function linuxReleaseFixture(root) {
  mkdirSync(root, { recursive: true });
  const appImage = `agi-stack-desktop-${VERSION}-linux-x64.AppImage`;
  const deb = `agi-stack-desktop-${VERSION}-linux-x64.deb`;
  const appImageContent = Buffer.from('appimage-installer-bytes');
  const blockMap = {
    version: '2',
    files: [
      {
        name: 'file',
        offset: 0,
        checksums: [Buffer.alloc(18, 7).toString('base64')],
        sizes: [appImageContent.byteLength],
      },
    ],
  };
  const compressed = deflateRawSync(Buffer.from(JSON.stringify(blockMap)));
  const trailer = Buffer.alloc(4);
  trailer.writeUInt32BE(compressed.byteLength);
  writeFileSync(join(root, appImage), Buffer.concat([appImageContent, compressed, trailer]));
  const debContent = Buffer.from('deb-installer-bytes');
  writeFileSync(join(root, deb), debContent);
  const files = [
    {
      url: appImage,
      sha512: sha512(Buffer.concat([appImageContent, compressed, trailer])),
      size: appImageContent.byteLength + compressed.byteLength + 4,
      blockMapSize: compressed.byteLength,
    },
    { url: deb, sha512: sha512(debContent), size: debContent.byteLength },
  ];
  writeFileSync(
    join(root, 'latest-linux.yml'),
    stringify({ version: VERSION, files, path: appImage, sha512: files[0].sha512 }),
  );
}

function passingInstallLaunchFragment(platform) {
  return {
    schema: INSTALL_LAUNCH_SMOKE_SCHEMA,
    platform,
    version: VERSION,
    tag: TAG,
    generated_at: new Date().toISOString(),
    legs: [
      {
        kind: 'fixture_leg',
        installer: 'fixture.AppImage',
        launched: true,
        sidecar_spawned: true,
        exit_observed: true,
        sidecar_probe: { handshake: 'initialize_hmac_proof_verified', clean_exit: true },
      },
    ],
    not_covered: [],
  };
}

function passingUpdateDrillFragment(platform) {
  return {
    schema: UPDATE_DRILL_SCHEMA,
    platform,
    version: VERSION,
    tag: TAG,
    generated_at: new Date().toISOString(),
    base_version: '0.1.0',
    candidate_version: '0.1.1',
    rollback_probe_version: '0.1.2',
    snapshot: { prepared: true, manifest_sha512_bytes: 64, manifest_size: 128 },
    apply: { applied: true, version_reported: '0.1.1', sidecar_probe: 'passed' },
    rollback_drills: [
      {
        mode: 'version_marker_mismatch',
        update_rejected: true,
        restored_version: '0.1.1',
        sidecar_probe_after_restore: 'passed',
      },
    ],
    coverage: { electron_updater_feed_apply: false, failed_update_rollback: true },
    not_covered: [],
  };
}

function withEvidenceWorkspace(run) {
  const root = mkdtempSync(join(tmpdir(), 'agistack-release-evidence-'));
  const releaseRoot = join(root, 'release');
  const evidenceDir = join(root, 'evidence');
  linuxReleaseFixture(releaseRoot);
  return Promise.resolve(run({ root, releaseRoot, evidenceDir })).finally(() =>
    rmSync(root, { recursive: true, force: true }),
  );
}

test('release evidence v3 composes package verification and both Wave 8 gates', async () => {
  await withEvidenceWorkspace(async ({ releaseRoot, evidenceDir }) => {
    await writeEvidenceFragment('install-launch-smoke.json', passingInstallLaunchFragment('linux'), {
      evidenceDir,
    });
    await writeEvidenceFragment('update-drill.json', passingUpdateDrillFragment('linux'), {
      evidenceDir,
    });
    const evidence = await composeReleaseEvidence({
      platform: 'linux',
      releaseRoot,
      evidenceDir,
      env: { AGISTACK_EXPECTED_VERSION: VERSION, AGISTACK_EXPECTED_TAG: TAG },
      now: () => '2026-09-17T00:00:00.000Z',
    });
    assert.equal(evidence.schema, RELEASE_EVIDENCE_SCHEMA);
    assert.equal(evidence.supersedes, RELEASE_EVIDENCE_SUPERSEDES);
    assert.deepEqual(evidence.evidence_scope, [
      'package_artifact_verification',
      'install_launch_smoke',
      'update_transaction_drill',
    ]);
    assert.equal(evidence.blockmap_verification_scope, BLOCKMAP_VERIFICATION_SCOPE);
    assert.equal(evidence.blockmap_verification_scope, 'blockmap_structure_and_coverage_only');
    assert.equal(evidence.release_disposition, RELEASE_DISPOSITION);
    assert.deepEqual(evidence.installers.sort(), [
      `agi-stack-desktop-${VERSION}-linux-x64.AppImage`,
      `agi-stack-desktop-${VERSION}-linux-x64.deb`,
    ]);
    assert.ok(evidence.not_covered.includes('electron_updater_hosted_feed_apply'));
    const written = JSON.parse(
      readFileSync(join(evidenceDir, 'desktop-release-evidence-v3.json'), 'utf8'),
    );
    assert.equal(written.schema, RELEASE_EVIDENCE_SCHEMA);
    assert.equal((statSync(join(evidenceDir, 'desktop-release-evidence-v3.json')).mode & 0o777), 0o600);
  });
});

test('release evidence compose fails closed on missing or failing gate fragments', async () => {
  await withEvidenceWorkspace(async ({ releaseRoot, evidenceDir }) => {
    const env = { AGISTACK_EXPECTED_VERSION: VERSION, AGISTACK_EXPECTED_TAG: TAG };
    await assert.rejects(
      composeReleaseEvidence({ platform: 'linux', releaseRoot, evidenceDir, env }),
      /ENOENT|install-launch/u,
    );
    const failingInstall = passingInstallLaunchFragment('linux');
    failingInstall.legs[0].sidecar_spawned = false;
    await writeEvidenceFragment('install-launch-smoke.json', failingInstall, { evidenceDir });
    await writeEvidenceFragment('update-drill.json', passingUpdateDrillFragment('linux'), {
      evidenceDir,
    });
    await assert.rejects(
      composeReleaseEvidence({ platform: 'linux', releaseRoot, evidenceDir, env }),
      /leg did not pass/u,
    );
    const wrongTag = passingInstallLaunchFragment('linux');
    wrongTag.tag = 'v9.9.9';
    await writeEvidenceFragment('install-launch-smoke.json', wrongTag, { evidenceDir });
    await assert.rejects(
      composeReleaseEvidence({ platform: 'linux', releaseRoot, evidenceDir, env }),
      /does not match this release/u,
    );
  });
});

test('gate fragment assertions reject unexecuted rollback coverage', () => {
  const drill = passingUpdateDrillFragment('darwin');
  drill.rollback_drills[0].update_rejected = false;
  assert.throws(() => assertUpdateDrillEvidence(drill), /rollback drill did not pass/u);
  drill.rollback_drills[0].update_rejected = true;
  assert.equal(assertUpdateDrillEvidence(drill), true);
  const install = passingInstallLaunchFragment('darwin');
  install.legs = [];
  assert.throws(() => assertInstallLaunchEvidence(install), /at least one install leg/u);
});

test('verify-tag requires passing evidence for all three platforms on the exact tag', async () => {
  const root = mkdtempSync(join(tmpdir(), 'agistack-gate-evidence-'));
  try {
    const seedEvidence = async (directory, platform, tag) => {
      mkdirSync(join(root, directory), { recursive: true });
      await writeEvidenceFragment(
        'desktop-release-evidence-v3.json',
        {
          schema: RELEASE_EVIDENCE_SCHEMA,
          supersedes: RELEASE_EVIDENCE_SUPERSEDES,
          version: VERSION,
          tag,
          platform,
          generated_at: '2026-09-17T00:00:00.000Z',
          evidence_scope: [...EVIDENCE_SCOPE],
          blockmap_verification_scope: BLOCKMAP_VERIFICATION_SCOPE,
          installers: [],
          install_launch_smoke: passingInstallLaunchFragment(platform),
          update_drill: passingUpdateDrillFragment(platform),
          not_covered: [],
          release_disposition: RELEASE_DISPOSITION,
        },
        { evidenceDir: join(root, directory) },
      );
    };
    await seedEvidence('macos', 'darwin', TAG);
    await seedEvidence('windows', 'win32', TAG);
    await seedEvidence('linux', 'linux', TAG);
    assert.deepEqual(await verifyTagEvidence({ evidenceRoot: root, expectedTag: TAG }), [
      'darwin',
      'linux',
      'win32',
    ]);
    await assert.rejects(
      verifyTagEvidence({ evidenceRoot: root, expectedTag: 'v9.9.9' }),
      /does not match tag/u,
    );
    rmSync(join(root, 'linux'), { recursive: true, force: true });
    await assert.rejects(
      verifyTagEvidence({ evidenceRoot: root, expectedTag: TAG }),
      /missing Wave 8 gate evidence for platforms: linux/u,
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
