/**
 * React hook for creating and managing a browser MCP client connection.
 *
 * Creates a persistent WebSocket connection to the sandbox MCP server
 * via the backend proxy, wrapping it in the official MCP SDK Client.
 * Used with @mcp-ui/client AppRenderer's `client` prop (Mode A).
 *
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Grace period before reporting disconnection (prevents UI flickering)
 * - Connection stability tracking
 */

import { useEffect, useRef, useState, useCallback, useMemo } from 'react';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';

import { useAuthStore } from '@/stores/auth';

import { BrowserWebSocketTransport } from '@/services/mcp/BrowserWebSocketTransport';
import { getWebSocketProtocol, getApiHost, getApiBasePath } from '@/services/sandboxWebSocketUtils';

/** Configuration for reconnection behavior */
interface ReconnectionConfig {
  /** Maximum number of reconnection attempts before giving up */
  maxAttempts: number;
  /** Initial delay in ms before first reconnection attempt */
  initialDelayMs: number;
  /** Maximum delay in ms between reconnection attempts */
  maxDelayMs: number;
  /** Grace period in ms before reporting disconnection (prevents UI flickering) */
  gracePeriodMs: number;
}

/** Default reconnection configuration */
const DEFAULT_RECONNECTION_CONFIG: ReconnectionConfig = {
  maxAttempts: 5,
  initialDelayMs: 1000,
  maxDelayMs: 30000,
  gracePeriodMs: 3000, // 3 seconds grace period before reporting disconnect
};

export interface UseMCPClientOptions {
  /** Project ID to connect to */
  projectId?: string;
  /** Whether the connection should be active */
  enabled?: boolean;
  /** Custom reconnection configuration */
  reconnectionConfig?: Partial<ReconnectionConfig>;
}

export interface UseMCPClientResult {
  /** MCP SDK Client instance (pass to AppRenderer's client prop) */
  client: Client | null;
  /** Connection status */
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  /** Error message if connection failed */
  error: string | null;
  /** Manually reconnect */
  reconnect: () => void;
  /** Whether currently in grace period (connection lost but not yet reported) */
  isInGracePeriod: boolean;
}

/**
 * Build the WebSocket URL for the MCP proxy endpoint.
 */
function buildMCPProxyUrl(projectId: string, token: string): string {
  const protocol = getWebSocketProtocol();
  const host = getApiHost();
  const basePath = getApiBasePath();
  return `${protocol}//${host}${basePath}/projects/${projectId}/sandbox/mcp/proxy?token=${encodeURIComponent(token)}`;
}

/**
 * Hook that creates and manages a persistent MCP SDK Client connected
 * to the sandbox MCP server via WebSocket proxy.
 *
 * The client auto-connects when projectId is provided and enabled=true,
 * and auto-disconnects on unmount or when disabled.
 *
 * Includes a grace period mechanism to prevent UI flickering during
 * brief connection interruptions.
 */
export function useMCPClient({
  projectId,
  enabled = true,
  reconnectionConfig: customReconnectionConfig,
}: UseMCPClientOptions): UseMCPClientResult {
  const reconnectionConfig = useMemo(
    () => ({
      ...DEFAULT_RECONNECTION_CONFIG,
      ...customReconnectionConfig,
    }),
    [customReconnectionConfig]
  );

  const [client, setClient] = useState<Client | null>(null);
  const [status, setStatus] = useState<UseMCPClientResult['status']>('disconnected');
  const [error, setError] = useState<string | null>(null);
  const [isInGracePeriod, setIsInGracePeriod] = useState(false);

  const clientRef = useRef<Client | null>(null);
  const connectingRef = useRef(false);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gracePeriodTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastConnectedStatusRef = useRef<boolean>(false);
  // Use ref for isInGracePeriod to avoid circular dependency in connect callback
  const isInGracePeriodRef = useRef(false);
  isInGracePeriodRef.current = isInGracePeriod;

  const token = useAuthStore((s) => s.token);

  /**
   * Clear all pending timers
   */
  const clearTimers = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (gracePeriodTimeoutRef.current) {
      clearTimeout(gracePeriodTimeoutRef.current);
      gracePeriodTimeoutRef.current = null;
    }
  }, []);

  /**
   * Calculate backoff delay with exponential increase
   */
  const calculateBackoffDelay = useCallback((attempt: number): number => {
    const { initialDelayMs, maxDelayMs } = reconnectionConfig;
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s...
    const delay = initialDelayMs * Math.pow(2, attempt);
    return Math.min(delay, maxDelayMs);
  }, [reconnectionConfig]);

  /**
   * Start the grace period before reporting disconnection
   * This prevents UI flickering during brief connection interruptions
   */
  const startGracePeriod = useCallback(() => {
    // Clear any existing grace period timer
    if (gracePeriodTimeoutRef.current) {
      clearTimeout(gracePeriodTimeoutRef.current);
    }

    setIsInGracePeriod(true);

    gracePeriodTimeoutRef.current = setTimeout(() => {
      // Grace period expired, report disconnection
      setIsInGracePeriod(false);
      setStatus('disconnected');
      setClient(null);
      lastConnectedStatusRef.current = false;
    }, reconnectionConfig.gracePeriodMs);
  }, [reconnectionConfig.gracePeriodMs]);

  /**
   * Cancel grace period (connection restored)
   */
  const cancelGracePeriod = useCallback(() => {
    if (gracePeriodTimeoutRef.current) {
      clearTimeout(gracePeriodTimeoutRef.current);
      gracePeriodTimeoutRef.current = null;
    }
    setIsInGracePeriod(false);
  }, []);

  /**
   * Schedule a reconnection attempt with exponential backoff
   */
  const scheduleReconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      return; // Already scheduled
    }

    const { maxAttempts } = reconnectionConfig;
    if (reconnectAttemptsRef.current >= maxAttempts) {
      console.warn(`[useMCPClient] Max reconnection attempts (${maxAttempts}) reached`);
      setStatus('error');
      setError('Connection lost and reconnection failed');
      return;
    }

    const delay = calculateBackoffDelay(reconnectAttemptsRef.current);
    reconnectAttemptsRef.current++;

    console.log(
      `[useMCPClient] Scheduling reconnect attempt ${reconnectAttemptsRef.current}/${maxAttempts} in ${delay}ms`
    );

    reconnectTimeoutRef.current = setTimeout(() => {
      reconnectTimeoutRef.current = null;
      // Trigger reconnection by calling connect again
      // Note: connect is intentionally omitted from deps to avoid circular dependency
      connect();
    }, delay);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reconnectionConfig, calculateBackoffDelay]);

  /**
   * Main connection function
   */
  const connect = useCallback(async () => {
    if (!projectId || !token || connectingRef.current) return;

    // Cleanup existing connection
    if (clientRef.current) {
      try {
        await clientRef.current.close();
      } catch {
        // Ignore close errors
      }
      clientRef.current = null;
    }

    connectingRef.current = true;

    // Only set connecting status if we're not in grace period
    if (!isInGracePeriodRef.current) {
      setStatus('connecting');
    }
    setError(null);

    try {
      const url = buildMCPProxyUrl(projectId, token);
      const transport = new BrowserWebSocketTransport({ url });

      const mcpClient = new Client(
        { name: 'memstack-web', version: '1.0.0' },
        { capabilities: {} },
      );

      // Set onclose BEFORE connect to avoid missing early disconnects
      transport.onclose = () => {
        if (clientRef.current === mcpClient) {
          console.log('[useMCPClient] Transport closed, starting grace period');

          // Start grace period instead of immediately reporting disconnect
          startGracePeriod();

          // Schedule reconnection attempt
          scheduleReconnect();
        }
      };

      // Connect establishes WS + performs MCP initialize handshake.
      // Wrap in a race with a timeout to avoid hanging on slow handshakes.
      const CONNECT_TIMEOUT_MS = 20_000;
      await Promise.race([
        mcpClient.connect(transport),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('MCP connect timeout')), CONNECT_TIMEOUT_MS),
        ),
      ]);

      clientRef.current = mcpClient;
      setClient(mcpClient);
      setStatus('connected');
      setError(null);
      lastConnectedStatusRef.current = true;

      // Cancel any grace period since we're connected
      cancelGracePeriod();

      // Reset reconnect attempts on successful connection
      reconnectAttemptsRef.current = 0;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      console.error('[useMCPClient] Connection error:', message);

      // Only update status if not in grace period
      if (!isInGracePeriodRef.current) {
        setError(message);
        setStatus('error');
      }
      clientRef.current = null;
      setClient(null);
      lastConnectedStatusRef.current = false;

      // Schedule reconnection on error
      scheduleReconnect();
    } finally {
      connectingRef.current = false;
    }
  }, [projectId, token, startGracePeriod, cancelGracePeriod, scheduleReconnect]);

  /**
   * Manual reconnect function
   */
  const reconnect = useCallback(() => {
    // Reset attempts for manual reconnect
    reconnectAttemptsRef.current = 0;
    clearTimers();
    cancelGracePeriod();
    connect();
  }, [connect, clearTimers, cancelGracePeriod]);

  // Auto-connect when enabled and projectId available
  useEffect(() => {
    if (enabled && projectId && token) {
      connect();
    }

    return () => {
      // Cleanup on unmount or dependency change
      clearTimers();
      cancelGracePeriod();
      if (clientRef.current) {
        clientRef.current.close().catch(() => {});
        clientRef.current = null;
      }
    };
  }, [enabled, projectId, token, connect, clearTimers, cancelGracePeriod]);

  return {
    client,
    status,
    error,
    reconnect,
    isInGracePeriod,
  };
}
