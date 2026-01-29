/**
 * Sandbox event types for SSE subscription.
 *
 * These types align with backend sandbox events in
 * src/domain/events/agent_events.py
 */

/**
 * All possible sandbox event types
 */
export type SandboxEventType =
  | "sandbox_created"
  | "sandbox_terminated"
  | "sandbox_status"
  | "desktop_started"
  | "desktop_stopped"
  | "desktop_status"
  | "terminal_started"
  | "terminal_stopped"
  | "terminal_status";

/**
 * Base sandbox SSE event format
 */
export interface BaseSandboxSSEEvent {
  type: SandboxEventType;
  data: unknown;
  timestamp: string;
}

/**
 * Sandbox created event data
 */
export interface SandboxCreatedEventData {
  sandbox_id: string;
  project_id: string;
  status: string;
  endpoint?: string;
  websocket_url?: string;
}

/**
 * Sandbox created SSE event
 */
export interface SandboxCreatedSSEEvent extends BaseSandboxSSEEvent {
  type: "sandbox_created";
  data: SandboxCreatedEventData;
}

/**
 * Sandbox terminated event data
 */
export interface SandboxTerminatedEventData {
  sandbox_id: string;
}

/**
 * Sandbox terminated SSE event
 */
export interface SandboxTerminatedSSEEvent extends BaseSandboxSSEEvent {
  type: "sandbox_terminated";
  data: SandboxTerminatedEventData;
}

/**
 * Sandbox status event data
 */
export interface SandboxStatusEventData {
  sandbox_id: string;
  status: string;
}

/**
 * Sandbox status SSE event
 */
export interface SandboxStatusSSEEvent extends BaseSandboxSSEEvent {
  type: "sandbox_status";
  data: SandboxStatusEventData;
}

/**
 * Desktop started event data
 */
export interface DesktopStartedEventData {
  sandbox_id: string;
  url?: string;
  display: string;
  resolution: string;
  port: number;
}

/**
 * Desktop started SSE event
 */
export interface DesktopStartedSSEEvent extends BaseSandboxSSEEvent {
  type: "desktop_started";
  data: DesktopStartedEventData;
}

/**
 * Desktop stopped event data
 */
export interface DesktopStoppedEventData {
  sandbox_id: string;
}

/**
 * Desktop stopped SSE event
 */
export interface DesktopStoppedSSEEvent extends BaseSandboxSSEEvent {
  type: "desktop_stopped";
  data: DesktopStoppedEventData;
}

/**
 * Desktop status event data
 */
export interface DesktopStatusEventData {
  sandbox_id: string;
  running: boolean;
  url?: string;
  display: string;
  resolution: string;
  port: number;
}

/**
 * Desktop status SSE event
 */
export interface DesktopStatusSSEEvent extends BaseSandboxSSEEvent {
  type: "desktop_status";
  data: DesktopStatusEventData;
}

/**
 * Terminal started event data
 */
export interface TerminalStartedEventData {
  sandbox_id: string;
  url?: string;
  port: number;
  session_id?: string;
  pid?: number;
}

/**
 * Terminal started SSE event
 */
export interface TerminalStartedSSEEvent extends BaseSandboxSSEEvent {
  type: "terminal_started";
  data: TerminalStartedEventData;
}

/**
 * Terminal stopped event data
 */
export interface TerminalStoppedEventData {
  sandbox_id: string;
  session_id?: string;
}

/**
 * Terminal stopped SSE event
 */
export interface TerminalStoppedSSEEvent extends BaseSandboxSSEEvent {
  type: "terminal_stopped";
  data: TerminalStoppedEventData;
}

/**
 * Terminal status event data
 */
export interface TerminalStatusEventData {
  sandbox_id: string;
  running: boolean;
  url?: string;
  port: number;
  session_id?: string;
  pid?: number;
}

/**
 * Terminal status SSE event
 */
export interface TerminalStatusSSEEvent extends BaseSandboxSSEEvent {
  type: "terminal_status";
  data: TerminalStatusEventData;
}

/**
 * Union type for all sandbox SSE events
 */
export type SandboxSSEEvent =
  | SandboxCreatedSSEEvent
  | SandboxTerminatedSSEEvent
  | SandboxStatusSSEEvent
  | DesktopStartedSSEEvent
  | DesktopStoppedSSEEvent
  | DesktopStatusSSEEvent
  | TerminalStartedSSEEvent
  | TerminalStoppedSSEEvent
  | TerminalStatusSSEEvent;

/**
 * Type guard to check if event is a specific type
 */
export function isSandboxEventType(
  event: BaseSandboxSSEEvent,
  type: SandboxEventType
): event is SandboxSSEEvent {
  return event.type === type;
}

/**
 * Type guard for sandbox_created event
 */
export function isSandboxCreatedEvent(
  event: SandboxSSEEvent
): event is SandboxCreatedSSEEvent {
  return event.type === "sandbox_created";
}

/**
 * Type guard for desktop_started event
 */
export function isDesktopStartedEvent(
  event: SandboxSSEEvent
): event is DesktopStartedSSEEvent {
  return event.type === "desktop_started";
}

/**
 * Type guard for terminal_started event
 */
export function isTerminalStartedEvent(
  event: SandboxSSEEvent
): event is TerminalStartedSSEEvent {
  return event.type === "terminal_started";
}
