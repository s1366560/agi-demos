import { logger } from '../../utils/logger';
import { getAuthToken } from '../../utils/tokenResolver';
import { createWebSocketAuthProtocols, createWebSocketUrl } from '../client/urlUtils';
import { attachWatchdog } from '../client/wsWatchdog';

import type { ServerMessage, WebSocketStatus } from './types';
import type { Watchdog } from '../client/wsWatchdog';

export interface WebSocketConnectionOptions {
  sessionId: string;
  onStatusChange?: (status: WebSocketStatus) => void;
  onMessage?: (message: ServerMessage) => void;
  onReconnect?: () => void;
}

export class WebSocketConnection {
  private ws: WebSocket | null = null;
  private status: WebSocketStatus = 'disconnected';
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private isManualClose = false;

  private sessionId: string;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private readonly HEARTBEAT_INTERVAL_MS = 30000;
  private watchdog: Watchdog | null = null;

  private connectingPromise: Promise<void> | null = null;

  private statusListeners: Set<(status: WebSocketStatus) => void> = new Set();
  private messageListeners: Set<(message: ServerMessage) => void> = new Set();
  private reconnectListeners: Set<() => void> = new Set();

  constructor(options: WebSocketConnectionOptions) {
    this.sessionId = options.sessionId;
    if (options.onStatusChange) this.onStatusChange(options.onStatusChange);
    if (options.onMessage) this.onMessage(options.onMessage);
    if (options.onReconnect) this.onReconnect(options.onReconnect);
  }

  private setStatus(status: WebSocketStatus): void {
    if (this.status !== status) {
      this.status = status;
      this.statusListeners.forEach((listener) => {
        listener(status);
      });
    }
  }

  getStatus(): WebSocketStatus {
    return this.status;
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  onStatusChange(listener: (status: WebSocketStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  onMessage(listener: (message: ServerMessage) => void): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  onReconnect(listener: () => void): () => void {
    this.reconnectListeners.add(listener);
    return () => this.reconnectListeners.delete(listener);
  }

  connect(): Promise<void> {
    if (this.connectingPromise) {
      logger.debug('[AgentWS] Connection already in progress, returning existing promise');
      return this.connectingPromise;
    }

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      logger.debug('[AgentWS] Already connected');
      return Promise.resolve();
    }

    this.isManualClose = false;
    this.setStatus('connecting');

    this.connectingPromise = this.doConnect();
    return this.connectingPromise;
  }

  private doConnect(): Promise<void> {
    return new Promise((resolve, reject) => {
      const token = getAuthToken();
      if (!token) {
        this.setStatus('error');
        reject(new Error('No authentication token'));
        return;
      }

      const wsUrl = createWebSocketUrl('/agent/ws', {
        session_id: this.sessionId,
      });

      try {
        this.ws = new WebSocket(wsUrl, createWebSocketAuthProtocols(token));
        this.watchdog?.stop();
        this.watchdog = attachWatchdog(this.ws, {
          staleAfterMs: this.HEARTBEAT_INTERVAL_MS * 3,
          label: 'AgentWS',
        });

        this.ws.onopen = () => {
          logger.debug(`[AgentWS] Connected (session: ${this.sessionId.substring(0, 8)}...)`);
          this.setStatus('connected');
          this.reconnectAttempts = 0;
          this.reconnectDelay = 1000;
          this.connectingPromise = null;

          this.startHeartbeat();

          this.reconnectListeners.forEach((listener) => {
            listener();
          });
          resolve();
        };

        this.ws.onmessage = (event) => {
          this.watchdog?.notifyMessage();
          try {
            if (typeof event.data !== 'string') {
              throw new Error('Expected text WebSocket message');
            }
            const message = JSON.parse(event.data) as ServerMessage;
            this.messageListeners.forEach((listener) => {
              listener(message);
            });
          } catch (err) {
            logger.error('[AgentWS] Failed to parse message:', err);
          }
        };

        this.ws.onclose = (event) => {
          logger.debug('[AgentWS] Disconnected', event.code, event.reason);
          const closedBeforeOpen = this.connectingPromise !== null;
          this.setStatus('disconnected');
          this.stopHeartbeat();
          this.stopWatchdog();
          this.ws = null;
          this.connectingPromise = null;

          if (!this.isManualClose && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.scheduleReconnect();
          }

          if (closedBeforeOpen) {
            reject(new Error(`WebSocket closed before connection opened: ${String(event.code)}`));
          }
        };

        this.ws.onerror = (error) => {
          logger.error('[AgentWS] Error:', error);
          this.setStatus('error');
          this.stopHeartbeat();
          this.stopWatchdog();
          this.connectingPromise = null;
          reject(error instanceof Error ? error : new Error('WebSocket error'));
        };
      } catch (err) {
        logger.error('[AgentWS] Connection error:', err);
        this.setStatus('error');
        this.connectingPromise = null;
        this.scheduleReconnect();
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    });
  }

  disconnect(): void {
    this.isManualClose = true;
    this.stopHeartbeat();
    this.stopWatchdog();

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.setStatus('disconnected');
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    logger.debug(
      `[AgentWS] Reconnecting in ${String(delay)}ms (attempt ${String(this.reconnectAttempts)}/${String(this.maxReconnectAttempts)})`
    );

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect().catch((err: unknown) => {
        logger.error('[AgentWS] Reconnect failed:', err);
      });
    }, delay);
  }

  private startHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
    }
    this.heartbeatInterval = setInterval(() => {
      if (this.isConnected()) {
        this.send({ type: 'heartbeat' });
      }
    }, this.HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  private stopWatchdog(): void {
    this.watchdog?.stop();
    this.watchdog = null;
  }

  send(message: Record<string, unknown>): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }
}
