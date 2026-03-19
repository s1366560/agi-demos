export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface ServerMessage {
  type: string;
  conversation_id?: string | undefined;
  project_id?: string | undefined;
  agent_id?: string | undefined;
  data?: unknown | undefined;
  event_time_us?: number | undefined;
  event_counter?: number | undefined;
  timestamp?: string | undefined;
  action?: string | undefined;
}
