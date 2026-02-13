/**
 * @deprecated Use StandardMCPAppRenderer instead.
 *
 * MCPAppRenderer - Legacy custom renderer for MCP Apps.
 * This component uses a non-standard postMessage protocol (`ui/toolResult`)
 * that is incompatible with the MCP Apps spec (SEP-1865).
 * The spec requires `ui/initialize` -> `ui/notifications/tool-input` ->
 * `ui/notifications/tool-result` lifecycle, which is handled by
 * StandardMCPAppRenderer (via @mcp-ui/client AppRenderer).
 *
 * Security: Does NOT enforce CSP on the inner iframe.
 * Kept temporarily as fallback until StandardMCPAppRenderer is fully verified.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';

import { Spin, Alert, Button } from 'antd';
import { RefreshCw } from 'lucide-react';

import { useMCPAppStore } from '@/stores/mcpAppStore';

import type { MCPAppUIMetadata } from '@/types/mcpApp';

export interface MCPAppRendererProps {
  /** The MCP App ID */
  appId: string;
  /** Pre-loaded HTML content (from SSE event or cache) */
  htmlContent?: string;
  /** Initial tool result to push to the app */
  toolResult?: unknown;
  /** UI metadata for permissions and CSP */
  uiMetadata?: MCPAppUIMetadata;
  /** Height of the iframe container */
  height?: string | number;
}

/**
 * Build sandbox attribute string from permissions list.
 * Always includes allow-scripts; additional permissions come from _meta.ui.permissions.
 */
function buildSandboxAttr(permissions?: string[]): string {
  const base = ['allow-scripts', 'allow-forms'];
  if (permissions?.includes('camera') || permissions?.includes('microphone')) {
    // These require allow-same-origin in some browsers
    // but we keep it restricted for security
  }
  return base.join(' ');
}

export const MCPAppRenderer: React.FC<MCPAppRendererProps> = ({
  appId,
  htmlContent: propHtmlContent,
  toolResult,
  uiMetadata,
  height = '100%',
}) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loading, setLoading] = useState(!propHtmlContent);
  const [error, setError] = useState<string | null>(null);
  const [html, setHtml] = useState<string | undefined>(propHtmlContent);

  const proxyToolCall = useMCPAppStore((s) => s.proxyToolCall);
  const loadResource = useMCPAppStore((s) => s.loadResource);
  const apps = useMCPAppStore((s) => s.apps);

  // Load HTML resource if not provided via props
  useEffect(() => {
    if (propHtmlContent) {
      setHtml(propHtmlContent);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);

    const doLoad = async () => {
      try {
        // Only try API if appId looks like a UUID (skip execution IDs like act-xxx, exec_xxx)
        const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(appId);
        if (isUUID) {
          const resource = await loadResource(appId);
          if (cancelled) return;
          if (resource?.html_content) {
            setHtml(resource.html_content);
            setLoading(false);
            return;
          }
        }
        // Fallback: search apps in store for a matching real app
        const realApp = Object.values(apps).find(
          (a) => a.id === appId || a.tool_name === appId,
        );
        if (realApp && realApp.id !== appId) {
          const r = await loadResource(realApp.id);
          if (cancelled) return;
          if (r?.html_content) {
            setHtml(r.html_content);
            setLoading(false);
            return;
          }
        }
        if (!cancelled) {
          setError('Failed to load MCP App resource');
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setError(String(err));
          setLoading(false);
        }
      }
    };
    doLoad();

    return () => {
      cancelled = true;
    };
  }, [appId, propHtmlContent, loadResource, apps]);

  // Handle postMessage from iframe (MCP App -> Host communication)
  const handleMessage = useCallback(
    async (event: MessageEvent) => {
      // Only accept messages from our iframe
      if (!iframeRef.current?.contentWindow) return;
      if (event.source !== iframeRef.current.contentWindow) return;

      const message = event.data;
      if (!message || typeof message !== 'object') return;

      // Handle JSON-RPC style messages from the MCP App
      const { method, id, params } = message;

      if (method === 'tools/call' && params) {
        // App is calling a tool on its MCP server
        try {
          const result = await proxyToolCall(appId, params.name, params.arguments || {});
          // Send result back to iframe
          iframeRef.current.contentWindow.postMessage(
            { jsonrpc: '2.0', id, result: { content: result.content } },
            '*',
          );
        } catch (err) {
          iframeRef.current.contentWindow.postMessage(
            { jsonrpc: '2.0', id, error: { message: String(err) } },
            '*',
          );
        }
      }
    },
    [appId, proxyToolCall],
  );

  useEffect(() => {
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [handleMessage]);

  // Push initial tool result to the iframe after it loads
  const handleIframeLoad = useCallback(() => {
    if (!iframeRef.current?.contentWindow || !toolResult) return;

    // Send tool result via postMessage
    iframeRef.current.contentWindow.postMessage(
      {
        jsonrpc: '2.0',
        method: 'ui/toolResult',
        params: { content: toolResult },
      },
      '*',
    );
  }, [toolResult]);

  const handleRetry = useCallback(() => {
    setError(null);
    setLoading(true);
    setHtml(undefined);
    loadResource(appId, true)  // bustCache=true to force fresh fetch
      .then((resource) => {
        if (resource) {
          setHtml(resource.html_content);
        } else {
          setError('Failed to load MCP App resource');
        }
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err));
        setLoading(false);
      });
  }, [appId, loadResource]);

  if (loading) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <Spin tip="Loading MCP App..." />
      </div>
    );
  }

  if (error || !html) {
    // If we have a tool result but no HTML, show the result in a readable format
    if (toolResult && !html) {
      const resultStr =
        typeof toolResult === 'string' ? toolResult : JSON.stringify(toolResult, null, 2);
      return (
        <div className="p-4 overflow-auto" style={{ height }}>
          <div className="text-xs text-slate-400 mb-2">Tool Result</div>
          <pre className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap font-mono bg-slate-50 dark:bg-slate-800/50 rounded-md p-3 border border-slate-200 dark:border-slate-700">
            {resultStr}
          </pre>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-4" style={{ height }}>
        <Alert
          type="error"
          message="Failed to load MCP App"
          description={error || 'No HTML resource available'}
          showIcon
        />
        <Button icon={<RefreshCw size={14} />} onClick={handleRetry} size="small">
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="mcp-app-container" style={{ height, width: '100%', position: 'relative' }}>
      <iframe
        ref={iframeRef}
        sandbox={buildSandboxAttr(uiMetadata?.permissions)}
        srcDoc={html}
        onLoad={handleIframeLoad}
        style={{
          width: '100%',
          height: '100%',
          border: 'none',
          borderRadius: '4px',
          background: '#fff',
        }}
        title={uiMetadata?.title || `MCP App ${appId}`}
      />
    </div>
  );
};
