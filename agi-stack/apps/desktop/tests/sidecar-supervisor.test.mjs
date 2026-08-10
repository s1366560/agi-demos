import assert from 'node:assert/strict';
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';

const { SidecarSupervisor, sidecarRendererEnvironment } =
  await import('file:///tmp/agistack-desktop-test-dist/electron/main/sidecarSupervisor.js');

test('sidecar renderer environment binds the exact validated development origin', () => {
  assert.deepEqual(
    sidecarRendererEnvironment(new URL('http://localhost:5175/route?ignored=true')),
    { AGISTACK_DESKTOP_RENDERER_ORIGIN: 'http://localhost:5175' },
  );
  assert.deepEqual(sidecarRendererEnvironment(null), {
    AGISTACK_DESKTOP_RENDERER_ORIGIN: '',
  });
});

const fakeSidecarSource = String.raw`#!/usr/bin/env node
const { createHmac } = require('node:crypto');
const { appendFileSync, readFileSync } = require('node:fs');
const readline = require('node:readline');

const counterPath = process.env.FAKE_SIDECAR_COUNTER;
appendFileSync(counterPath, Date.now() + '\n');
const startCount = readFileSync(counterPath, 'utf8').trim().split('\n').length;
const crashCount = Number(process.env.FAKE_SIDECAR_CRASH_COUNT || 1);
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

function send(value) {
  process.stdout.write(JSON.stringify(value) + '\n');
}

input.once('line', (line) => {
  const initialize = JSON.parse(line);
  const legacyCandidatesPath = process.env.FAKE_SIDECAR_LEGACY_CANDIDATES;
  if (legacyCandidatesPath) {
    appendFileSync(
      legacyCandidatesPath,
      JSON.stringify(initialize.legacyDataDirectories) + '\n',
    );
  }
  const apiBaseUrl = 'http://127.0.0.1:' + (41000 + startCount);
  const apiToken = 'sidecar-token-' + startCount;
  const pid = process.pid;
  const becomeReady = () => {
    const message = [
      initialize.protocolVersion,
      initialize.nonce,
      pid,
      apiBaseUrl,
      apiToken,
    ].join('\n');
    const proof = createHmac(
      'sha256',
      Buffer.from(initialize.secret, 'base64url'),
    ).update(message).digest('base64url');
    send({
      type: 'ready',
      protocolVersion: initialize.protocolVersion,
      nonce: initialize.nonce,
      pid,
      apiBaseUrl,
      apiToken,
      proof,
    });

    input.on('line', (requestLine) => {
      const request = JSON.parse(requestLine);
      if (
        request.command === 'local_runtime_status' &&
        startCount <= crashCount &&
        stderrBytes === 0
      ) {
        process.exit(19);
      }
      send({
        type: 'response',
        id: request.id,
        ok: true,
        result: request.command === 'local_runtime_configure'
          ? { running: true, config: request.args?.config }
          : { running: true, api_base_url: apiBaseUrl, api_token: apiToken },
      });
    });
  };
  const stderrBytes = Number(process.env.FAKE_SIDECAR_STDERR_BYTES || 0);
  if (stderrBytes > 0) {
    process.stderr.write('x'.repeat(stderrBytes), becomeReady);
  } else {
    becomeReady();
  }
});
`;

test('sidecar initialization serializes explicit empty legacy migration candidates', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-empty-legacy-'));
  const binaryPath = join(root, 'fake-sidecar.cjs');
  const counterPath = join(root, 'starts.txt');
  const legacyCandidatesPath = join(root, 'legacy-candidates.jsonl');
  await writeFile(binaryPath, fakeSidecarSource, 'utf8');
  await chmod(binaryPath, 0o700);

  const supervisor = new SidecarSupervisor({
    binaryPath,
    dataDirectory: join(root, 'data'),
    workspaceRoot: root,
    legacyDataDirectories: [],
    environment: {
      FAKE_SIDECAR_COUNTER: counterPath,
      FAKE_SIDECAR_LEGACY_CANDIDATES: legacyCandidatesPath,
    },
  });

  try {
    await supervisor.start();
    assert.deepEqual(JSON.parse((await readFile(legacyCandidatesPath, 'utf8')).trim()), []);
  } finally {
    await supervisor.stop();
    await rm(root, { recursive: true, force: true });
  }
});

test('sidecar handshake is authenticated and the supervisor recovers after a crash', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-supervisor-'));
  const binaryPath = join(root, 'fake-sidecar.cjs');
  const counterPath = join(root, 'starts.txt');
  await writeFile(binaryPath, fakeSidecarSource, 'utf8');
  await chmod(binaryPath, 0o700);
  let recoveryNotifications = 0;

  const supervisor = new SidecarSupervisor({
    binaryPath,
    dataDirectory: join(root, 'data'),
    workspaceRoot: root,
    legacyDataDirectories: [join(root, 'legacy')],
    environment: { FAKE_SIDECAR_COUNTER: counterPath },
    restartDelaysMs: [1, 1, 1],
    onRecovered: () => {
      recoveryNotifications += 1;
    },
  });

  try {
    await assert.rejects(supervisor.invoke('local_runtime_status'), /sidecar exited unexpectedly/);
    const recoveredStatus = await supervisor.invoke('local_runtime_status');
    assert.equal(recoveredStatus.running, true);
    assert.equal(recoveredStatus.api_base_url, 'http://127.0.0.1:41002');
    assert.equal(recoveredStatus.api_token, 'sidecar-token-2');
    assert.equal(recoveryNotifications, 1);

    const configured = await supervisor.invoke('local_runtime_configure', {
      config: { workspaceRoot: root },
    });
    assert.deepEqual(configured.config, { workspaceRoot: root });
    assert.equal((await readFile(counterPath, 'utf8')).trim().split('\n').length, 2);
  } finally {
    await supervisor.stop();
    await rm(root, { recursive: true, force: true });
  }
});

test('sidecar handshake rejects forged readiness responses', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-forgery-'));
  const binaryPath = join(root, 'forged-sidecar.cjs');
  await writeFile(
    binaryPath,
    `#!/usr/bin/env node
const readline = require('node:readline');
readline.createInterface({ input: process.stdin }).once('line', (line) => {
  const request = JSON.parse(line);
  process.stdout.write(JSON.stringify({
    type: 'ready',
    protocolVersion: request.protocolVersion,
    nonce: request.nonce,
    pid: process.pid,
    apiBaseUrl: 'http://127.0.0.1:40000',
    apiToken: 'forged-token',
    proof: 'forged-proof',
  }) + '\\n');
});
`,
    'utf8',
  );
  await chmod(binaryPath, 0o700);
  const supervisor = new SidecarSupervisor({
    binaryPath,
    dataDirectory: join(root, 'data'),
    workspaceRoot: root,
    legacyDataDirectories: [],
  });

  try {
    await assert.rejects(supervisor.start(), /sidecar handshake proof is invalid/);
  } finally {
    await supervisor.stop();
    await rm(root, { recursive: true, force: true });
  }
});

test('sidecar restart backoff grows across rapid crashes and remains capped', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-backoff-'));
  const binaryPath = join(root, 'crashing-sidecar.cjs');
  const counterPath = join(root, 'starts.txt');
  await writeFile(binaryPath, fakeSidecarSource, 'utf8');
  await chmod(binaryPath, 0o700);
  const supervisor = new SidecarSupervisor({
    binaryPath,
    dataDirectory: join(root, 'data'),
    workspaceRoot: root,
    legacyDataDirectories: [],
    environment: {
      FAKE_SIDECAR_COUNTER: counterPath,
      FAKE_SIDECAR_CRASH_COUNT: '3',
    },
    restartDelaysMs: [25, 50],
    restartStabilityMs: 5_000,
  });

  try {
    await assert.rejects(supervisor.invoke('local_runtime_status'), /sidecar exited unexpectedly/);
    await assert.rejects(supervisor.invoke('local_runtime_status'), /sidecar exited unexpectedly/);
    await assert.rejects(supervisor.invoke('local_runtime_status'), /sidecar exited unexpectedly/);
    const recoveredStatus = await supervisor.invoke('local_runtime_status');
    assert.equal(recoveredStatus.running, true);

    const starts = (await readFile(counterPath, 'utf8')).trim().split('\n').map(Number);
    assert.equal(starts.length, 4);
    assert.ok(starts[1] - starts[0] >= 20);
    assert.ok(starts[2] - starts[1] >= 40);
    assert.ok(starts[3] - starts[2] >= 40);
  } finally {
    await supervisor.stop();
    await rm(root, { recursive: true, force: true });
  }
});

test('sidecar diagnostics are drained without blocking readiness or requests', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-stderr-'));
  const binaryPath = join(root, 'noisy-sidecar.cjs');
  const counterPath = join(root, 'starts.txt');
  await writeFile(binaryPath, fakeSidecarSource, 'utf8');
  await chmod(binaryPath, 0o700);
  const supervisor = new SidecarSupervisor({
    binaryPath,
    dataDirectory: join(root, 'data'),
    workspaceRoot: root,
    legacyDataDirectories: [],
    environment: {
      FAKE_SIDECAR_COUNTER: counterPath,
      FAKE_SIDECAR_STDERR_BYTES: String(8 * 1024 * 1024),
    },
    handshakeTimeoutMs: 5_000,
  });

  try {
    const identity = await supervisor.start();
    assert.match(identity.apiBaseUrl, /^http:\/\/127\.0\.0\.1:\d+$/u);
    const status = await supervisor.invoke('local_runtime_status');
    assert.equal(status.running, true);
  } finally {
    await supervisor.stop();
    await rm(root, { recursive: true, force: true });
  }
});
