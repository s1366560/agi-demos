/**
 * React hook for creating and managing a browser MCP client connection.
 *
 * Creates a persistent WebSocket connection to the sandbox MCP server
 * via the backend proxy, wrapping it in the official MCP SDK Client.
 * Used with @mcp-ui/client AppRenderer's `client` prop (Mode A).
 */

import { useEffect, useRef, useState, useCallback } from 'react';

import { Client } from '@modelcontextprotocol/sdk/client/index.js';

import { BrowserWebSocketTransport } from '@/services/mcp/BrowserWebSocketTransport';
import { getWebSocketProtocol, getApiHost, getApiBasePath } from '@/services/sandboxWebSocketUtils';
import { useAuthStore } from '@/stores/auth';

export interface UseMCPClientOptions {
  /** Project ID to connect to */
  projectId?: string;
  /** Whether the connection should be active */
  enabled?: boolean;
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
 */
export function useMCPClient({
  projectId,
  enabled = true,
}: UseMCPClientOptions): UseMCPClientResult {
  const [client, setClient] = useState<Client | null>(null);
  const [status, setStatus] = useState<UseMCPClientResult['status']>('disconnected');
  const [error, setError] = useState<string | null>(null);
  const clientRef = useRef<Client | null>(null);
  const connectingRef = useRef(false);
  const token = useAuthStore((s) => s.token);

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
      setClient(null);
    }

    connectingRef.current = true;
    setStatus('connecting');
    setError(null);

    try {
      const url = buildMCPProxyUrl(projectId, token);
      const transport = new BrowserWebSocketTransport({ url });

      const mcpClient = new Client(
        { name: 'memstack-web', version: '1.0.0' },
        { capabilities: {} },
      );

      // Connect establishes WS + performs MCP initialize handshake
      await mcpClient.connect(transport);

      clientRef.current = mcpClient;
      setClient(mcpClient);
      setStatus('connected');

      // Handle disconnect
      transport.onclose = () => {
        if (clientRef.current === mcpClient) {
          clientRef.current = null;
          setClient(null);
          setStatus('disconnected');
        }
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setStatus('error');
      clientRef.current = null;
      setClient(null);
    } finally {
      connectingRef.current = false;
    }
  }, [projectId, token]);

  // Auto-connect when enabled and projectId available
  useEffect(() => {
    if (enabled && projectId && token) {
      connect();
    }

    return () => {
      // Cleanup on unmount or dependency change
      if (clientRef.current) {
        clientRef.current.close().catch(() => {});
        clientRef.current = null;
      }
    };
  }, [enabled, projectId, token, connect]);

  return {
    client,
    status,
    error,
    reconnect: connect,
  };
}
