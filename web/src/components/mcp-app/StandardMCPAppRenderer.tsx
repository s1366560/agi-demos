import React, {
  useMemo,
  useCallback,
  useState,
  useRef,
  useEffect,
  useLayoutEffect,
  useImperativeHandle,
  forwardRef,
} from 'react';

import ReactDOM from 'react-dom';
import { useTranslation } from 'react-i18next';

import { Alert, Button } from 'antd';
import { RefreshCw } from 'lucide-react';

import { useConversationsStore } from '@/stores/agent/conversationsStore';
import { useProjectStore } from '@/stores/project';
import { useThemeStore } from '@/stores/theme';

import { mcpAppAPI } from '@/services/mcpAppService';

import { useMCPClient } from '@/hooks/useMCPClient';

import { logger } from '@/utils/logger';

import { ErrorBoundary } from '@/components/common/ErrorBoundary';
import { Spinner } from '@/components/common/Spinner';

import { buildHostStyles } from './hostStyles';
import { callMcpAppHttpSessionV2 } from './mcpAppHttpSessionV2';
import {
  isRecord,
  toCallToolResult,
  getMessageText,
  getMessageRole,
  getSandboxProxyUrl,
  getMcpAppRenderKeyV2,
} from './mcpAppRendererProtocolV2';
import { useMcpAppFrameSessionV2 } from './useMcpAppFrameSessionV2';

import type {
  MCPAppUIMetadata,
  MCPAppDisplayMode,
  MCPAppCapabilities,
  MCPAppTool,
} from '@/types/mcpApp';

import type { AppRendererHandle, AppRendererProps, McpUiHostContext } from '@mcp-ui/client';

// Synthetic IDs are a declared wire identifier namespace.
export const SYNTHETIC_APP_ID_PREFIX = '_synthetic_';

const LazyAppRenderer = React.lazy(async () => {
  const mod = await import('./ControlledMCPAppRendererV2');
  return { default: mod.default };
});

type AppMessageHandler = NonNullable<AppRendererProps['onMessage']>;
type AppSizeChangedHandler = NonNullable<AppRendererProps['onSizeChanged']>;
type AppOpenLinkHandler = NonNullable<AppRendererProps['onOpenLink']>;

export interface StandardMCPAppRendererHandle {
  teardown: () => void;
  listAppTools: () => Promise<MCPAppTool[]>;
  callAppTool: (name: string, args?: Record<string, unknown>) => Promise<unknown>;
}

export interface StandardMCPAppRendererProps {
  toolName: string;
  resourceUri?: string | undefined;
  html?: string | undefined;
  toolInput?: Record<string, unknown> | undefined;
  toolResult?: unknown;
  toolCancelled?: boolean | undefined;
  projectId?: string | undefined;
  serverName?: string | undefined;
  appId?: string | undefined;
  uiMetadata?: MCPAppUIMetadata | undefined;
  onMessage?:
    | ((message: { role: string; content: { type: string; text: string } }) => void)
    | undefined;
  onUpdateModelContext?: ((context: Record<string, unknown>) => void) | undefined;
  onSizeChanged?:
    | ((size: { width?: number | undefined; height?: number | undefined }) => void)
    | undefined;
  height?: string | number | undefined;
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
    const { t } = useTranslation();
    const translate = useCallback(
      (key: string, fallback: string) => {
        const value = t(key, fallback);
        return value === key ? fallback : value;
      },
      [t]
    );
    const storeProjectId = useProjectStore((state) => state.currentProject?.id);
    const conversationProjectId = useConversationsStore(
      (state) => state.currentConversation?.project_id
    );
    const effectiveProjectId = projectId || conversationProjectId || storeProjectId;

    const [error, setError] = useState<string | null>(null);
    const [containerSize, setContainerSize] = useState<{ width: number; height: number }>({
      width: 0,
      height: 0,
    });
    const [appInitialized, setAppInitialized] = useState(false);
    const [displayMode, setDisplayMode] = useState<MCPAppDisplayMode>('inline');
    const fullscreenExitRef = useRef<HTMLButtonElement>(null);

    useEffect(() => {
      if (displayMode !== 'fullscreen') return undefined;
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          setDisplayMode('inline');
        }
      };
      document.addEventListener('keydown', handleKeyDown);
      fullscreenExitRef.current?.focus();
      return () => {
        document.removeEventListener('keydown', handleKeyDown);
      };
    }, [displayMode]);
    const containerRef = useRef<HTMLDivElement>(null);

    const [appCapabilities, setAppCapabilities] = useState<MCPAppCapabilities | null>(null);

    const frameCleanup = useRef<() => void>(() => {});
    const frameOwner = useRef<unknown>(null);
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
      operation,
      canFallback,
      assertFallback,
      retired,
    } = useMCPClient({
      projectId: effectiveProjectId,
      appId,
      serverName,
      toolName,
      resourceUri:
        resourceUri ||
        uiMetadata?.resourceUri ||
        (uiMetadata as { resource_uri?: string } | undefined)?.resource_uri,
      onAdmitted: (admitted) => () => {
        if (frameOwner.current !== admitted) return;
        frameCleanup.current();
        containerRef.current?.querySelectorAll('iframe').forEach((frame) => {
          frame.src = 'about:blank';
        });
      },
      enabled: !!effectiveProjectId && !!serverName,
      reconnectionConfig: mcpClientReconnectionConfig,
    });

    const useDirectClient = mcpClient !== null && mcpStatus === 'connected';

    const shouldUseFallback = canFallback && !retired;
    const shouldUseHttpToolCall = shouldUseFallback;
    const requireOperation = useCallback(() => {
      if (!operation || retired) throw new DOMException('MCP app session retired', 'AbortError');
      operation.check();
      return operation;
    }, [operation, retired]);
    const requireFallback = useCallback(() => {
      requireOperation();
      const active = assertFallback();
      if (active !== operation) throw new DOMException('MCP app session replaced', 'AbortError');
    }, [requireOperation, assertFallback, operation]);
    const appRendererRef = useRef<AppRendererHandle | null>(null);
    const computedTheme = useThemeStore((s) => s.computedTheme);

    const {
      sendRpc: sendRpcToApp,
      notify: sendNotificationToApp,
      clear: clearFrameRequests,
    } = useMcpAppFrameSessionV2(operation, containerRef, setAppCapabilities, setDisplayMode);
    useLayoutEffect(() => {
      frameCleanup.current = clearFrameRequests;
      frameOwner.current = operation;
      return () => {
        if (frameOwner.current === operation) frameOwner.current = null;
      };
    }, [clearFrameRequests, operation]);
    useEffect(() => {
      if (toolResult != null && appInitialized) {
        sendNotificationToApp('ui/notifications/tool-result-chunk', {
          toolName,
          chunk: toolResult,
        });
      }
    }, [toolResult, appInitialized, toolName, sendNotificationToApp]);

    useImperativeHandle(
      ref,
      () => ({
        teardown: () => {
          clearFrameRequests();
          try {
            requireOperation();
            void Promise.resolve(appRendererRef.current?.teardownResource()).catch(() => {
              /* A retired app may reject teardown. */
            });
          } catch {
            /* An already-retired bridge needs no teardown notification. */
          }
        },
        listAppTools: async (): Promise<MCPAppTool[]> => {
          requireOperation();
          if (!appCapabilities?.tools) return [];
          try {
            const result = await sendRpcToApp('tools/list');
            const data = result as { tools?: MCPAppTool[] } | undefined;
            return data?.tools ?? [];
          } catch (err) {
            requireOperation();
            console.error('[StandardMCPAppRenderer] listAppTools failed:', err);
            return [];
          }
        },
        callAppTool: async (name: string, args?: Record<string, unknown>): Promise<unknown> => {
          requireOperation();
          if (!appCapabilities?.tools) {
            throw new Error('App does not declare tools capability');
          }
          return sendRpcToApp('tools/call', { name, arguments: args ?? {} });
        },
      }),
      [appCapabilities, sendRpcToApp, requireOperation, clearFrameRequests]
    );

    useEffect(() => {
      const el = containerRef.current;
      if (!el || !operation) return;
      const observer = new ResizeObserver((entries) => {
        try {
          operation.check();
        } catch {
          return;
        }
        const entry = entries[0];
        if (entry) {
          setContainerSize({
            width: Math.round(entry.contentRect.width),
            height: Math.round(entry.contentRect.height),
          });
        }
      });
      observer.observe(el);
      const stop = () => {
        observer.disconnect();
      };
      operation.signal.addEventListener('abort', stop, { once: true });
      return () => {
        operation.signal.removeEventListener('abort', stop);
        observer.disconnect();
      };
    }, [operation]);

    useLayoutEffect(() => {
      setAppInitialized(false);
      setError(null);
      setAppCapabilities(null);
    }, [appId, resourceUri, operation]);
    const handleInitialized = useCallback(() => {
      try {
        requireOperation();
      } catch {
        return;
      }
      setAppInitialized(true);
    }, [requireOperation]);

    const effectiveHtml = html || undefined;
    const effectiveUri =
      resourceUri ||
      uiMetadata?.resourceUri ||
      (uiMetadata as { resource_uri?: string | undefined } | undefined)?.resource_uri ||
      undefined;

    const sandboxConfig = useMemo(() => {
      const config: {
        url: URL;
        permissions: string;
        csp?: {
          connectDomains?: string[];
          resourceDomains?: string[];
          frameDomains?: string[];
          baseUriDomains?: string[];
        };
      } = {
        url: getSandboxProxyUrl(),
        permissions: 'allow-scripts allow-same-origin allow-forms',
      };
      if (uiMetadata?.csp) {
        const csp: {
          connectDomains?: string[];
          resourceDomains?: string[];
          frameDomains?: string[];
          baseUriDomains?: string[];
        } = {};
        if (uiMetadata.csp.connectDomains) {
          csp.connectDomains = uiMetadata.csp.connectDomains;
        }
        if (uiMetadata.csp.resourceDomains) {
          csp.resourceDomains = uiMetadata.csp.resourceDomains;
        }
        if (uiMetadata.csp.frameDomains) {
          csp.frameDomains = uiMetadata.csp.frameDomains;
        }
        if (uiMetadata.csp.baseUriDomains) {
          csp.baseUriDomains = uiMetadata.csp.baseUriDomains;
        }
        config.csp = csp;
      }
      return config;
    }, [uiMetadata?.csp]);

    const iframeAllowPolicy = useMemo(() => {
      const permissions = uiMetadata?.permissions;
      if (!permissions) return '';
      const policies: string[] = [];
      if (permissions.camera !== undefined) policies.push('camera');
      if (permissions.microphone !== undefined) policies.push('microphone');
      if (permissions.geolocation !== undefined) policies.push('geolocation');
      if (permissions.clipboardWrite !== undefined) policies.push('clipboard-write');
      return policies.join('; ');
    }, [uiMetadata?.permissions]);

    useEffect(() => {
      if (!iframeAllowPolicy || !containerRef.current || !operation) return;
      const applyAllow = (): void => {
        try {
          operation.check();
        } catch {
          return;
        }
        const iframes = containerRef.current?.querySelectorAll('iframe');
        iframes?.forEach((iframe) => {
          if (iframe.allow !== iframeAllowPolicy) {
            iframe.allow = iframeAllowPolicy;
          }
        });
      };
      applyAllow();
      const observer = new MutationObserver(() => {
        applyAllow();
      });
      observer.observe(containerRef.current, { childList: true, subtree: true });
      const stop = () => {
        observer.disconnect();
      };
      operation.signal.addEventListener('abort', stop, { once: true });
      return () => {
        operation.signal.removeEventListener('abort', stop);
        observer.disconnect();
      };
    }, [iframeAllowPolicy, operation]);

    const hostStyles = useMemo(() => buildHostStyles(computedTheme), [computedTheme]);

    const hostContext = useMemo<McpUiHostContext | undefined>(() => {
      if (!appInitialized) return undefined;

      const containerDimensions =
        containerSize.width > 0
          ? ({
              width: containerSize.width,
              maxHeight: containerSize.height,
            } satisfies NonNullable<McpUiHostContext['containerDimensions']>)
          : undefined;

      return {
        theme: computedTheme,
        styles: hostStyles as NonNullable<McpUiHostContext['styles']>,
        platform: 'web' as const,
        userAgent: 'memstack',
        displayMode: displayMode,
        availableDisplayModes: ['inline', 'fullscreen', 'pip'],
        locale: navigator.language,
        timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        hostCapabilities: {
          openLinks: {},
          serverTools: { listChanged: false },
          serverResources: { listChanged: false },
          logging: {},
        },
        ...(containerDimensions ? { containerDimensions } : {}),
      };
    }, [
      appInitialized,
      computedTheme,
      hostStyles,
      containerSize.width,
      containerSize.height,
      displayMode,
    ]);

    const handleReadResource = useCallback<NonNullable<AppRendererProps['onReadResource']>>(
      async (params) => {
        const parent = requireOperation();
        if (!effectiveProjectId) throw new Error('projectId required for resource fetching');
        return parent.runChild(async (child) => {
          child.check();
          const result = await mcpAppAPI.readResource(params.uri, effectiveProjectId, serverName, {
            operation: child,
            signal: child.signal,
          });
          child.check();
          return result;
        });
      },
      [requireOperation, effectiveProjectId, serverName]
    );
    const handleCallTool = useCallback<NonNullable<AppRendererProps['onCallTool']>>(
      async (params) => {
        requireFallback();
        const parent = requireOperation();
        if (!effectiveProjectId) throw new Error('projectId required for tool calls');
        return callMcpAppHttpSessionV2(
          parent,
          { projectId: effectiveProjectId, serverName, appId, toolName },
          params,
          requireFallback,
          translate('common.notFound', 'Not Found')
        );
      },
      [
        requireFallback,
        requireOperation,
        effectiveProjectId,
        serverName,
        appId,
        toolName,
        translate,
      ]
    );
    const handleListResources = useCallback<
      NonNullable<AppRendererProps['onListResources']>
    >(async () => {
      requireFallback();
      const parent = requireOperation();
      if (!effectiveProjectId) throw new Error('projectId required for resources');
      return parent.runChild(async (child) => {
        child.check();
        const result = await mcpAppAPI.listResources(effectiveProjectId, serverName, {
          operation: child,
          signal: child.signal,
        });
        child.check();
        return {
          resources: result.resources.map((resource) => ({
            ...resource,
            name: resource.name ?? resource.uri,
          })),
        };
      });
    }, [requireFallback, requireOperation, effectiveProjectId, serverName]);

    const handleMessage: AppMessageHandler = useCallback(
      (params: unknown) => {
        requireOperation();
        if (isRecord(params) && params.method === 'ui/update-model-context') {
          const context: unknown = params.context;
          if (isRecord(context)) {
            onUpdateModelContext?.(context);
          }
          return Promise.resolve({});
        }
        if (onMessage) {
          const text = getMessageText(params);
          if (text) {
            onMessage({
              role: getMessageRole(params),
              content: { type: 'text', text },
            });
          }
        }
        return Promise.resolve({});
      },
      [onMessage, onUpdateModelContext, requireOperation]
    );

    const handleSizeChanged = useCallback<AppSizeChangedHandler>(
      (params) => {
        try {
          requireOperation();
        } catch {
          return;
        }
        onSizeChanged?.({ width: params.width, height: params.height });
      },
      [onSizeChanged, requireOperation]
    );

    const handleOpenLink = useCallback<AppOpenLinkHandler>(
      ({ url }) => {
        requireOperation();
        let parsedUrl: URL;
        try {
          parsedUrl = new URL(url, window.location.origin);
        } catch {
          return Promise.resolve({});
        }
        if (!['http:', 'https:', 'mailto:'].includes(parsedUrl.protocol)) {
          return Promise.resolve({});
        }
        window.open(parsedUrl.toString(), '_blank', 'noopener,noreferrer');
        return Promise.resolve({});
      },
      [requireOperation]
    );

    const handleError = useCallback(
      (err: Error) => {
        try {
          requireOperation();
        } catch {
          return;
        }
        console.error('[StandardMCPAppRenderer] Error:', err);
        setError(err.message);
      },
      [requireOperation]
    );

    useEffect(() => {
      logger.debug('[StandardMCPAppRenderer] Props for AppRenderer:', {
        effectiveHtml: effectiveHtml ? `${effectiveHtml.slice(0, 50)}...` : undefined,
        effectiveUri,
        effectiveProjectId,
        serverName,
        hasOnReadResource: !!effectiveUri, // effectiveUri determines if onReadResource is provided
        hasClient: !!(!shouldUseFallback && mcpClient),
      });
    }, [effectiveHtml, effectiveUri, effectiveProjectId, serverName, shouldUseFallback, mcpClient]);

    if (!operation || retired) return <Spinner />;

    if (error) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 p-4" style={{ height }}>
          <Alert
            type="error"
            title={translate('components.mcpApp.renderer.loadFailed', 'Failed to load MCP App')}
            description={error}
            showIcon
          />
          <Button
            icon={<RefreshCw size={14} />}
            onClick={() => {
              setError(null);
            }}
            size="small"
          >
            {translate('common.retry', 'Retry')}
          </Button>
        </div>
      );
    }

    if (!effectiveHtml && !effectiveUri) {
      return (
        <div className="h-full overflow-auto p-4" style={{ height }}>
          <Alert
            type="info"
            title={toolName}
            description={translate(
              'components.mcpApp.renderer.noUiResource',
              'This MCP tool does not provide a UI resource. Showing tool result below.'
            )}
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

    const borderStyle =
      uiMetadata?.prefersBorder === false
        ? {}
        : { border: '1px solid var(--color-border-primary, #e2e8f0)', borderRadius: '6px' };
    const portalSurfaceBackground =
      computedTheme === 'dark' ? 'var(--color-surface-dark)' : 'var(--color-surface-light)';

    const appContent = (
      <div
        ref={displayMode === 'inline' ? containerRef : undefined}
        style={
          displayMode === 'inline'
            ? { height, width: '100%', position: 'relative' as const, ...borderStyle }
            : { width: '100%', height: '100%' }
        }
      >
        <ErrorBoundary context="MCP App" showHomeButton={false}>
          <React.Suspense
            fallback={
              <div className="flex items-center justify-center" style={{ height }}>
                <Spinner
                  tip={translate('components.mcpApp.renderer.loading', 'Loading MCP App…')}
                />
              </div>
            }
          >
            <LazyAppRenderer
              key={getMcpAppRenderKeyV2(operation)}
              ref={appRendererRef}
              operation={operation}
              toolName={toolName}
              sandbox={sandboxConfig}
              {...(effectiveHtml != null ? { html: effectiveHtml } : {})}
              {...(effectiveUri != null ? { toolResourceUri: effectiveUri } : {})}
              {...(toolInput != null ? { toolInput } : {})}
              {...(toolCancelled != null ? { toolCancelled } : {})}
              {...(toolResult != null ? { toolResult: toCallToolResult(toolResult) } : {})}
              {...(hostContext != null ? { hostContext } : {})}
              {...(useDirectClient && mcpClient
                ? { client: mcpClient as unknown as NonNullable<AppRendererProps['client']> }
                : {})}
              {...(effectiveUri ? { onReadResource: handleReadResource } : {})}
              {...(shouldUseHttpToolCall ? { onCallTool: handleCallTool } : {})}
              {...(shouldUseFallback ? { onListResources: handleListResources } : {})}
              onMessage={handleMessage}
              onSizeChanged={handleSizeChanged}
              onInitialized={handleInitialized}
              onError={handleError}
              onOpenLink={handleOpenLink}
            />
          </React.Suspense>
        </ErrorBoundary>
      </div>
    );

    if (displayMode === 'fullscreen') {
      return (
        <>
          {/* Placeholder in the original position so layout does not collapse */}
          <div style={{ height, width: '100%' }} />
          {ReactDOM.createPortal(
            <div
              ref={containerRef}
              style={{
                position: 'fixed',
                inset: 0,
                zIndex: 9999,
                background: portalSurfaceBackground,
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {/* Fullscreen toolbar */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  padding: '8px 12px',
                  borderBottom: '1px solid var(--color-border-primary, #e2e8f0)',
                  flexShrink: 0,
                }}
              >
                <Button
                  ref={fullscreenExitRef}
                  size="small"
                  onClick={() => {
                    setDisplayMode('inline');
                  }}
                >
                  {translate('components.mcpApp.renderer.exitFullscreen', 'Exit fullscreen')}
                </Button>
              </div>
              <div style={{ flex: 1, overflow: 'auto' }}>{appContent}</div>
            </div>,
            document.body
          )}
        </>
      );
    }

    if (displayMode === 'pip') {
      return (
        <>
          {/* Placeholder in the original position */}
          <div style={{ height, width: '100%' }} />
          {ReactDOM.createPortal(
            <div
              ref={containerRef}
              style={{
                position: 'fixed',
                bottom: 16,
                right: 16,
                width: 400,
                height: 300,
                zIndex: 9998,
                background: portalSurfaceBackground,
                border: '1px solid var(--color-border-primary, #e2e8f0)',
                borderRadius: 8,
                boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
              }}
            >
              {/* PiP toolbar */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '4px 8px',
                  borderBottom: '1px solid var(--color-border-primary, #e2e8f0)',
                  flexShrink: 0,
                  fontSize: 12,
                  color: 'var(--color-text-secondary, #64748b)',
                }}
              >
                <span>{uiMetadata?.title ?? toolName}</span>
                <div style={{ display: 'flex', gap: 4 }}>
                  <Button
                    size="small"
                    onClick={() => {
                      setDisplayMode('fullscreen');
                    }}
                  >
                    {translate('components.mcpApp.renderer.fullscreen', 'Fullscreen')}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      setDisplayMode('inline');
                    }}
                  >
                    {translate('components.mcpApp.renderer.close', 'Close')}
                  </Button>
                </div>
              </div>
              <div style={{ flex: 1, overflow: 'auto' }}>{appContent}</div>
            </div>,
            document.body
          )}
        </>
      );
    }

    return appContent;
  }
);
StandardMCPAppRenderer.displayName = 'StandardMCPAppRenderer';
