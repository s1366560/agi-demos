/**
 * WebSocket half-open connection watchdog.
 *
 * Browsers do not expose WebSocket ping/pong frames to JS, so when NAT / LB /
 * laptop sleep silently drops a TCP connection, `readyState` stays OPEN,
 * `onclose` never fires, and the reconnect path never runs.
 *
 * Pattern (borrowed from multica audit):
 *   - Track `lastMessageTime` on every inbound message.
 *   - A periodic watchdog timer closes the socket when no message has been
 *     received for `staleAfterMs`. The existing reconnect path then picks up.
 *
 * The server side already sends periodic frames (ping from client is echoed
 * as pong; agent stream emits status/event frames), so any silent gap longer
 * than the heartbeat interval means the connection is half-open.
 */
export interface WatchdogOptions {
  /** If no inbound message within this window, treat as half-open. */
  staleAfterMs: number;
  /** How often to check. Default: staleAfterMs / 3 (min 5s). */
  checkIntervalMs?: number;
  /** Called when the connection is declared stale. Default: ws.close(4000). */
  onStale?: (ws: WebSocket) => void;
  /** Label for debug logs. */
  label?: string;
}

export interface Watchdog {
  /** Call on every inbound message (including pongs). */
  notifyMessage(): void;
  /** Stop the watchdog and clear timers. */
  stop(): void;
}

export function attachWatchdog(ws: WebSocket, options: WatchdogOptions): Watchdog {
  const staleAfterMs = options.staleAfterMs;
  const checkIntervalMs = Math.max(options.checkIntervalMs ?? Math.floor(staleAfterMs / 3), 5000);
  const label = options.label ?? 'WS';

  let lastMessageTime = Date.now();
  let stopped = false;

  const OPEN = typeof WebSocket !== 'undefined' ? WebSocket.OPEN : 1;

  const timer = setInterval(() => {
    if (stopped) return;
    if (ws.readyState !== OPEN) return;
    const elapsed = Date.now() - lastMessageTime;
    if (elapsed > staleAfterMs) {
      console.warn(
        `[${label}] watchdog: no inbound for ${String(elapsed)}ms (>${String(staleAfterMs)}ms), closing as stale`
      );
      stopped = true;
      clearInterval(timer);
      if (options.onStale) {
        options.onStale(ws);
      } else {
        try {
          ws.close(4000, 'watchdog-stale');
        } catch {
          // ignore
        }
      }
    }
  }, checkIntervalMs);

  return {
    notifyMessage() {
      lastMessageTime = Date.now();
    },
    stop() {
      stopped = true;
      clearInterval(timer);
    },
  };
}
