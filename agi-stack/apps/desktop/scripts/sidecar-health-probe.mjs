import { spawn } from 'node:child_process';
import { createHmac, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { constants } from 'node:fs';
import { access, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

export const SIDECAR_PROBE_PROTOCOL_VERSION = 1;
const DEFAULT_HANDSHAKE_TIMEOUT_MS = 90_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
const DEFAULT_EXIT_TIMEOUT_MS = 30_000;

/**
 * Minimal environment for a probed sidecar. Mirrors the recovery-helper
 * environment in smoke-update-recovery.mjs: the probe must not inherit grant
 * credentials, tokens, or CI secrets, so only the variables the runtime needs
 * are forwarded.
 */
export function sidecarProbeEnvironment(env = process.env, platform = process.platform) {
  const probeEnvironment = { PATH: env.PATH ?? '' };
  if (platform === 'win32') {
    probeEnvironment.SystemRoot = env.SystemRoot ?? '';
    probeEnvironment.ComSpec = env.ComSpec ?? '';
  }
  return probeEnvironment;
}

function withTimeout(promise, timeoutMs, label) {
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function* lineIterator(stream) {
  const reader = createInterface({ input: stream, crlfDelay: Infinity });
  try {
    for await (const line of reader) {
      yield line;
    }
  } finally {
    reader.close();
  }
}

async function nextJsonLine(iterator, timeoutMs, label) {
  const next = await withTimeout(iterator.next(), timeoutMs, label);
  if (next.done) {
    throw new Error(`${label} failed: sidecar closed the control channel`);
  }
  try {
    return JSON.parse(next.value);
  } catch {
    throw new Error(`${label} failed: sidecar emitted invalid control JSON`);
  }
}

function requireReadyMessage(message) {
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    throw new Error('sidecar readiness response is invalid');
  }
  if (
    message.type !== 'ready' ||
    message.protocolVersion !== SIDECAR_PROBE_PROTOCOL_VERSION ||
    typeof message.nonce !== 'string' ||
    !Number.isSafeInteger(message.pid) ||
    message.pid <= 0 ||
    typeof message.apiBaseUrl !== 'string' ||
    !/^http:\/\/127\.0\.0\.1:\d+$/u.test(message.apiBaseUrl) ||
    typeof message.apiToken !== 'string' ||
    message.apiToken.length < 8 ||
    typeof message.proof !== 'string'
  ) {
    throw new Error('sidecar readiness response is invalid');
  }
  return message;
}

function verifyReadyProof(ready, secretBytes, expectedNonce) {
  if (ready.nonce !== expectedNonce) {
    throw new Error('sidecar handshake nonce is invalid');
  }
  const message = [
    ready.protocolVersion,
    ready.nonce,
    ready.pid,
    ready.apiBaseUrl,
    ready.apiToken,
  ].join('\n');
  const expected = createHmac('sha256', secretBytes).update(message).digest();
  const received = Buffer.from(ready.proof, 'base64url');
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) {
    throw new Error('sidecar handshake proof is invalid');
  }
}

function awaitChildExit(child, exitTimeoutMs) {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child.exitCode, signal: child.signalCode });
  }
  return withTimeout(
    new Promise((resolveExit) => {
      child.once('exit', (code, signal) => resolveExit({ code, signal }));
    }),
    exitTimeoutMs,
    'sidecar exit',
  );
}

/**
 * Drive the real sidecar initialize/ready handshake against a packaged binary,
 * verify the HMAC readiness proof and nonce, round-trip a
 * `local_runtime_status` health request, then close stdin and require a clean
 * exit. The returned evidence never contains the nonce, secret, proof, or
 * runtime API token.
 */
export async function probeSidecarHealth({
  sidecarPath,
  workspaceCorePath,
  spawnImpl = spawn,
  rootDirectory,
  handshakeTimeoutMs = DEFAULT_HANDSHAKE_TIMEOUT_MS,
  requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  exitTimeoutMs = DEFAULT_EXIT_TIMEOUT_MS,
}) {
  const sidecar = resolve(sidecarPath);
  const workspaceCore = resolve(workspaceCorePath);
  await access(sidecar, constants.X_OK);
  await access(workspaceCore, constants.X_OK);

  const ownedRoot = rootDirectory === undefined;
  const root = rootDirectory ?? (await mkdtemp(join(tmpdir(), 'agistack-sidecar-probe-')));
  const dataDirectory = join(root, 'data');
  const workspaceRoot = join(root, 'workspace');
  await mkdir(workspaceRoot, { recursive: true });

  const secretBytes = randomBytes(32);
  const nonce = randomBytes(32).toString('base64url');
  const child = spawnImpl(sidecar, [], {
    env: sidecarProbeEnvironment(),
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });
  const spawnError = new Promise((_, reject) => {
    child.once('error', (error) =>
      reject(new Error(`packaged sidecar failed to spawn: ${error.message}`)),
    );
  });
  // Drain the private diagnostics pipe without forwarding runtime details.
  child.stderr.resume();

  const finish = async (work) => {
    try {
      return await Promise.race([work, spawnError]);
    } finally {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
      secretBytes.fill(0);
      if (ownedRoot) await rm(root, { recursive: true, force: true });
    }
  };

  return finish(
    (async () => {
      const lines = lineIterator(child.stdout);
      child.stdin.write(
        `${JSON.stringify({
          type: 'initialize',
          protocolVersion: SIDECAR_PROBE_PROTOCOL_VERSION,
          nonce,
          secret: secretBytes.toString('base64url'),
          dataDirectory,
          workspaceRoot,
          workspaceCoreBinaryPath: workspaceCore,
          legacyDataDirectories: [],
        })}\n`,
      );
      const ready = requireReadyMessage(
        await nextJsonLine(lines, handshakeTimeoutMs, 'sidecar handshake'),
      );
      verifyReadyProof(ready, secretBytes, nonce);

      const requestId = randomUUID();
      child.stdin.write(
        `${JSON.stringify({ type: 'request', id: requestId, command: 'local_runtime_status' })}\n`,
      );
      const response = await nextJsonLine(lines, requestTimeoutMs, 'sidecar health request');
      if (
        !response ||
        response.type !== 'response' ||
        response.id !== requestId ||
        response.ok !== true
      ) {
        throw new Error('sidecar local_runtime_status health check failed');
      }

      child.stdin.end();
      const exit = await awaitChildExit(child, exitTimeoutMs);
      if (exit.code !== 0 || exit.signal !== null) {
        throw new Error(
          `packaged sidecar did not exit cleanly (code ${exit.code ?? 'unknown'}, ` +
            `signal ${exit.signal ?? 'none'})`,
        );
      }
      return Object.freeze({
        handshake: 'initialize_hmac_proof_verified',
        protocol_version: SIDECAR_PROBE_PROTOCOL_VERSION,
        sidecar_pid: ready.pid,
        api_bind_host: '127.0.0.1',
        local_runtime_status: 'ok',
        clean_exit: true,
      });
    })(),
  );
}

async function main() {
  const [, , sidecarPath, workspaceCorePath] = process.argv;
  if (!sidecarPath || !workspaceCorePath) {
    throw new Error(
      'usage: node scripts/sidecar-health-probe.mjs <sidecar-binary> <workspace-core-binary>',
    );
  }
  const evidence = await probeSidecarHealth({ sidecarPath, workspaceCorePath });
  process.stdout.write(
    `SIDECAR_HEALTH_PROBE_OK pid=${evidence.sidecar_pid} ` +
      `handshake=${evidence.handshake} status=${evidence.local_runtime_status}\n`,
  );
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main();
}
