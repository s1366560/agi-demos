import { describe, expect, it, vi } from 'vitest';
import {
  GET_SIDE_PANEL_SESSION_METHOD,
  SIDE_PANEL_SESSION_KEY,
  SIDE_PANEL_SOURCE,
  createSidePanelChat,
  normalizeTimelineItem,
  type ChatFetch,
  type ChatWebSocket,
  type SidePanelSession,
} from '../src/sidepanel-chat';
import { createChromeMock, flush, type ChromeMock } from './chrome-mock';

const SESSION: SidePanelSession = {
  apiBaseUrl: 'http://127.0.0.1:8088',
  launchCapability: 'lc-1',
  credential: 'cred-1',
};

class MockSocket implements ChatWebSocket {
  static instances: MockSocket[] = [];
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number; reason?: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(
    public url: string,
    public protocols: string[],
  ) {
    MockSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.onclose?.({ code: 1000 });
  }
}

function setup(overrides: { sendRequest?: ReturnType<typeof vi.fn>; fetchFn?: ChatFetch } = {}) {
  const { chrome } = createChromeMock();
  MockSocket.instances = [];
  const sendRequest = overrides.sendRequest ?? vi.fn(async () => SESSION);
  const fetchFn =
    overrides.fetchFn ??
    (vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    })) as unknown as ChatFetch);
  const chat = createSidePanelChat({
    chrome,
    transport: {
      sendRequest: sendRequest as (method: string, params?: unknown) => Promise<unknown>,
    },
    fetchFn,
    createSocket: (url, protocols) => new MockSocket(url, protocols),
    randomId: () => 'mid-1',
    reconnectDelayMs: 10,
  });
  return { chrome, sendRequest, fetchFn: fetchFn as unknown as ReturnType<typeof vi.fn>, chat };
}

interface PanelResponse {
  ok: boolean;
  result?: unknown;
  error?: string;
}

function panelRequest(chrome: ChromeMock, method: string, params?: unknown): Promise<PanelResponse> {
  return new Promise((resolve) => {
    chrome.runtime.onMessage.fire(
      { source: SIDE_PANEL_SOURCE, method, params },
      {},
      (response) => resolve(response as PanelResponse),
    );
  });
}

function okJson(payload: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => payload };
}

describe('session bootstrap and cache', () => {
  it('mints the session via getSidePanelSession and caches it in storage.session', async () => {
    const { chrome, sendRequest, fetchFn } = setup();
    fetchFn.mockResolvedValue(okJson({ items: [{ id: 'c1', title: 'First chat' }] }));

    const response = await panelRequest(chrome, 'sidepanel.listConversations');
    expect(response).toEqual({
      ok: true,
      result: { conversations: [{ id: 'c1', title: 'First chat' }] },
    });
    expect(sendRequest).toHaveBeenCalledTimes(1);
    expect(sendRequest).toHaveBeenCalledWith(GET_SIDE_PANEL_SESSION_METHOD, {});
    expect(chrome.storage.session.set).toHaveBeenCalledWith({
      [SIDE_PANEL_SESSION_KEY]: SESSION,
    });
    expect(fetchFn).toHaveBeenCalledWith(
      'http://127.0.0.1:8088/api/v1/agent/conversations',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer cred-1',
          'X-Agistack-Launch': 'lc-1',
        }),
      }),
    );

    // Second call reuses the in-memory cache: no new native request.
    await panelRequest(chrome, 'sidepanel.listConversations');
    expect(sendRequest).toHaveBeenCalledTimes(1);
  });

  it('restores the session from storage.session without a native request', async () => {
    const { chrome, sendRequest } = setup();
    chrome.storage.session.get.mockResolvedValue({ [SIDE_PANEL_SESSION_KEY]: SESSION });

    const response = await panelRequest(chrome, 'sidepanel.listConversations');
    expect(response.ok).toBe(true);
    expect(sendRequest).not.toHaveBeenCalled();
  });

  it('re-mints the session once on HTTP 401 and retries with the new credential', async () => {
    const renewed: SidePanelSession = { ...SESSION, credential: 'cred-2' };
    const sendRequest = vi.fn().mockResolvedValueOnce(SESSION).mockResolvedValueOnce(renewed);
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(okJson({ detail: 'expired' }, 401))
      .mockResolvedValueOnce(okJson({ items: [] })) as unknown as ChatFetch;
    const { chrome } = setup({ sendRequest, fetchFn });
    const fetchMock = fetchFn as unknown as ReturnType<typeof vi.fn>;

    const response = await panelRequest(chrome, 'sidepanel.listConversations');
    expect(response.ok).toBe(true);
    expect(sendRequest).toHaveBeenCalledTimes(2);
    expect(chrome.storage.session.remove).toHaveBeenCalledWith(SIDE_PANEL_SESSION_KEY);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondCall = fetchMock.mock.calls[1] as [string, { headers: Record<string, string> }];
    expect(secondCall[1].headers.Authorization).toBe('Bearer cred-2');
  });

  it('fails instead of looping when the re-minted credential also gets a 401', async () => {
    const fetchFn = vi.fn(async () => okJson({ detail: 'expired' }, 401)) as unknown as ChatFetch;
    const { chrome, sendRequest } = setup({ fetchFn });

    const response = await panelRequest(chrome, 'sidepanel.listConversations');
    expect(response.ok).toBe(false);
    expect(response.error).toContain('401');
    expect(sendRequest).toHaveBeenCalledTimes(2); // initial mint + one re-mint
  });

  it('surfaces a broken getSidePanelSession payload as an error', async () => {
    const sendRequest = vi.fn(async () => ({ apiBaseUrl: '' }));
    const { chrome } = setup({ sendRequest });
    const response = await panelRequest(chrome, 'sidepanel.listConversations');
    expect(response.ok).toBe(false);
    expect(response.error).toContain('apiBaseUrl');
  });
});

describe('conversation and history APIs', () => {
  it('creates a conversation with a default title and normalizes the response', async () => {
    const fetchFn = vi.fn(async () =>
      okJson({ id: 'c9', title: 'Side panel chat' }),
    ) as unknown as ChatFetch;
    const { chrome } = setup({ fetchFn });
    const fetchMock = fetchFn as unknown as ReturnType<typeof vi.fn>;

    const response = await panelRequest(chrome, 'sidepanel.createConversation', {});
    expect(response).toEqual({
      ok: true,
      result: { conversation: { id: 'c9', title: 'Side panel chat' } },
    });
    const firstCall = fetchMock.mock.calls[0] as [string, { body: string }];
    expect(JSON.parse(firstCall[1].body)).toEqual({
      title: 'Side panel chat',
    });
  });

  it('maps history onto panel entries: text passes, HITL degrades, tool calls drop', async () => {
    const fetchFn = vi.fn(async () =>
      okJson({
        timeline: [
          { id: 'm1', type: 'user_message', role: 'user', content: 'hello', timestamp: 1 },
          { id: 'm2', type: 'assistant_message', role: 'assistant', content: 'hi', timestamp: 2 },
          { id: 'h1', type: 'hitl_clarification', question: 'Which file?' },
          { id: 't1', type: 'tool_call', toolName: 'read_file' },
        ],
      }),
    ) as unknown as ChatFetch;
    const { chrome } = setup({ fetchFn });

    const response = await panelRequest(chrome, 'sidepanel.getHistory', { conversationId: 'c1' });
    expect(response.ok).toBe(true);
    expect(response.result).toEqual({
      items: [
        { kind: 'text', id: 'm1', role: 'user', text: 'hello', timestamp: 1 },
        { kind: 'text', id: 'm2', role: 'assistant', text: 'hi', timestamp: 2 },
        { kind: 'desktop-required', id: 'h1', summary: 'Which file?' },
      ],
    });
  });

  it('rejects requests missing required params', async () => {
    const { chrome } = setup();
    const response = await panelRequest(chrome, 'sidepanel.getHistory', {});
    expect(response.ok).toBe(false);
    expect(response.error).toContain('conversationId');
  });

  it('ignores runtime messages that are not sidepanel requests', async () => {
    const { chrome } = setup();
    const sendResponse = vi.fn();
    chrome.runtime.onMessage.fire({ type: 'AGENT_CURSOR_PING' }, {}, sendResponse);
    chrome.runtime.onMessage.fire(
      { source: 'other', method: 'sidepanel.listConversations' },
      {},
      sendResponse,
    );
    await flush();
    expect(sendResponse).not.toHaveBeenCalled();
  });

  it('reports unknown sidepanel methods as errors', async () => {
    const { chrome } = setup();
    const response = await panelRequest(chrome, 'sidepanel.nope');
    expect(response.ok).toBe(false);
    expect(response.error).toContain('unknown sidepanel method');
  });
});

describe('agent websocket', () => {
  async function openSocket(chrome: ChromeMock): Promise<MockSocket> {
    const pending = panelRequest(chrome, 'sidepanel.subscribe', { conversationId: 'c1' });
    await flush();
    const socket = MockSocket.instances[0];
    if (!socket) throw new Error('socket was not created');
    socket.onopen?.();
    await pending;
    return socket;
  }

  it('dials the agent ws with launch + auth subprotocols and subscribes', async () => {
    const { chrome } = setup();
    const socket = await openSocket(chrome);
    expect(socket.url).toBe('ws://127.0.0.1:8088/api/v1/agent/ws');
    expect(socket.protocols).toEqual(['memstack.launch', 'lc-1', 'memstack.auth', 'cred-1']);
    expect(socket.sent.map((f) => JSON.parse(f))).toContainEqual({
      type: 'subscribe',
      conversation_id: 'c1',
    });
  });

  it('sends send_message frames with a generated message id', async () => {
    const { chrome } = setup();
    const socket = await openSocket(chrome);
    const response = await panelRequest(chrome, 'sidepanel.sendMessage', {
      conversationId: 'c1',
      message: '  hello agent  ',
    });
    expect(response).toEqual({ ok: true, result: { queued: true, messageId: 'mid-1' } });
    expect(socket.sent.map((f) => JSON.parse(f))).toContainEqual({
      type: 'send_message',
      conversation_id: 'c1',
      message: 'hello agent',
      message_id: 'mid-1',
    });
  });

  it('refuses to send an empty message', async () => {
    const { chrome } = setup();
    await openSocket(chrome);
    const response = await panelRequest(chrome, 'sidepanel.sendMessage', {
      conversationId: 'c1',
      message: '   ',
    });
    expect(response.ok).toBe(false);
    expect(response.error).toContain('must not be empty');
  });

  it('broadcasts normalized timeline frames to the panel', async () => {
    const { chrome } = setup();
    const socket = await openSocket(chrome);
    chrome.runtime.sendMessage.mockClear();

    socket.onmessage?.({
      data: JSON.stringify({
        type: 'timeline_item',
        conversation_id: 'c1',
        payload: { id: 'i1', type: 'assistant_message', role: 'assistant', content: 'Hi there' },
      }),
    });
    await flush();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      source: SIDE_PANEL_SOURCE,
      type: 'timeline',
      conversationId: 'c1',
      item: { kind: 'text', id: 'i1', role: 'assistant', text: 'Hi there', timestamp: null },
    });
  });

  it('broadcasts HITL frames as desktop-required entries', async () => {
    const { chrome } = setup();
    const socket = await openSocket(chrome);
    chrome.runtime.sendMessage.mockClear();

    socket.onmessage?.({
      data: JSON.stringify({
        type: 'timeline_item',
        conversation_id: 'c1',
        payload: { id: 'h1', type: 'approval_request', description: 'Delete build output?' },
      }),
    });
    await flush();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      source: SIDE_PANEL_SOURCE,
      type: 'timeline',
      conversationId: 'c1',
      item: { kind: 'desktop-required', id: 'h1', summary: 'Delete build output?' },
    });
  });

  it('broadcasts acks for send_message', async () => {
    const { chrome } = setup();
    const socket = await openSocket(chrome);
    chrome.runtime.sendMessage.mockClear();

    socket.onmessage?.({
      data: JSON.stringify({
        type: 'ack',
        action: 'send_message',
        message_id: 'mid-1',
        conversation_id: 'c1',
      }),
    });
    await flush();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({
      source: SIDE_PANEL_SOURCE,
      type: 'ack',
      action: 'send_message',
      messageId: 'mid-1',
      conversationId: 'c1',
    });
  });

  it('ignores malformed socket payloads', async () => {
    const { chrome } = setup();
    const socket = await openSocket(chrome);
    chrome.runtime.sendMessage.mockClear();

    socket.onmessage?.({ data: 'not json' });
    socket.onmessage?.({ data: JSON.stringify({ type: 'timeline_item', payload: null }) });
    socket.onmessage?.({ data: JSON.stringify([1, 2, 3]) });
    await flush();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
  });

  it('reconnects and re-subscribes after the socket drops', async () => {
    const { chrome } = setup();
    const socket = await openSocket(chrome); // real timers while opening
    vi.useFakeTimers();
    try {
      socket.onclose?.({ code: 1006 });
      expect(MockSocket.instances).toHaveLength(1); // waiting on the backoff timer

      await vi.advanceTimersByTimeAsync(10);
      await vi.advanceTimersByTimeAsync(0);
      expect(MockSocket.instances).toHaveLength(2);
      const reopened = MockSocket.instances[1];
      if (!reopened) throw new Error('socket did not reconnect');
      reopened.onopen?.();
      await vi.advanceTimersByTimeAsync(0);
      expect(reopened.sent.map((f) => JSON.parse(f))).toContainEqual({
        type: 'subscribe',
        conversation_id: 'c1',
      });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('normalizeTimelineItem', () => {
  it('infers the user role from the item type when role is missing', () => {
    expect(normalizeTimelineItem({ id: 'x', type: 'user_message', content: 'hi' })).toEqual({
      kind: 'text',
      id: 'x',
      role: 'user',
      text: 'hi',
      timestamp: null,
    });
  });

  it('drops non-text, non-HITL items', () => {
    expect(normalizeTimelineItem({ id: 'x', type: 'tool_call', toolName: 'grep' })).toBeNull();
    expect(normalizeTimelineItem('garbage')).toBeNull();
  });
});
