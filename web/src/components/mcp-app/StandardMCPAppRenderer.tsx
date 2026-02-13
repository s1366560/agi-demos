/**
 * StandardMCPAppRenderer - Wraps the official @mcp-ui/client AppRenderer
 *
 * Uses the MCP Apps standard SDK for rendering MCP App UIs.
 * The sandbox proxy runs on the backend (different origin) for iframe security.
 *
 * Two client modes:
 * - Mode A (preferred): Direct WebSocket MCP client via `client` prop
 *   Browser <-> WS proxy <-> Sandbox MCP server (2 logical hops)
 * - Mode B (fallback): HTTP callback handlers when WS unavailable
 *   Browser <-> HTTP POST <-> Backend <-> WS <-> Sandbox (5 hops)
 *
 * Two rendering modes:
 * - html prop provided (SSE streaming): renders immediately, no fetch
 * - resourceUri provided (Open App / refresh): fetches HTML via backend proxy
 */

import React, { useMemo, useCallback, useState, useRef, useEffect, useImperativeHandle, forwardRef } from 'react';

import { Alert, Button, Spin } from 'antd';
import { RefreshCw } from 'lucide-react';

import { useMCPClient } from '@/hooks/useMCPClient';
import { mcpAppAPI } from '@/services/mcpAppService';
import { useThemeStore } from '@/stores/theme';

import type { MCPAppUIMetadata } from '@/types/mcpApp';

// Lazy import to avoid pulling @mcp-ui/client into the main bundle
// when MCP Apps are not used.
const LazyAppRenderer = React.lazy(async () => {
  const mod = await import('@mcp-ui/client');
  return { default: mod.AppRenderer };
});

/** Imperative handle exposed to parent for lifecycle management */
export interface StandardMCPAppRendererHandle {
  /** Call teardownResource() on the inner AppRenderer before unmounting */
  teardown: () => void;
}

export interface StandardMCPAppRendererProps {
  /** MCP tool name (required by AppRenderer) */
  toolName: string;
  /** Resource URI for deferred HTML fetching */
  resourceUri?: string;
  /** Pre-fetched HTML content (skips all fetching when provided) */
  html?: string;
  /** Tool input arguments */
  toolInput?: Record<string, unknown>;
  /** Tool execution result (loosely typed - cast to CallToolResult internally) */
  toolResult?: unknown;
  /** Project ID for backend proxy calls */
  projectId?: string;
  /** MCP server name (for proxy routing) */
  serverName?: string;
  /** MCP App ID (for efficient tool call proxy - avoids listing all apps) */
  appId?: string;
  /** UI metadata with CSP, permissions, and display preferences */
  uiMetadata?: MCPAppUIMetadata;
  /** Callback when the app sends a ui/message to add to conversation */
  onMessage?: (message: { role: string; content: { type: string; text: string } }) => void;
  /** Callback when the app updates model context via ui/update-model-context (SEP-1865) */
  onUpdateModelContext?: (context: Record<string, unknown>) => void;
  /** Callback when the app reports a size change */
  onSizeChanged?: (size: { width?: number; height?: number }) => void;
  /** Height of the container */
  height?: string | number;
}

/**
 * Get the sandbox proxy URL.
 * The proxy must be on a different origin from the frontend for iframe security.
 */
function getSandboxProxyUrl(): URL {
  const apiHost = import.meta.env.VITE_API_HOST || 'localhost:8000';
  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  return new URL(`${protocol}//${apiHost}/static/sandbox_proxy.html`);
}

export const StandardMCPAppRenderer = forwardRef<StandardMCPAppRendererHandle, StandardMCPAppRendererProps>(({
  toolName,
  resourceUri,
  html,
  toolInput,
  toolResult,
  projectId,
  serverName,
  appId,
  uiMetadata,
  onMessage,
  onUpdateModelContext,
  onSizeChanged,
  height = '100%',
}, ref) => {
  const [error, setError] = useState<string | null>(null);
  const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
  // Defer hostContext until the app bridge is connected to avoid
  // "Not connected" errors from @mcp-ui/client setHostContext.
  const [appInitialized, setAppInitialized] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Mode A: Direct WebSocket MCP client (low-latency, 2-hop)
  const { client: mcpClient, status: mcpStatus } = useMCPClient({
    projectId,
    enabled: !!projectId && !!serverName,
  });
  const useDirectClient = mcpClient !== null && mcpStatus === 'connected';
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const appRendererRef = useRef<any>(null);
  const computedTheme = useThemeStore((s) => s.computedTheme);

  // Expose teardown handle to parent for graceful cleanup (SEP-1865 ui/resource-teardown)
  useImperativeHandle(ref, () => ({
    teardown: () => {
      try {
        appRendererRef.current?.teardownResource?.();
      } catch {
        // Ignore errors during teardown
      }
    },
  }), []);

  // Track container dimensions via ResizeObserver for hostContext
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContainerSize({
          width: Math.round(entry.contentRect.width),
          height: Math.round(entry.contentRect.height),
        });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Mark app as initialized after the iframe has time to connect.
  // This defers hostContext delivery to avoid "Not connected" errors
  // from @mcp-ui/client's internal setHostContext → notification().
  useEffect(() => {
    const timer = setTimeout(() => setAppInitialized(true), 2000);
    return () => clearTimeout(timer);
  }, []);

  // Normalize: treat empty strings as undefined
  const effectiveHtml = html || undefined;
  const effectiveUri = resourceUri || undefined;

  const sandboxConfig = useMemo(
    () => ({
      url: getSandboxProxyUrl(),
      permissions: 'allow-scripts allow-same-origin allow-forms',
      // Forward CSP metadata to sandbox proxy for enforcement on inner iframe
      ...(uiMetadata?.csp ? { csp: uiMetadata.csp } : {}),
    }),
    [uiMetadata?.csp],
  );

  // Host context per SEP-1865: theme, styles, dimensions
  // Only provided after app initialization to avoid "Not connected" errors
  // from @mcp-ui/client's internal setHostContext → notification call.
  const hostContext = useMemo(
    () =>
      appInitialized
        ? {
            theme: computedTheme as 'light' | 'dark',
            platform: 'web' as const,
            userAgent: 'memstack',
            containerDimensions:
              containerSize.width > 0
                ? {
                    width: containerSize.width,
                    height: containerSize.height,
                    mode: 'flexible' as const,
                  }
                : undefined,
          }
        : undefined,
    [appInitialized, computedTheme, containerSize.width, containerSize.height],
  );

  // Handler for resources/read requests (when html prop is not provided)
  const handleReadResource = useCallback(
    async (params: { uri: string }) => {
      if (!projectId) {
        throw new Error('projectId required for resource fetching');
      }
      const result = await mcpAppAPI.readResource(params.uri, projectId, serverName);
      return result;
    },
    [projectId, serverName],
  );

  // Handler for tool calls from the guest app back to its MCP server
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleCallTool = useCallback(
    async (params: { name: string; arguments?: Record<string, unknown> }): Promise<any> => {
      if (!projectId) {
        throw new Error('projectId required for tool calls');
      }

      // For synthetic auto-discovered apps (no DB record), use the direct proxy
      // endpoint that routes by project_id + server_name without DB lookup.
      if (appId?.startsWith('auto-') && serverName) {
        const result = await mcpAppAPI.proxyToolCallDirect({
          project_id: projectId,
          server_name: serverName,
          tool_name: params.name,
          arguments: params.arguments || {},
        });
        return {
          content: result.content || [],
          isError: result.is_error,
        };
      }

      // Fast path: use appId directly if available (DB-backed app)
      if (appId) {
        const result = await mcpAppAPI.proxyToolCall(appId, {
          tool_name: params.name,
          arguments: params.arguments || {},
        });
        return {
          content: result.content || [],
          isError: result.is_error,
        };
      }

      // Fallback: find the app by server/tool name
      const apps = await mcpAppAPI.list(projectId);
      const app = apps.find((a) => a.server_name === serverName || a.tool_name === toolName);
      if (!app) {
        // Last resort: try direct proxy if we have a serverName
        if (serverName) {
          const result = await mcpAppAPI.proxyToolCallDirect({
            project_id: projectId,
            server_name: serverName,
            tool_name: params.name,
            arguments: params.arguments || {},
          });
          return {
            content: result.content || [],
            isError: result.is_error,
          };
        }
        return {
          content: [{ type: 'text' as const, text: `No app found for tool ${toolName}` }],
          isError: true,
        };
      }
      const result = await mcpAppAPI.proxyToolCall(app.id, {
        tool_name: params.name,
        arguments: params.arguments || {},
      });
      return {
        content: result.content || [],
        isError: result.is_error,
      };
    },
    [projectId, serverName, toolName, appId],
  );

  // Handler for resources/list requests from the guest app
  const handleListResources = useCallback(
    async () => {
      if (!projectId) {
        return { resources: [] };
      }
      try {
        return await mcpAppAPI.listResources(projectId, serverName);
      } catch {
        return { resources: [] };
      }
    },
    [projectId, serverName],
  );

  // Handler for ui/message from the app (SEP-1865 section: MCP Apps Specific Messages)
  // Also handles ui/update-model-context if the app sends context via the message channel.
  const handleMessage = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async (params: any) => {
      // Route ui/update-model-context
      if (params?.method === 'ui/update-model-context' && params?.context) {
        onUpdateModelContext?.(params.context);
        return {};
      }
      // Route regular ui/message
      if (onMessage && params?.content?.text) {
        onMessage({
          role: params.role || 'user',
          content: { type: 'text', text: params.content.text },
        });
      }
      return {};
    },
    [onMessage, onUpdateModelContext],
  );

  // Handler for ui/notifications/size-changed from the app (SEP-1865)
  const handleSizeChanged = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (params: any) => {
      onSizeChanged?.({ width: params?.width, height: params?.height });
    },
    [onSizeChanged],
  );

  const handleError = useCallback((err: Error) => {
    console.error('[StandardMCPAppRenderer] Error:', err);
    setError(err.message);
  }, []);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-4" style={{ height }}>
        <Alert
          type="error"
          message="Failed to load MCP App"
          description={error}
          showIcon
        />
        <Button
          icon={<RefreshCw size={14} />}
          onClick={() => setError(null)}
          size="small"
        >
          Retry
        </Button>
      </div>
    );
  }

  // AppRenderer requires either html, client, or (toolResourceUri + onReadResource).
  // If none is available, show tool result as fallback instead of crashing.
  if (!effectiveHtml && !effectiveUri) {
    return (
      <div className="h-full overflow-auto p-4" style={{ height }}>
        <Alert
          type="info"
          message={toolName}
          description="This MCP tool does not provide a UI resource. Showing tool result below."
          showIcon
          className="mb-3"
        />
        {toolResult != null && (
          <pre className="text-sm font-mono text-slate-700 dark:text-slate-300 whitespace-pre-wrap bg-slate-50 dark:bg-slate-900 rounded p-3">
            {typeof toolResult === 'string' ? toolResult : JSON.stringify(toolResult, null, 2)}
          </pre>
        )}
      </div>
    );
  }

  // Determine container border based on prefersBorder metadata
  const borderStyle = uiMetadata?.prefersBorder === false
    ? {}
    : { border: '1px solid var(--color-border-primary, #e2e8f0)', borderRadius: '6px' };

  return (
    <div ref={containerRef} style={{ height, width: '100%', position: 'relative', ...borderStyle }}>
      <React.Suspense
        fallback={
          <div className="flex items-center justify-center" style={{ height }}>
            <Spin tip="Loading MCP App...">
              <div style={{ minHeight: 100 }} />
            </Spin>
          </div>
        }
      >
        <LazyAppRenderer
          ref={appRendererRef}
          toolName={toolName}
          sandbox={sandboxConfig}
          html={effectiveHtml}
          toolResourceUri={effectiveUri}
          toolInput={toolInput}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          toolResult={toolResult as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          hostContext={hostContext as any}
          // Mode A: pass MCP client for direct WS communication
          // Mode B fallback: use HTTP callback handlers
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          client={useDirectClient ? mcpClient as any : undefined}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onReadResource={!useDirectClient && effectiveUri ? handleReadResource as any : undefined}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onCallTool={!useDirectClient ? handleCallTool as any : undefined}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onListResources={!useDirectClient ? handleListResources as any : undefined}
          // Host-specific handlers (always needed regardless of mode)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onMessage={handleMessage as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onSizeChanged={handleSizeChanged as any}
          onError={handleError}
          onOpenLink={async ({ url }) => {
            window.open(url, '_blank', 'noopener,noreferrer');
            return {};
          }}
        />
      </React.Suspense>
    </div>
  );
});
StandardMCPAppRenderer.displayName = 'StandardMCPAppRenderer';
