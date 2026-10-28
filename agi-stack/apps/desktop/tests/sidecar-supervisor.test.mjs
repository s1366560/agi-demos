import assert from 'node:assert/strict';
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import test from 'node:test';

const { SidecarSupervisor, sidecarChildEnvironment, sidecarRendererEnvironment } =
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

test('sidecar child environment excludes plugin data-plane bootstrap secrets', () => {
  const credential = `ms_dp_${'d'.repeat(64)}`;
  const environment = sidecarChildEnvironment(
    {
      PATH: '/usr/bin',
      AGISTACK_PLUGIN_DATA_PLANE_CREDENTIAL_V2: credential,
      AGISTACK_PLUGIN_DATA_PLANE_API_BASE_URL_V2: 'https://plugins.example.test',
      AGISTACK_PLUGIN_DATA_PLANE_ACK_PARTICIPATION_V2: 'true',
    },
    {
      AGISTACK_DESKTOP_RENDERER_ORIGIN: 'http://localhost:5175',
      AGISTACK_PLUGIN_DATA_PLANE_CREDENTIAL_V2: credential,
    },
  );

  assert.deepEqual(environment, {
    PATH: '/usr/bin',
    AGISTACK_DESKTOP_RENDERER_ORIGIN: 'http://localhost:5175',
  });
  assert.equal(JSON.stringify(environment).includes(credential), false);
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
      if (request.command === 'computer_input_fixture') {
        send({ type: 'computer_use_input', input: request.args?.input });
      }
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

test('authenticated sidecar input push is typed, independent of responses, and cleared on disconnect', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-input-'));
  const binaryPath = join(root, 'fake-sidecar.cjs');
  await writeFile(binaryPath, fakeSidecarSource, 'utf8');
  await chmod(binaryPath, 0o700);
  const received = [];
  let cleared = 0;
  const supervisor = new SidecarSupervisor({
    binaryPath, workspaceCoreBinaryPath: binaryPath, dataDirectory: join(root, 'data'),
    workspaceRoot: root, legacyDataDirectories: [],
    environment: { FAKE_SIDECAR_COUNTER: join(root, 'starts.txt'), FAKE_SIDECAR_CRASH_COUNT: '0' },
    onComputerUseInput: (value) => { received.push(value); throw new Error('decorative consumer failed'); },
    onComputerUseInputDisconnected: () => { cleared++; },
  });
  const input = {
    mode: 'local', tenant_id: 'tenant', project_id: 'project', conversation_id: 'conversation',
    run_id: 'run', session_id: 'session', input_mode: 'background', input_generation: 'generation',
    sequence: 1, updated_at: 1, phase: 'holding', target_pid: 42, target_window_id: 'window',
    virtual_cursor: { x: 10, y: 20, width: 300, height: 200, window_id: 'window' },
    held_keys: [55], held_buttons: [0], evidence: 'dispatched', typed_text: 'discard this field',
  };
  try {
    const response = await supervisor.invoke('computer_input_fixture', { input });
    assert.equal(response.running, true);
    assert.equal(received.length, 1);
    assert.equal('typed_text' in received[0], false);
    await supervisor.invoke('computer_input_fixture', { input: { ...input, sequence: -1 } });
    assert.equal(received.length, 1, 'invalid notifications do not reach the display consumer');
    assert.equal((await supervisor.invoke('local_runtime_status')).running, true);
    await supervisor.stop();
    assert.ok(cleared >= 1);
  } finally {
    await supervisor.stop();
    await rm(root, { recursive: true, force: true });
  }
});

test('sidecar initialization serializes explicit empty legacy migration candidates', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-empty-legacy-'));
  const binaryPath = join(root, 'fake-sidecar.cjs');
  const counterPath = join(root, 'starts.txt');
  const legacyCandidatesPath = join(root, 'legacy-candidates.jsonl');
  await writeFile(binaryPath, fakeSidecarSource, 'utf8');
  await chmod(binaryPath, 0o700);

  const supervisor = new SidecarSupervisor({
    binaryPath,
    workspaceCoreBinaryPath: binaryPath,
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

test('sidecar shutdown waits for authenticated helper cleanup before forcing termination', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-graceful-stop-'));
  const binaryPath = join(root, 'graceful-sidecar.cjs');
  const markerPath = join(root, 'shutdown.txt');
  const counterPath = join(root, 'starts.txt');
  await writeFile(
    binaryPath,
    String.raw`#!/usr/bin/env node
const { createHmac } = require('node:crypto');
const { appendFileSync } = require('node:fs');
const readline = require('node:readline');

const markerPath = process.env.FAKE_SIDECAR_SHUTDOWN_MARKER;
const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
process.on('SIGTERM', () => {
  appendFileSync(markerPath, 'sigterm\n');
  process.exit(143);
});
input.once('line', (line) => {
  const initialize = JSON.parse(line);
  const apiBaseUrl = 'http://127.0.0.1:41999';
  const apiToken = 'graceful-sidecar-token';
  const message = [
    initialize.protocolVersion,
    initialize.nonce,
    process.pid,
    apiBaseUrl,
    apiToken,
  ].join('\n');
  const proof = createHmac(
    'sha256',
    Buffer.from(initialize.secret, 'base64url'),
  ).update(message).digest('base64url');
  process.stdout.write(JSON.stringify({
    type: 'ready',
    protocolVersion: initialize.protocolVersion,
    nonce: initialize.nonce,
    pid: process.pid,
    apiBaseUrl,
    apiToken,
    proof,
  }) + '\n');
});
input.on('close', () => {
  setTimeout(() => {
    appendFileSync(markerPath, 'graceful\n');
    process.exit(0);
  }, 50);
});
`,
    'utf8',
  );
  await chmod(binaryPath, 0o700);
  await writeFile(counterPath, '', 'utf8');
  const supervisor = new SidecarSupervisor({
    binaryPath,
    workspaceCoreBinaryPath: binaryPath,
    dataDirectory: join(root, 'data'),
    workspaceRoot: root,
    legacyDataDirectories: [],
    environment: {
      FAKE_SIDECAR_COUNTER: counterPath,
      FAKE_SIDECAR_SHUTDOWN_MARKER: markerPath,
    },
    shutdownTimeoutMs: 500,
  });

  try {
    await supervisor.start();
    await supervisor.stop();
    assert.equal(await readFile(markerPath, 'utf8'), 'graceful\n');
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
    workspaceCoreBinaryPath: binaryPath,
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
    workspaceCoreBinaryPath: binaryPath,
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
    workspaceCoreBinaryPath: binaryPath,
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

test('sidecar crash recovery stops after the configured restart budget is exhausted', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-sidecar-restart-budget-'));
  const binaryPath = join(root, 'crashing-sidecar.cjs');
  const counterPath = join(root, 'starts.txt');
  await writeFile(binaryPath, fakeSidecarSource, 'utf8');
  await chmod(binaryPath, 0o700);
  const supervisor = new SidecarSupervisor({
    binaryPath,
    workspaceCoreBinaryPath: binaryPath,
    dataDirectory: join(root, 'data'),
    workspaceRoot: root,
    legacyDataDirectories: [],
    environment: {
      FAKE_SIDECAR_COUNTER: counterPath,
      FAKE_SIDECAR_CRASH_COUNT: '99',
    },
    restartDelaysMs: [1],
    restartStabilityMs: 5_000,
    maxRestartAttempts: 2,
  });

  try {
    await assert.rejects(supervisor.invoke('local_runtime_status'), /sidecar exited unexpectedly/);
    await assert.rejects(supervisor.invoke('local_runtime_status'), /sidecar exited unexpectedly/);
    await assert.rejects(supervisor.invoke('local_runtime_status'), /sidecar exited unexpectedly/);
    await assert.rejects(supervisor.start(), /sidecar restart budget exhausted/u);
    await new Promise((resolve) => setTimeout(resolve, 20));

    assert.equal((await readFile(counterPath, 'utf8')).trim().split('\n').length, 3);
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
    workspaceCoreBinaryPath: binaryPath,
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

test('only exact native component actions and cloud execution extend the IPC wait', async () => {
  const { sidecarRequestTimeoutMs } = await import('file:///tmp/agistack-desktop-test-dist/electron/main/sidecarSupervisor.js');
  const management = action => ({ input: { mode: 'local', operation: { action } } });
  assert.equal(sidecarRequestTimeoutMs('computer_use_manage_v2', management('locked_use_install')), 310_000);
  assert.equal(sidecarRequestTimeoutMs('computer_use_manage_v2', management('locked_use_uninstall')), 310_000);
  for (const action of ['status', 'locked_use_probe', 'locked_use_install_extra', 'grant', 'audio_stop']) {
    assert.equal(sidecarRequestTimeoutMs('computer_use_manage_v2', management(action)), 30_000);
  }
  assert.equal(sidecarRequestTimeoutMs('other_command', management('locked_use_install')), 30_000);
  assert.equal(sidecarRequestTimeoutMs('computer_use_manage_v2', { input: { action: 'locked_use_install' } }), 30_000);
  assert.equal(sidecarRequestTimeoutMs('local_runtime_status', undefined, 12), 12);
  const now = 1_000_000;
  const call = { input: { action: 'call' }, request_deadline_ms: now + 315_000 };
  assert.equal(sidecarRequestTimeoutMs('computer_use_cloud_v2', call, 30_000, now), 320_000);
  assert.equal(sidecarRequestTimeoutMs('computer_use_cloud_v2', { ...call, request_deadline_ms: now + 90_000 }, 30_000, now), 95_000);
  assert.equal(sidecarRequestTimeoutMs('computer_use_cloud_v2', { ...call, request_deadline_ms: Number.MAX_SAFE_INTEGER }, 30_000, now), 321_000);
  assert.equal(sidecarRequestTimeoutMs('computer_use_cloud_v2', { input: { action: 'call' } }, 30_000, now), 321_000);
  assert.equal(sidecarRequestTimeoutMs('computer_use_cloud_v2', { ...call, input: { action: 'media' } }, 30_000, now), 30_000);
  assert.equal(sidecarRequestTimeoutMs('cloud_request', call, 30_000, now), 30_000);
});
