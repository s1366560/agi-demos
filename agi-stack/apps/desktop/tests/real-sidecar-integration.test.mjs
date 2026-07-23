import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { SidecarSupervisor } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/sidecarSupervisor.js',
);
const binaryPath = process.env.AGISTACK_REAL_SIDECAR;

test(
  'Electron supervisor completes a real sidecar handshake and credential round trip',
  { skip: binaryPath ? false : 'AGISTACK_REAL_SIDECAR is not configured' },
  async () => {
    const root = await mkdtemp(join(tmpdir(), 'agistack-real-sidecar-'));
    const dataDirectory = join(root, 'data');
    const workspaceRoot = join(root, 'workspace');
    await mkdir(workspaceRoot);
    const supervisor = new SidecarSupervisor({
      binaryPath: resolve(binaryPath),
      dataDirectory,
      workspaceRoot,
      legacyDataDirectories: [],
      handshakeTimeoutMs: 30_000,
    });
    const record = {
      version: 1,
      api_base_url: 'https://cloud.example.test',
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'real-sidecar-sensitive-test-value',
      expires_at: null,
    };

    try {
      const identity = await supervisor.start();
      assert.match(identity.apiBaseUrl, /^http:\/\/127\.0\.0\.1:\d+$/u);
      assert.ok(identity.apiToken.length >= 32);

      const status = await supervisor.invoke('local_runtime_status');
      assert.equal(status.api_base_url, identity.apiBaseUrl);
      assert.equal(status.api_token, identity.apiToken);

      await supervisor.invoke('trusted_session_save', { input: record });
      assert.deepEqual(await supervisor.invoke('trusted_session_load'), {
        version: record.version,
        api_base_url: record.api_base_url,
        runtime_mode: record.runtime_mode,
        credential_kind: record.credential_kind,
        credential: record.credential,
      });
      await supervisor.invoke('trusted_session_clear');
      assert.equal(await supervisor.invoke('trusted_session_load'), null);
    } finally {
      await supervisor.stop();
      await rm(root, { recursive: true, force: true });
    }
  },
);

test(
  'real sidecar migrates the legacy credential vault and local session database',
  { skip: binaryPath ? false : 'AGISTACK_REAL_SIDECAR is not configured' },
  async () => {
    const root = await mkdtemp(join(tmpdir(), 'agistack-real-sidecar-migration-'));
    const legacyDataDirectory = join(root, 'legacy-tauri-data');
    const electronDataDirectory = join(root, 'electron-data');
    const workspaceRoot = join(root, 'workspace');
    await mkdir(workspaceRoot);
    const cloudRecord = {
      version: 1,
      api_base_url: 'https://cloud.example.test',
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'legacy-cloud-credential-test-value',
      expires_at: null,
    };
    const localRecord = {
      version: 1,
      api_base_url: 'http://127.0.0.1:1',
      runtime_mode: 'local',
      credential_kind: 'local_session_reference',
      credential: 'legacy-local-session-reference',
      expires_at: null,
    };
    const legacySupervisor = new SidecarSupervisor({
      binaryPath: resolve(binaryPath),
      dataDirectory: legacyDataDirectory,
      workspaceRoot,
      legacyDataDirectories: [],
      handshakeTimeoutMs: 30_000,
    });
    const migratedSupervisor = new SidecarSupervisor({
      binaryPath: resolve(binaryPath),
      dataDirectory: electronDataDirectory,
      workspaceRoot,
      legacyDataDirectories: [legacyDataDirectory],
      handshakeTimeoutMs: 30_000,
    });

    try {
      await legacySupervisor.start();
      await legacySupervisor.invoke('trusted_session_save', { input: cloudRecord });
      await legacySupervisor.invoke('local_trusted_session_save', { input: localRecord });
      await legacySupervisor.stop();

      await migratedSupervisor.start();
      assert.deepEqual(await migratedSupervisor.invoke('trusted_session_load'), {
        version: cloudRecord.version,
        api_base_url: cloudRecord.api_base_url,
        runtime_mode: cloudRecord.runtime_mode,
        credential_kind: cloudRecord.credential_kind,
        credential: cloudRecord.credential,
      });
      assert.deepEqual(await migratedSupervisor.invoke('local_trusted_session_load'), {
        version: localRecord.version,
        api_base_url: localRecord.api_base_url,
        runtime_mode: localRecord.runtime_mode,
        credential_kind: localRecord.credential_kind,
        credential: localRecord.credential,
      });
      const marker = JSON.parse(
        await readFile(
          join(electronDataDirectory, '.tauri-data-migration-v1.json'),
          'utf8',
        ),
      );
      assert.equal(marker.version, 1);
      assert.equal(resolve(marker.source), resolve(legacyDataDirectory));
    } finally {
      await legacySupervisor.stop();
      await migratedSupervisor.stop();
      await rm(root, { recursive: true, force: true });
    }
  },
);
