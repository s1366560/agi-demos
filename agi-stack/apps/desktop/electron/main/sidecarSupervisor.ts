import { createHmac, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createInterface } from 'node:readline';

import {
  PLUGIN_DATA_PLANE_ACK_PARTICIPATION_ENV_V2,
  PLUGIN_DATA_PLANE_API_BASE_URL_ENV_V2,
  PLUGIN_DATA_PLANE_CREDENTIAL_ENV_V2,
  PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_ENV_V2,
  PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_ENV_V2,
  PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_ENV_V2,
} from './platformPluginDataPlaneCredentialPolicy';
import type { LocalKnowledgeAcceptanceRequest } from './qaProfilePolicy';
import { parseComputerUseInput, type ComputerUseInput } from '../../src/api/computerUseInput';

const SIDECAR_PROTOCOL_VERSION = 1;
const DEFAULT_HANDSHAKE_TIMEOUT_MS = 15_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
const NATIVE_COMPONENT_INSTALL_TIMEOUT_MS = 310_000;
const MAX_CLOUD_EXECUTION_TIMEOUT_MS = 321_000;

/** Waiting limits do not grant authority; the sidecar still claims the server request. */
export function sidecarRequestTimeoutMs(
  command: string,
  args?: Record<string, unknown>,
  configuredTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  now = Date.now(),
): number {
  const input = args?.input;
  if (!input || typeof input !== 'object' || Array.isArray(input)) return configuredTimeoutMs;
  const value = input as Record<string, unknown>;
  if (command === 'computer_use_manage_v2') {
    const operation = value.operation;
    if (operation && typeof operation === 'object' && !Array.isArray(operation)) {
      const action = (operation as Record<string, unknown>).action;
      if (action === 'locked_use_install' || action === 'locked_use_uninstall') {
        return Math.max(configuredTimeoutMs, NATIVE_COMPONENT_INSTALL_TIMEOUT_MS);
      }
    }
  }
  if (command === 'computer_use_cloud_v2' && value.action === 'call') {
    const deadline = args?.request_deadline_ms;
    const remaining = typeof deadline === 'number' && Number.isSafeInteger(deadline)
      ? Math.max(1, deadline - now + 5_000)
      : MAX_CLOUD_EXECUTION_TIMEOUT_MS;
    return Math.max(configuredTimeoutMs, Math.min(MAX_CLOUD_EXECUTION_TIMEOUT_MS, remaining));
  }
  return configuredTimeoutMs;
}

const DEFAULT_RESTART_DELAYS_MS = [250, 1_000, 4_000, 10_000] as const;
const DEFAULT_RESTART_STABILITY_MS = 60_000;
const DEFAULT_MAX_RESTART_ATTEMPTS = 4;
const DEFAULT_SHUTDOWN_TIMEOUT_MS = 40_000;

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
  cleanup: () => void;
};

type BrowserBridgeConfiguration = Readonly<{
  enabled: boolean;
  port: number;
  extension_ids: readonly string[];
  full_cdp_access_enabled: boolean;
  cdp_endpoints: readonly Readonly<{ id: string; name: string; endpoint: string; enabled: boolean }>[];
  default_browser_id: string;
}>;

export type SidecarSupervisorOptions = {
  binaryPath: string;
  dataDirectory: string;
  workspaceRoot: string;
  localKnowledgeAcceptance?: LocalKnowledgeAcceptanceRequest;
  workspaceCoreBinaryPath: string;
  legacyDataDirectories: readonly string[];
  environment?: Readonly<Record<string, string>>;
  handshakeTimeoutMs?: number;
  requestTimeoutMs?: number;
  restartDelaysMs?: readonly number[];
  restartStabilityMs?: number;
  maxRestartAttempts?: number;
  shutdownTimeoutMs?: number;
  onRecovered?: () => void;
  onComputerUseInput?: (input: ComputerUseInput) => void;
  onComputerUseInputDisconnected?: () => void;
};

export function sidecarRendererEnvironment(
  developmentUrl: URL | null,
): Readonly<Record<string, string>> {
  return Object.freeze({
    AGISTACK_DESKTOP_RENDERER_ORIGIN: developmentUrl?.origin ?? '',
  });
}

export function sidecarChildEnvironment(
  inherited: NodeJS.ProcessEnv,
  configured?: Readonly<Record<string, string>>,
): NodeJS.ProcessEnv {
  const environment = {
    ...inherited,
    ...configured,
  };
  delete environment[PLUGIN_DATA_PLANE_CREDENTIAL_ENV_V2];
  delete environment[PLUGIN_DATA_PLANE_API_BASE_URL_ENV_V2];
  delete environment[PLUGIN_DATA_PLANE_ACK_PARTICIPATION_ENV_V2];
  delete environment[PLUGIN_RENDERER_DATA_PLANE_CREDENTIAL_ENV_V2];
  delete environment[PLUGIN_RENDERER_DATA_PLANE_API_BASE_URL_ENV_V2];
  delete environment[PLUGIN_RENDERER_DATA_PLANE_ACK_PARTICIPATION_ENV_V2];
  return environment;
}

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
  #restartExhausted = false;
  #shouldRun = false;
  #hasBeenReady = false;
  #stopRevision = 0;
  #configurationTail: Promise<void> = Promise.resolve();
  #bridgeConfiguration: BrowserBridgeConfiguration | null = null;
  #bridgeConfigurationRevision = 0;

  constructor(options: SidecarSupervisorOptions) {
    this.#options = options;
  }

  get identity(): SidecarRuntimeIdentity | null {
    return this.#identity && !this.#starting ? { ...this.#identity } : null;
  }

  async start(): Promise<SidecarRuntimeIdentity> {
    this.#shouldRun = true;
    if (this.#restartDelay) await this.#restartDelay;
    if (!this.#shouldRun) throw new Error('sidecar stopped');
    if (this.#restartExhausted) throw new Error('sidecar restart budget exhausted');
    if (this.#starting) return this.#starting;
    if (this.#identity) return { ...this.#identity };
    const starting = this.#launch();
    this.#starting = starting;
    try {
      return await starting;
    } finally {
      if (this.#starting === starting) this.#starting = null;
    }
  }

  async invoke<T = unknown>(command: string, args?: Record<string, unknown>): Promise<T> {
    const stopRevision = this.#stopRevision;
    if (command !== 'local_runtime_configure') {
      return this.#invokeReady<T>(command, args, stopRevision);
    }
    const request = args === undefined ? undefined : structuredClone(args);
    const config = request?.config;
    const changesBridge = isRecord(config) && Object.hasOwn(config, 'browser_bridge');
    const revision = changesBridge ? ++this.#bridgeConfigurationRevision : null;
    // An unacknowledged disable must never leave an older enable eligible for replay.
    if (changesBridge) this.#bridgeConfiguration = null;
    const task = this.#configurationTail.then(() =>
      this.#invokeReady<T>(command, request, stopRevision, (result) => {
        if (revision === this.#bridgeConfigurationRevision) {
          const requested = isRecord(config) ? browserBridgeConfiguration(config.browser_bridge) : null;
          const confirmed = configuredBrowserBridge(result);
          if (requested && confirmed && sameBrowserBridge(requested, confirmed)) {
            this.#bridgeConfiguration = confirmed;
          }
        }
      }),
    );
    this.#configurationTail = task.then(() => undefined, () => undefined);
    return task;
  }

  /** Only a verified App callback may wait on human approval beyond the IPC budget. */
  async invokeCancellable<T = unknown>(
    command: string,
    args: Record<string, unknown>,
    signal: AbortSignal,
  ): Promise<T> {
    if (signal.aborted) throw new DOMException('MCP App request cancelled', 'AbortError');
    if (command !== 'mcp_app_operation' || args.operation !== 'tools/call' ||
        typeof args.tabId !== 'string' || typeof args.mountNonce !== 'string') {
      throw new Error('sidecar cancellable request is not an App callback');
    }
    const stopRevision = this.#stopRevision;
    const request = structuredClone(args);
    await waitForSignal(this.start(), signal);
    const child = this.#child;
    if (signal.aborted) throw new DOMException('MCP App request cancelled', 'AbortError');
    if (stopRevision !== this.#stopRevision || !child || !this.#identity) {
      throw new Error('sidecar stopped');
    }
    const result = await this.#request<T>(child, command, request, signal);
    if (this.#child !== child || stopRevision !== this.#stopRevision) {
      throw new Error('sidecar response belongs to a retired process');
    }
    return result;
  }

  async #invokeReady<T>(
    command: string,
    args: Record<string, unknown> | undefined,
    stopRevision: number,
    onAccepted?: (result: T) => void,
  ): Promise<T> {
    if (stopRevision !== this.#stopRevision) throw new Error('sidecar stopped');
    await this.start();
    const child = this.#child;
    if (stopRevision !== this.#stopRevision || !child || !this.#identity) {
      throw new Error('sidecar is unavailable');
    }
    const result = await this.#request<T>(child, command, args);
    if (this.#child !== child || stopRevision !== this.#stopRevision) {
      throw new Error('sidecar response belongs to a retired process');
    }
    onAccepted?.(result);
    return result;
  }

  #request<T = unknown>(
    child: ChildProcessWithoutNullStreams,
    command: string,
    args?: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<T> {
    const id = randomUUID();
    return new Promise<T>((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException('MCP App request cancelled', 'AbortError'));
        return;
      }
      const abort = (): void => {
        const pending = this.#pending.get(id);
        if (!pending) return;
        this.#pending.delete(id);
        pending.cleanup();
        const cancelled = (confirmed: boolean): void => reject(Object.assign(
          new DOMException('MCP App request cancelled', 'AbortError'),
          { cancellationConfirmed: confirmed },
        ));
        if (this.#child === child && this.#identity && child.stdin.writable) {
          // The transport id never crosses renderer IPC. Cancellation uses this
          // same private pipe and cannot start or address a replacement process.
          // Ignore the original response while aborting: it can precede the
          // cancellation acknowledgement that proves the waiter was dropped.
          void this.#request<{ cancelled?: boolean }>(child, 'mcp_app_operation_cancel', {
            requestId: id, tabId: args?.tabId, mountNonce: args?.mountNonce,
          }).then((ack) => cancelled(ack?.cancelled === true), () => cancelled(false));
        } else cancelled(false);
      };
      const timeout = signal ? null : setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`sidecar request timed out: ${command}`));
      }, sidecarRequestTimeoutMs(command, args, this.#options.requestTimeoutMs));
      this.#pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        cleanup: () => {
          if (timeout) clearTimeout(timeout);
          signal?.removeEventListener('abort', abort);
        },
      });
      signal?.addEventListener('abort', abort, { once: true });
      child.stdin.write(`${JSON.stringify({ type: 'request', id, command, args })}\n`, (error) => {
        if (!error) return;
        const pending = this.#pending.get(id);
        if (!pending) return;
        pending.cleanup();
        this.#pending.delete(id);
        pending.reject(new Error(`failed to send sidecar request: ${error.message}`));
      });
    });
  }

  async #restoreBrowserBridge(child: ChildProcessWithoutNullStreams): Promise<void> {
    const previous = this.#bridgeConfiguration;
    if (!previous) return;
    for (;;) {
      if (this.#child !== child || !this.#shouldRun) throw new Error('sidecar stopped');
      const revision = this.#bridgeConfigurationRevision;
      // A newer pending user change fences an in-flight restore before readiness is exposed.
      const config = this.#bridgeConfiguration ?? {
        ...previous, enabled: false, full_cdp_access_enabled: false,
      };
      const result = await this.#request(child, 'local_runtime_configure', {
        config: { browser_bridge: config },
      });
      const confirmed = configuredBrowserBridge(result);
      if (this.#child !== child || !this.#shouldRun) throw new Error('sidecar stopped');
      if (!confirmed || !sameBrowserBridge(config, confirmed)) {
        throw new Error('sidecar browser bridge recovery was not confirmed');
      }
      if (revision === this.#bridgeConfigurationRevision) return;
    }
  }

  async stop(): Promise<void> {
    this.#stopRevision += 1;
    this.#shouldRun = false;
    this.#restartAttempt = 0;
    this.#restartExhausted = false;
    this.#cancelRestartDelay();
    this.#clearRestartStabilityTimer();
    const child = this.#child;
    this.#child = null;
    this.#identity = null;
    this.#clearComputerUseInput();
    this.#rejectPending(new Error('sidecar stopped'));
    if (!child || child.exitCode !== null) return;

    await new Promise<void>((resolve) => {
      const shutdownTimeoutMs = Math.max(
        1,
        this.#options.shutdownTimeoutMs ?? DEFAULT_SHUTDOWN_TIMEOUT_MS,
      );
      let settled = false;
      let killTimer: NodeJS.Timeout;
      const finish = (): void => {
        if (settled) return;
        settled = true;
        clearTimeout(killTimer);
        resolve();
      };
      killTimer = setTimeout(() => {
        child.kill('SIGKILL');
      }, shutdownTimeoutMs);
      child.once('exit', finish);
      child.stdin.once('error', () => {
        if (child.exitCode === null) child.kill('SIGKILL');
      });
      child.stdin.end();
    });
  }

  async #launch(): Promise<SidecarRuntimeIdentity> {
    const secretBytes = randomBytes(32);
    const secret = secretBytes.toString('base64url');
    const nonce = randomBytes(32).toString('base64url');
    const child = spawn(this.#options.binaryPath, [], {
      env: sidecarChildEnvironment(process.env, this.#options.environment),
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
    });
    // The sidecar writes diagnostics to stderr. Drain the private pipe without
    // forwarding potentially sensitive runtime details to Electron logs.
    child.stderr.resume();
    this.#child = child;

    return new Promise<SidecarRuntimeIdentity>((resolve, reject) => {
      let settled = false;
      let authenticated = false;
      const handshakeTimeout = setTimeout(() => {
        fail(new Error('sidecar handshake timed out'));
      }, this.#options.handshakeTimeoutMs ?? DEFAULT_HANDSHAKE_TIMEOUT_MS);
      const output = createInterface({
        input: child.stdout,
        crlfDelay: Infinity,
      });

      const fail = (error: Error): void => {
        if (settled) return;
        settled = true;
        clearTimeout(handshakeTimeout);
        secretBytes.fill(0);
        output.close();
        if (child.exitCode === null) child.kill('SIGKILL');
        if (this.#child === child) {
          this.#child = null;
          this.#identity = null;
          this.#rejectPending(error);
        }
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
        if (!authenticated) {
          try {
            const ready = requireReadyMessage(message);
            verifyReadyMessage(ready, secretBytes, nonce);
            if (this.#child !== child || !this.#shouldRun) throw new Error('sidecar stopped');
            authenticated = true;
            clearTimeout(handshakeTimeout);
            secretBytes.fill(0);
            this.#identity = {
              pid: ready.pid,
              apiBaseUrl: ready.apiBaseUrl,
              apiToken: ready.apiToken,
            };
            void this.#restoreBrowserBridge(child).then(() => {
              if (this.#child !== child || !this.#identity || !this.#shouldRun) {
                throw new Error('sidecar stopped');
              }
              settled = true;
              const recovered = this.#hasBeenReady;
              this.#hasBeenReady = true;
              this.#armRestartStabilityReset(child);
              resolve({ ...this.#identity });
              if (recovered) {
                queueMicrotask(() => {
                  try { this.#options.onRecovered?.(); }
                  catch { /* Recovery notifications cannot restart a healthy sidecar. */ }
                });
              }
            }).catch((error) => fail(error instanceof Error ? error : new Error('sidecar recovery failed')));
          } catch (error) {
            fail(error instanceof Error ? error : new Error('sidecar handshake failed'));
          }
          return;
        }
        if (this.#child !== child || !this.#identity) return;
        if (message && typeof message === 'object' &&
          (message as { type?: unknown }).type === 'computer_use_input') {
          const input = parseComputerUseInput((message as { input?: unknown }).input);
          if (input) {
            try { this.#options.onComputerUseInput?.(input); }
            catch { /* Telemetry consumers cannot interrupt control response delivery. */ }
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
          fail(new Error(`sidecar exited during handshake (${formatExitReason(code, signal)})`));
          return;
        }
        if (this.#child !== child) return;
        this.#child = null;
        this.#identity = null;
        this.#clearComputerUseInput();
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
          localKnowledgeAcceptance: this.#options.localKnowledgeAcceptance,
          workspaceCoreBinaryPath: this.#options.workspaceCoreBinaryPath,
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
    pending.cleanup();
    this.#pending.delete(message.id);
    if (message.ok) {
      pending.resolve(message.result);
    } else {
      pending.reject(new Error(message.error || 'sidecar request failed'));
    }
  }

  #clearComputerUseInput(): void {
    try { this.#options.onComputerUseInputDisconnected?.(); }
    catch { /* Input decoration must not prevent sidecar shutdown or recovery. */ }
  }

  #rejectPending(error: Error): void {
    for (const pending of this.#pending.values()) {
      pending.cleanup();
      pending.reject(error);
    }
    this.#pending.clear();
  }

  #scheduleRestart(): void {
    if (this.#restartDelay || this.#starting || !this.#shouldRun) return;
    const maxRestartAttempts = Math.max(
      0,
      this.#options.maxRestartAttempts ?? DEFAULT_MAX_RESTART_ATTEMPTS,
    );
    if (this.#restartAttempt >= maxRestartAttempts) {
      this.#restartExhausted = true;
      return;
    }
    const delays = this.#options.restartDelaysMs?.length
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
    const stabilityMs = this.#options.restartStabilityMs ?? DEFAULT_RESTART_STABILITY_MS;
    this.#restartStabilityTimer = setTimeout(() => {
      this.#restartStabilityTimer = null;
      if (this.#child === child && this.#identity) {
        this.#restartAttempt = 0;
        this.#restartExhausted = false;
      }
    }, stabilityMs);
    this.#restartStabilityTimer.unref();
  }

  #clearRestartStabilityTimer(): void {
    if (this.#restartStabilityTimer) clearTimeout(this.#restartStabilityTimer);
    this.#restartStabilityTimer = null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function waitForSignal<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = (): void => reject(new DOMException('MCP App request cancelled', 'AbortError'));
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
    void promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort));
  });
}

function browserBridgeConfiguration(value: unknown): BrowserBridgeConfiguration | null {
  if (!isRecord(value) || typeof value.enabled !== 'boolean' ||
      typeof value.port !== 'number' || !Number.isSafeInteger(value.port) ||
      value.port < 0 || value.port > 65535 || !Array.isArray(value.extension_ids) ||
      !value.extension_ids.every((id): id is string => typeof id === 'string') ||
      typeof value.full_cdp_access_enabled !== 'boolean') return null;
  const endpoints = value.cdp_endpoints ?? [];
  const defaultBrowser = value.default_browser_id ?? 'iab';
  if (!Array.isArray(endpoints) || !endpoints.every(endpoint => isRecord(endpoint) &&
      ['id', 'name', 'endpoint'].every(key => typeof endpoint[key] === 'string' && endpoint[key]) &&
      typeof endpoint.enabled === 'boolean') || typeof defaultBrowser !== 'string' || !defaultBrowser) return null;
  return Object.freeze({
    enabled: value.enabled,
    port: value.port,
    extension_ids: Object.freeze([...value.extension_ids]),
    full_cdp_access_enabled: value.full_cdp_access_enabled,
    cdp_endpoints: Object.freeze(endpoints.map(endpoint => Object.freeze({
      id: endpoint.id as string, name: endpoint.name as string, endpoint: endpoint.endpoint as string,
      enabled: endpoint.enabled as boolean,
    }))),
    default_browser_id: defaultBrowser,
  });
}

function configuredBrowserBridge(value: unknown): BrowserBridgeConfiguration | null {
  return isRecord(value) && isRecord(value.config)
    ? browserBridgeConfiguration(value.config.browser_bridge) : null;
}

function sameBrowserBridge(left: BrowserBridgeConfiguration, right: BrowserBridgeConfiguration): boolean {
  return left.enabled === right.enabled && left.port === right.port &&
    left.full_cdp_access_enabled === right.full_cdp_access_enabled &&
    left.default_browser_id === right.default_browser_id &&
    left.cdp_endpoints.length === right.cdp_endpoints.length &&
    left.cdp_endpoints.every((endpoint, index) => {
      const other = right.cdp_endpoints[index];
      return endpoint.id === other.id && endpoint.name === other.name &&
        endpoint.endpoint === other.endpoint && endpoint.enabled === other.enabled;
    }) &&
    left.extension_ids.length === right.extension_ids.length &&
    left.extension_ids.every((id, index) => id === right.extension_ids[index]);
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

function verifyReadyMessage(ready: SidecarReady, secret: Buffer, expectedNonce: string): void {
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
