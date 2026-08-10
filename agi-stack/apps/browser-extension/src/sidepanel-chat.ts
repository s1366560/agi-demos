import type { ChromeApi } from './chrome-api';
import type { NativeTransport } from './transport';

/**
 * Side panel chat (SW half). All HTTP/WS traffic to the sidecar's agent API
 * lives here in the service worker — host_permissions <all_urls> makes the SW
 * CORS-exempt, while the side panel page stays a dumb UI proxied over
 * chrome.runtime messages (`sidepanel.*` methods).
 *
 * Session bootstrap: the broker answers the SW-initiated native request
 * `getSidePanelSession {}` with `{apiBaseUrl, launchCapability, credential}`.
 * The session is cached in chrome.storage.session and re-minted on HTTP 401.
 */

export const SIDE_PANEL_SESSION_KEY = 'memstackSidePanelSession';
export const GET_SIDE_PANEL_SESSION_METHOD = 'getSidePanelSession';
export const SIDE_PANEL_SOURCE = 'memstack.sidepanel';

export interface SidePanelSession {
  apiBaseUrl: string;
  launchCapability: string;
  credential: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
}

export type PanelTimelineEntry =
  | { kind: 'text'; id: string; role: string; text: string; timestamp: number | null }
  | { kind: 'desktop-required'; id: string; summary: string };

export interface PanelSocketEvent {
  source: typeof SIDE_PANEL_SOURCE;
  type: 'timeline' | 'ack' | 'status';
  conversationId?: string;
  item?: PanelTimelineEntry;
  action?: string;
  messageId?: string;
  connected?: boolean;
}

/** Minimal structural view of the WebSocket this module drives. */
export interface ChatWebSocket {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number; reason?: string }) => void) | null;
  onerror: (() => void) | null;
}

export interface ChatFetchResponse {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}

export type ChatFetch = (
  url: string,
  init: { method: string; headers: Record<string, string>; body?: string },
) => Promise<ChatFetchResponse>;

export interface SidePanelChatDeps {
  chrome: ChromeApi;
  transport: NativeTransport;
  fetchFn?: ChatFetch;
  createSocket?: (url: string, protocols: string[]) => ChatWebSocket;
  randomId?: () => string;
  /** Delay before re-dialing the agent socket while subscriptions are live. */
  reconnectDelayMs?: number;
}

export interface SidePanelChat {
  handlePanelRequest(message: unknown): Promise<unknown>;
}

const DEFAULT_RECONNECT_DELAY_MS = 2_000;
const HITL_TYPE_PATTERN = /hitl|approval|clarification|decision|permission|env_var/i;

let fallbackItemCounter = 0;

function parseSession(raw: unknown): SidePanelSession {
  if (typeof raw !== 'object' || raw === null) {
    throw new Error('getSidePanelSession returned a non-object payload');
  }
  const o = raw as Record<string, unknown>;
  if (typeof o.apiBaseUrl !== 'string' || o.apiBaseUrl.length === 0) {
    throw new Error('getSidePanelSession: apiBaseUrl must be a non-empty string');
  }
  if (typeof o.launchCapability !== 'string' || o.launchCapability.length === 0) {
    throw new Error('getSidePanelSession: launchCapability must be a non-empty string');
  }
  if (typeof o.credential !== 'string' || o.credential.length === 0) {
    throw new Error('getSidePanelSession: credential must be a non-empty string');
  }
  return { apiBaseUrl: o.apiBaseUrl, launchCapability: o.launchCapability, credential: o.credential };
}

function readArray(payload: unknown, keys: string[]): unknown[] {
  if (Array.isArray(payload)) return payload;
  if (typeof payload === 'object' && payload !== null) {
    for (const key of keys) {
      const value = (payload as Record<string, unknown>)[key];
      if (Array.isArray(value)) return value;
    }
  }
  return [];
}

function normalizeConversation(raw: unknown): ConversationSummary | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const o = raw as Record<string, unknown>;
  const id =
    typeof o.id === 'string' ? o.id : typeof o.conversation_id === 'string' ? o.conversation_id : null;
  if (!id) return null;
  const title = typeof o.title === 'string' && o.title.length > 0 ? o.title : 'Untitled conversation';
  return { id, title };
}

/** Map one server timeline item onto the panel's reduced entry model. */
export function normalizeTimelineItem(raw: unknown): PanelTimelineEntry | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const o = raw as Record<string, unknown>;
  const id = typeof o.id === 'string' && o.id.length > 0 ? o.id : `item-${++fallbackItemCounter}`;
  const type = typeof o.type === 'string' ? o.type : '';
  if (HITL_TYPE_PATTERN.test(type)) {
    const summary =
      typeof o.question === 'string' && o.question.length > 0
        ? o.question
        : typeof o.description === 'string' && o.description.length > 0
          ? o.description
          : typeof o.content === 'string' && o.content.length > 0
            ? o.content
            : 'This step needs your input';
    return { kind: 'desktop-required', id, summary };
  }
  const content = typeof o.content === 'string' ? o.content : null;
  if (content && content.trim().length > 0) {
    const role =
      typeof o.role === 'string' && o.role.length > 0
        ? o.role
        : /user/i.test(type)
          ? 'user'
          : 'assistant';
    const timestamp = typeof o.timestamp === 'number' ? o.timestamp : null;
    return { kind: 'text', id, role, text: content, timestamp };
  }
  return null; // tool calls and other non-text items are not rendered in the panel
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function readString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function requireStringParam(params: unknown, name: string): string {
  const value = isRecord(params) ? readString(params[name]) : null;
  if (!value) throw new Error(`params.${name} must be a non-empty string`);
  return value;
}

function optionalStringParam(params: unknown, name: string): string | undefined {
  if (!isRecord(params)) return undefined;
  const value = params[name];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string') throw new Error(`params.${name} must be a string`);
  return value;
}

export function createSidePanelChat(deps: SidePanelChatDeps): SidePanelChat {
  const { chrome, transport } = deps;
  const fetchFn: ChatFetch =
    deps.fetchFn ?? ((globalThis.fetch as unknown as ChatFetch | undefined) ?? missingFetch());
  const createSocket =
    deps.createSocket ??
    ((url, protocols) => new WebSocket(url, protocols) as unknown as ChatWebSocket);
  const randomId = deps.randomId ?? (() => crypto.randomUUID());
  const reconnectDelayMs = deps.reconnectDelayMs ?? DEFAULT_RECONNECT_DELAY_MS;

  let cachedSession: SidePanelSession | null = null;
  let minting: Promise<SidePanelSession> | null = null;
  let socket: ChatWebSocket | null = null;
  let socketOpen = false;
  let connecting: Promise<void> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  const subscriptions = new Set<string>();

  function missingFetch(): never {
    throw new Error('fetch is not available in this context');
  }

  function broadcast(event: PanelSocketEvent): void {
    void Promise.resolve(chrome.runtime.sendMessage(event)).catch(() => {
      /* no side panel listening */
    });
  }

  async function mintSession(): Promise<SidePanelSession> {
    if (minting) return minting;
    minting = (async () => {
      const session = parseSession(
        await transport.sendRequest(GET_SIDE_PANEL_SESSION_METHOD, {}),
      );
      cachedSession = session;
      await chrome.storage.session?.set({ [SIDE_PANEL_SESSION_KEY]: session });
      return session;
    })().finally(() => {
      minting = null;
    });
    return minting;
  }

  async function getSession(): Promise<SidePanelSession> {
    if (cachedSession) return cachedSession;
    const store = chrome.storage.session;
    if (store) {
      const items = await store.get(SIDE_PANEL_SESSION_KEY);
      const raw = items[SIDE_PANEL_SESSION_KEY];
      if (raw !== undefined) {
        try {
          cachedSession = parseSession(raw);
          return cachedSession;
        } catch {
          await store.remove(SIDE_PANEL_SESSION_KEY); // stale/corrupt cache entry
        }
      }
    }
    return mintSession();
  }

  async function invalidateSession(): Promise<void> {
    cachedSession = null;
    await chrome.storage.session?.remove(SIDE_PANEL_SESSION_KEY);
  }

  function apiUrl(session: SidePanelSession, path: string): string {
    return `${session.apiBaseUrl.replace(/\/+$/, '')}${path}`;
  }

  async function apiFetch(
    path: string,
    init: { method?: string; body?: unknown } = {},
    allowRemint = true,
  ): Promise<unknown> {
    const session = await getSession();
    const method = init.method ?? 'GET';
    const headers: Record<string, string> = {
      Accept: 'application/json',
      Authorization: `Bearer ${session.credential}`,
      'X-Agistack-Launch': session.launchCapability,
    };
    if (init.body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetchFn(apiUrl(session, path), {
      method,
      headers,
      body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
    if (response.status === 401 && allowRemint) {
      await invalidateSession(); // credential expired: re-mint once and retry
      return apiFetch(path, init, false);
    }
    if (!response.ok) {
      throw new Error(`agent api ${method} ${path} failed with status ${response.status}`);
    }
    return response.json();
  }

  async function listConversations(): Promise<ConversationSummary[]> {
    const payload = await apiFetch('/api/v1/agent/conversations');
    return readArray(payload, ['items', 'conversations', 'data'])
      .map(normalizeConversation)
      .filter((c): c is ConversationSummary => c !== null);
  }

  async function createConversation(title?: string, projectId?: string): Promise<ConversationSummary> {
    const payload = await apiFetch('/api/v1/agent/conversations', {
      method: 'POST',
      body: {
        title: title?.trim() || 'Side panel chat',
        ...(projectId ? { project_id: projectId } : {}),
      },
    });
    const conversation = normalizeConversation(payload);
    if (!conversation) throw new Error('create conversation returned an unrecognized payload');
    return conversation;
  }

  async function getHistory(conversationId: string): Promise<PanelTimelineEntry[]> {
    const payload = await apiFetch(
      `/api/v1/agent/conversations/${encodeURIComponent(conversationId)}/messages`,
    );
    return readArray(payload, ['timeline', 'items', 'messages', 'data'])
      .map(normalizeTimelineItem)
      .filter((entry): entry is PanelTimelineEntry => entry !== null);
  }

  function wsUrl(session: SidePanelSession): string {
    const base = session.apiBaseUrl.replace(/^http/, 'ws').replace(/\/+$/, '');
    return `${base}/api/v1/agent/ws`;
  }

  function scheduleReconnect(): void {
    if (reconnectTimer !== null || subscriptions.size === 0) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      void ensureSocket().catch(() => scheduleReconnect());
    }, reconnectDelayMs);
  }

  function onSocketClosed(code: number): void {
    socketOpen = false;
    socket = null;
    broadcast({ source: SIDE_PANEL_SOURCE, type: 'status', connected: false });
    if (subscriptions.size === 0) return;
    if (code === 1008 || code === 4001 || code === 4401) {
      // Auth rejected: drop the cached session so the reconnect re-mints.
      void invalidateSession().finally(scheduleReconnect);
    } else {
      scheduleReconnect();
    }
  }

  function ensureSocket(): Promise<void> {
    if (socket && socketOpen) return Promise.resolve();
    if (connecting) return connecting;
    connecting = (async () => {
      const session = await getSession();
      const ws = createSocket(wsUrl(session), [
        'memstack.launch',
        session.launchCapability,
        'memstack.auth',
        session.credential,
      ]);
      socket = ws;
      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => {
          socketOpen = true;
          broadcast({ source: SIDE_PANEL_SOURCE, type: 'status', connected: true });
          for (const conversationId of subscriptions) {
            ws.send(JSON.stringify({ type: 'subscribe', conversation_id: conversationId }));
          }
          resolve();
        };
        ws.onmessage = (event) => handleSocketMessage(event.data);
        ws.onerror = () => {
          /* onclose always follows */
        };
        ws.onclose = (event) => {
          const wasOpen = socketOpen;
          onSocketClosed(event.code);
          if (!wasOpen) reject(new Error(`agent socket closed before open (code ${event.code})`));
        };
      });
    })().finally(() => {
      connecting = null;
    });
    return connecting;
  }

  async function subscribe(conversationId: string): Promise<void> {
    subscriptions.add(conversationId);
    await ensureSocket();
    socket?.send(JSON.stringify({ type: 'subscribe', conversation_id: conversationId }));
  }

  async function sendChatMessage(
    conversationId: string,
    message: string,
    projectId?: string,
  ): Promise<{ queued: boolean; messageId: string }> {
    const text = message.trim();
    if (text.length === 0) throw new Error('message must not be empty');
    await ensureSocket();
    const messageId = randomId();
    socket?.send(
      JSON.stringify({
        type: 'send_message',
        conversation_id: conversationId,
        ...(projectId ? { project_id: projectId } : {}),
        message: text,
        message_id: messageId,
      }),
    );
    return { queued: true, messageId };
  }

  /** Pull timeline-item candidates out of whatever frame shape the server sent. */
  function extractTimelineItems(frame: Record<string, unknown>): unknown[] {
    const payload = frame.payload ?? frame.item ?? frame.items;
    if (Array.isArray(payload)) return payload;
    if (isRecord(payload)) {
      const inner = payload.timeline;
      if (Array.isArray(inner)) return inner;
      return [payload];
    }
    // Top-level item: the frame itself carries the timeline fields.
    if (typeof frame.content === 'string' || typeof frame.role === 'string') return [frame];
    return [];
  }

  function handleSocketMessage(data: unknown): void {
    let frame: unknown = data;
    if (typeof data === 'string') {
      try {
        frame = JSON.parse(data);
      } catch {
        return; // not JSON: ignore
      }
    }
    if (!isRecord(frame)) return;
    const type = readString(frame.type) ?? readString(frame.event_type) ?? '';
    const conversationId =
      readString(frame.conversation_id) ??
      (isRecord(frame.payload) ? readString(frame.payload.conversation_id) : null);
    if (type === 'ack') {
      broadcast({
        source: SIDE_PANEL_SOURCE,
        type: 'ack',
        action: readString(frame.action) ?? undefined,
        messageId: readString(frame.message_id) ?? undefined,
        conversationId: conversationId ?? undefined,
      });
      return;
    }
    for (const raw of extractTimelineItems(frame)) {
      const item = normalizeTimelineItem(raw);
      if (!item) continue;
      const itemConversationId =
        (isRecord(raw) ? readString(raw.conversation_id) : null) ?? conversationId;
      if (!itemConversationId) continue;
      broadcast({
        source: SIDE_PANEL_SOURCE,
        type: 'timeline',
        conversationId: itemConversationId,
        item,
      });
    }
  }

  async function handlePanelRequest(message: unknown): Promise<unknown> {
    if (!isRecord(message)) throw new Error('sidepanel request must be an object');
    const params = message.params;
    switch (message.method) {
      case 'sidepanel.getStatus':
        return { connected: socketOpen, sessionReady: cachedSession !== null };
      case 'sidepanel.listConversations':
        return { conversations: await listConversations() };
      case 'sidepanel.createConversation': {
        const conversation = await createConversation(
          optionalStringParam(params, 'title'),
          optionalStringParam(params, 'projectId'),
        );
        return { conversation };
      }
      case 'sidepanel.getHistory':
        return { items: await getHistory(requireStringParam(params, 'conversationId')) };
      case 'sidepanel.sendMessage':
        return sendChatMessage(
          requireStringParam(params, 'conversationId'),
          requireStringParam(params, 'message'),
          optionalStringParam(params, 'projectId'),
        );
      case 'sidepanel.subscribe':
        await subscribe(requireStringParam(params, 'conversationId'));
        return {};
      default:
        throw new Error(`unknown sidepanel method: ${String(message.method)}`);
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!isRecord(message)) return false;
    if (message.source !== SIDE_PANEL_SOURCE) return false;
    if (typeof message.method !== 'string' || !message.method.startsWith('sidepanel.')) {
      return false;
    }
    handlePanelRequest(message).then(
      (result) => sendResponse({ ok: true, result }),
      (error: unknown) =>
        sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }),
    );
    return true; // async sendResponse
  });

  return { handlePanelRequest };
}
