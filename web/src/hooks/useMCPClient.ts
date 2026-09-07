import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';

import {
  MCPAppRetainedSessionV2,
  emptyMCPSnapshotV2,
  type MCPAppSessionOptionsV2,
  type MCPAppSessionSnapshotV2,
} from '@/services/mcp/MCPAppRetainedSessionV2';

import {
  getWebOperationAvailabilityV2,
  subscribeWebOperationAvailabilityV2,
  type WebOperationContextV2,
} from '@/plugins/webOperationAdmissionV2';

export interface ReconnectionConfig {
  maxAttempts: number;
  initialDelayMs: number;
  maxDelayMs: number;
  gracePeriodMs: number;
}
export interface UseMCPClientOptions {
  projectId?: string | undefined;
  appId?: string | undefined;
  serverName?: string | undefined;
  toolName?: string | undefined;
  resourceUri?: string | undefined;
  enabled?: boolean | undefined;
  reconnectionConfig?: Partial<ReconnectionConfig> | undefined;
  onAdmitted?: MCPAppSessionOptionsV2['onAdmitted'];
}
export interface UseMCPClientResult extends MCPAppSessionSnapshotV2 {
  reconnect: () => Promise<void>;
  assertFallback: () => WebOperationContextV2;
}
export function useMCPClient(options: UseMCPClientOptions): UseMCPClientResult {
  const availability = useSyncExternalStore(
    subscribeWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2,
    getWebOperationAvailabilityV2
  );
  const {
    projectId,
    appId,
    serverName,
    toolName,
    resourceUri,
    enabled = true,
    reconnectionConfig,
  } = options;
  const maxAttempts = reconnectionConfig?.maxAttempts ?? 5,
    initialDelayMs = reconnectionConfig?.initialDelayMs ?? 1000,
    maxDelayMs = reconnectionConfig?.maxDelayMs ?? 30000,
    gracePeriodMs = reconnectionConfig?.gracePeriodMs ?? 3000;
  const identity = useMemo(
    () => ({
      owner: availability.owner,
      projectId,
      appId,
      serverName,
      toolName,
      resourceUri,
      enabled,
      maxAttempts,
      initialDelayMs,
      maxDelayMs,
      gracePeriodMs,
    }),
    [
      availability.owner,
      projectId,
      appId,
      serverName,
      toolName,
      resourceUri,
      enabled,
      maxAttempts,
      initialDelayMs,
      maxDelayMs,
      gracePeriodMs,
    ]
  );
  const callbacks = useRef(options);
  useLayoutEffect(() => {
    callbacks.current = options;
  });
  const current = useRef<{ identity: object; session: MCPAppRetainedSessionV2 } | null>(null);
  const [view, setView] = useState<{ identity: object; snapshot: MCPAppSessionSnapshotV2 }>({
    identity,
    snapshot: emptyMCPSnapshotV2,
  });
  useLayoutEffect(() => {
    if (!identity.projectId || !availability.available) return;
    let active = true;
    const session = new MCPAppRetainedSessionV2({
      ...identity,
      projectId: identity.projectId,
      onAdmitted: callbacks.current.onAdmitted,
      changed: (snapshot) => {
        if (active) setView({ identity, snapshot });
      },
    });
    current.current = { identity, session };
    return () => {
      active = false;
      void session.disconnect().catch(() => undefined);
      if (current.current?.session === session) current.current = null;
    };
  }, [identity, availability.available]);
  const reconnect = useCallback(() => {
    const value = current.current;
    if (value?.identity !== identity)
      return Promise.reject(new DOMException('MCP App retired', 'AbortError'));
    return value.session.reconnect();
  }, [identity]);
  const assertFallback = useCallback(() => {
    const value = current.current;
    if (value?.identity !== identity) throw new DOMException('MCP App retired', 'AbortError');
    return value.session.assertFallback();
  }, [identity]);
  return {
    ...(view.identity === identity ? view.snapshot : emptyMCPSnapshotV2),
    reconnect,
    assertFallback,
  };
}
