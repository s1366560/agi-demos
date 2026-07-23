import {
  createHmac,
  randomBytes,
  randomUUID,
  timingSafeEqual,
} from 'node:crypto';
import {
  spawn,
  type ChildProcessWithoutNullStreams,
} from 'node:child_process';
import { createInterface } from 'node:readline';

const SIDECAR_PROTOCOL_VERSION = 1;
const DEFAULT_HANDSHAKE_TIMEOUT_MS = 15_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
const DEFAULT_RESTART_DELAYS_MS = [250, 1_000, 4_000, 10_000] as const;
const DEFAULT_RESTART_STABILITY_MS = 60_000;

type SidecarReady = {
  type: 'ready';
  protocolVersion: number;
  nonce: string;
  pid: number;
  apiBaseUrl: string;
  apiToken: string;
  proof: string;
};

type SidecarResponse = {
  type: 'response';
  id: string;
  ok: boolean;
  result?: unknown;
  error?: string;
};

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timeout: NodeJS.Timeout;
};

export type SidecarSupervisorOptions = {
  binaryPath: string;
  dataDirectory: string;
  workspaceRoot: string;
  legacyDataDirectories: readonly string[];
  environment?: Readonly<Record<string, string>>;
  handshakeTimeoutMs?: number;
  requestTimeoutMs?: number;
  restartDelaysMs?: readonly number[];
  restartStabilityMs?: number;
  onRecovered?: () => void;
};

export type SidecarRuntimeIdentity = {
  pid: number;
  apiBaseUrl: string;
  apiToken: string;
};

/**
 * Owns the private stdio control channel to the Rust local-runtime sidecar.
 *
 * The bootstrap secret is written exactly once through stdin, authenticated by
 * an HMAC in the readiness response, and never appears in argv or the child
 * environment. Subsequent messages remain confined to the inherited pipes.
 */
export class SidecarSupervisor {
  readonly #options: SidecarSupervisorOptions;
  readonly #pending = new Map<string, PendingRequest>();
  #child: ChildProcessWithoutNullStreams | null = null;
  #identity: SidecarRuntimeIdentity | null = null;
  #starting: Promise<SidecarRuntimeIdentity> | null = null;
  #restartTimer: NodeJS.Timeout | null = null;
  #restartDelay: Promise<void> | null = null;
  #resolveRestartDelay: (() => void) | null = null;
  #restartStabilityTimer: NodeJS.Timeout | null = null;
  #restartAttempt = 0;
  #shouldRun = false;
  #hasBeenReady = false;

  constructor(options: SidecarSupervisorOptions) {
    this.#options = options;
  }

  get identity(): SidecarRuntimeIdentity | null {
    return this.#identity ? { ...this.#identity } : null;
  }

  async start(): Promise<SidecarRuntimeIdentity> {
    this.#shouldRun = true;
    if (this.#restartDelay) await this.#restartDelay;
    if (!this.#shouldRun) throw new Error('sidecar stopped');
    if (this.#identity) return { ...this.#identity };
    if (this.#starting) return this.#starting;
    const starting = this.#launch();
    this.#starting = starting;
    try {
      return await starting;
    } finally {
      if (this.#starting === starting) this.#starting = null;
    }
  }

  async invoke<T = unknown>(
    command: string,
    args?: Record<string, unknown>,
  ): Promise<T> {
    await this.start();
    const child = this.#child;
    if (!child || !this.#identity) {
      throw new Error('sidecar is unavailable');
    }
    const id = randomUUID();
    return new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`sidecar request timed out: ${command}`));
      }, this.#options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS);
      this.#pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        timeout,
      });
      child.stdin.write(
        `${JSON.stringify({ type: 'request', id, command, args })}\n`,
        (error) => {
          if (!error) return;
          const pending = this.#pending.get(id);
          if (!pending) return;
          clearTimeout(pending.timeout);
          this.#pending.delete(id);
          pending.reject(new Error(`failed to send sidecar request: ${error.message}`));
        },
      );
    });
  }

  async stop(): Promise<void> {
    this.#shouldRun = false;
    this.#cancelRestartDelay();
    this.#clearRestartStabilityTimer();
    const child = this.#child;
    this.#child = null;
    this.#identity = null;
    this.#rejectPending(new Error('sidecar stopped'));
    if (!child || child.exitCode !== null) return;

    await new Promise<void>((resolve) => {
      const killTimer = setTimeout(() => {
        child.kill('SIGKILL');
      }, 2_000);
      child.once('exit', () => {
        clearTimeout(killTimer);
        resolve();
      });
      child.stdin.end();
      child.kill('SIGTERM');
    });
  }

  async #launch(): Promise<SidecarRuntimeIdentity> {
    const secretBytes = randomBytes(32);
    const secret = secretBytes.toString('base64url');
    const nonce = randomBytes(32).toString('base64url');
    const child = spawn(this.#options.binaryPath, [], {
      env: {
        ...process.env,
        ...this.#options.environment,
      },
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    // The sidecar writes diagnostics to stderr. Drain the private pipe without
    // forwarding potentially sensitive runtime details to Electron logs.
    child.stderr.resume();
    this.#child = child;

    return new Promise<SidecarRuntimeIdentity>((resolve, reject) => {
      let settled = false;
      const handshakeTimeout = setTimeout(() => {
        fail(new Error('sidecar handshake timed out'));
      }, this.#options.handshakeTimeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT_MS);
      const output = createInterface({ input: child.stdout, crlfDelay: Infinity });

      const fail = (error: Error): void => {
        if (settled) return;
        settled = true;
        clearTimeout(handshakeTimeout);
        secretBytes.fill(0);
        output.close();
        if (child.exitCode === null) child.kill('SIGKILL');
        if (this.#child === child) this.#child = null;
        reject(error);
      };

      output.on('line', (line) => {
        let message: unknown;
        try {
          message = JSON.parse(line);
        } catch {
          fail(new Error('sidecar emitted invalid control JSON'));
          return;
        }
        if (!settled) {
          try {
            const ready = requireReadyMessage(message);
            verifyReadyMessage(ready, secretBytes, nonce);
            settled = true;
            clearTimeout(handshakeTimeout);
            secretBytes.fill(0);
            this.#identity = {
              pid: ready.pid,
              apiBaseUrl: ready.apiBaseUrl,
              apiToken: ready.apiToken,
            };
            const recovered = this.#hasBeenReady;
            this.#hasBeenReady = true;
            this.#armRestartStabilityReset(child);
            resolve({ ...this.#identity });
            if (recovered) {
              queueMicrotask(() => {
                try {
                  this.#options.onRecovered?.();
                } catch {
                  // Recovery notification failures must not restart a healthy sidecar.
                }
              });
            }
          } catch (error) {
            fail(error instanceof Error ? error : new Error('sidecar handshake failed'));
          }
          return;
        }
        this.#handleResponse(message);
      });

      child.once('error', (error) => {
        fail(new Error(`failed to launch sidecar: ${error.message}`));
      });
      child.once('exit', (code, signal) => {
        const wasReady = this.#identity !== null;
        if (!settled) {
          fail(
            new Error(
              `sidecar exited during handshake (${formatExitReason(code, signal)})`,
            ),
          );
          return;
        }
        if (this.#child === child) this.#child = null;
        this.#identity = null;
        this.#clearRestartStabilityTimer();
        this.#rejectPending(
          new Error(`sidecar exited unexpectedly (${formatExitReason(code, signal)})`),
        );
        if (wasReady && this.#shouldRun) this.#scheduleRestart();
      });

      child.stdin.write(
        `${JSON.stringify({
          type: 'initialize',
          protocolVersion: SIDECAR_PROTOCOL_VERSION,
          nonce,
          secret,
          dataDirectory: this.#options.dataDirectory,
          workspaceRoot: this.#options.workspaceRoot,
          legacyDataDirectories: this.#options.legacyDataDirectories,
        })}\n`,
        (error) => {
          if (error) fail(new Error(`failed to initialize sidecar: ${error.message}`));
        },
      );
    });
  }

  #handleResponse(message: unknown): void {
    if (!isSidecarResponse(message)) return;
    const pending = this.#pending.get(message.id);
    if (!pending) return;
    clearTimeout(pending.timeout);
    this.#pending.delete(message.id);
    if (message.ok) {
      pending.resolve(message.result);
    } else {
      pending.reject(new Error(message.error || 'sidecar request failed'));
    }
  }

  #rejectPending(error: Error): void {
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.#pending.clear();
  }

  #scheduleRestart(): void {
    if (this.#restartDelay || this.#starting || !this.#shouldRun) return;
    const delays =
      this.#options.restartDelaysMs?.length
        ? this.#options.restartDelaysMs
        : DEFAULT_RESTART_DELAYS_MS;
    const delay = delays[Math.min(this.#restartAttempt, delays.length - 1)] ?? 10_000;
    this.#restartAttempt += 1;
    this.#restartDelay = new Promise<void>((resolve) => {
      this.#resolveRestartDelay = resolve;
    });
    this.#restartTimer = setTimeout(() => {
      this.#restartTimer = null;
      const resolveRestartDelay = this.#resolveRestartDelay;
      this.#resolveRestartDelay = null;
      this.#restartDelay = null;
      resolveRestartDelay?.();
      void this.start().catch(() => {
        if (this.#shouldRun) this.#scheduleRestart();
      });
    }, delay);
  }

  #cancelRestartDelay(): void {
    if (this.#restartTimer) clearTimeout(this.#restartTimer);
    this.#restartTimer = null;
    const resolveRestartDelay = this.#resolveRestartDelay;
    this.#resolveRestartDelay = null;
    this.#restartDelay = null;
    resolveRestartDelay?.();
  }

  #armRestartStabilityReset(child: ChildProcessWithoutNullStreams): void {
    this.#clearRestartStabilityTimer();
    const stabilityMs =
      this.#options.restartStabilityMs ?? DEFAULT_RESTART_STABILITY_MS;
    this.#restartStabilityTimer = setTimeout(() => {
      this.#restartStabilityTimer = null;
      if (this.#child === child && this.#identity) this.#restartAttempt = 0;
    }, stabilityMs);
    this.#restartStabilityTimer.unref();
  }

  #clearRestartStabilityTimer(): void {
    if (this.#restartStabilityTimer) clearTimeout(this.#restartStabilityTimer);
    this.#restartStabilityTimer = null;
  }
}

function requireReadyMessage(value: unknown): SidecarReady {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('sidecar readiness response is invalid');
  }
  const message = value as Record<string, unknown>;
  if (
    message.type !== 'ready' ||
    message.protocolVersion !== SIDECAR_PROTOCOL_VERSION ||
    typeof message.nonce !== 'string' ||
    typeof message.pid !== 'number' ||
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
  return message as SidecarReady;
}

function verifyReadyMessage(
  ready: SidecarReady,
  secret: Buffer,
  expectedNonce: string,
): void {
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
  const expected = createHmac('sha256', secret).update(message).digest();
  let received: Buffer;
  try {
    received = Buffer.from(ready.proof, 'base64url');
  } catch {
    throw new Error('sidecar handshake proof is invalid');
  }
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) {
    throw new Error('sidecar handshake proof is invalid');
  }
}

function isSidecarResponse(value: unknown): value is SidecarResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const response = value as Record<string, unknown>;
  return (
    response.type === 'response' &&
    typeof response.id === 'string' &&
    typeof response.ok === 'boolean' &&
    (response.error === undefined || typeof response.error === 'string')
  );
}

function formatExitReason(code: number | null, signal: NodeJS.Signals | null): string {
  if (signal) return `signal ${signal}`;
  return `code ${code ?? 'unknown'}`;
}
