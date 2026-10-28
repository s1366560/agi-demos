import {
  WebContentsView,
  session,
  type BrowserWindow,
  type IpcMainInvokeEvent,
  type Session,
  type WebContents,
} from 'electron';
import { randomUUID } from 'node:crypto';
import {
  MCP_APP_GUEST_EVENT,
  MCP_APP_GUEST_METHODS,
  mcpAppGuestDocumentKey,
  type McpAppGuestActivation,
  type McpAppGuestConfig,
  type McpAppGuestHostEvent,
  type McpAppGuestIdentity,
  type McpAppGuestRect,
  type McpAppGuestMethod,
  type McpAppGuestRequest,
} from '../../src/features/chat/mcpAppGuestProtocol';

type Pending = {
  resolve(value: unknown): void;
  reject(error: Error): void;
  request: McpAppGuestRequest;
};
type Entry = {
  key: string;
  identity: McpAppGuestIdentity;
  config: McpAppGuestConfig;
  view: WebContentsView;
  parent: BrowserWindow;
  active: boolean;
  loaded: boolean;
  loading?: Promise<void>;
  started: boolean;
  ready: boolean;
  registered: boolean;
  sequence: number;
  documentFrames: Set<number>;
  pending: Map<string, Pending>;
};
type Options = {
  getWindow(): BrowserWindow | null;
  preload: string;
  entryUrl(): string;
  installProtocol(session: Session): void;
  retireMount(input: { tabId: string; frameName: string }): Promise<unknown>;
};

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('mcp_app_guest_input_invalid');
  return value as Record<string, unknown>;
}
function text(value: unknown, limit = 4096): string {
  if (typeof value !== 'string' || !value.length || value.length > limit)
    throw new Error('mcp_app_guest_input_invalid');
  return value;
}
function mountName(value: unknown): string {
  const name = text(value, 44);
  if (!/^mcpapp-[a-f0-9-]{36}$/u.test(name)) throw new Error('mcp_app_guest_mount_invalid');
  return name;
}
function requestId(value: unknown): string {
  const id = text(value, 36);
  if (!/^[a-f0-9-]{36}$/u.test(id)) throw new Error('mcp_app_guest_request_invalid');
  return id;
}
function configValue(input: unknown): McpAppGuestConfig {
  const config = object(input);
  const sandbox = object(config.sandbox);
  const url = new URL(text(sandbox.url));
  if (!['http:', 'https:', 'agistack:'].includes(url.protocol))
    throw new Error('mcp_app_guest_sandbox_invalid');
  text(config.toolName);
  if (JSON.stringify(config).length > 16_000_000) throw new Error('mcp_app_guest_config_too_large');
  return structuredClone(config) as McpAppGuestConfig;
}

/** One private, nonpersistent rendering surface for each visible/retained MCP App. */
export class McpAppGuestHost {
  readonly #entries = new Map<string, Entry>();
  readonly #cancelled = new Set<string>();

  constructor(private readonly options: Options) {}

  open(input: unknown): McpAppGuestIdentity {
    const value = object(input);
    const key = text(value.key);
    const frameName = mountName(value.frameName);
    const tabId = value.tabId === undefined ? undefined : mountName(value.tabId);
    if (this.#cancelled.has(frameName)) throw new Error('mcp_app_guest_mount_cancelled');
    const parent = this.options.getWindow();
    if (!parent || parent.isDestroyed()) throw new Error('mcp_app_guest_parent_unavailable');
    const config = configValue(value.config);
    let entry = this.#entries.get(key);
    if (
      entry &&
      (entry.parent !== parent ||
        entry.identity.tabId !== tabId ||
        entry.view.webContents.isDestroyed() ||
        mcpAppGuestDocumentKey(entry.config) !== mcpAppGuestDocumentKey(config))
    ) {
      this.destroy(entry);
      entry = undefined;
    }
    for (const current of this.#entries.values()) if (current.active) this.retire(current);
    if (!entry) {
      if (this.#entries.size >= 32) throw new Error('mcp_app_guests_busy');
      const guestId = randomUUID();
      const isolatedSession = session.fromPartition(`mcp-app-${guestId}`, { cache: false });
      isolatedSession.setPermissionRequestHandler((_contents, _permission, callback) =>
        callback(false),
      );
      isolatedSession.setPermissionCheckHandler(() => false);
      isolatedSession.setDevicePermissionHandler(() => false);
      isolatedSession.setDisplayMediaRequestHandler((_request, callback) => callback({}));
      isolatedSession.setBluetoothPairingHandler((_details, callback) =>
        callback({ confirmed: false }),
      );
      isolatedSession.on('will-download', (event) => event.preventDefault());
      this.options.installProtocol(isolatedSession);
      const view = new WebContentsView({
        webPreferences: {
          preload: this.options.preload,
          session: isolatedSession,
          sandbox: true,
          contextIsolation: true,
          nodeIntegration: false,
          nodeIntegrationInSubFrames: false,
          webSecurity: true,
          backgroundThrottling: false,
          spellcheck: false,
        },
      });
      view.setVisible(false);
      view.setBounds({ x: 0, y: 0, width: 1, height: 1 });
      view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      view.webContents.on('will-navigate', (event) => event.preventDefault());
      view.webContents.on('will-attach-webview', (event) => event.preventDefault());
      view.webContents.on('select-bluetooth-device', (event, _devices, callback) => {
        event.preventDefault();
        callback('');
      });
      entry = {
        key,
        identity: { guestId, frameName, ...(tabId ? { tabId } : {}) },
        config,
        view,
        parent,
        active: false,
        loaded: false,
        started: false,
        ready: false,
        registered: false,
        sequence: -1,
        documentFrames: new Set(),
        pending: new Map(),
      };
      const created = entry;
      view.webContents.on('did-start-navigation', (details) => {
        if (details.isSameDocument) return;
        if (
          (details.isMainFrame && created.loaded) ||
          (details.frame && created.documentFrames.has(details.frame.frameTreeNodeId))
        ) {
          this.send(created, {
            ...created.identity,
            kind: 'retired',
            reason: 'mcp_app_guest_document_changed',
          });
          this.destroy(created);
        }
      });
      view.webContents.once('render-process-gone', () => {
        this.send(created, {
          ...created.identity,
          kind: 'retired',
          reason: 'mcp_app_guest_renderer_unavailable',
        });
        this.destroy(created);
      });
      view.webContents.once('destroyed', () => this.destroy(created));
      this.#entries.set(key, entry);
    }
    entry.identity = { guestId: entry.identity.guestId, frameName, ...(tabId ? { tabId } : {}) };
    entry.config = config;
    entry.active = true;
    entry.started = false;
    entry.registered = false;
    entry.sequence = -1;
    return entry.identity;
  }

  async start(input: unknown): Promise<void> {
    const entry = this.current(input);
    if (entry.started) return;
    entry.started = true;
    const nonce = entry.identity.frameName;
    if (!entry.loaded) {
      entry.loading ??= entry.view.webContents.loadURL(this.options.entryUrl()).then(
        () => {
          entry.loaded = true;
        },
        (error) => {
          entry.loading = undefined;
          throw error;
        },
      );
      await entry.loading;
    }
    if (!entry.active || entry.identity.frameName !== nonce)
      throw new Error('mcp_app_guest_expired');
    entry.view.webContents.send(MCP_APP_GUEST_EVENT, {
      kind: 'activate',
      value: this.activation(entry),
    });
  }

  update(input: unknown): void {
    const value = object(input);
    const entry = this.current(value);
    const config = configValue(value.config);
    if (mcpAppGuestDocumentKey(config) !== mcpAppGuestDocumentKey(entry.config))
      throw new Error('mcp_app_guest_document_changed');
    entry.config = config;
    if (entry.loaded && entry.started)
      entry.view.webContents.send(MCP_APP_GUEST_EVENT, {
        kind: 'activate',
        value: this.activation(entry),
      });
  }

  registered(input: unknown): void {
    const entry = this.current(input);
    const host = entry.view.webContents.mainFrame;
    const outer = host.frames;
    if (outer.length !== 1 || outer[0].frames.length !== 1)
      throw new Error('mcp_app_guest_frame_invalid');
    entry.documentFrames = new Set([
      host.frameTreeNodeId,
      outer[0].frameTreeNodeId,
      outer[0].frames[0].frameTreeNodeId,
    ]);
    if (!entry.registered) {
      entry.registered = true;
      for (const pending of entry.pending.values()) this.send(entry, pending.request);
    }
  }

  ownsVisibleSurface(owner: WebContents): boolean {
    return [...this.#entries.values()].some(
      (entry) =>
        entry.active &&
        entry.started &&
        entry.view.webContents === owner &&
        !owner.isDestroyed() &&
        entry.parent === this.options.getWindow() &&
        !entry.parent.isDestroyed() &&
        entry.view.getVisible() &&
        entry.parent.contentView.children.includes(entry.view),
    );
  }

  /** Only root's authenticated register command can turn this owner into an automation mount. */
  owner(input: unknown): WebContents {
    const entry = this.current(input);
    if (!entry.started || !entry.ready || !entry.identity.tabId)
      throw new Error('mcp_app_guest_not_ready');
    return entry.view.webContents;
  }

  layout(input: unknown): void {
    const value = object(input);
    const entry = this.current(value);
    const sequence = value.sequence;
    if (!Number.isSafeInteger(sequence) || (sequence as number) <= entry.sequence) return;
    entry.sequence = sequence as number;
    if (value.bounds === null) {
      this.hide(entry);
      return;
    }
    const rect = object(value.bounds) as McpAppGuestRect;
    if (
      ![rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) ||
      rect.width <= 0 ||
      rect.height <= 0
    ) {
      this.hide(entry);
      return;
    }
    const zoom = entry.parent.webContents.getZoomFactor();
    const [width, height] = entry.parent.getContentSize();
    const x = Math.max(0, Math.ceil(rect.x * zoom));
    const y = Math.max(0, Math.ceil(rect.y * zoom));
    const right = Math.min(width, Math.floor((rect.x + rect.width) * zoom));
    const bottom = Math.min(height, Math.floor((rect.y + rect.height) * zoom));
    if (right <= x || bottom <= y) {
      this.hide(entry);
      return;
    }
    entry.view.webContents.setZoomFactor(zoom);
    entry.view.setBounds({ x, y, width: right - x, height: bottom - y });
    if (!entry.parent.contentView.children.includes(entry.view))
      entry.parent.contentView.addChildView(entry.view);
    entry.view.setVisible(true);
  }

  release(input: unknown): void {
    const value = object(input);
    const frameName = mountName(value.frameName);
    this.#cancelled.add(frameName);
    for (const entry of this.#entries.values())
      if (entry.identity.frameName === frameName) this.retire(entry);
  }

  prune(input: unknown): void {
    const value = object(input);
    if (!Array.isArray(value.keys) || value.keys.length > 32)
      throw new Error('mcp_app_guest_input_invalid');
    const keys = new Set(value.keys.map((key) => text(key)));
    for (const entry of this.#entries.values()) if (!keys.has(entry.key)) this.destroy(entry);
  }

  clear(): void {
    for (const entry of [...this.#entries.values()]) this.destroy(entry);
    // Keep nonce tombstones for this parent lifetime: delayed opens must not revive.
  }

  async receive(event: IpcMainInvokeEvent, command: unknown, input?: unknown): Promise<unknown> {
    const entry = [...this.#entries.values()].find(
      (candidate) => candidate.view.webContents === event.sender,
    );
    if (
      !entry ||
      !entry.active ||
      !entry.started ||
      event.senderFrame !== event.sender.mainFrame ||
      event.senderFrame.url !== this.options.entryUrl()
    )
      throw new Error('mcp_app_guest_sender_invalid');
    this.current(entry.identity);
    if (command === 'initialize') return this.activation(entry);
    const value = object(input);
    if (this.current(value) !== entry) throw new Error('mcp_app_guest_sender_invalid');
    if (command === 'ready') {
      entry.ready = true;
      return undefined;
    }
    const id = requestId(value.requestId);
    if (command === 'cancel') {
      this.cancel(entry, id);
      return undefined;
    }
    if (
      command !== 'request' ||
      !(MCP_APP_GUEST_METHODS as readonly unknown[]).includes(value.method)
    ) {
      throw new Error('mcp_app_guest_method_invalid');
    }
    if (entry.pending.size >= 32 || entry.pending.has(id))
      throw new Error('mcp_app_guest_requests_busy');
    if (JSON.stringify(value.params ?? null).length > 2_000_000)
      throw new Error('mcp_app_guest_request_too_large');
    return new Promise((resolve, reject) => {
      const request: McpAppGuestRequest = {
        ...entry.identity,
        kind: 'request',
        requestId: id,
        method: value.method as McpAppGuestMethod,
        params: value.params,
      };
      entry.pending.set(id, { resolve, reject, request });
      if (
        !entry.identity.tabId ||
        entry.registered ||
        request.method === 'error' ||
        request.method === 'sizeChanged'
      )
        this.send(entry, request);
    });
  }

  respond(input: unknown): void {
    const value = object(input);
    const entry = this.current(value);
    const id = requestId(value.requestId);
    const pending = entry.pending.get(id);
    if (!pending) throw new Error('mcp_app_guest_request_expired');
    entry.pending.delete(id);
    if (value.ok === true) pending.resolve(value.result);
    else
      pending.reject(
        new Error(
          typeof value.error === 'string'
            ? value.error.slice(0, 4096)
            : 'mcp_app_guest_request_failed',
        ),
      );
  }

  private activation(entry: Entry): McpAppGuestActivation {
    return { ...entry.identity, config: entry.config };
  }

  private current(input: unknown): Entry {
    const value = object(input);
    const entry = [...this.#entries.values()].find(
      (candidate) => candidate.identity.guestId === value.guestId,
    );
    if (
      !entry ||
      !entry.active ||
      entry.parent !== this.options.getWindow() ||
      entry.parent.isDestroyed() ||
      entry.view.webContents.isDestroyed() ||
      entry.identity.frameName !== value.frameName ||
      entry.identity.tabId !== value.tabId
    ) {
      throw new Error('mcp_app_guest_expired');
    }
    return entry;
  }

  private send(entry: Entry, event: McpAppGuestHostEvent): void {
    if (!entry.parent.isDestroyed()) entry.parent.webContents.send(MCP_APP_GUEST_EVENT, event);
  }

  private cancel(entry: Entry, id: string): void {
    const pending = entry.pending.get(id);
    if (!pending) return;
    entry.pending.delete(id);
    this.send(entry, { ...entry.identity, kind: 'cancel', requestId: id });
    pending.reject(new Error('mcp_app_guest_request_cancelled'));
  }

  private hide(entry: Entry): void {
    entry.view.setVisible(false);
    if (!entry.parent.isDestroyed() && entry.parent.contentView.children.includes(entry.view)) {
      entry.parent.contentView.removeChildView(entry.view);
    }
  }

  private retire(entry: Entry): void {
    if (!entry.active) return;
    entry.active = false;
    this.#cancelled.add(entry.identity.frameName);
    for (const id of [...entry.pending.keys()]) this.cancel(entry, id);
    this.hide(entry);
    if (!entry.view.webContents.isDestroyed()) {
      entry.view.webContents.send(MCP_APP_GUEST_EVENT, {
        kind: 'retire',
        frameName: entry.identity.frameName,
      });
    }
    if (entry.identity.tabId)
      void this.options
        .retireMount({
          tabId: entry.identity.tabId,
          frameName: entry.identity.frameName,
        })
        .catch(() => {});
  }

  private destroy(entry: Entry): void {
    if (this.#entries.get(entry.key) !== entry) return;
    this.#entries.delete(entry.key);
    this.retire(entry);
    if (!entry.view.webContents.isDestroyed()) entry.view.webContents.close();
  }
}
