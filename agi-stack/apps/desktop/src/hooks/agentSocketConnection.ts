import { useSyncExternalStore } from 'react';

/**
 * Module-level mirror of the agent socket's live connection state. App owns
 * the single socket instance; surfaces that cannot receive the connected flag
 * through props subscribe here instead. The snapshot defaults to connected so
 * a surface rendered without a socket hook keeps the previous enabled state.
 */
const listeners = new Set<() => void>();
let snapshot = true;

export function publishAgentSocketConnected(connected: boolean): void {
  if (snapshot === connected) return;
  snapshot = connected;
  for (const listener of listeners) listener();
}

export function subscribeAgentSocketConnected(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getAgentSocketConnectedSnapshot(): boolean {
  return snapshot;
}

export function useAgentSocketConnected(): boolean {
  return useSyncExternalStore(subscribeAgentSocketConnected, getAgentSocketConnectedSnapshot, () => true);
}
