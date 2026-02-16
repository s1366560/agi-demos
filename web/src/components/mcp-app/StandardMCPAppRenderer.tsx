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

import { useProjectStore } from '@/stores/project';
import { useThemeStore } from '@/stores/theme';
import { useAgentV3Store } from '@/stores/agentV3';

import { mcpAppAPI } from '@/services/mcpAppService';

import { useMCPClient } from '@/hooks/useMCPClient';

import { ErrorBoundary } from '@/components/common/ErrorBoundary';

import { buildHostStyles } from './hostStyles';

import type { MCPAppUIMetadata } from '@/types/mcpApp';

/**
 * Prefix for synthetic (auto-discovered) MCP App IDs that have no DB record.
 * Uses a non-colliding prefix to avoid clashing with real UUID-based app IDs.
 */
export const SYNTHETIC_APP_ID_PREFIX = '_synthetic_';

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
  /** Whether tool execution was cancelled (SEP-1865 ui/notifications/tool-cancelled) */
  toolCancelled?: boolean;
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
  toolCancelled,
  projectId,
  serverName,
  appId,
  uiMetadata,
  onMessage,
  onUpdateModelContext,
  onSizeChanged,
  height = '100%',
}, ref) => {
  // Fall back to current project from store when prop is not provided
  // Also try conversation's project_id as a second fallback (for page refresh scenarios)
  const storeProjectId = useProjectStore((state) => state.currentProject?.id);
  const conversationProjectId = useAgentV3Store((state) => state.currentConversation?.project_id);
  const effectiveProjectId = projectId || storeProjectId || conversationProjectId;

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
  const { client: mcpClient, status: mcpStatus, isInGracePeriod } = useMCPClient({
    projectId: effectiveProjectId,
    enabled: !!effectiveProjectId && !!serverName,
    reconnectionConfig: {
      maxAttempts: 5,
      initialDelayMs: 1000,
      maxDelayMs: 30000,
      gracePeriodMs: 3000, // 3 seconds grace period
    },
  });

  // Only use direct client if connected OR in grace period (prevents UI flickering)
  // During grace period, we keep using the last known good state
  const useDirectClient = mcpClient !== null && mcpStatus === 'connected';

  // Track if we've ever been connected to avoid showing mode B during initial connection
  const [everConnected, setEverConnected] = useState(false);

  useEffect(() => {
    if (mcpStatus === 'connected') {
      setEverConnected(true);
    }
  }, [mcpStatus]);

  // Determine if we should show Mode B (HTTP fallback)
  // Only switch to Mode B if:
  // 1. We're not connected
  // 2. We're NOT in grace period
  // 3. We've never been connected OR connection has failed completely
  const shouldUseFallback = !useDirectClient && !isInGracePeriod && (!everConnected || mcpStatus === 'error');
   
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

  // Mark app as initialized once the MCP client connects (Mode A) or
  // after a short fallback delay (Mode B / no direct client).
  // This defers hostContext delivery to avoid "Not connected" errors
  // from @mcp-ui/client's internal setHostContext -> notification().
  useEffect(() => {
    if (useDirectClient) {
      // Mode A: MCP client is already connected, initialize immediately
      setAppInitialized(true);
      return;
    }
    // Mode B: No direct client, use a short delay for iframe bridge setup
    const timer = setTimeout(() => setAppInitialized(true), 500);
    return () => clearTimeout(timer);
  }, [useDirectClient]);

  // Normalize: treat empty strings as undefined
  const effectiveHtml = html || undefined;
  const effectiveUri = resourceUri || undefined;

  const sandboxConfig = useMemo(
    () => ({
      url: getSandboxProxyUrl(),
      permissions: 'allow-scripts allow-same-origin allow-forms',
      // Forward CSP and permissions metadata to sandbox proxy for enforcement
      ...(uiMetadata?.csp ? { csp: uiMetadata.csp } : {}),
      ...(uiMetadata?.permissions ? { appPermissions: uiMetadata.permissions } : {}),
    }),
    [uiMetadata?.csp, uiMetadata?.permissions],
  );

  // SEP-1865 host styles: map Ant Design tokens to standardized CSS variables
  const hostStyles = useMemo(() => buildHostStyles(computedTheme), [computedTheme]);

  // Host context per SEP-1865: theme, styles, dimensions, display modes
  // Only provided after app initialization to avoid "Not connected" errors
  // from @mcp-ui/client's internal setHostContext -> notification call.
  // When hostContext prop changes, @mcp-ui/client sends ui/notifications/host-context-changed.
  const hostContext = useMemo(
    () =>
      appInitialized
        ? {
            theme: computedTheme as 'light' | 'dark',
            styles: hostStyles,
            platform: 'web' as const,
            userAgent: 'memstack',
            displayMode: 'inline' as const,
            availableDisplayModes: ['inline'],
            locale: navigator.language,
            timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            containerDimensions:
              containerSize.width > 0
                ? { width: containerSize.width, maxHeight: containerSize.height }
                : undefined,
          }
        : undefined,
    [appInitialized, computedTheme, hostStyles, containerSize.width, containerSize.height],
  );

  // Handler for resources/read requests (when html prop is not provided)
  const handleReadResource = useCallback(
    async (params: { uri: string }) => {
      if (!effectiveProjectId) {
        throw new Error('projectId required for resource fetching');
      }
      const result = await mcpAppAPI.readResource(params.uri, effectiveProjectId, serverName);
      return result;
    },
    [effectiveProjectId, serverName],
  );

  // Handler for tool calls from the guest app back to its MCP server

  const handleCallTool = useCallback(
    async (params: { name: string; arguments?: Record<string, unknown> }): Promise<any> => {
      if (!effectiveProjectId) {
        throw new Error('projectId required for tool calls');
      }

      // For synthetic auto-discovered apps (no DB record), use the direct proxy
      // endpoint that routes by project_id + server_name without DB lookup.
      if (appId?.startsWith(SYNTHETIC_APP_ID_PREFIX) && serverName) {
        // Log warning when using synthetic ID for diagnostics
        console.warn(
          `[StandardMCPAppRenderer] Using synthetic app ID "${appId}" for tool call. ` +
            `Attempting to find real app via server_name="${serverName}" tool_name="${params.name}"`
        );

        // Try to find real app by server_name + tool_name for better routing
        try {
          const apps = await mcpAppAPI.list(effectiveProjectId);
          const realApp = apps.find(
            (a) => a.server_name === serverName && a.tool_name === params.name
          );
          if (realApp) {
            console.info(
              `[StandardMCPAppRenderer] Found real app ID "${realApp.id}" for synthetic "${appId}", using real ID for tool call`
            );
            const result = await mcpAppAPI.proxyToolCall(realApp.id, {
              tool_name: params.name,
              arguments: params.arguments || {},
            });
            return {
              content: result.content || [],
              isError: result.is_error,
            };
          }
        } catch (err) {
          console.warn(
            `[StandardMCPAppRenderer] Failed to lookup real app for synthetic ID, falling back to direct proxy:`,
            err
          );
        }

        // Fallback to direct proxy if no real app found
        const result = await mcpAppAPI.proxyToolCallDirect({
          project_id: effectiveProjectId,
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
      const apps = await mcpAppAPI.list(effectiveProjectId);
      const app = apps.find((a) => a.server_name === serverName || a.tool_name === toolName);
      if (!app) {
        // Last resort: try direct proxy if we have a serverName
        if (serverName) {
          const result = await mcpAppAPI.proxyToolCallDirect({
            project_id: effectiveProjectId,
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
    [effectiveProjectId, serverName, toolName, appId],
  );

  // Handler for resources/list requests from the guest app
  const handleListResources = useCallback(
    async () => {
      if (!effectiveProjectId) {
        return { resources: [] };
      }
      try {
        return await mcpAppAPI.listResources(effectiveProjectId, serverName);
      } catch {
        return { resources: [] };
      }
    },
    [effectiveProjectId, serverName],
  );

  // Handler for ui/message from the app (SEP-1865 section: MCP Apps Specific Messages)
  // Also handles ui/update-model-context if the app sends context via the message channel.
  const handleMessage = useCallback(
     
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
      <ErrorBoundary context="MCP App" showHomeButton={false}>
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
          // Force re-mount when connection mode changes to avoid stale handlers
          // Use stable key during grace period to prevent UI flickering
          key={shouldUseFallback ? 'mode-b-http' : 'mode-a-ws'}
          ref={appRendererRef}
          toolName={toolName}
          sandbox={sandboxConfig}
          html={effectiveHtml}
          toolResourceUri={effectiveUri}
          toolInput={toolInput}
          toolCancelled={toolCancelled}

          toolResult={toolResult as any}

          hostContext={hostContext as any}
          // Mode A: pass MCP client for direct WS communication
          // Mode B fallback: use HTTP callback handlers

          client={!shouldUseFallback && mcpClient ? mcpClient as any : undefined}

          onReadResource={shouldUseFallback && effectiveUri ? handleReadResource as any : undefined}

          onCallTool={shouldUseFallback ? handleCallTool as any : undefined}

          onListResources={shouldUseFallback ? handleListResources as any : undefined}
          // Host-specific handlers (always needed regardless of mode)

          onMessage={handleMessage as any}

          onSizeChanged={handleSizeChanged as any}
          onError={handleError}
          onOpenLink={async ({ url }) => {
            window.open(url, '_blank', 'noopener,noreferrer');
            return {};
          }}
        />
        </React.Suspense>
      </ErrorBoundary>
    </div>
  );
});
StandardMCPAppRenderer.displayName = 'StandardMCPAppRenderer';
