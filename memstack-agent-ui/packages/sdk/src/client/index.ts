/**
 * memstack-agent-ui - WebSocket Client Package
 *
 * WebSocket client with automatic reconnection, heartbeat, and event routing.
 *
 * @packageDocumentation
 */

export type {
  WebSocketClientOptions,
  WebSocketStatus,
  WebSocketClient,
} from './WebSocketClient';

export type {
  EventRouter,
} from './handlers';

export type {
  EventHandler,
  AgentEvent,
} from './types';

// Re-export main client
export { WebSocketClient } from './WebSocketClient';

// Re-export event router
export { EventRouter } from './handlers';
