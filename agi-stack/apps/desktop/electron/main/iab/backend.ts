/**
 * iab bridge backend (Electron main process).
 *
 * Reads the sidecar's browser-bridge registry
 * (`~/.memstack/browser-bridge/registry.json`), connects to the bridge
 * WebSocket — preferring the advertised unix socket, TCP otherwise — and
 * serves the sidecar → backend JSON-RPC contract over the view pool:
 * `hello` / `ping` / `attach` / `detach` / `executeCdp` / `getTabs` /
 * `createTab` / `closeTab` / `focusTab` / `ensureTabGroup` / `assignTab` /
 * `ungroupTab` / `moveMouse` / `turnEnded`. CDP events and debugger detaches
 * are forwarded upstream as `onCDPEvent` / `onCDPDetach` notifications.
 *
 * Reconnects forever with the same capped backoff as the Rust broker
 * (`sidecar/src/native_host.rs`: 250ms / 1s / 4s / 10s), re-reading the
 * registry on every attempt because the sidecar rewrites it on every bridge
 * start.
 */

import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';

import { connectIabBridgeSocket, type IabBridgeSocket } from './bridgeSocket';
import {
  iabBridgeBackoffDelayMs,
  parseIabBridgeRegistry,
  pickIabBridgeTransport,
} from './iabRegistry';
import {
  IAB_NOTIFY_ON_CDP_DETACH,
  IAB_NOTIFY_ON_CDP_EVENT,
  IabInvalidParamsError,
  buildIabHelloResult,
  createIabRpcRouter,
  encodeIabNotification,
  optionalIabString,
  parseIabTurnEndedLeases,
  requireIabCoordinate,
  requireIabParamsRecord,
  requireIabString,
  requireIabTabId,
} from './iabMessageRouter';
import type { IabViewPool } from './viewPool';
import { browserCaller, browserSurface } from './iabOwnership';

export type IabBackendStatus = 'disabled' | 'connecting' | 'connected';

export type IabBackendOptions = Readonly<{
  pool: IabViewPool;
  registryPath?: string;
  /** Test seam (same pattern as SidecarSupervisor.restartDelaysMs). */
  retryDelaysMs?: readonly number[];
  /** Test seam for deterministic connect and stop races. */
  connectBridgeSocket?: typeof connectIabBridgeSocket;
  log?: (message: string) => void;
  executeMcpApp?: (input: unknown) => Promise<unknown>;
  /** Fires on every failed connect attempt, before the backoff sleep. */
  onRetry?: (failures: number, error: string) => void;
}>;

/** Offline log throttling: log the first failure, then every Nth. */
const LOG_EVERY_NTH_FAILURE = 12;

export function defaultIabRegistryPath(): string {
  return join(homedir(), '.memstack', 'browser-bridge', 'registry.json');
}

export class IabBackend {
  readonly #options: IabBackendOptions;
  readonly #router: ReturnType<typeof createIabRpcRouter>;
  #shouldRun = false;
  #running = false;
  #socket: IabBridgeSocket | null = null;
  #status: IabBackendStatus = 'disabled';
  #pendingSleep: { timer: NodeJS.Timeout; wake: () => void } | null = null;

  constructor(options: IabBackendOptions) {
    this.#options = options;
    this.#router = createIabRpcRouter(this.#buildHandlers());
  }

  get status(): IabBackendStatus {
    return this.#status;
  }

  /** Called by the pool when a debugger session emits a CDP event. */
  notifyCdpEvent(tabId: number, method: string, params: unknown, sessionId?: string): void {
    this.#sendNotification(IAB_NOTIFY_ON_CDP_EVENT, { tabId, method, params: params ?? null, ...(sessionId ? { sessionId } : {}) });
  }

  /** Called by the pool when a debugger session detaches. */
  notifyCdpDetach(tabId: number, reason: string): void {
    this.#sendNotification(IAB_NOTIFY_ON_CDP_DETACH, { tabId, reason });
  }

  start(): void {
    if (this.#shouldRun) return;
    this.#shouldRun = true;
    if (!this.#running) void this.#runLoop();
  }

  async stop(): Promise<void> {
    this.#shouldRun = false;
    const pendingSleep = this.#pendingSleep;
    if (pendingSleep) {
      this.#pendingSleep = null;
      clearTimeout(pendingSleep.timer);
      pendingSleep.wake();
    }
    const socket = this.#socket;
    this.#socket = null;
    socket?.close();
    this.#status = 'disabled';
    this.#options.pool.releaseBridge?.();
  }

  #sendNotification(method: string, params: unknown): void {
    try {
      this.#socket?.send(encodeIabNotification(method, params));
    } catch {
      // Notifications are best-effort; the next reconnect resyncs state.
    }
  }

  #retryDelayMs(failures: number): number {
    const delays = this.#options.retryDelaysMs;
    if (delays && delays.length > 0) {
      return delays[Math.min(Math.max(failures, 0), delays.length - 1)] ?? 10_000;
    }
    return iabBridgeBackoffDelayMs(failures);
  }

  /** Backoff sleep that `stop()` can cut short (SidecarSupervisor pattern). */
  #sleep(ms: number): Promise<void> {
    return new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        this.#pendingSleep = null;
        resolve();
      }, ms);
      this.#pendingSleep = { timer, wake: resolve };
    });
  }

  async #runLoop(): Promise<void> {
    this.#running = true;
    let failures = 0;
    try {
      while (this.#shouldRun) {
        const registryPath = this.#options.registryPath ?? defaultIabRegistryPath();
        try {
          const registry = parseIabBridgeRegistry(
            JSON.parse(await readFile(registryPath, 'utf8')),
          );
          const transport = pickIabBridgeTransport(
            registry,
            registry.socketPath !== null && existsSync(registry.socketPath),
          );
          this.#status = 'connecting';
          // `activeSocket` is the TDZ-safe handle for the onClose closure:
          // referencing the `const socket` binding below from a callback that
          // can fire before `await connect…` returns would throw a
          // ReferenceError inside the socket's 'close' emit — uncaught, and
          // Electron answers uncaught main-process exceptions with a modal
          // dialog that parks the whole process. (bridgeSocket also gates
          // onClose on handshake completion; both layers stay.)
          let activeSocket: IabBridgeSocket | null = null;
          let signalClosed: (reason: string) => void = () => undefined;
          const closed = new Promise<string>((resolve) => {
            signalClosed = resolve;
          });
          const connectBridgeSocket =
            this.#options.connectBridgeSocket ?? connectIabBridgeSocket;
          const socket = await connectBridgeSocket(transport, registry.token, {
            onMessage: (text) => void this.#handleMessage(text),
            onClose: (reason) => {
              if (this.#socket === activeSocket) this.#options.pool.releaseBridge?.();
              if (activeSocket !== null && this.#socket === activeSocket) {
                this.#socket = null;
              }
              if (this.#shouldRun) this.#status = 'connecting';
              signalClosed(reason);
            },
          });
          if (!this.#shouldRun) {
            socket.close();
            break;
          }
          activeSocket = socket;
          this.#socket = socket;
          this.#status = 'connected';
          if (failures > 0) {
            this.#log(`iab bridge connected after ${failures} failed attempt(s)`);
          }
          failures = 0;
          // Serve this socket until it closes (or stop() tears it down).
          await closed;
        } catch (error) {
          if (!this.#shouldRun) break;
          const message = error instanceof Error ? error.message : String(error);
          // Throttled offline logging: first failure, then every Nth — a
          // down bridge must not spam the main-process log forever.
          if (failures === 0 || (failures + 1) % LOG_EVERY_NTH_FAILURE === 0) {
            this.#log(`iab bridge connect failed: ${message}`);
          }
          try {
            this.#options.onRetry?.(failures + 1, message);
          } catch {
            // Retry observers must not break the reconnect loop.
          }
          const delay = this.#retryDelayMs(failures);
          failures += 1;
          await this.#sleep(delay);
        }
      }
    } finally {
      this.#running = false;
      this.#status = 'disabled';
    }
  }

  async #handleMessage(text: string): Promise<void> {
    const response = await this.#router(text);
    if (response === null) return;
    try {
      this.#socket?.send(response);
    } catch {
      // A dropped response is retried by the sidecar's own timeout.
    }
  }

  #buildHandlers(): Record<string, (params: unknown) => unknown | Promise<unknown>> {
    const pool = this.#options.pool;
    const handlers: Record<string, (params: unknown) => unknown | Promise<unknown>> = {
      hello: () => buildIabHelloResult(),
      ping: () => ({}),
      mcpAppsExecute: (params) => {
        if (!this.#options.executeMcpApp) throw new Error('mcp_app_frame_unavailable');
        return this.#options.executeMcpApp(params);
      },
      attach: (params) => {
        const tabId = requireIabTabId(requireIabParamsRecord(params, 'attach'), 'attach');
        pool.attachDebugger(tabId);
        return {};
      },
      detach: (params) => {
        const tabId = requireIabTabId(requireIabParamsRecord(params, 'detach'), 'detach');
        pool.detachDebugger(tabId);
        return {};
      },
      executeCdp: async (params) => {
        const record = requireIabParamsRecord(params, 'executeCdp');
        const tabId = requireIabTabId(record, 'executeCdp');
        const method = requireIabString(record, 'method', 'executeCdp', { maxLength: 256 });
        const sessionId = optionalIabString(record, 'sessionId', 'executeCdp', { maxLength: 256 }) ?? undefined;
        const result = await pool.executeCdp(tabId, method, record.params, sessionId);
        return { result: result === undefined ? null : result };
      },
      getTabs: params => ({ tabs: pool.scopedTabs(browserCaller(params), browserSurface(params)) }),
      getUserTabs: params => ({ tabs: pool.scopedTabs(browserCaller(params), browserSurface(params), true) }),
      claimUserTab: params => {
        const tabId = requireIabTabId(requireIabParamsRecord(params, 'claimUserTab'), 'claimUserTab');
        pool.ownership.claim(tabId, browserCaller(params), browserSurface(params));
        return { tabId };
      },
      markTab: params => {
        const record = requireIabParamsRecord(params, 'markTab');
        if (record.mark !== 'handoff' && record.mark !== 'deliverable') throw new IabInvalidParamsError('invalid tab mark');
        pool.ownership.mark(requireIabTabId(record, 'markTab'), browserCaller(params), browserSurface(params), record.mark);
        return {};
      },
      facadeCapabilities: () => ({ browser: ['visibility', 'viewport'], tab: ['cdp', 'pageAssets', 'webmcp'] }),
      browserPresentation: async (params) => {
        const record = requireIabParamsRecord(params, 'browserPresentation');
        const args = Array.isArray(record.args) ? record.args : [];
        switch (record.operation) {
          case 'capability.visibility.get': return pool.browserVisible;
          case 'capability.visibility.set': {
            if (typeof args[0] !== 'boolean') throw new IabInvalidParamsError('visibility requires a boolean');
            await pool.setBrowserVisible(args[0]); return null;
          }
          case 'capability.viewport.set': {
            const size = requireIabParamsRecord(args[0], 'viewport.set');
            await pool.setScopedViewport(browserCaller(params), browserSurface(params), { width: Number(size.width), height: Number(size.height) }); return null;
          }
          case 'capability.viewport.reset': await pool.setScopedViewport(browserCaller(params), browserSurface(params), null); return null;
          default: throw new IabInvalidParamsError('unsupported browser presentation operation');
        }
      },
      createTab: async (params) => {
        const record = params === undefined || params === null ? {} : requireIabParamsRecord(params, 'createTab');
        const url = optionalIabString(record, 'url', 'createTab');
        const tabId = await pool.createTab(url, browserCaller(params), browserSurface(params));
        return { tabId };
      },
      closeTab: (params) => {
        const tabId = requireIabTabId(requireIabParamsRecord(params, 'closeTab'), 'closeTab');
        pool.closeTab(tabId);
        return {};
      },
      focusTab: (params) => {
        const tabId = requireIabTabId(requireIabParamsRecord(params, 'focusTab'), 'focusTab');
        pool.focusTab(tabId);
        return {};
      },
      ensureTabGroup: (params) => {
        const record = requireIabParamsRecord(params, 'ensureTabGroup');
        const key = requireIabString(record, 'key', 'ensureTabGroup', { maxLength: 256 });
        return { groupId: pool.registry.ensureTabGroup(key) };
      },
      nameSession: (params) => {
        const record = requireIabParamsRecord(params, 'nameSession');
        const key = requireIabString(record, 'key', 'nameSession', { maxLength: 256 });
        const title = requireIabString(record, 'title', 'nameSession', { maxLength: 256 });
        pool.registry.nameSession(key, title);
        return {};
      },
      assignTab: (params) => {
        const record = requireIabParamsRecord(params, 'assignTab');
        const tabId = requireIabTabId(record, 'assignTab');
        const groupId = record.groupId;
        if (typeof groupId !== 'number' || !Number.isSafeInteger(groupId) || groupId <= 0) {
          throw new IabInvalidParamsError('assignTab requires a positive integer groupId');
        }
        pool.registry.assignTab(tabId, groupId);
        return {};
      },
      ungroupTab: (params) => {
        const tabId = requireIabTabId(requireIabParamsRecord(params, 'ungroupTab'), 'ungroupTab');
        pool.registry.ungroupTab(tabId);
        return {};
      },
      moveMouse: async (params) => {
        const record = requireIabParamsRecord(params, 'moveMouse');
        const tabId = requireIabTabId(record, 'moveMouse');
        const x = requireIabCoordinate(record, 'x', 'moveMouse');
        const y = requireIabCoordinate(record, 'y', 'moveMouse');
        const waitForArrival = record.waitForArrival === true;
        try {
          const webContents = pool.webContentsFor(tabId);
          await pool.cursor.moveMouse(tabId, webContents, x, y, waitForArrival);
        } catch {
          // moveMouse always succeeds: the cursor can never block actions.
        }
        return {};
      },
      turnEnded: (params) => {
        const record = requireIabParamsRecord(params, 'turnEnded');
        return typeof record.turnId === 'string' ? pool.releaseTurn(record.turnId) : pool.turnEnded(parseIabTurnEndedLeases(params));
      },
    };
    // Every operation entering native browser state is scoped by the trusted host.
    // The main process UI has its own authenticated IPC path and can take control.
    return Object.fromEntries(Object.entries(handlers).map(([method, handler]) => [method, async (params: unknown) => {
      if (['hello', 'ping', 'mcpAppsExecute', 'turnEnded'].includes(method)) return handler(params);
      const caller = browserCaller(params);
      const surface = browserSurface(params);
      pool.ownership.observe(caller, surface);
      const record = requireIabParamsRecord(params, method);
      if (typeof record.tabId === 'number') pool.ownership.claim(record.tabId, caller, surface);
      return handler(params);
    }]));
  }

  #log(message: string): void {
    try {
      this.#options.log?.(message);
    } catch {
      // Logging must never break the reconnect loop.
    }
  }
}
