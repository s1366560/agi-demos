import {
  getWebOperationAvailabilityV2,
  runWebOperationV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';
import { logger } from '../../utils/logger';
import { getAuthToken } from '../../utils/tokenResolver';
import { createWebSocketAuthProtocols, createWebSocketUrl } from '../client/urlUtils';
import { attachWatchdog, type Watchdog } from '../client/wsWatchdog';
import type { ServerMessage, WebSocketStatus } from './types';

export interface WebSocketConnectionOptions {
  sessionId: string;
  onStatusChange?: (status: WebSocketStatus) => void;
  onMessage?: (message: ServerMessage) => void;
  onReconnect?: () => void;
}
function deferred() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  let settled = false;
  const promise = new Promise<void>((yes, no) => {
    resolve = () => {
      settled = true;
      yes();
    };
    reject = (error) => {
      settled = true;
      no(error);
    };
  });
  void promise.catch(() => undefined);
  return {
    promise,
    resolve,
    reject,
    get settled() {
      return settled;
    },
  };
}
interface Attempt {
  socket: WebSocket;
  watchdog?: Watchdog | undefined;
  heartbeat?: ReturnType<typeof setInterval> | undefined;
}
interface Session {
  readonly token: string;
  readonly abort: AbortController;
  opened: ReturnType<typeof deferred>;
  readonly closed: ReturnType<typeof deferred>;
  context?: WebOperationContextV2 | undefined;
  attempt?: Attempt | undefined;
  timer?: ReturnType<typeof setTimeout> | undefined;
  task: Promise<void>;
  active: boolean;
  retries: number;
  ready: boolean;
  closeFailure?: { error: unknown };
}
const cancelled = () => new DOMException('Agent connection cancelled', 'AbortError');

/** A connection, including all reconnect attempts, owns one admitted operation until actual close. */
export class WebSocketConnection {
  private session?: Session;
  private pendingConnect: Promise<void> | undefined;
  private pendingOwner: object | undefined;
  private intent = 0;
  private status: WebSocketStatus = 'disconnected';
  private readonly sessionId: string;
  private readonly statusListeners = new Set<(status: WebSocketStatus) => void>();
  private readonly messageListeners = new Set<(message: ServerMessage) => void>();
  private readonly reconnectListeners = new Set<() => void>();
  private readonly retiredListeners = new Set<(context: WebOperationContextV2) => void>();

  constructor(options: WebSocketConnectionOptions) {
    this.sessionId = options.sessionId;
    if (options.onStatusChange) this.onStatusChange(options.onStatusChange);
    if (options.onMessage) this.onMessage(options.onMessage);
    if (options.onReconnect) this.onReconnect(options.onReconnect);
  }
  private notify<T>(listeners: Set<(value: T) => void>, value: T): void {
    for (const listener of listeners) {
      try {
        listener(value);
      } catch {
        logger.error('[AgentWS] Listener failed');
      }
    }
  }
  private setStatus(status: WebSocketStatus): void {
    if (this.status === status) return;
    this.status = status;
    this.notify(this.statusListeners, status);
  }
  getStatus(): WebSocketStatus {
    return this.status;
  }
  getOperationContext(): WebOperationContextV2 | undefined {
    const session = this.session;
    if (!session?.active || !session.context) return undefined;
    try {
      session.context.check();
      return session.context;
    } catch {
      return undefined;
    }
  }
  isConnected(): boolean {
    return (
      !!this.getOperationContext() && this.session?.attempt?.socket.readyState === WebSocket.OPEN
    );
  }
  onStatusChange(listener: (status: WebSocketStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => {
      this.statusListeners.delete(listener);
    };
  }
  onMessage(listener: (message: ServerMessage) => void): () => void {
    this.messageListeners.add(listener);
    return () => {
      this.messageListeners.delete(listener);
    };
  }
  onReconnect(listener: () => void): () => void {
    this.reconnectListeners.add(listener);
    return () => {
      this.reconnectListeners.delete(listener);
    };
  }
  onRetired(listener: (context: WebOperationContextV2) => void): () => void {
    this.retiredListeners.add(listener);
    return () => {
      this.retiredListeners.delete(listener);
    };
  }
  connect(): Promise<void> {
    if (this.isConnected()) return Promise.resolve();
    if (this.session?.active) {
      if (this.session.ready) {
        this.session.ready = false;
        this.session.opened = deferred();
      }
      return this.session.opened.promise;
    }
    const owner = getWebOperationAvailabilityV2().owner;
    if (this.pendingConnect && this.pendingOwner === owner) return this.pendingConnect;
    const intent = ++this.intent;
    const token = getAuthToken();
    const previous = this.session?.task;
    const pending = (async () => {
      if (previous) await Promise.allSettled([previous]);
      if (intent !== this.intent || getWebOperationAvailabilityV2().owner !== owner)
        throw cancelled();
      if (!token) {
        this.setStatus('error');
        throw new Error('No authentication token');
      }
      const session: Session = {
        token,
        abort: new AbortController(),
        opened: deferred(),
        closed: deferred(),
        task: Promise.resolve(),
        active: true,
        retries: 0,
        ready: false,
      };
      this.session = session;
      session.task = runWebOperationV2(
        async (context) => {
          if (getWebOperationAvailabilityV2().owner !== owner || context.owner !== owner)
            throw cancelled();
          session.context = context;
          const abort = () => this.retire(session);
          context.signal.addEventListener('abort', abort, { once: true });
          try {
            if (!session.active || context.signal.aborted) this.retire(session);
            else this.attempt(session);
            await session.closed.promise;
            if (session.closeFailure) throw session.closeFailure.error;
          } finally {
            context.signal.removeEventListener('abort', abort);
          }
        },
        { signal: session.abort.signal }
      ).catch((error) => {
        session.opened.reject(error);
        this.retire(session);
        if (
          this.session === session &&
          !(error instanceof DOMException && error.name === 'AbortError')
        )
          this.setStatus('error');
        if (!(error instanceof DOMException && error.name === 'AbortError')) throw error;
      });
      void session.task.catch(() => undefined);
      return await session.opened.promise;
    })();
    this.pendingConnect = pending;
    this.pendingOwner = owner;
    void pending
      .finally(() => {
        if (this.pendingConnect === pending) {
          this.pendingConnect = undefined;
          this.pendingOwner = undefined;
        }
      })
      .catch(() => undefined);
    return pending;
  }
  disconnect(): Promise<void> {
    ++this.intent;
    const session = this.session;
    if (session) this.retire(session);
    else this.setStatus('disconnected');
    return session?.task ?? Promise.resolve();
  }
  private current(session: Session, attempt?: Attempt): boolean {
    if (this.session !== session || !session.active || (attempt && session.attempt !== attempt))
      return false;
    try {
      session.context?.check();
      return !!session.context;
    } catch {
      this.retire(session);
      return false;
    }
  }
  private stopAttempt(attempt: Attempt): void {
    attempt.watchdog?.stop();
    if (attempt.heartbeat !== undefined) clearInterval(attempt.heartbeat);
    attempt.heartbeat = undefined;
  }
  private retire(session: Session): void {
    if (session.active) {
      session.active = false;
      if (session.timer !== undefined) clearTimeout(session.timer);
      session.timer = undefined;
      session.opened.reject(cancelled());
      if (session.context) this.notify(this.retiredListeners, session.context);
      if (this.session === session) this.setStatus('disconnected');
      session.abort.abort();
    }
    const attempt = session.attempt;
    if (!attempt) {
      session.closed.resolve();
      return;
    }
    this.stopAttempt(attempt);
    this.closeAttempt(session, attempt);
  }
  private closeAttempt(session: Session, attempt: Attempt): void {
    if (attempt.socket.readyState === WebSocket.CLOSED) {
      this.closed(session, attempt);
      return;
    }
    try {
      attempt.socket.close();
    } catch (error) {
      session.closeFailure ??= { error };
      // CONNECTING close can throw in an embedder: keep onopen/onclose installed and drain it.
      // The late open handler closes again; never pretend an unclosed socket has released.
    }
  }
  private closed(session: Session, attempt: Attempt): void {
    if (session.attempt !== attempt) return;
    this.stopAttempt(attempt);
    attempt.socket.onopen = null;
    attempt.socket.onmessage = null;
    attempt.socket.onerror = null;
    attempt.socket.onclose = null;
    session.attempt = undefined;
    if (!session.active) {
      session.closed.resolve();
      return;
    }
    if (!this.current(session)) return;
    session.ready = false;
    if (session.opened.settled) session.opened = deferred();
    this.setStatus('disconnected');
    this.scheduleReconnect(session);
  }
  private attempt(session: Session): void {
    if (!this.current(session)) return;
    this.setStatus('connecting');
    if (!this.current(session)) return;
    try {
      const socket = new WebSocket(
        createWebSocketUrl('/agent/ws', { session_id: this.sessionId }),
        createWebSocketAuthProtocols(session.token)
      );
      const attempt: Attempt = { socket };
      session.attempt = attempt;
      socket.onopen = () => {
        if (!this.current(session, attempt)) {
          this.closeAttempt(session, attempt);
          return;
        }
        session.retries = 0;
        this.setStatus('connected');
        if (!this.current(session, attempt)) return;
        attempt.watchdog = attachWatchdog(socket, { staleAfterMs: 90000, label: 'AgentWS' });
        attempt.heartbeat = setInterval(() => {
          if (this.current(session, attempt) && socket.readyState === WebSocket.OPEN)
            socket.send(JSON.stringify({ type: 'heartbeat' }));
        }, 30000);
        session.ready = true;
        session.opened.resolve();
        for (const listener of this.reconnectListeners) {
          if (!this.current(session, attempt)) break;
          try {
            listener();
          } catch {
            logger.error('[AgentWS] Reconnect listener failed');
          }
        }
      };
      socket.onmessage = (event) => {
        if (!this.current(session, attempt)) return;
        attempt.watchdog?.notifyMessage();
        try {
          if (typeof event.data !== 'string') throw new Error('Expected text WebSocket message');
          const message = JSON.parse(event.data) as ServerMessage;
          for (const listener of this.messageListeners) {
            if (!this.current(session, attempt)) break;
            listener(message);
          }
        } catch {
          logger.error('[AgentWS] Failed to parse or deliver message');
        }
      };
      socket.onclose = (event) => {
        if (session.attempt !== attempt) return;
        if (session.active && this.status !== 'connected')
          session.opened.reject(
            new Error(`WebSocket closed before connection opened: ${String(event.code)}`)
          );
        this.closed(session, attempt);
      };
      socket.onerror = () => {
        if (!this.current(session, attempt)) return;
        this.setStatus('error');
        session.opened.reject(new Error('WebSocket error'));
        this.stopAttempt(attempt);
        // Error is not close. Reconnect only after this socket's actual close event.
        this.closeAttempt(session, attempt);
      };
    } catch (error) {
      if (!this.current(session)) return;
      session.opened.reject(error);
      this.setStatus('error');
      this.scheduleReconnect(session);
    }
  }
  private scheduleReconnect(session: Session): void {
    if (!this.current(session) || session.timer !== undefined) return;
    if (session.retries >= 5) {
      this.retire(session);
      return;
    }
    const delay = 1000 * 2 ** session.retries++;
    session.timer = setTimeout(() => {
      session.timer = undefined;
      if (this.current(session)) this.attempt(session);
    }, delay);
  }
  send(message: Record<string, unknown>): boolean {
    const session = this.session,
      attempt = session?.attempt;
    if (
      !session ||
      !attempt ||
      !this.current(session, attempt) ||
      attempt.socket.readyState !== WebSocket.OPEN
    )
      return false;
    attempt.socket.send(JSON.stringify(message));
    return true;
  }
}
