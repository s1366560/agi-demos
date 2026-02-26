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

import React, {
  useMemo,
  useCallback,
  useState,
  useRef,
  useEffect,
  useImperativeHandle,
  forwardRef,
} from 'react';

import { Alert, Button, Spin } from 'antd';
import { RefreshCw } from 'lucide-react';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useProjectStore } from '@/stores/project';
import { useThemeStore } from '@/stores/theme';

import { mcpAppAPI } from '@/services/mcpAppService';

import { useMCPClient } from '@/hooks/useMCPClient';

import { ErrorBoundary } from '@/components/common/ErrorBoundary';

import { buildHostStyles } from './hostStyles';

import type { MCPAppUIMetadata, MCPAppDisplayMode } from '@/types/mcpApp';

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

/** Valid display modes for MCP App ui/request-display-mode handling */
const VALID_DISPLAY_MODES: readonly MCPAppDisplayMode[] = ['inline', 'fullscreen', 'pip'];

/** Imperative handle exposed to parent for lifecycle management */
export interface StandardMCPAppRendererHandle {
  /** Call teardownResource() on the inner AppRenderer before unmounting */
  teardown: () => void;
}

export interface StandardMCPAppRendererProps {
  /** MCP tool name (required by AppRenderer) */
  toolName: string;
  /** Resource URI for deferred HTML fetching */
  resourceUri?: string | undefined;
  /** Pre-fetched HTML content (skips all fetching when provided) */
  html?: string | undefined;
  /** Tool input arguments */
  toolInput?: Record<string, unknown> | undefined;
  /** Tool execution result (loosely typed - cast to CallToolResult internally) */
  toolResult?: unknown | undefined;
  /** Whether tool execution was cancelled (SEP-1865 ui/notifications/tool-cancelled) */
  toolCancelled?: boolean | undefined;
  /** Project ID for backend proxy calls */
  projectId?: string | undefined;
  /** MCP server name (for proxy routing) */
  serverName?: string | undefined;
  /** MCP App ID (for efficient tool call proxy - avoids listing all apps) */
  appId?: string | undefined;
  /** UI metadata with CSP, permissions, and display preferences */
  uiMetadata?: MCPAppUIMetadata | undefined;
  /** Callback when the app sends a ui/message to add to conversation */
  onMessage?: ((message: { role: string; content: { type: string; text: string } }) => void) | undefined;
  /** Callback when the app updates model context via ui/update-model-context (SEP-1865) */
  onUpdateModelContext?: ((context: Record<string, unknown>) => void) | undefined;
  /** Callback when the app reports a size change */
  onSizeChanged?: ((size: { width?: number | undefined; height?: number | undefined }) => void) | undefined;
  /** Height of the container */
  height?: string | number | undefined;
}

/**
 * Get the sandbox proxy URL.
 * The proxy must be on a different origin from the frontend for iframe security.
 */
function getSandboxProxyUrl(): URL {
  // Accept both host-only (localhost:8000) and full URL forms
  // (http://localhost:8000/api/v1) from env configs.
  const envApiTarget =
    import.meta.env.VITE_API_HOST ||
    (import.meta.env as { VITE_API_URL?: string | undefined }).VITE_API_URL ||
    (window.location.host.includes(':3000') ? 'localhost:8000' : window.location.host);
  const apiHost = envApiTarget.replace(/^[a-z]+:\/\//i, '').split('/')[0] || 'localhost:8000';
  const protocol = window.location.protocol === 'https:' ? 'https:' : 'http:';
  return new URL(`${protocol}//${apiHost}/static/sandbox_proxy.html`);
}

export const StandardMCPAppRenderer = forwardRef<
  StandardMCPAppRendererHandle,
  StandardMCPAppRendererProps
>(
  (
    {
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
    },
    ref
  ) => {
    // Fall back to current project from store when prop is not provided
    // Also try conversation's project_id as a second fallback (for page refresh scenarios)
    const storeProjectId = useProjectStore((state) => state.currentProject?.id);
    const conversationProjectId = useConversationsStore(
      (state) => state.currentConversation?.project_id
    );
    const effectiveProjectId = projectId || storeProjectId || conversationProjectId;

    const [error, setError] = useState<string | null>(null);
    const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({
      width: 0,
      height: 0,
    });
    // Defer hostContext until the app bridge is connected to avoid
    // "Not connected" errors from @mcp-ui/client setHostContext.
    const [appInitialized, setAppInitialized] = useState(false);
    const [displayMode, setDisplayMode] = useState<MCPAppDisplayMode>('inline');
    const containerRef = useRef<HTMLDivElement>(null);

    // Mode A: Direct WebSocket MCP client (low-latency, 2-hop)
    // Memoize reconnectionConfig to prevent reconnection loops
    const mcpClientReconnectionConfig = useMemo(
      () => ({
        maxAttempts: 5,
        initialDelayMs: 1000,
        maxDelayMs: 30000,
        gracePeriodMs: 3000, // 3 seconds grace period
      }),
      []
    );

    const {
      client: mcpClient,
      status: mcpStatus,
      isInGracePeriod,
    } = useMCPClient({
      projectId: effectiveProjectId,
      enabled: !!effectiveProjectId && !!serverName,
      reconnectionConfig: mcpClientReconnectionConfig,
    });

    // Only use direct client if connected OR in grace period (prevents UI flickering)
    // During grace period, we keep using the last known good state
    const useDirectClient = mcpClient !== null && mcpStatus === 'connected';

    // Determine if we should show Mode B (HTTP fallback)
    // Only switch to Mode B if:
    // 1. We're not connected AND not connecting (to avoid interrupting initial connection)
    // 2. We're NOT in grace period
    // 3. Connection has failed completely (status === 'error')
    const isConnecting = mcpStatus === 'connecting';
    const shouldUseFallback =
      !useDirectClient && !isInGracePeriod && !isConnecting && mcpStatus === 'error';
    const shouldUseHttpToolCall = shouldUseFallback || !mcpClient;

    const appRendererRef = useRef<any>(null);
    const computedTheme = useThemeStore((s) => s.computedTheme);

    // Expose teardown handle to parent for graceful cleanup (SEP-1865 ui/resource-teardown)
    useImperativeHandle(
      ref,
      () => ({
        teardown: () => {
          try {
            appRendererRef.current?.teardownResource?.();
          } catch {
            // Ignore errors during teardown
          }
        },
      }),
      []
    );

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
      return () => { observer.disconnect(); };
    }, []);

    // Defer hostContext until the sandbox bridge is connected to avoid
    // "Not connected" Promise rejections from @mcp-ui/client setHostContext.
    //
    // The bridge connects after: React.lazy bundle download + iframe load +
    // PROXY_READY handshake. On cold cache this can take 500-1000ms total.
    //
    // We reset appInitialized when appId/effectiveUri changes so a new app
    // opened with the stable key="mcp-app-renderer" properly re-initializes.
    //
    // We also set appInitialized=true immediately when the app sends a
    // size-change notification (handled in handleSizeChanged), giving an
    // early signal for apps that initialize quickly.
    useEffect(() => {
      setAppInitialized(false);

      if (useDirectClient) {
        // Mode A: WS client connected; iframe proxy handshake still needed.
        // 1500ms covers lazy-bundle load + proxy handshake on cold cache.
        const timer = setTimeout(() => { setAppInitialized(true); }, 1500);
        return () => { clearTimeout(timer); };
      }
      // Mode B: no direct client. 3000ms generous fallback for cold cache.
      // handleSizeChanged fires earlier when the app reports its size.
      const timer = setTimeout(() => { setAppInitialized(true); }, 3000);
      return () => { clearTimeout(timer); };
    }, [useDirectClient, appId, resourceUri]);

    // Normalize: treat empty strings as undefined
    const effectiveHtml = html || undefined;
    const effectiveUri =
      resourceUri ||
      uiMetadata?.resourceUri ||
      (uiMetadata as { resource_uri?: string | undefined } | undefined)?.resource_uri ||
      undefined;

    const sandboxConfig = useMemo(() => {
      const config: { url: URL; permissions: string; csp?: { connectDomains?: string[]; resourceDomains?: string[] } } = {
        url: getSandboxProxyUrl(),
        permissions: 'allow-scripts allow-same-origin allow-forms',
      };
      // Forward CSP metadata to sandbox proxy for enforcement
      if (uiMetadata?.csp) {
        const csp: { connectDomains?: string[]; resourceDomains?: string[] } = {};
        if (uiMetadata.csp.connectDomains) {
          csp.connectDomains = uiMetadata.csp.connectDomains;
        }
        if (uiMetadata.csp.resourceDomains) {
          csp.resourceDomains = uiMetadata.csp.resourceDomains;
        }
        config.csp = csp;
      }
      return config;
    }, [uiMetadata?.csp]);

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
              theme: computedTheme,
              styles: hostStyles,
              platform: 'web' as const,
              userAgent: 'memstack',
              displayMode: displayMode,
              availableDisplayModes: ['inline', 'fullscreen', 'pip'],
              locale: navigator.language,
              timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              containerDimensions:
                containerSize.width > 0
                  ? { width: containerSize.width, maxHeight: containerSize.height }
                  : undefined,
            }
          : undefined,
      [appInitialized, computedTheme, hostStyles, containerSize.width, containerSize.height, displayMode]
    );

    // Handler for resources/read requests (when html prop is not provided)
    // @mcp-ui/client expects the MCP format { contents: [{ uri, mimeType, text }] }
    // It will extract the text internally
    const handleReadResource = useCallback(
      async (params: { uri: string }) => {
        console.log('[StandardMCPAppRenderer] handleReadResource called:', {
          uri: params.uri,
          effectiveProjectId,
          serverName,
        });

        if (!effectiveProjectId) {
          const error = 'projectId required for resource fetching';
          console.error('[StandardMCPAppRenderer] handleReadResource error:', error);
          throw new Error(error);
        }

        try {
          const result = await mcpAppAPI.readResource(params.uri, effectiveProjectId, serverName);
          console.log('[StandardMCPAppRenderer] readResource result:', result);

          // Return the full MCP format - @mcp-ui/client will extract the text
          // The API returns { contents: [{ uri, mimeType, text }] }
          return result;
        } catch (err) {
          console.error('[StandardMCPAppRenderer] handleReadResource failed:', err);
          throw err;
        }
      },
      [effectiveProjectId, serverName]
    );

    // Handler for tool calls from the guest app back to its MCP server

    const handleCallTool = useCallback(
      async (params: { name: string; arguments?: Record<string, unknown> | undefined }): Promise<any> => {
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
      [effectiveProjectId, serverName, toolName, appId]
    );

    // Handler for resources/list requests from the guest app
    const handleListResources = useCallback(async () => {
      if (!effectiveProjectId) {
        return { resources: [] };
      }
      try {
        return await mcpAppAPI.listResources(effectiveProjectId, serverName);
      } catch {
        return { resources: [] };
      }
    }, [effectiveProjectId, serverName]);

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
      [onMessage, onUpdateModelContext]
    );

    // Handler for ui/notifications/size-changed from the app (SEP-1865)
    // Also fires immediately when the bridge is working — used as an early
    // "ready" signal to unblock hostContext delivery before the fallback timer.
    const handleSizeChanged = useCallback(
      (params: any) => {
        // Bridge is confirmed live: app can only send notifications after connect()
        setAppInitialized(true);
        onSizeChanged?.({ width: params?.width, height: params?.height });
      },
      [onSizeChanged]
    );

    const handleError = useCallback((err: Error) => {
      console.error('[StandardMCPAppRenderer] Error:', err);
      setError(err.message);
    }, []);

    // Debug log for props being passed to AppRenderer
    // MUST be called before any conditional returns to satisfy React hooks rules
    useEffect(() => {
      console.log('[StandardMCPAppRenderer] Props for AppRenderer:', {
        effectiveHtml: effectiveHtml ? `${effectiveHtml.slice(0, 50)}...` : undefined,
        effectiveUri,
        effectiveProjectId,
        serverName,
        hasOnReadResource: !!effectiveUri, // effectiveUri determines if onReadResource is provided
        hasClient: !!(effectiveHtml && !shouldUseFallback && mcpClient),
      });
    }, [effectiveHtml, effectiveUri, effectiveProjectId, serverName, shouldUseFallback, mcpClient]);

    // Listen for ui/request-display-mode JSON-RPC messages from MCP App iframes.
    // The @mcp-ui/client library does NOT expose a callback for this method,
    // so we handle it manually via the postMessage bridge.
    useEffect(() => {
      const handleDisplayModeRequest = (event: MessageEvent<unknown>): void => {
        // Only process object payloads that look like JSON-RPC
        if (typeof event.data !== 'object' || event.data === null) return;

        const data = event.data as Record<string, unknown>;
        if (data.jsonrpc !== '2.0' || data.method !== 'ui/request-display-mode') return;

        // Validate params.mode
        const params = data.params as Record<string, unknown> | undefined;
        const requestedMode = params?.mode;
        if (
          typeof requestedMode !== 'string' ||
          !VALID_DISPLAY_MODES.includes(requestedMode as MCPAppDisplayMode)
        ) {
          return;
        }

        // Update local state
        setDisplayMode(requestedMode as MCPAppDisplayMode);

        // Send JSON-RPC success response back to the source iframe
        if (event.source) {
          (event.source as Window).postMessage(
            {
              jsonrpc: '2.0',
              id: data.id,
              result: { mode: requestedMode },
            },
            event.origin
          );
        }
      };

      window.addEventListener('message', handleDisplayModeRequest);
      return () => {
        window.removeEventListener('message', handleDisplayModeRequest);
      };
    }, []);

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 p-4" style={{ height }}>
          <Alert type="error" title="Failed to load MCP App" description={error} showIcon />
          <Button icon={<RefreshCw size={14} />} onClick={() => { setError(null); }} size="small">
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
            title={toolName}
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
    const borderStyle =
      uiMetadata?.prefersBorder === false
        ? {}
        : { border: '1px solid var(--color-border-primary, #e2e8f0)', borderRadius: '6px' };

    return (
      <div
        ref={containerRef}
        style={{ height, width: '100%', position: 'relative', ...borderStyle }}
      >
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
              key="mcp-app-renderer"
              ref={appRendererRef}
              toolName={toolName}
              sandbox={sandboxConfig}
              {...(effectiveHtml != null ? { html: effectiveHtml } : {})}
              {...(effectiveUri != null ? { toolResourceUri: effectiveUri } : {})}
              {...(toolInput != null ? { toolInput } : {})}
              {...(toolCancelled != null ? { toolCancelled } : {})}
              {...(toolResult != null ? { toolResult: toolResult as any } : {})}
              {...(hostContext != null ? { hostContext: hostContext as any } : {})}
              {...(effectiveHtml && !shouldUseFallback && mcpClient
                ? { client: mcpClient as any }
                : {})}
              {...(effectiveUri ? { onReadResource: handleReadResource as any } : {})}
              {...(shouldUseHttpToolCall ? { onCallTool: handleCallTool as any } : {})}
              {...(shouldUseFallback ? { onListResources: handleListResources as any } : {})}
              onMessage={handleMessage as any}
              onSizeChanged={handleSizeChanged as any}
              onError={handleError}
              onOpenLink={async ({ url }) => {
                let parsedUrl: URL;
                try {
                  parsedUrl = new URL(url, window.location.origin);
                } catch {
                  return {};
                }
                if (!['http:', 'https:', 'mailto:'].includes(parsedUrl.protocol)) {
                  return {};
                }
                window.open(parsedUrl.toString(), '_blank', 'noopener,noreferrer');
                return {};
              }}
            />
          </React.Suspense>
        </ErrorBoundary>
      </div>
    );
  }
);
StandardMCPAppRenderer.displayName = 'StandardMCPAppRenderer';
