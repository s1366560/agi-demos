// Sidecar audit harness: spawns the real agistack-desktop-sidecar through the
// same SidecarSupervisor path used by tests/real-sidecar-integration.test.mjs,
// then performs the HMAC-secured handshake and opens an authenticated local
// session. No secrets are logged.
import { mkdtemp, mkdir, createWriteStream } from 'node:fs';
import { mkdtemp as mkdtempAsync, mkdir as mkdirAsync } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { SidecarSupervisor } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/sidecarSupervisor.js',
);

export const REPO_ROOT = resolve('/Users/tiejunsun/github/agi-demos');
export const SIDECAR_BIN =
  process.env.AGISTACK_REAL_SIDECAR ??
  join(REPO_ROOT, 'agi-stack/target/debug/agistack-desktop-sidecar');
export const WORKSPACE_CORE_BIN =
  process.env.AGISTACK_REAL_WORKSPACE_CORE ??
  join(REPO_ROOT, '.cache/avernet-bcs/target/debug/memstack-workspace-core');

export class SidecarHarness {
  constructor({ logPath } = {}) {
    this.supervisor = null;
    this.identity = null;
    this.session = null; // { accessToken, context: {tenant_id, project_id}, sessionId }
    this.root = null;
    this.logStream = logPath ? createWriteStream(logPath, { flags: 'a' }) : null;
  }

  log(line) {
    const stamped = `[${new Date().toISOString()}] ${line}`;
    this.logStream?.write(`${stamped}\n`);
  }

  async start() {
    this.root = await mkdtempAsync(join(tmpdir(), 'desktop-audit-'));
    const dataDirectory = join(this.root, 'data');
    const workspaceRoot = join(this.root, 'workspace');
    await mkdirAsync(workspaceRoot, { recursive: true });
    this.supervisor = new SidecarSupervisor({
      binaryPath: resolve(SIDECAR_BIN),
      workspaceCoreBinaryPath: resolve(WORKSPACE_CORE_BIN),
      dataDirectory,
      workspaceRoot,
      legacyDataDirectories: [],
      handshakeTimeoutMs: 30_000,
      requestTimeoutMs: 60_000,
    });
    this.identity = await this.supervisor.start();
    this.log(`sidecar ready at ${this.identity.apiBaseUrl} (pid ${this.identity.pid})`);
    return this.identity;
  }

  async stop() {
    try {
      await this.supervisor?.stop();
    } finally {
      this.logStream?.end();
    }
  }

  async invoke(command, args) {
    return this.supervisor.invoke(command, args);
  }

  /** Raw HTTP against the local runtime. Returns {status, json|text}. */
  async rawFetch(path, { method = 'GET', body, token, headers = {} } = {}) {
    const auth = token ?? this.session?.accessToken ?? this.identity.apiToken;
    const res = await fetch(`${this.identity.apiBaseUrl}${path}`, {
      method,
      headers: {
        authorization: `Bearer ${auth}`,
        'x-agistack-launch': this.identity.apiToken,
        ...(body !== undefined ? { 'content-type': 'application/json' } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let json = null;
    try {
      json = JSON.parse(text);
    } catch {
      /* non-JSON */
    }
    return { status: res.status, json, text };
  }

  /** HTTP helper that throws on non-2xx. */
  async http(path, options = {}) {
    const { status, json, text } = await this.rawFetch(path, options);
    if (status < 200 || status >= 300) {
      throw new Error(
        `${options.method ?? 'GET'} ${path} -> ${status}: ${text.slice(0, 500)}`,
      );
    }
    return json;
  }

  /** Create the authenticated local session (launch capability -> user session). */
  async createSession() {
    const { status, json, text } = await this.rawFetch('/api/v1/auth/local-session', {
      method: 'POST',
      body: { trusted_device: false },
      token: this.identity.apiToken,
    });
    if (status !== 200 && status !== 201) {
      throw new Error(`local-session failed: ${status} ${text.slice(0, 300)}`);
    }
    this.session = {
      accessToken: json.access_token,
      context: json.context,
      sessionId: json.session?.session_id,
    };
    this.log(
      `session created: tenant=${this.session.context.tenant_id} project=${this.session.context.project_id}`,
    );
    return this.session;
  }

  /** Open the agent websocket with the session credential subprotocol. */
  async openAgentWs() {
    const wsUrl = `${this.identity.apiBaseUrl.replace(/^http/, 'ws')}/api/v1/agent/ws`;
    const ws = new WebSocket(wsUrl, [
      'memstack.launch',
      this.identity.apiToken,
      'memstack.auth',
      this.session.accessToken,
    ]);
    const events = [];
    const waiters = [];
    ws.addEventListener('message', (event) => {
      let value = event.data;
      try {
        value = JSON.parse(event.data);
      } catch {
        /* keep raw */
      }
      events.push(value);
      this.log(`ws<= ${typeof value === 'string' ? value : JSON.stringify(value)}`);
      for (let i = waiters.length - 1; i >= 0; i -= 1) {
        if (waiters[i].predicate(value)) {
          clearTimeout(waiters[i].timer);
          waiters[i].resolve(value);
          waiters.splice(i, 1);
        }
      }
    });
    await new Promise((resolvePromise, rejectPromise) => {
      ws.addEventListener('open', resolvePromise, { once: true });
      ws.addEventListener('error', rejectPromise, { once: true });
    });
    const waitFor = (predicate, timeoutMs = 60_000, label = 'event') =>
      new Promise((resolvePromise, rejectPromise) => {
        const existing = events.find(predicate);
        if (existing) {
          resolvePromise(existing);
          return;
        }
        const timer = setTimeout(() => {
          const index = waiters.findIndex((w) => w.timer === timer);
          if (index >= 0) waiters.splice(index, 1);
          rejectPromise(
            new Error(
              `timed out waiting for ${label}; seen: ${events
                .map((e) => (typeof e === 'string' ? e : e?.type ?? JSON.stringify(e)))
                .join(', ')}`,
            ),
          );
        }, timeoutMs);
        waiters.push({ predicate, resolve: resolvePromise, timer });
      });
    return { ws, events, waitFor };
  }
}

export function summarizeEvent(event) {
  if (typeof event === 'string') return event;
  if (!event || typeof event !== 'object') return String(event);
  const type = event.type ?? 'unknown';
  const extra = event.tool_name ?? event.name ?? event.skill_id ?? event.code ?? '';
  return extra ? `${type}(${extra})` : type;
}
