/**
 * useWebSocket Hook
 *
 * A custom hook that manages a WebSocket connection with support for
 * automatic reconnection, event callbacks, and connection state tracking.
 *
 * @example
 * const { ws, status, send, connect, disconnect } = useWebSocket({
 *   url: 'ws://localhost:8080',
 *   onMessage: (event) => console.log('Received:', event.data),
 *   reconnect: true,
 *   reconnectInterval: 3000,
 * });
 */

import { useRef, useCallback, useEffect, useState } from 'react';

export type WebSocketStatus = 'connecting' | 'open' | 'closing' | 'closed';

export interface UseWebSocketOptions {
  url: string | (() => string);
  onMessage?: ((event: MessageEvent) => void) | undefined;
  onError?: ((event: Event) => void) | undefined;
  onOpen?: ((event: Event) => void) | undefined;
  onClose?: ((event: CloseEvent) => void) | undefined;
  reconnect?: boolean | undefined;
  reconnectInterval?: number | undefined;
  maxReconnectAttempts?: number | undefined;
}

export interface UseWebSocketReturn {
  ws: WebSocket | null;
  status: WebSocketStatus;
  send: (data: string | object) => void;
  connect: () => void;
  disconnect: () => void;
}

const getStatus = (ws: WebSocket | null): WebSocketStatus => {
  if (!ws) return 'closed';
  switch (ws.readyState) {
    case WebSocket.CONNECTING:
      return 'connecting';
    case WebSocket.OPEN:
      return 'open';
    case WebSocket.CLOSING:
      return 'closing';
    case WebSocket.CLOSED:
      return 'closed';
    default:
      return 'closed';
  }
};

export function useWebSocket({
  url,
  onMessage,
  onError,
  onOpen,
  onClose,
  reconnect = false,
  reconnectInterval = 3000,
  maxReconnectAttempts = Infinity,
}: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isManualCloseRef = useRef(false);
  const isMountedRef = useRef(true);

  const [status, setStatus] = useState<WebSocketStatus>('closed');
  const [ws, setWs] = useState<WebSocket | null>(null);

  const getUrl = useCallback(() => {
    return typeof url === 'function' ? url() : url;
  }, [url]);

  const updateWsState = useCallback((newWs: WebSocket | null) => {
    wsRef.current = newWs;
    setWs(newWs);
    setStatus(getStatus(newWs));
  }, []);

  const cleanup = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    isManualCloseRef.current = true;
    cleanup();

    if (wsRef.current) {
      if (
        wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING
      ) {
        wsRef.current.close();
      }
      updateWsState(null);
    }

    reconnectAttemptsRef.current = 0;
    setStatus('closed');
  }, [cleanup, updateWsState]);

  // Use a ref for the connect function to allow recursive calls
  const connectRef = useRef<(() => void) | null>(null);

  const connect = useCallback(() => {
    // Don't connect if already connecting or connected
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.CONNECTING ||
        wsRef.current.readyState === WebSocket.OPEN)
    ) {
      return;
    }

    // Clean up any existing reconnection timer
    cleanup();

    // Reset manual close flag for new connection
    isManualCloseRef.current = false;

    try {
      const wsUrl = getUrl();
      const newWs = new WebSocket(wsUrl);
      updateWsState(newWs);

      newWs.onopen = (event) => {
        if (!isMountedRef.current) return;

        reconnectAttemptsRef.current = 0;
        setStatus('open');
        onOpen?.(event);
      };

      newWs.onmessage = (event) => {
        if (!isMountedRef.current) return;
        onMessage?.(event);
      };

      newWs.onerror = (event) => {
        if (!isMountedRef.current) return;
        onError?.(event);
        // After error, connection will close - let onclose handle the state
      };

      newWs.onclose = (event) => {
        if (!isMountedRef.current) return;

        updateWsState(null);
        setStatus('closed');
        onClose?.(event);

        // Attempt reconnection if enabled and not manually closed
        if (
          reconnect &&
          !isManualCloseRef.current &&
          reconnectAttemptsRef.current < maxReconnectAttempts
        ) {
          reconnectAttemptsRef.current += 1;
          reconnectTimeoutRef.current = setTimeout(() => {
            if (isMountedRef.current && !isManualCloseRef.current) {
              connectRef.current?.();
            }
          }, reconnectInterval);
        }
      };
    } catch (error) {
      console.error('WebSocket connection error:', error);
      updateWsState(null);
      setStatus('closed');
    }
  }, [
    getUrl,
    onMessage,
    onError,
    onOpen,
    onClose,
    reconnect,
    reconnectInterval,
    maxReconnectAttempts,
    cleanup,
    updateWsState,
  ]);

  // Store the latest connect function in the ref
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const send = useCallback((data: string | object) => {
    const currentWs = wsRef.current;
    if (!currentWs || currentWs.readyState !== WebSocket.OPEN) {
      return;
    }

    const message = typeof data === 'string' ? data : JSON.stringify(data);
    currentWs.send(message);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;

    return () => {
      isMountedRef.current = false;
      isManualCloseRef.current = true;
      cleanup();
      if (wsRef.current) {
        wsRef.current.close();
        updateWsState(null);
      }
    };
  }, [cleanup, updateWsState]);

  return {
    ws,
    status,
    send,
    connect,
    disconnect,
  };
}
