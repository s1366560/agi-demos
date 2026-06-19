import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { WebSocketConnection } from '@/services/agent/wsConnection';

class ManualWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  static instances: ManualWebSocket[] = [];

  url: string;
  protocols: string | string[] | undefined;
  readyState = ManualWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sentMessages: string[] = [];

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    ManualWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sentMessages.push(data);
  }

  close(code = 1000, reason = ''): void {
    this.readyState = ManualWebSocket.CLOSED;
    this.onclose?.({ code, reason } as CloseEvent);
  }

  open(): void {
    this.readyState = ManualWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }
}

describe('WebSocketConnection reconnect recovery', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    ManualWebSocket.instances = [];
    localStorage.setItem(
      'memstack-auth-storage',
      JSON.stringify({ state: { token: 'agent-ws-test-token' } })
    );
    vi.stubGlobal('WebSocket', ManualWebSocket);
  });

  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('does not let a pre-open close pin the reconnect path to a stale promise', async () => {
    const onReconnect = vi.fn();
    const connection = new WebSocketConnection({
      sessionId: 'session-1',
      onReconnect,
    });

    const firstConnect = connection.connect();
    expect(ManualWebSocket.instances).toHaveLength(1);

    ManualWebSocket.instances[0]?.close(1006, 'network-reset');
    await expect(firstConnect).rejects.toThrow('WebSocket closed before connection opened: 1006');

    await vi.advanceTimersByTimeAsync(1000);
    expect(ManualWebSocket.instances).toHaveLength(2);

    ManualWebSocket.instances[1]?.open();
    expect(connection.getStatus()).toBe('connected');
    expect(connection.isConnected()).toBe(true);
    expect(onReconnect).toHaveBeenCalledTimes(1);

    connection.disconnect();
  });

  it('sends the server-supported heartbeat message while connected', async () => {
    const connection = new WebSocketConnection({
      sessionId: 'session-heartbeat',
    });

    const connectPromise = connection.connect();
    const socket = ManualWebSocket.instances[0];
    expect(socket).toBeDefined();
    socket?.open();
    await expect(connectPromise).resolves.toBeUndefined();

    await vi.advanceTimersByTimeAsync(30000);

    expect(socket?.sentMessages.map((message) => JSON.parse(message))).toContainEqual({
      type: 'heartbeat',
    });

    connection.disconnect();
  });
});
